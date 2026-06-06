#!/usr/bin/env python3
"""Verifier-facing gate for PostgreSQL/HA/backup/restore evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "postgres_ha_evidence_gate/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def parse_check(
    *,
    name: str,
    status: str,
    expected: Any,
    actual: Any,
    missing_prerequisites: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
    }
    if missing_prerequisites is not None:
        payload["missing_prerequisites"] = missing_prerequisites
    return payload


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--live-evidence-archive", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    backup_restore_path = out_dir / "metadata_backup_restore_drill.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_metadata_backup_restore_drill.py"),
        "--out", str(backup_restore_path),
    ])
    require_ok(res, label="check_metadata_backup_restore_drill")
    backup_restore = load_json(backup_restore_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_metadata_backup_restore_drill",
            status="ok" if backup_restore.get("status") == "ok" else "fail",
            expected="backup/restore is SHA-bound, portability-checked, and rejects tampered backups",
            actual=backup_restore,
        )
    )
    artifacts.append(artifact(backup_restore_path, schema="metadata_backup_restore_drill/v1"))

    failover_path = out_dir / "metadata_db_failover_test.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "test_metadata_db_failover.py"),
        "--output", str(failover_path),
        "--assert-ok",
    ])
    require_ok(res, label="test_metadata_db_failover")
    failover = load_json(failover_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_metadata_db_failover_test",
            status="ok" if failover.get("status") == "ok" else "fail",
            expected="retry/connect path survives transient failover within target and preserves rows",
            actual=failover,
        )
    )
    artifacts.append(artifact(failover_path, schema="metadata_db_failover_test/v1"))

    topo_dir = out_dir / "postgres_ha_topology"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "render_postgres_ha_topology.py"),
        "--out-dir", str(topo_dir),
        "--output", str(out_dir / "postgres_ha_topology_report.json"),
    ])
    require_ok(res, label="render_postgres_ha_topology")
    topo = load_json(out_dir / "postgres_ha_topology_report.json")
    repo_side_checks.append(
        parse_check(
            name="repo_side_postgres_primary_replica_topology",
            status="ok" if topo.get("status") == "ok" else "fail",
            expected="primary/replica topology render stays coherent and replication query remains present",
            actual=topo,
        )
    )
    artifacts.append(artifact(out_dir / "postgres_ha_topology_report.json", schema="postgres_ha_topology_report/v1"))

    patroni_dir = out_dir / "patroni_failover_topology"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "render_patroni_failover_topology.py"),
        "--out-dir", str(patroni_dir),
        "--output", str(out_dir / "patroni_failover_topology_report.json"),
    ])
    require_ok(res, label="render_patroni_failover_topology")
    patroni = load_json(out_dir / "patroni_failover_topology_report.json")
    repo_side_checks.append(
        parse_check(
            name="repo_side_patroni_failover_topology",
            status="ok" if patroni.get("status") == "ok" else "fail",
            expected="Patroni failover topology render stays coherent and failover commands remain present",
            actual=patroni,
        )
    )
    artifacts.append(artifact(out_dir / "patroni_failover_topology_report.json", schema="patroni_failover_topology_report/v1"))

    pgbouncer_dir = out_dir / "pgbouncer_topology"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "render_pgbouncer_topology.py"),
        "--out-dir", str(pgbouncer_dir),
        "--output", str(out_dir / "pgbouncer_topology_report.json"),
    ])
    require_ok(res, label="render_pgbouncer_topology")
    pgbouncer = load_json(out_dir / "pgbouncer_topology_report.json")
    repo_side_checks.append(
        parse_check(
            name="repo_side_pgbouncer_topology",
            status="ok" if pgbouncer.get("status") == "ok" else "fail",
            expected="pgBouncer topology render stays coherent and direct-primary bypass remains documented",
            actual=pgbouncer,
        )
    )
    artifacts.append(artifact(out_dir / "pgbouncer_topology_report.json", schema="pgbouncer_topology_report/v1"))

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="postgres_ha_live_archive",
            archive_filename="postgres_ha_live_evidence_archive.json",
            expected_schema="postgres_ha_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_postgres_ha_evidence_archive",
                status="skipped",
                expected="operator provides a unified PostgreSQL/HA live evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_postgres_ha_evidence_archive",
                status="fail",
                expected="operator provides a unified PostgreSQL/HA live evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="postgres_ha_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_postgres_ha_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified PostgreSQL/HA live evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live PostgreSQL/HA artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_postgres_ha_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_postgres_ha_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree backup/restore baseline is frozen into the live PostgreSQL/HA archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_postgres_ha_foundation"),
                missing_prerequisites=["live_repo_side_postgres_ha_foundation not present in postgres/ha live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_primary_replica_report",
                "live_patroni_failover_report",
                "live_pgbouncer_report",
                "live_restored_api_smoke",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_postgres_ha_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real primary/replica, Patroni, pgBouncer, or restored API artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_primary_replica_report",
                        "live_patroni_failover_report",
                        "live_pgbouncer_report",
                        "live_restored_api_smoke",
                    )
                },
                missing_prerequisites=["real postgres/ha rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] == "ok" for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_postgres_ha_evidence_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_postgres_ha_rollout"]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in concrete_live)
        else "ok" if rollout_live and all(item["status"] == "ok" for item in rollout_live)
        else "skipped"
    )

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove backup/restore integrity, failover retry semantics, and committed PostgreSQL/Patroni/pgBouncer topology coherence.",
            "They do not prove a real PostgreSQL primary/replica deployment, Patroni failover, pgBouncer pool behavior, or external backup storage worked on target hosts.",
        ],
        "live_boundary": [
            "Live PostgreSQL/HA readiness requires operator-provided evidence for real primary/replica, Patroni failover, pgBouncer pooling, external backup/restore, and restored API/query smoke.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete HA durability.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "postgres_ha_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
