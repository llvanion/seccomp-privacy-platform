# -*- coding:utf-8 _*-
import argparse
import sys
import urllib.parse

from services.record_recovery.bootstrap import ensure_repo_paths
from services.record_recovery.config import (
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_scope_value,
    merged_record_recovery_service_value,
)


REPO_ROOT, _SSE_ROOT = ensure_repo_paths()

from services.record_recovery.http_service import main as http_service_main  # noqa: E402
from services.record_recovery.service import main as unix_service_main  # noqa: E402


def _dispatch(main_fn, argv: list[str]) -> int:
    previous_argv = sys.argv
    try:
        sys.argv = argv
        return int(main_fn() or 0)
    finally:
        sys.argv = previous_argv


def _repo_path(path_value: str) -> str:
    if not path_value:
        return ""
    if path_value.startswith("/"):
        return path_value
    return str((REPO_ROOT / path_value).resolve())


def _resolved_runtime(args: argparse.Namespace) -> dict:
    config = load_resolved_record_recovery_service_config(_repo_path(args.config)) if args.config else {}
    transport = merged_record_recovery_service_value(args.transport, config.get("transport", "unix_socket"))
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
    socket_path = merged_record_recovery_service_value(args.socket_path, config.get("socket_path", ""))
    socket_mode = merged_record_recovery_service_value(args.socket_mode, config.get("socket_mode", "600"))
    endpoint_url = merged_record_recovery_service_value(args.endpoint_url, config.get("endpoint_url", ""))
    bind_host = merged_record_recovery_service_value(args.bind_host, config.get("bind_host", ""))
    port = merged_record_recovery_service_value(args.port, config.get("port", None))
    auth_token_env = merged_record_recovery_service_value(args.auth_token_env, config.get("auth_token_env", ""))
    metadata_db_path = merged_record_recovery_service_value(args.metadata_db_path, config.get("metadata_db_path", ""))
    identity_token_config = merged_record_recovery_service_value(args.identity_token_config, config.get("identity_token_config", ""))
    authz_config = merged_record_recovery_service_value(args.authz_config, config.get("authz_config", ""))
    allowed_callers = merged_record_recovery_service_value(args.allowed_caller, config.get("allowed_callers", [])) or []
    allowed_output_roots = merged_record_recovery_service_value(args.allowed_output_root, config.get("allowed_output_roots", [])) or []
    allowed_record_store_roots = merged_record_recovery_service_value(args.allowed_record_store_root, config.get("allowed_record_store_roots", [])) or []
    audit_log = merged_record_recovery_service_value(args.audit_log, config.get("audit_log", ""))
    pid_file = merged_record_recovery_service_value(args.pid_file, config.get("pid_file", ""))
    ready_file = merged_record_recovery_service_value(args.ready_file, config.get("ready_file", ""))

    if transport == "http" and endpoint_url and (not bind_host or port in (None, "")):
        parsed = urllib.parse.urlparse(endpoint_url)
        bind_host = bind_host or (parsed.hostname or "")
        port = port if port not in (None, "") else parsed.port

    return {
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
        "max_rows_per_request": int(getattr(args, "max_rows_per_request", 0) or 0),
    }


def _serve(args: argparse.Namespace) -> int:
    runtime = _resolved_runtime(args)
    if runtime["transport"] == "http":
        if not runtime["bind_host"] or runtime["port"] in (None, ""):
            raise SystemExit("[ERROR] HTTP record recovery service requires bind_host and port")
        argv = [
            "record_recovery_service_http",
            "--service-id",
            runtime["service_id"],
            "--tenant-id",
            runtime["tenant_id"],
            "--dataset-id",
            runtime["dataset_id"],
            "--bind-host",
            str(runtime["bind_host"]),
            "--port",
            str(runtime["port"]),
        ]
        if runtime["endpoint_url"]:
            argv.extend(["--endpoint-url", runtime["endpoint_url"]])
        if runtime["auth_token_env"]:
            argv.extend(["--auth-token-env", runtime["auth_token_env"]])
        if runtime["metadata_db_path"]:
            argv.extend(["--metadata-db-path", runtime["metadata_db_path"]])
        if runtime["identity_token_config"]:
            argv.extend(["--identity-token-config", runtime["identity_token_config"]])
        if runtime["authz_config"]:
            argv.extend(["--authz-config", runtime["authz_config"]])
        for caller in runtime["allowed_callers"]:
            argv.extend(["--allowed-caller", caller])
        for root in runtime["allowed_output_roots"]:
            argv.extend(["--allowed-output-root", root])
        for root in runtime["allowed_record_store_roots"]:
            argv.extend(["--allowed-record-store-root", root])
        if runtime["audit_log"]:
            argv.extend(["--audit-log", runtime["audit_log"]])
        if runtime["pid_file"]:
            argv.extend(["--pid-file", runtime["pid_file"]])
        if runtime["ready_file"]:
            argv.extend(["--ready-file", runtime["ready_file"]])
        if runtime.get("max_rows_per_request", 0) > 0:
            argv.extend(["--max-rows-per-request", str(runtime["max_rows_per_request"])])
        return _dispatch(http_service_main, argv)

    if not runtime["socket_path"]:
        raise SystemExit("[ERROR] Unix-socket record recovery service requires socket_path")
    argv = [
        "record_recovery_service_unix",
        "--service-id",
        runtime["service_id"],
        "--tenant-id",
        runtime["tenant_id"],
        "--dataset-id",
        runtime["dataset_id"],
        "--socket-path",
        runtime["socket_path"],
        "--socket-mode",
        str(runtime["socket_mode"] or "600"),
    ]
    if runtime["auth_token_env"]:
        argv.extend(["--auth-token-env", runtime["auth_token_env"]])
    if runtime["metadata_db_path"]:
        argv.extend(["--metadata-db-path", runtime["metadata_db_path"]])
    if runtime["identity_token_config"]:
        argv.extend(["--identity-token-config", runtime["identity_token_config"]])
    if runtime["authz_config"]:
        argv.extend(["--authz-config", runtime["authz_config"]])
    for caller in runtime["allowed_callers"]:
        argv.extend(["--allowed-caller", caller])
    for root in runtime["allowed_output_roots"]:
        argv.extend(["--allowed-output-root", root])
    for root in runtime["allowed_record_store_roots"]:
        argv.extend(["--allowed-record-store-root", root])
    if runtime["audit_log"]:
        argv.extend(["--audit-log", runtime["audit_log"]])
    if runtime["pid_file"]:
        argv.extend(["--pid-file", runtime["pid_file"]])
    if runtime["ready_file"]:
        argv.extend(["--ready-file", runtime["ready_file"]])
    if runtime.get("max_rows_per_request", 0) > 0:
        argv.extend(["--max-rows-per-request", str(runtime["max_rows_per_request"])])
    return _dispatch(unix_service_main, argv)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Standalone record recovery service launcher.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve")
    serve.add_argument("--config", default="")
    serve.add_argument("--transport", default="")
    serve.add_argument("--service-id", default="")
    serve.add_argument("--tenant-id", default="")
    serve.add_argument("--dataset-id", default="")
    serve.add_argument("--socket-path", default="")
    serve.add_argument("--socket-mode", default="")
    serve.add_argument("--endpoint-url", default="")
    serve.add_argument("--bind-host", default="")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--auth-token-env", default="")
    serve.add_argument("--metadata-db-path", default="")
    serve.add_argument("--identity-token-config", default="")
    serve.add_argument("--authz-config", default="")
    serve.add_argument("--allowed-caller", action="append", default=[])
    serve.add_argument("--allowed-output-root", action="append", default=[])
    serve.add_argument("--allowed-record-store-root", action="append", default=[])
    serve.add_argument("--audit-log", default="")
    serve.add_argument("--pid-file", default="")
    serve.add_argument("--ready-file", default="")
    serve.add_argument("--max-rows-per-request", type=int, default=0,
                       help="Hard cap on rows returned per recovery request (0 = unlimited)")

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    if args.cmd == "serve":
        return _serve(args)
    raise SystemExit(f"[ERROR] unsupported command: {args.cmd}")
