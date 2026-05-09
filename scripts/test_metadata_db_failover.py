#!/usr/bin/env python3
"""J2-b: metadata sidecar DB failover test.

Verifies the sidecar metadata DB connect-and-retry path that operators rely on
during a Patroni-style PostgreSQL failover. Default smoke runs entirely
in-process against a fresh SQLite DB and simulates transient connection
failures by patching ``metadata_db.connect_db`` so the first ``--simulated-
failure-count`` calls raise a fake ``OperationalError`` and the next call
succeeds. ``connect_db_with_retry`` should ride out the simulated outage
within the configured ``--failover-target-seconds`` window.

The test then exercises a tiny end-to-end metadata round-trip against the
recovered connection: insert one ``jobs`` row before the failover, insert a
second row after the retry succeeds, and confirm both rows are visible from a
fresh read connection. This proves the retry helper plus the metadata DB
schema both survive a transient outage without losing data.

Emits ``metadata_db_failover_test/v1``. The script is intentionally side-effect
isolated: it allocates a unique work directory under ``tmp/`` (or honours
``--work-dir`` when an operator pins one) and removes it on success.

Operator drill (against a real Patroni cluster — outside default smoke):

```
python3 scripts/test_metadata_db_failover.py \
  --db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres \
  --simulated-failure-count 2 \
  --failover-target-seconds 30 \
  --output tmp/metadata_db_failover_test.json \
  --assert-ok
```

The simulation flag stays the same against a live Postgres backend; for a true
end-to-end Patroni drill, the operator should pair this with ``patronictl
switchover`` and use the same ``--db-dsn`` for both legs.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import metadata_db  # noqa: E402
from scripts.metadata_db import (  # noqa: E402
    apply_migrations,
    connect_db,
    connect_db_with_retry,
    utc_now,
)


SCHEMA_ID = "metadata_db_failover_test/v1"


class SimulatedOperationalError(Exception):
    """Raised by the in-process simulator to mimic a Patroni-side connection drop."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def insert_job_row(
    conn: Any,
    *,
    job_id: str,
    intersection_size: int,
    intersection_sum: int,
    out_base: str,
) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            (
                "INSERT INTO jobs ("
                "job_id, correlation_id, out_base, status, "
                "intersection_size, intersection_sum, imported_at_utc"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                job_id,
                f"corr-{job_id}",
                out_base,
                "released",
                intersection_size,
                intersection_sum,
                utc_now(),
            ),
        )
    finally:
        try:
            cursor.close()
        except Exception:
            pass
    conn.commit()


def query_job_count(conn: Any, *, job_id: str | None = None) -> tuple[int, str | None]:
    cursor = conn.cursor()
    try:
        if job_id is None:
            cursor.execute("SELECT COUNT(*) FROM jobs")
        else:
            cursor.execute("SELECT COUNT(*), MAX(job_id) FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
    if row is None:
        return 0, None
    if job_id is None:
        return int(row[0]), None
    return int(row[0]), (str(row[1]) if row[1] is not None else None)


def install_failure_simulator(
    *,
    failure_count: int,
) -> tuple[Any, dict[str, int]]:
    """Patch ``metadata_db.connect_db`` so the first ``failure_count`` calls fail.

    The patch counts every attempt — including retries inside
    ``connect_db_with_retry`` — so a caller that asks for 2 simulated failures
    and uses ``retries=3`` will see 2 SimulatedOperationalError raises followed
    by a real connect on the third attempt.
    """
    state = {"calls": 0, "failures_emitted": 0}
    original = metadata_db.connect_db

    def patched(db_path: str = "", dsn: str = "") -> Any:
        state["calls"] += 1
        if state["failures_emitted"] < failure_count:
            state["failures_emitted"] += 1
            raise SimulatedOperationalError(
                f"simulated transient connect failure #{state['failures_emitted']}"
            )
        return original(db_path, dsn=dsn)

    metadata_db.connect_db = patched
    return original, state


def restore_connect(original: Any) -> None:
    metadata_db.connect_db = original


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--db-path",
        default="",
        help="SQLite path for default smoke. Ignored when --db-dsn is set.",
    )
    ap.add_argument(
        "--db-dsn",
        default="",
        help="PostgreSQL DSN for live operator drills (psycopg2 required).",
    )
    ap.add_argument(
        "--work-dir",
        default="",
        help="Pinned work dir. When omitted, an isolated tmp dir is created and removed on success.",
    )
    ap.add_argument(
        "--simulated-failure-count",
        type=int,
        default=2,
        help="Number of transient connect failures to inject before letting the real connect succeed.",
    )
    ap.add_argument(
        "--retry-attempts-allowed",
        type=int,
        default=4,
        help="Retry budget passed to connect_db_with_retry. Must exceed --simulated-failure-count.",
    )
    ap.add_argument(
        "--retry-base-delay-seconds",
        type=float,
        default=0.05,
        help="Base delay for connect_db_with_retry exponential backoff (seconds).",
    )
    ap.add_argument(
        "--failover-target-seconds",
        type=float,
        default=30.0,
        help="Acceptance budget for the simulated failover round trip.",
    )
    ap.add_argument("--output", default="", help="Path to write the JSON report.")
    ap.add_argument("--assert-ok", action="store_true", help="Exit non-zero if status != ok.")
    return ap.parse_args(argv)


def build_failure_reason_summary(
    *,
    state: dict[str, int],
    target_failures: int,
) -> str | None:
    if target_failures == 0:
        return None
    return f"simulated_operational_error x{state['failures_emitted']}"


def run(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.simulated_failure_count < 0:
        raise SystemExit("[ERROR] --simulated-failure-count must be >= 0")
    if args.retry_attempts_allowed < 1:
        raise SystemExit("[ERROR] --retry-attempts-allowed must be >= 1")
    if args.retry_attempts_allowed <= args.simulated_failure_count:
        raise SystemExit(
            "[ERROR] --retry-attempts-allowed must exceed --simulated-failure-count "
            "so the retry budget can ride out the simulated outage"
        )

    backend = "postgres" if args.db_dsn else "sqlite"
    work_dir_owned = False
    work_dir: Path
    if args.work_dir:
        work_dir = Path(args.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="metadata_db_failover_test_"))
        work_dir_owned = True

    db_path = ""
    if backend == "sqlite":
        db_path = args.db_path or str(work_dir / "primary.db")

    errors: list[str] = []

    baseline_query = {
        "ok": False,
        "duration_ms": 0.0,
        "rows_returned": 0,
        "job_id": "",
    }
    failover_request = {
        "primary_attempt_failed": False,
        "simulated_failure_count": int(args.simulated_failure_count),
        "actual_attempts_used": 0,
        "total_failover_duration_ms": None,
        "within_failover_target": False,
        "ok": False,
        "failure_reason": None,
    }
    post_failover_query = {
        "ok": False,
        "duration_ms": 0.0,
        "rows_returned": 0,
        "job_id": "",
        "data_round_trip_ok": False,
    }
    data_integrity = {
        "rows_inserted_pre_failover": 0,
        "rows_inserted_post_failover": 0,
        "rows_observed_post_failover": 0,
        "no_data_lost": False,
        "errors": [],
    }

    pre_job_id = f"j2b-pre-{uuid.uuid4().hex[:12]}"
    post_job_id = f"j2b-post-{uuid.uuid4().hex[:12]}"

    try:
        # Setup: apply migrations + insert the pre-failover row through the
        # normal connect path. This proves the DB is healthy before we start
        # injecting failures.
        setup_conn = connect_db(db_path, dsn=args.db_dsn)
        try:
            apply_migrations(setup_conn)
            insert_job_row(
                setup_conn,
                job_id=pre_job_id,
                intersection_size=2,
                intersection_sum=425,
                out_base=str(work_dir / "pre"),
            )
        finally:
            setup_conn.close()
        data_integrity["rows_inserted_pre_failover"] = 1

        # Baseline: read the pre-failover row through a fresh connection.
        baseline_start = time.perf_counter()
        baseline_conn = connect_db(db_path, dsn=args.db_dsn)
        try:
            count, observed_job_id = query_job_count(baseline_conn, job_id=pre_job_id)
        finally:
            baseline_conn.close()
        baseline_query["duration_ms"] = (time.perf_counter() - baseline_start) * 1000.0
        baseline_query["rows_returned"] = count
        baseline_query["job_id"] = observed_job_id or ""
        baseline_query["ok"] = count == 1 and observed_job_id == pre_job_id
        if not baseline_query["ok"]:
            errors.append("baseline_query did not see the pre-failover row")

        # Simulated failover: inject ``simulated_failure_count`` transient
        # OperationalError raises before allowing the real connect to succeed,
        # then ride them out via ``connect_db_with_retry``.
        original_connect, state = install_failure_simulator(
            failure_count=int(args.simulated_failure_count),
        )
        failover_start = time.perf_counter()
        recovered_conn: Any = None
        try:
            try:
                recovered_conn = connect_db_with_retry(
                    db_path,
                    dsn=args.db_dsn,
                    retries=int(args.retry_attempts_allowed),
                    delay=float(args.retry_base_delay_seconds),
                )
            except Exception as exc:  # pragma: no cover - covered by error path
                failover_request["failure_reason"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                errors.append(
                    f"connect_db_with_retry exhausted retry budget: {failover_request['failure_reason']}"
                )
        finally:
            failover_request["total_failover_duration_ms"] = (
                time.perf_counter() - failover_start
            ) * 1000.0
            restore_connect(original_connect)

        failover_request["actual_attempts_used"] = int(state["calls"])
        failover_request["primary_attempt_failed"] = state["failures_emitted"] > 0
        if recovered_conn is not None:
            try:
                insert_job_row(
                    recovered_conn,
                    job_id=post_job_id,
                    intersection_size=2,
                    intersection_sum=425,
                    out_base=str(work_dir / "post"),
                )
                data_integrity["rows_inserted_post_failover"] = 1
                failover_request["ok"] = True
                if failover_request["failure_reason"] is None:
                    failover_request["failure_reason"] = (
                        build_failure_reason_summary(
                            state=state,
                            target_failures=int(args.simulated_failure_count),
                        )
                    )
            except Exception as exc:
                errors.append(f"post-failover insert raised: {type(exc).__name__}: {exc}")
            finally:
                try:
                    recovered_conn.close()
                except Exception:
                    pass
        within_target = (
            failover_request["total_failover_duration_ms"] is not None
            and failover_request["total_failover_duration_ms"]
            <= float(args.failover_target_seconds) * 1000.0
        )
        failover_request["within_failover_target"] = bool(
            within_target and failover_request["ok"]
        )

        # Post-failover: read both rows through yet another fresh connection.
        post_start = time.perf_counter()
        post_conn = connect_db(db_path, dsn=args.db_dsn)
        try:
            total_rows, _ = query_job_count(post_conn)
            post_count, post_observed_job_id = query_job_count(post_conn, job_id=post_job_id)
            pre_count, _ = query_job_count(post_conn, job_id=pre_job_id)
        finally:
            post_conn.close()
        post_failover_query["duration_ms"] = (time.perf_counter() - post_start) * 1000.0
        post_failover_query["rows_returned"] = post_count
        post_failover_query["job_id"] = post_observed_job_id or ""
        post_failover_query["ok"] = post_count == 1 and post_observed_job_id == post_job_id
        post_failover_query["data_round_trip_ok"] = bool(
            post_failover_query["ok"] and pre_count == 1
        )

        data_integrity["rows_observed_post_failover"] = total_rows
        data_integrity["no_data_lost"] = bool(
            data_integrity["rows_observed_post_failover"]
            >= data_integrity["rows_inserted_pre_failover"]
            + data_integrity["rows_inserted_post_failover"]
        )
        if not data_integrity["no_data_lost"]:
            data_integrity["errors"].append(
                f"expected {data_integrity['rows_inserted_pre_failover'] + data_integrity['rows_inserted_post_failover']} rows, observed {data_integrity['rows_observed_post_failover']}"
            )

        status = "ok"
        if errors:
            status = "fail"
        if not baseline_query["ok"]:
            status = "fail"
        if not failover_request["ok"]:
            status = "fail"
        if not failover_request["within_failover_target"]:
            status = "fail"
        if not post_failover_query["ok"]:
            status = "fail"
        if not data_integrity["no_data_lost"]:
            status = "fail"

        report = {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "status": status,
            "configuration": {
                "backend": backend,
                "simulation_mode": "in_process_simulated",
                "simulated_failure_count": int(args.simulated_failure_count),
                "retry_attempts_allowed": int(args.retry_attempts_allowed),
                "retry_base_delay_seconds": float(args.retry_base_delay_seconds),
                "failover_target_seconds": float(args.failover_target_seconds),
                "db_path": db_path or None,
                "db_dsn": args.db_dsn or None,
            },
            "baseline_query": baseline_query,
            "failover_request": failover_request,
            "post_failover_query": post_failover_query,
            "data_integrity": data_integrity,
            "errors": errors,
        }
    finally:
        if work_dir_owned and work_dir.exists():
            try:
                shutil.rmtree(work_dir)
            except OSError:
                pass

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    if args.assert_ok and report["status"] != "ok":
        return 1
    return 0


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
