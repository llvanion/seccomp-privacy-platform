#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_DIR = REPO_ROOT / "sse"
SSE_PY = SSE_DIR / ".venv" / "bin" / "python"
SERVICE_PY = REPO_ROOT / "scripts" / "run_record_recovery_service.py"

sys.path.insert(0, str(SSE_DIR))
sys.path.insert(0, str(REPO_ROOT))

from services.record_recovery.config import (  # noqa: E402
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_scope_value,
    merged_record_recovery_service_value,
)
from services.record_recovery.client import request_record_recovery_health  # noqa: E402


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


def resolve_runtime(args: argparse.Namespace) -> dict:
    config = load_resolved_config(getattr(args, "config", ""))
    transport = merged_record_recovery_service_value(getattr(args, "transport", ""), config.get("transport", "unix_socket"))
    service_id = merged_record_recovery_service_scope_value(
        args.service_id,
        config.get("service_id", ""),
        field_name="service_id",
    )
    tenant_id = merged_record_recovery_service_scope_value(
        args.tenant_id,
        config.get("tenant_id", ""),
        field_name="tenant_id",
    )
    dataset_id = merged_record_recovery_service_scope_value(
        args.dataset_id,
        config.get("dataset_id", ""),
        field_name="dataset_id",
    )
    socket_path = merged_record_recovery_service_value(getattr(args, "socket_path", ""), config.get("socket_path", ""))
    socket_mode = merged_record_recovery_service_value(getattr(args, "socket_mode", ""), config.get("socket_mode", "600"))
    endpoint_url = merged_record_recovery_service_value(getattr(args, "endpoint_url", ""), config.get("endpoint_url", ""))
    bind_host = merged_record_recovery_service_value(getattr(args, "bind_host", ""), config.get("bind_host", ""))
    port = merged_record_recovery_service_value(getattr(args, "port", None), config.get("port", None))
    auth_token_env = merged_record_recovery_service_value(getattr(args, "auth_token_env", ""), config.get("auth_token_env", ""))
    metadata_db_path = merged_record_recovery_service_value(getattr(args, "metadata_db_path", ""), config.get("metadata_db_path", ""))
    identity_token_config = merged_record_recovery_service_value(getattr(args, "identity_token_config", ""), config.get("identity_token_config", ""))
    authz_config = merged_record_recovery_service_value(getattr(args, "authz_config", ""), config.get("authz_config", ""))
    allowed_callers = merged_record_recovery_service_value(getattr(args, "allowed_caller", []), config.get("allowed_callers", [])) or []
    allowed_output_roots = merged_record_recovery_service_value(getattr(args, "allowed_output_root", []), config.get("allowed_output_roots", [])) or []
    allowed_record_store_roots = merged_record_recovery_service_value(getattr(args, "allowed_record_store_root", []), config.get("allowed_record_store_roots", [])) or []
    audit_log = merged_record_recovery_service_value(getattr(args, "audit_log", ""), config.get("audit_log", ""))
    pid_file = merged_record_recovery_service_value(getattr(args, "pid_file", ""), config.get("pid_file", ""))
    ready_file = merged_record_recovery_service_value(getattr(args, "ready_file", ""), config.get("ready_file", ""))
    log_file = merged_record_recovery_service_value(getattr(args, "log_file", ""), config.get("log_file", ""))
    tls_config = config.get("tls") if isinstance(config.get("tls"), dict) else {}
    config_path = optional_path(getattr(args, "config", ""))
    if transport == "http" and endpoint_url and (not bind_host or port in (None, "")):
        parsed = urllib.parse.urlparse(endpoint_url)
        bind_host = bind_host or (parsed.hostname or "")
        port = port if port not in (None, "") else parsed.port

    return {
        "config": config,
        "config_path": config_path,
        "transport": transport,
        "service_id": service_id,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "socket_path": socket_path,
        "socket_mode": socket_mode,
        "endpoint_url": endpoint_url,
        "bind_host": bind_host,
        "port": port,
        "auth_token_env": auth_token_env,
        "metadata_db_path": metadata_db_path,
        "identity_token_config": identity_token_config,
        "authz_config": authz_config,
        "allowed_callers": list(allowed_callers),
        "allowed_output_roots": list(allowed_output_roots),
        "allowed_record_store_roots": list(allowed_record_store_roots),
        "audit_log": audit_log,
        "pid_file": pid_file,
        "ready_file": ready_file,
        "log_file": log_file,
        "tls": tls_config,
    }


def service_python_executable() -> str:
    if SSE_PY.is_file():
        return str(SSE_PY)
    return sys.executable


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


def wait_for_http_url(
    endpoint_url: str,
    *,
    auth_token_env: str,
    identity_token_env: str,
    tls_config: dict | None = None,
    timeout_sec: float = 10.0,
) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            request_record_recovery_health(
                socket_path=None,
                endpoint_url=endpoint_url,
                auth_env=auth_token_env,
                identity_auth_env=identity_token_env,
                tls_config=tls_config,
            )
            return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"record recovery service HTTP endpoint did not become ready: {endpoint_url}")


def wait_for_exit(pid: int, *, timeout_sec: float = 10.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not pid_is_running(pid):
            return
        time.sleep(0.1)
    raise RuntimeError(f"record recovery service pid did not exit: {pid}")


def build_service_command(runtime: dict) -> list[str]:
    transport = runtime["transport"]
    service_id = runtime["service_id"]
    tenant_id = runtime["tenant_id"]
    dataset_id = runtime["dataset_id"]
    socket_path = runtime["socket_path"]
    socket_mode = runtime["socket_mode"]
    endpoint_url = runtime["endpoint_url"]
    bind_host = runtime["bind_host"]
    port = runtime["port"]
    auth_token_env = runtime["auth_token_env"]
    metadata_db_path = runtime["metadata_db_path"]
    identity_token_config = runtime["identity_token_config"]
    authz_config = runtime["authz_config"]
    allowed_callers = runtime["allowed_callers"]
    allowed_output_roots = runtime["allowed_output_roots"]
    allowed_record_store_roots = runtime["allowed_record_store_roots"]
    audit_log = runtime["audit_log"]
    pid_file = runtime["pid_file"]
    ready_file = runtime["ready_file"]
    tls = runtime.get("tls") or {}

    if transport == "http":
        if not bind_host or port in (None, ""):
            raise SystemExit("[ERROR] record recovery HTTP service requires bind_host and port")
        cmd = [
            service_python_executable(),
            str(SERVICE_PY),
            "serve",
            "--transport",
            "http",
            "--service-id",
            service_id,
            "--tenant-id",
            tenant_id,
            "--dataset-id",
            dataset_id,
            "--bind-host",
            bind_host,
            "--port",
            str(port),
        ]
        if endpoint_url:
            cmd.extend(["--endpoint-url", endpoint_url])
        if tls.get("enabled"):
            cmd.extend(["--tls-cert-file", normalize_path(str(tls.get("server_cert") or ""))])
            cmd.extend(["--tls-key-file", normalize_path(str(tls.get("server_key") or ""))])
            if tls.get("ca_cert"):
                cmd.extend(["--tls-ca-cert", normalize_path(str(tls.get("ca_cert") or ""))])
            if tls.get("require_client_cert"):
                cmd.append("--tls-require-client-cert")
    else:
        if not socket_path:
            raise SystemExit("[ERROR] record recovery unix_socket service requires socket_path")
        cmd = [
            service_python_executable(),
            str(SERVICE_PY),
            "serve",
            "--transport",
            "unix_socket",
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
    if metadata_db_path:
        cmd.extend(["--metadata-db-path", normalize_path(metadata_db_path)])
    if identity_token_config:
        cmd.extend(["--identity-token-config", normalize_path(identity_token_config)])
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


def sanitize_unit_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.@-]+", "-", value).strip("-")
    return cleaned or "record-recovery"


def derived_unit_name(unit_name: str, runtime: dict) -> str:
    if unit_name:
        base = unit_name
    else:
        service_id = runtime["service_id"] or f"record-recovery-{runtime['transport']}"
        base = f"seccomp-{sanitize_unit_name(service_id)}"
    if not base.endswith(".service"):
        base += ".service"
    return base


def derived_environment_file(environment_file: str, *, unit_name: str, environment_variables: list[str]) -> str:
    if environment_file:
        return environment_file
    if not environment_variables:
        return ""
    return str(Path("/etc/seccomp") / f"{unit_name.removesuffix('.service')}.env")


def build_environment_template(environment_variables: list[str], *, unit_name: str) -> str:
    lines = [
        f"# Environment file for {unit_name}",
        "# Fill in real secret values before enabling the unit.",
    ]
    if environment_variables:
        for variable_name in environment_variables:
            lines.append(f"{variable_name}=CHANGE_ME")
    else:
        lines.append("# No startup environment variables are required by the current config.")
    return "\n".join(lines) + "\n"


def format_systemd_execstart(command: list[str]) -> str:
    return shlex.join(command)


def derive_writable_paths(runtime: dict) -> list[str]:
    """Return the set of directories the service must write to.

    Used to populate ReadWritePaths= when ProtectSystem=strict is in effect.
    Includes parent dirs of lifecycle files, the socket dir, audit log dir, and
    any explicitly allowed output root directories.
    """
    dirs: list[str] = []
    seen: set[str] = set()

    def _add(path_value: str) -> None:
        if not path_value:
            return
        p = Path(path_value)
        candidate = str(p.parent if p.suffix or p.name else p)
        if candidate and candidate not in seen:
            seen.add(candidate)
            dirs.append(candidate)

    _add(runtime.get("audit_log", ""))
    _add(runtime.get("socket_path", ""))
    _add(runtime.get("pid_file", ""))
    _add(runtime.get("ready_file", ""))
    for root in runtime.get("allowed_output_roots", []):
        _add(str(root) + "/")  # trailing slash ensures the dir itself is added
    return dirs


def build_systemd_unit(
    *,
    runtime: dict,
    command: list[str],
    description: str,
    unit_name: str,
    service_user: str,
    service_group: str,
    working_directory: str,
    environment_file: str,
    restart: str,
    restart_sec: float,
) -> str:
    resolved_workdir = normalize_path(working_directory)
    writable_paths = derive_writable_paths(runtime)
    lines = [
        "[Unit]",
        f"Description={description}",
    ]
    if runtime["transport"] == "http":
        lines.extend(
            [
                "After=network-online.target",
                "Wants=network-online.target",
            ]
        )
    lines.extend(
        [
            "",
            "[Service]",
            "Type=simple",
            f"User={service_user}",
            f"Group={service_group}",
            f"WorkingDirectory={resolved_workdir}",
            "UMask=0077",
            # Privilege and filesystem hardening
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "PrivateDevices=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "LockPersonality=true",
            "RestrictSUIDSGID=true",
            "SystemCallFilter=@system-service",
        ]
    )
    if writable_paths:
        lines.append(f"ReadWritePaths={' '.join(writable_paths)}")
    if environment_file:
        lines.append(f"EnvironmentFile={environment_file}")
    lines.extend(
        [
            f"ExecStart={format_systemd_execstart(command)}",
            "StandardOutput=journal",
            "StandardError=journal",
            f"Restart={restart}",
            f"RestartSec={restart_sec:g}",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )
    return "\n".join(lines)


def write_text_output(path_value: str, text: str) -> str:
    output_path = Path(path_value)
    if not output_path.is_absolute():
        output_path = (REPO_ROOT / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return str(output_path)


def status_payload(
    *,
    socket_path: str,
    endpoint_url: str,
    auth_token_env: str,
    identity_token_env: str,
    pid_file: str,
    ready_file: str,
    tls_config: dict | None = None,
) -> dict:
    payload = {
        "socket_path": normalize_path(socket_path) if socket_path else None,
        "endpoint_url": endpoint_url or None,
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
            socket_path=Path(normalize_path(socket_path)) if socket_path else None,
            endpoint_url=endpoint_url,
            auth_env=auth_token_env,
            identity_auth_env=identity_token_env,
            tls_config=tls_config,
        )
        payload["health"] = health
        payload["reachable"] = True
    except Exception as e:
        payload["health"] = None
        payload["reachable"] = False
        payload["error"] = str(e)
    return payload


def cmd_start(args: argparse.Namespace) -> int:
    runtime = resolve_runtime(args)
    config = runtime["config"]
    if not SERVICE_PY.is_file():
        raise SystemExit(f"[ERROR] missing standalone record recovery launcher: {SERVICE_PY}")
    transport = runtime["transport"]
    socket_path = normalize_path(runtime["socket_path"]) if runtime["socket_path"] else ""
    endpoint_url = runtime["endpoint_url"]
    pid_file = optional_path(runtime["pid_file"])
    ready_file = optional_path(runtime["ready_file"])
    log_file = optional_path(runtime["log_file"])
    if transport == "unix_socket" and not socket_path:
        raise SystemExit("[ERROR] --socket-path or --config with socket_path is required")
    if transport == "http" and not endpoint_url:
        raise SystemExit("[ERROR] --endpoint-url or --config with endpoint_url/http_listener is required")
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
            build_service_command(runtime),
            cwd=str(SSE_DIR),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
        if transport == "http":
            wait_for_http_url(
                endpoint_url,
                auth_token_env=runtime["auth_token_env"],
                identity_token_env=args.identity_token_env,
                tls_config=runtime.get("tls") or None,
                timeout_sec=args.timeout_sec,
            )
        else:
            wait_for_socket(socket_path, timeout_sec=args.timeout_sec)
        result = status_payload(
            socket_path=socket_path,
            endpoint_url=endpoint_url,
            auth_token_env=runtime["auth_token_env"],
            identity_token_env=args.identity_token_env,
            pid_file=pid_file,
            ready_file=ready_file,
            tls_config=runtime.get("tls") or None,
        )
        result["started_pid"] = proc.pid
        result["log_file"] = log_file or None
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        log_handle.close()


def cmd_status(args: argparse.Namespace) -> int:
    runtime = resolve_runtime(args)
    endpoint_url = runtime["endpoint_url"]
    socket_path = runtime["socket_path"]
    if not socket_path and not endpoint_url:
        raise SystemExit("[ERROR] --socket-path / --endpoint-url or --config with one of them is required")
    result = status_payload(
        socket_path=socket_path,
        endpoint_url=endpoint_url,
        auth_token_env=runtime["auth_token_env"],
        identity_token_env=args.identity_token_env,
        pid_file=runtime["pid_file"],
        ready_file=runtime["ready_file"],
        tls_config=runtime.get("tls") or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("reachable") else 1


def cmd_stop(args: argparse.Namespace) -> int:
    runtime = resolve_runtime(args)
    pid_file = optional_path(runtime["pid_file"])
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
        "socket_path": normalize_path(runtime["socket_path"]) if runtime["socket_path"] else None,
        "endpoint_url": runtime["endpoint_url"] or None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_render_systemd(args: argparse.Namespace) -> int:
    runtime = resolve_runtime(args)
    command = build_service_command(runtime)
    unit_name = derived_unit_name(args.unit_name, runtime)
    description = args.description or (
        f"Seccomp record recovery service ({runtime['service_id'] or runtime['transport']})"
    )
    service_user = args.service_user.strip() or "record-recovery"
    service_group = args.service_group.strip() or service_user
    environment_variables: list[str] = []
    if runtime["auth_token_env"]:
        environment_variables.append(runtime["auth_token_env"])
    environment_file = derived_environment_file(
        args.environment_file,
        unit_name=unit_name,
        environment_variables=environment_variables,
    )
    unit_text = build_systemd_unit(
        runtime=runtime,
        command=command,
        description=description,
        unit_name=unit_name,
        service_user=service_user,
        service_group=service_group,
        working_directory=args.working_directory,
        environment_file=environment_file,
        restart=args.restart,
        restart_sec=args.restart_sec,
    )
    env_text = build_environment_template(environment_variables, unit_name=unit_name)
    output_path = write_text_output(args.output, unit_text) if args.output else ""
    env_output_path = write_text_output(args.env_output, env_text) if args.env_output else ""
    notes = []
    if runtime["log_file"]:
        notes.append(
            "lifecycle.log_file is only used by the local manager start command; under systemd, service stdout/stderr go to journald."
        )
    if runtime["config_path"]:
        notes.append("The generated unit preserves the current config/runtime contract by calling the existing standalone launcher.")
    result = {
        "unit_name": unit_name,
        "transport": runtime["transport"],
        "service_id": runtime["service_id"] or None,
        "config_path": runtime["config_path"] or None,
        "exec_start": format_systemd_execstart(command),
        "working_directory": normalize_path(args.working_directory),
        "service_user": service_user,
        "service_group": service_group,
        "environment_file": environment_file or None,
        "environment_variables": environment_variables,
        "read_write_paths": derive_writable_paths(runtime),
        "unit_output": output_path or None,
        "env_output": env_output_path or None,
        "notes": notes,
        "unit_text": unit_text,
        "env_text": env_text,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage the record recovery service lifecycle outside the pipeline auto-start path.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("start")
    start.add_argument("--config", default="")
    start.add_argument("--service-id", default="")
    start.add_argument("--tenant-id", default="")
    start.add_argument("--dataset-id", default="")
    start.add_argument("--transport", default="")
    start.add_argument("--socket-path", default="")
    start.add_argument("--socket-mode", default="")
    start.add_argument("--endpoint-url", default="")
    start.add_argument("--bind-host", default="")
    start.add_argument("--port", type=int, default=None)
    start.add_argument("--auth-token-env", default="")
    start.add_argument("--identity-token-env", default="")
    start.add_argument("--metadata-db-path", default="")
    start.add_argument("--identity-token-config", default="")
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
    status.add_argument("--endpoint-url", default="")
    status.add_argument("--auth-token-env", default="")
    status.add_argument("--identity-token-env", default="")
    status.add_argument("--pid-file", default="")
    status.add_argument("--ready-file", default="")

    stop = sub.add_parser("stop")
    stop.add_argument("--config", default="")
    stop.add_argument("--service-id", default="")
    stop.add_argument("--tenant-id", default="")
    stop.add_argument("--dataset-id", default="")
    stop.add_argument("--pid-file", default="")
    stop.add_argument("--socket-path", default="")
    stop.add_argument("--endpoint-url", default="")
    stop.add_argument("--timeout-sec", type=float, default=10.0)

    render = sub.add_parser("render-systemd")
    render.add_argument("--config", default="")
    render.add_argument("--service-id", default="")
    render.add_argument("--tenant-id", default="")
    render.add_argument("--dataset-id", default="")
    render.add_argument("--transport", default="")
    render.add_argument("--socket-path", default="")
    render.add_argument("--socket-mode", default="")
    render.add_argument("--endpoint-url", default="")
    render.add_argument("--bind-host", default="")
    render.add_argument("--port", type=int, default=None)
    render.add_argument("--auth-token-env", default="")
    render.add_argument("--metadata-db-path", default="")
    render.add_argument("--identity-token-config", default="")
    render.add_argument("--authz-config", default="")
    render.add_argument("--allowed-caller", action="append", default=[])
    render.add_argument("--allowed-output-root", action="append", default=[])
    render.add_argument("--allowed-record-store-root", action="append", default=[])
    render.add_argument("--audit-log", default="")
    render.add_argument("--pid-file", default="")
    render.add_argument("--ready-file", default="")
    render.add_argument("--log-file", default="")
    render.add_argument("--unit-name", default="")
    render.add_argument("--description", default="")
    render.add_argument("--service-user", default="record-recovery")
    render.add_argument("--service-group", default="")
    render.add_argument("--working-directory", default=str(REPO_ROOT))
    render.add_argument("--environment-file", default="")
    render.add_argument("--restart", default="on-failure")
    render.add_argument("--restart-sec", type=float, default=2.0)
    render.add_argument("--output", default="")
    render.add_argument("--env-output", default="")

    args = ap.parse_args()
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "stop":
        return cmd_stop(args)
    return cmd_render_systemd(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
