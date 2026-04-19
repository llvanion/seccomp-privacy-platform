#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_DIR = REPO_ROOT / "sse"
SSE_PY = SSE_DIR / ".venv" / "bin" / "python"

sys.path.insert(0, str(SSE_DIR))

from toolkit.record_recovery_client import request_record_recovery_health  # noqa: E402
from toolkit.record_recovery_service_config import (  # noqa: E402
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_value,
)


def normalize_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((REPO_ROOT / path).resolve())


def optional_path(path_value: str) -> str:
    if not path_value:
        return ""
    return normalize_path(path_value)


def load_resolved_config(config_path: str) -> dict:
    if not config_path:
        return {}
    return load_resolved_record_recovery_service_config(optional_path(config_path))


def read_pid(pid_file: str) -> Optional[int]:
    path = Path(pid_file)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return int(raw)


def pid_is_running(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_socket(socket_path: str, *, timeout_sec: float = 10.0) -> None:
    deadline = time.time() + timeout_sec
    path = Path(socket_path)
    while time.time() < deadline:
        if path.exists() and path.is_socket():
            return
        time.sleep(0.1)
    raise RuntimeError(f"record recovery service socket did not become ready: {socket_path}")


def wait_for_exit(pid: int, *, timeout_sec: float = 10.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not pid_is_running(pid):
            return
        time.sleep(0.1)
    raise RuntimeError(f"record recovery service pid did not exit: {pid}")


def build_service_command(args: argparse.Namespace) -> list[str]:
    config = load_resolved_config(getattr(args, "config", ""))
    service_id = merged_record_recovery_service_value(args.service_id, config.get("service_id", ""))
    tenant_id = merged_record_recovery_service_value(args.tenant_id, config.get("tenant_id", ""))
    dataset_id = merged_record_recovery_service_value(args.dataset_id, config.get("dataset_id", ""))
    socket_path = merged_record_recovery_service_value(args.socket_path, config.get("socket_path", ""))
    socket_mode = merged_record_recovery_service_value(args.socket_mode, config.get("socket_mode", "600"))
    auth_token_env = merged_record_recovery_service_value(args.auth_token_env, config.get("auth_token_env", ""))
    authz_config = merged_record_recovery_service_value(args.authz_config, config.get("authz_config", ""))
    allowed_callers = merged_record_recovery_service_value(args.allowed_caller, config.get("allowed_callers", [])) or []
    allowed_output_roots = merged_record_recovery_service_value(args.allowed_output_root, config.get("allowed_output_roots", [])) or []
    allowed_record_store_roots = merged_record_recovery_service_value(args.allowed_record_store_root, config.get("allowed_record_store_roots", [])) or []
    audit_log = merged_record_recovery_service_value(args.audit_log, config.get("audit_log", ""))
    pid_file = merged_record_recovery_service_value(args.pid_file, config.get("pid_file", ""))
    ready_file = merged_record_recovery_service_value(args.ready_file, config.get("ready_file", ""))

    cmd = [
        str(SSE_PY),
        "run_client.py",
        "serve-record-recovery",
        "--service-id",
        service_id,
        "--tenant-id",
        tenant_id,
        "--dataset-id",
        dataset_id,
        "--socket-path",
        normalize_path(socket_path),
        "--socket-mode",
        socket_mode,
    ]
    if auth_token_env:
        cmd.extend(["--auth-token-env", auth_token_env])
    if authz_config:
        cmd.extend(["--authz-config", authz_config])
    for caller in allowed_callers:
        cmd.extend(["--allowed-caller", caller])
    for root in allowed_output_roots:
        cmd.extend(["--allowed-output-root", normalize_path(root)])
    for root in allowed_record_store_roots:
        cmd.extend(["--allowed-record-store-root", normalize_path(root)])
    if audit_log:
        cmd.extend(["--audit-log", normalize_path(audit_log)])
    if pid_file:
        cmd.extend(["--pid-file", normalize_path(pid_file)])
    if ready_file:
        cmd.extend(["--ready-file", normalize_path(ready_file)])
    return cmd


def status_payload(*, socket_path: str, auth_token_env: str, pid_file: str, ready_file: str) -> dict:
    payload = {
        "socket_path": normalize_path(socket_path),
        "pid_file": optional_path(pid_file) or None,
        "ready_file": optional_path(ready_file) or None,
    }
    if pid_file:
        pid = read_pid(normalize_path(pid_file))
        payload["pid"] = pid
        payload["pid_running"] = pid_is_running(pid)
    else:
        payload["pid"] = None
        payload["pid_running"] = None
    if ready_file:
        payload["ready_file_exists"] = Path(normalize_path(ready_file)).is_file()
    else:
        payload["ready_file_exists"] = None
    try:
        health = request_record_recovery_health(
            socket_path=Path(normalize_path(socket_path)),
            auth_env=auth_token_env,
        )
        payload["health"] = health
        payload["reachable"] = True
    except Exception as e:
        payload["health"] = None
        payload["reachable"] = False
        payload["error"] = str(e)
    return payload


def cmd_start(args: argparse.Namespace) -> int:
    config = load_resolved_config(args.config)
    if not SSE_PY.is_file():
        raise SystemExit(f"[ERROR] missing SSE python: {SSE_PY}")
    socket_path = normalize_path(merged_record_recovery_service_value(args.socket_path, config.get("socket_path", "")))
    pid_file = optional_path(merged_record_recovery_service_value(args.pid_file, config.get("pid_file", "")))
    ready_file = optional_path(merged_record_recovery_service_value(args.ready_file, config.get("ready_file", "")))
    log_file = optional_path(merged_record_recovery_service_value(args.log_file, config.get("log_file", "")))
    if not socket_path:
        raise SystemExit("[ERROR] --socket-path or --config with socket_path is required")
    if not pid_file:
        raise SystemExit("[ERROR] --pid-file or --config with lifecycle.pid_file is required")

    if pid_file:
        existing_pid = read_pid(pid_file)
        if pid_is_running(existing_pid):
            raise SystemExit(f"[ERROR] record recovery service already running with pid {existing_pid}")

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "a", encoding="utf-8")
    else:
        log_handle = open(os.devnull, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            build_service_command(args),
            cwd=str(SSE_DIR),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
        wait_for_socket(socket_path, timeout_sec=args.timeout_sec)
        result = status_payload(
            socket_path=socket_path,
            auth_token_env=merged_record_recovery_service_value(args.auth_token_env, config.get("auth_token_env", "")),
            pid_file=pid_file,
            ready_file=ready_file,
        )
        result["started_pid"] = proc.pid
        result["log_file"] = log_file or None
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        log_handle.close()


def cmd_status(args: argparse.Namespace) -> int:
    config = load_resolved_config(args.config)
    socket_path = merged_record_recovery_service_value(args.socket_path, config.get("socket_path", ""))
    if not socket_path:
        raise SystemExit("[ERROR] --socket-path or --config with socket_path is required")
    result = status_payload(
        socket_path=socket_path,
        auth_token_env=merged_record_recovery_service_value(args.auth_token_env, config.get("auth_token_env", "")),
        pid_file=merged_record_recovery_service_value(args.pid_file, config.get("pid_file", "")),
        ready_file=merged_record_recovery_service_value(args.ready_file, config.get("ready_file", "")),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("reachable") else 1


def cmd_stop(args: argparse.Namespace) -> int:
    config = load_resolved_config(args.config)
    pid_file = optional_path(merged_record_recovery_service_value(args.pid_file, config.get("pid_file", "")))
    if not pid_file:
        raise SystemExit("[ERROR] --pid-file is required for stop")
    pid = read_pid(pid_file)
    if pid is None:
        raise SystemExit(f"[ERROR] record recovery service pid file not found or empty: {pid_file}")
    if not pid_is_running(pid):
        raise SystemExit(f"[ERROR] record recovery service pid is not running: {pid}")

    os.kill(pid, signal.SIGTERM)
    wait_for_exit(pid, timeout_sec=args.timeout_sec)
    result = {
        "stopped_pid": pid,
        "pid_file": pid_file,
        "socket_path": normalize_path(merged_record_recovery_service_value(args.socket_path, config.get("socket_path", ""))) if merged_record_recovery_service_value(args.socket_path, config.get("socket_path", "")) else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage the Unix-socket record recovery service lifecycle outside the pipeline auto-start path.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("start")
    start.add_argument("--config", default="")
    start.add_argument("--service-id", default="")
    start.add_argument("--tenant-id", default="")
    start.add_argument("--dataset-id", default="")
    start.add_argument("--socket-path", default="")
    start.add_argument("--socket-mode", default="")
    start.add_argument("--auth-token-env", default="")
    start.add_argument("--authz-config", default="")
    start.add_argument("--allowed-caller", action="append", default=[])
    start.add_argument("--allowed-output-root", action="append", default=[])
    start.add_argument("--allowed-record-store-root", action="append", default=[])
    start.add_argument("--audit-log", default="")
    start.add_argument("--pid-file", default="")
    start.add_argument("--ready-file", default="")
    start.add_argument("--log-file", default="")
    start.add_argument("--timeout-sec", type=float, default=10.0)

    status = sub.add_parser("status")
    status.add_argument("--config", default="")
    status.add_argument("--service-id", default="")
    status.add_argument("--tenant-id", default="")
    status.add_argument("--dataset-id", default="")
    status.add_argument("--socket-path", default="")
    status.add_argument("--auth-token-env", default="")
    status.add_argument("--pid-file", default="")
    status.add_argument("--ready-file", default="")

    stop = sub.add_parser("stop")
    stop.add_argument("--config", default="")
    stop.add_argument("--service-id", default="")
    stop.add_argument("--tenant-id", default="")
    stop.add_argument("--dataset-id", default="")
    stop.add_argument("--pid-file", default="")
    stop.add_argument("--socket-path", default="")
    stop.add_argument("--timeout-sec", type=float, default=10.0)

    args = ap.parse_args()
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "status":
        return cmd_status(args)
    return cmd_stop(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
