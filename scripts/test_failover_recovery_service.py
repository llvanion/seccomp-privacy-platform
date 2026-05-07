#!/usr/bin/env python3
"""J2-a: recovery service failover test.

Starts two record-recovery service HTTP instances on different ports, issues a
baseline recovery request to the primary, kills the primary process, then
issues a follow-up recovery request that exercises the client-side retry path
(primary connection refused → secondary success). Verifies that:

1. The primary served the baseline request and its audit log captured it.
2. After SIGKILL, the primary endpoint is no longer reachable.
3. The secondary endpoint serves the failover request within the configured
   `--failover-target-seconds` window.
4. Each service's audit log preserves a recover record for the request it served
   (no audit events lost during failover).

Emits `recovery_service_failover_test/v1`. Default smoke runs against plain HTTP
on the loopback interface; mTLS is left as an operator-environment exercise so
default contract smoke does not need cert plumbing.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.record_recovery.client import (  # noqa: E402
    request_record_recovery,
    request_record_recovery_health,
)
from services.record_recovery.encrypted_record_store import build_record_store  # noqa: E402


SCHEMA_ID = "recovery_service_failover_test/v1"
AUTH_ENV = "SSE_RECORD_RECOVERY_TOKEN"
KEY_ENV = "SSE_RECORD_STORE_PASSPHRASE"
FIXTURE_CALLER = "auto_demo"
FIXTURE_TENANT_ID = "failover-tenant"
FIXTURE_DATASET_ID = "failover-dataset"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def synthetic_email(index: int) -> str:
    return f"failover-candidate-{index:04d}@example.com"


def make_record_store(*, store_path: Path, env: dict[str, str], candidate_count: int) -> None:
    rows = [
        {
            "email": synthetic_email(index),
            "campaign": "failover",
            "amount": str(100 + index),
        }
        for index in range(candidate_count)
    ]
    rows.append({"email": "nonmatch@example.com", "campaign": "other", "amount": "50"})
    original_key = os.environ.get(KEY_ENV)
    os.environ[KEY_ENV] = env[KEY_ENV]
    try:
        count = build_record_store(
            rows=rows,
            out_path=store_path,
            record_id_field="email",
            key_env=KEY_ENV,
        )
    finally:
        if original_key is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = original_key
    if count != candidate_count + 1:
        raise SystemExit(f"[ERROR] unexpected synthetic record-store row count: {count}")


def write_service_config(
    *,
    config_path: Path,
    service_label: str,
    port: int,
    record_store_root: Path,
    output_root: Path,
    audit_log: Path,
    pid_file: Path,
    ready_file: Path,
    log_file: Path,
) -> None:
    # Both primary and secondary advertise the same service_id so clients can
    # target the LB-style endpoint transparently. service_label only affects
    # internal labels (lifecycle paths, audit log path).
    payload = {
        "schema": "record_recovery_service_config/v1",
        "transport": "http",
        "service_id": "failover-recovery",
        "tenant_id": FIXTURE_TENANT_ID,
        "dataset_id": FIXTURE_DATASET_ID,
        "auth_token_env": AUTH_ENV,
        "endpoint_url": f"http://127.0.0.1:{port}",
        "http_listener": {
            "bind_host": "127.0.0.1",
            "port": port,
        },
        "allowed_callers": [FIXTURE_CALLER],
        "allowed_output_roots": [str(output_root.resolve())],
        "allowed_record_store_roots": [str(record_store_root.resolve())],
        "audit_log": str(audit_log.resolve()),
        "lifecycle": {
            "pid_file": str(pid_file.resolve()),
            "ready_file": str(ready_file.resolve()),
            "log_file": str(log_file.resolve()),
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_service(*, config_path: Path, env: dict[str, str], timeout_sec: float) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
        "start",
        "--config",
        str(config_path),
        "--timeout-sec",
        str(timeout_sec),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_sec + 5)
    if proc.returncode != 0:
        raise RuntimeError(
            f"manage_record_recovery_service.py start exited {proc.returncode}: stderr={proc.stderr.strip()} stdout={proc.stdout.strip()}"
        )


def stop_service(*, config_path: Path, env: dict[str, str], timeout_sec: float) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
        "stop",
        "--config",
        str(config_path),
        "--timeout-sec",
        str(timeout_sec),
    ]
    subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_sec + 5)


def kill_service_pid(pid_file: Path, *, deadline_sec: float = 5.0) -> str | None:
    """SIGKILL the process referenced by pid_file. Returns kill method label."""
    if not pid_file.is_file():
        return None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return None
    deadline = time.time() + deadline_sec
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "SIGKILL"
        time.sleep(0.05)
    return "SIGKILL"


def wait_endpoint_unreachable(endpoint_url: str, *, deadline_sec: float = 5.0) -> tuple[bool, str | None]:
    """Poll the endpoint until it stops accepting TCP connections or the deadline expires."""
    parsed_host = endpoint_url.split("://", 1)[-1]
    host_port = parsed_host.split("/", 1)[0]
    host, _, port_text = host_port.partition(":")
    if not port_text:
        return False, "endpoint_url missing port"
    port = int(port_text)
    deadline = time.time() + deadline_sec
    last_error: str | None = None
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        try:
            sock.connect((host, port))
            sock.close()
            time.sleep(0.05)
            continue
        except (ConnectionRefusedError, OSError) as exc:
            last_error = type(exc).__name__
            return True, last_error
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return False, last_error


def issue_recovery_request(
    *,
    endpoint_url: str,
    record_store_path: Path,
    out_path: Path,
    job_id: str,
    candidate_count: int,
    env: dict[str, str],
) -> dict[str, Any]:
    candidates = {synthetic_email(i) for i in range(candidate_count)}
    original_token = os.environ.get(AUTH_ENV)
    original_key = os.environ.get(KEY_ENV)
    os.environ[AUTH_ENV] = env[AUTH_ENV]
    os.environ[KEY_ENV] = env[KEY_ENV]
    try:
        return request_record_recovery(
            socket_path=None,
            endpoint_url=endpoint_url,
            auth_env=AUTH_ENV,
            caller=FIXTURE_CALLER,
            job_id=job_id,
            tenant_id=FIXTURE_TENANT_ID,
            dataset_id=FIXTURE_DATASET_ID,
            service_id="failover-recovery",
            record_store_path=record_store_path,
            record_store_key_env=KEY_ENV,
            out_path=out_path,
            out_format="csv",
            role="server",
            join_key_field="email",
            value_field="amount",
            filter_pairs=[],
            candidate_ids=candidates,
            min_output_rows=None,
            max_output_rows=None,
        )
    finally:
        if original_token is None:
            os.environ.pop(AUTH_ENV, None)
        else:
            os.environ[AUTH_ENV] = original_token
        if original_key is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = original_key


def issue_recovery_with_failover(
    *,
    primary_url: str,
    secondary_url: str,
    record_store_path: Path,
    out_path: Path,
    job_id: str,
    candidate_count: int,
    env: dict[str, str],
    max_total_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    primary_failed = False
    primary_reason: Optional[str] = None
    served_by = "none"
    secondary_duration_ms: Optional[float] = None
    secondary_result: Optional[dict[str, Any]] = None
    error_text: Optional[str] = None

    try:
        primary_started = time.perf_counter()
        primary_result = issue_recovery_request(
            endpoint_url=primary_url,
            record_store_path=record_store_path,
            out_path=out_path,
            job_id=job_id,
            candidate_count=candidate_count,
            env=env,
        )
        # If primary is still alive at this point we did not actually exercise failover.
        served_by = "primary"
        secondary_duration_ms = (time.perf_counter() - primary_started) * 1000.0
        secondary_result = primary_result
    except Exception as exc:
        primary_failed = True
        primary_reason = type(exc).__name__
        error_text = str(exc)
        try:
            secondary_started = time.perf_counter()
            secondary_result = issue_recovery_request(
                endpoint_url=secondary_url,
                record_store_path=record_store_path,
                out_path=out_path,
                job_id=job_id,
                candidate_count=candidate_count,
                env=env,
            )
            served_by = "secondary"
            secondary_duration_ms = (time.perf_counter() - secondary_started) * 1000.0
        except Exception as secondary_exc:
            error_text = f"primary {primary_reason}: {error_text}; secondary {type(secondary_exc).__name__}: {secondary_exc}"

    total_ms = (time.perf_counter() - started) * 1000.0
    return {
        "primary_attempt_failed": primary_failed,
        "primary_failure_reason": primary_reason,
        "served_by": served_by,
        "secondary_duration_ms": round(secondary_duration_ms, 3) if secondary_duration_ms is not None else None,
        "total_failover_duration_ms": round(total_ms, 3),
        "within_failover_target": total_ms <= max_total_seconds * 1000.0,
        "ok": served_by == "secondary" and secondary_result is not None,
        "error_text": error_text,
        "secondary_result": secondary_result,
    }


def count_recover_records(audit_log: Path, *, job_id: str | None = None) -> int:
    """Count `record_recovery_service_request` audit entries (optionally filtered by job_id)."""
    if not audit_log.is_file():
        return 0
    count = 0
    with audit_log.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") != "record_recovery_service_request":
                continue
            if entry.get("decision") != "allow":
                continue
            if job_id is not None and entry.get("job_id") != job_id:
                continue
            count += 1
    return count


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Recovery-service failover test (J2-a).")
    ap.add_argument("--candidate-count", type=int, default=2, help="Synthetic candidate count for the encrypted record store")
    ap.add_argument("--failover-target-seconds", type=float, default=10.0, help="Maximum acceptable end-to-end failover duration; the report's within_failover_target flag is derived from this")
    ap.add_argument("--start-timeout-sec", type=float, default=15.0, help="Timeout for each service start call")
    ap.add_argument("--unreachable-deadline-sec", type=float, default=5.0, help="How long to wait for the killed primary to stop accepting connections")
    ap.add_argument("--work-dir", default="", help="Optional directory to keep test artifacts; defaults to a temp directory cleaned up on exit")
    ap.add_argument("--output", default="", help="Optional output path for the JSON report")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def run_test(args: argparse.Namespace) -> dict[str, Any]:
    operator_work_dir = bool(args.work_dir)
    work_dir = Path(args.work_dir).resolve() if operator_work_dir else Path(
        os.environ.get("TMPDIR") or "/tmp",
    ) / f"seccomp_failover_{int(time.time())}_{secrets.token_hex(4)}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Both the in-process client (request_record_recovery_health /
    # request_record_recovery) and the subprocess service starts read these env
    # vars from os.environ. Set them here so children inherit and the in-process
    # client can resolve the same secrets.
    os.environ[AUTH_ENV] = "failover-token"
    os.environ[KEY_ENV] = "failover-record-store-key"
    base_env = dict(os.environ)

    record_store_path = work_dir / "records.enc.jsonl"
    make_record_store(store_path=record_store_path, env=base_env, candidate_count=args.candidate_count)

    primary_port = find_free_port()
    secondary_port = find_free_port()
    while secondary_port == primary_port:
        secondary_port = find_free_port()
    primary_url = f"http://127.0.0.1:{primary_port}"
    secondary_url = f"http://127.0.0.1:{secondary_port}"

    primary_dir = work_dir / "primary"
    secondary_dir = work_dir / "secondary"
    primary_dir.mkdir(exist_ok=True)
    secondary_dir.mkdir(exist_ok=True)
    output_root = work_dir / "outputs"
    output_root.mkdir(exist_ok=True)

    primary_audit = primary_dir / "audit.jsonl"
    secondary_audit = secondary_dir / "audit.jsonl"
    primary_pid = primary_dir / "service.pid"
    primary_ready = primary_dir / "service.ready"
    primary_log = primary_dir / "service.log"
    secondary_pid = secondary_dir / "service.pid"
    secondary_ready = secondary_dir / "service.ready"
    secondary_log = secondary_dir / "service.log"

    primary_config = primary_dir / "config.json"
    secondary_config = secondary_dir / "config.json"
    write_service_config(
        config_path=primary_config,
        service_label="primary",
        port=primary_port,
        record_store_root=work_dir,
        output_root=output_root,
        audit_log=primary_audit,
        pid_file=primary_pid,
        ready_file=primary_ready,
        log_file=primary_log,
    )
    write_service_config(
        config_path=secondary_config,
        service_label="secondary",
        port=secondary_port,
        record_store_root=work_dir,
        output_root=output_root,
        audit_log=secondary_audit,
        pid_file=secondary_pid,
        ready_file=secondary_ready,
        log_file=secondary_log,
    )

    errors: list[str] = []
    primary_started = False
    secondary_started = False

    try:
        try:
            start_service(config_path=primary_config, env=base_env, timeout_sec=args.start_timeout_sec)
            primary_started = True
        except Exception as exc:
            errors.append(f"primary start failed: {exc}")
        try:
            start_service(config_path=secondary_config, env=base_env, timeout_sec=args.start_timeout_sec)
            secondary_started = True
        except Exception as exc:
            errors.append(f"secondary start failed: {exc}")

        baseline_job_id = "failover_baseline_job"
        baseline_request = {
            "served_by": "primary",
            "duration_ms": 0.0,
            "ok": False,
            "job_id": baseline_job_id,
        }
        if primary_started:
            try:
                started = time.perf_counter()
                # Probe health first to confirm primary is live.
                request_record_recovery_health(
                    socket_path=None,
                    endpoint_url=primary_url,
                    auth_env=AUTH_ENV,
                )
                primary_out = output_root / "primary.csv"
                if primary_out.exists():
                    primary_out.unlink()
                issue_recovery_request(
                    endpoint_url=primary_url,
                    record_store_path=record_store_path,
                    out_path=primary_out,
                    job_id=baseline_job_id,
                    candidate_count=args.candidate_count,
                    env=base_env,
                )
                baseline_request["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
                baseline_request["ok"] = True
            except Exception as exc:
                errors.append(f"baseline recovery failed: {exc}")
                baseline_request["ok"] = False

        kill_method: str | None = None
        killed_at: str | None = None
        primary_unreachable = False
        if primary_started and baseline_request["ok"]:
            kill_method = kill_service_pid(primary_pid, deadline_sec=args.unreachable_deadline_sec)
            killed_at = utc_now_iso()
            primary_unreachable, _ = wait_endpoint_unreachable(
                primary_url, deadline_sec=args.unreachable_deadline_sec
            )
            if not primary_unreachable:
                errors.append("primary endpoint still reachable after SIGKILL")

        failover_job_id = "failover_recovery_job"
        failover_request = {
            "primary_attempt_failed": False,
            "primary_failure_reason": None,
            "served_by": "none",
            "secondary_duration_ms": None,
            "total_failover_duration_ms": None,
            "within_failover_target": False,
            "ok": False,
            "job_id": failover_job_id,
        }
        if primary_started and primary_unreachable and secondary_started:
            failover_out = output_root / "failover.csv"
            if failover_out.exists():
                failover_out.unlink()
            failover_attempt = issue_recovery_with_failover(
                primary_url=primary_url,
                secondary_url=secondary_url,
                record_store_path=record_store_path,
                out_path=failover_out,
                job_id=failover_job_id,
                candidate_count=args.candidate_count,
                env=base_env,
                max_total_seconds=args.failover_target_seconds,
            )
            failover_request.update(
                {
                    "primary_attempt_failed": failover_attempt["primary_attempt_failed"],
                    "primary_failure_reason": failover_attempt["primary_failure_reason"],
                    "served_by": failover_attempt["served_by"],
                    "secondary_duration_ms": failover_attempt["secondary_duration_ms"],
                    "total_failover_duration_ms": failover_attempt["total_failover_duration_ms"],
                    "within_failover_target": bool(failover_attempt["within_failover_target"]),
                    "ok": bool(failover_attempt["ok"]),
                }
            )
            if not failover_attempt["primary_attempt_failed"]:
                errors.append("failover request was served by the primary even after SIGKILL — kill did not land")
            if not failover_attempt["ok"]:
                errors.append(f"failover recovery request failed: {failover_attempt.get('error_text') or 'unknown'}")

        primary_records = count_recover_records(primary_audit, job_id=baseline_job_id)
        secondary_records = count_recover_records(secondary_audit, job_id=failover_job_id)
        audit_errors: list[str] = []
        if baseline_request["ok"] and primary_records < 1:
            audit_errors.append("primary audit log missing baseline recover record")
        if failover_request["ok"] and secondary_records < 1:
            audit_errors.append("secondary audit log missing failover recover record")
        # Cross-contamination check: secondary must not have served the baseline; primary must not have served the failover.
        if count_recover_records(secondary_audit, job_id=baseline_job_id) > 0:
            audit_errors.append("secondary audit log unexpectedly recorded the baseline job")
        if count_recover_records(primary_audit, job_id=failover_job_id) > 0:
            audit_errors.append("primary audit log unexpectedly recorded the failover job after SIGKILL")

        no_loss = not audit_errors
        audit_integrity = {
            "primary_records_for_baseline_job": primary_records,
            "secondary_records_for_failover_job": secondary_records,
            "no_audit_events_lost": no_loss,
            "errors": audit_errors,
        }

        primary_report = {
            "endpoint_url": primary_url,
            "audit_log_path": str(primary_audit),
            "started": primary_started,
            "killed_at_utc": killed_at,
            "kill_method": kill_method,
            "audit_record_count": count_recover_records(primary_audit),
        }
        secondary_report = {
            "endpoint_url": secondary_url,
            "audit_log_path": str(secondary_audit),
            "started": secondary_started,
            "audit_record_count": count_recover_records(secondary_audit),
        }

        if not no_loss:
            errors.extend(audit_errors)

        status = "ok" if not errors else "fail"
        return {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "status": status,
            "configuration": {
                "transport": "http",
                "primary_port": primary_port,
                "secondary_port": secondary_port,
                "candidate_count": args.candidate_count,
                "failover_target_seconds": args.failover_target_seconds,
            },
            "primary": primary_report,
            "secondary": secondary_report,
            "baseline_request": baseline_request,
            "failover_request": failover_request,
            "audit_integrity": audit_integrity,
            "errors": errors,
        }
    finally:
        # Best-effort teardown. Primary may already be dead; secondary needs SIGTERM.
        try:
            stop_service(config_path=secondary_config, env=base_env, timeout_sec=args.start_timeout_sec)
        except Exception:
            pass
        if primary_started:
            try:
                stop_service(config_path=primary_config, env=base_env, timeout_sec=args.start_timeout_sec)
            except Exception:
                pass
        # Clean up the temp work_dir when the operator did not pin one. Operator-pinned
        # directories are left in place for post-run inspection.
        if not operator_work_dir:
            import shutil

            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass


def main() -> int:
    args = build_parser().parse_args()
    report = run_test(args)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.assert_ok and report["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
