# -*- coding:utf-8 _*-
import argparse
import hashlib
import json
import os
import signal
import socketserver
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from toolkit.encrypted_record_store import iter_candidate_rows
from toolkit.record_recovery_authz import (
    authz_policy_path,
    authorize_record_recovery_request,
    load_authz_policy,
)
from toolkit.record_recovery_common import (
    ERROR_SCHEMA,
    build_health_result,
    build_error,
    build_result,
    enforce_row_limits,
    parse_candidate_payload,
    select_bridge_rows,
    write_selected_rows,
)


def _path_within_roots(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


class RecordRecoveryUnixStreamServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self,
                 socket_path: str,
                 handler,
                 *,
                 service_id: str,
                 tenant_id: str,
                 dataset_id: str,
                 auth_token: str,
                 allowed_callers: set[str],
                 authz_policy: dict,
                 authz_policy_path_value: str | None,
                 allowed_output_roots: list[Path],
                 allowed_record_store_roots: list[Path],
                 audit_log: Path | None):
        self.service_id = service_id
        self.tenant_id = tenant_id
        self.dataset_id = dataset_id
        self.auth_token = auth_token
        self.allowed_callers = allowed_callers
        self.authz_policy = authz_policy
        self.authz_policy_path_value = authz_policy_path_value
        self.allowed_output_roots = allowed_output_roots
        self.allowed_record_store_roots = allowed_record_store_roots
        self.audit_log = audit_log
        super().__init__(socket_path, handler)


class RecordRecoveryRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.read()
        if not raw:
            return

        try:
            payload = json.loads(raw.decode("utf-8"))
            result = _handle_request(payload, self.server)
            if str(payload.get("op", "recover") or "recover") == "recover":
                _append_service_audit(
                    server=self.server,
                    payload=payload,
                    result=result,
                    decision="allow",
                    reason_code="ok",
                    reason="ok",
                )
        except Exception as e:
            result = build_error(message=str(e))
            payload_for_audit = payload if "payload" in locals() and isinstance(payload, dict) else {}
            if str(payload_for_audit.get("op", "recover") or "recover") == "recover":
                _append_service_audit(
                    server=self.server,
                    payload=payload_for_audit,
                    result=None,
                    decision="deny",
                    reason_code="service_request_failed",
                    reason=str(e),
                )

        self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        self.wfile.flush()


def _handle_request(payload: dict, server: RecordRecoveryUnixStreamServer) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("record recovery service request must be a JSON object")

    op = str(payload.get("op", "recover") or "recover")
    if server.auth_token:
        provided = str(payload.get("auth_token", ""))
        if not provided or provided != server.auth_token:
            raise PermissionError("record recovery service auth failed")
    if op == "health":
        return build_health_result(
            service_id=server.service_id,
            tenant_id=server.tenant_id,
            dataset_id=server.dataset_id,
            socket_path=str(server.server_address),
            auth_required=bool(server.auth_token),
            authz_policy_config=server.authz_policy_path_value,
            allowed_callers=sorted(server.allowed_callers),
            allowed_output_roots=[str(root.resolve()) for root in server.allowed_output_roots],
            allowed_record_store_roots=[str(root.resolve()) for root in server.allowed_record_store_roots],
            audit_log=str(server.audit_log.resolve()) if server.audit_log is not None else None,
            pid=os.getpid(),
        )
    if op != "recover":
        raise ValueError(f"unsupported record recovery service op: {op}")

    caller = str(payload.get("caller", ""))
    tenant_id = str(payload.get("tenant_id", "")).strip()
    dataset_id = str(payload.get("dataset_id", "")).strip()
    service_id = str(payload.get("service_id", "")).strip()
    if server.allowed_callers and caller not in server.allowed_callers:
        raise PermissionError(f"caller {caller or '<missing>'} is not allowed to use record recovery service")
    if server.service_id and service_id and service_id != server.service_id:
        raise PermissionError(f"service_id {service_id} does not match service instance {server.service_id}")
    if server.service_id and not service_id:
        service_id = server.service_id
    if server.tenant_id and tenant_id and tenant_id != server.tenant_id:
        raise PermissionError(f"tenant_id {tenant_id} does not match service tenant {server.tenant_id}")
    if server.tenant_id and not tenant_id:
        tenant_id = server.tenant_id
    if server.dataset_id and dataset_id and dataset_id != server.dataset_id:
        raise PermissionError(f"dataset_id {dataset_id} does not match service dataset {server.dataset_id}")
    if server.dataset_id and not dataset_id:
        dataset_id = server.dataset_id

    candidate_ids, filters = parse_candidate_payload(payload)
    record_store_path_value = str(payload.get("record_store_path", "")).strip()
    record_store_key_env = str(payload.get("record_store_key_env", ""))
    out_path_value = str(payload.get("out_path", "")).strip()
    out_format = str(payload.get("out_format", "csv"))
    role = str(payload.get("role", ""))
    join_key_field = str(payload.get("join_key_field", ""))
    value_field = str(payload.get("value_field", ""))
    min_output_rows = payload.get("min_output_rows")
    max_output_rows = payload.get("max_output_rows")

    if not record_store_path_value:
        raise ValueError("record_store_path is required")
    if not out_path_value:
        raise ValueError("out_path is required")
    if out_format not in {"jsonl", "csv"}:
        raise ValueError("out_format must be jsonl or csv")
    if role not in {"server", "client"}:
        raise ValueError("role must be server or client")
    if not join_key_field:
        raise ValueError("join_key_field is required")
    if role == "client" and not value_field:
        raise ValueError("value_field is required for client role")
    record_store_path = Path(record_store_path_value)
    out_path = Path(out_path_value)
    if server.allowed_output_roots and not _path_within_roots(out_path, server.allowed_output_roots):
        raise PermissionError(f"output path {out_path} is outside allowed output roots")
    if server.allowed_record_store_roots and not _path_within_roots(record_store_path, server.allowed_record_store_roots):
        raise PermissionError(f"record store path {record_store_path} is outside allowed record-store roots")
    effective_min_rows, effective_max_rows = authorize_record_recovery_request(
        policy=server.authz_policy,
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
        role=role,
        join_key_field=join_key_field,
        value_field=value_field,
        filters=filters,
        candidate_count=len(candidate_ids),
        requested_min_output_rows=int(min_output_rows) if min_output_rows is not None else None,
        requested_max_output_rows=int(max_output_rows) if max_output_rows is not None else None,
        record_store_path=record_store_path,
        out_path=out_path,
    )

    rows = iter_candidate_rows(
        store_path=record_store_path,
        key_env=record_store_key_env,
        candidate_ids=candidate_ids,
    )
    input_rows, selected_rows = select_bridge_rows(
        rows=rows,
        role=role,
        join_key_field=join_key_field,
        value_field=value_field,
        filters=filters,
    )
    enforce_row_limits(
        output_rows=len(selected_rows),
        min_rows=effective_min_rows,
        max_rows=effective_max_rows,
    )
    output_sha256 = write_selected_rows(
        rows=selected_rows,
        out_path=out_path,
        out_format=out_format,
        role=role,
        join_key_field=join_key_field,
        value_field=value_field,
    )
    return build_result(
        input_rows=input_rows,
        output_rows=len(selected_rows),
        output_sha256=output_sha256,
        candidate_count=len(candidate_ids),
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _path_file_type(path: Path | None) -> str:
    if not path:
        return "missing"
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISFIFO(mode):
        return "fifo"
    return "other"


def _append_service_audit(*,
                          server: RecordRecoveryUnixStreamServer,
                          payload: dict,
                          result: dict | None,
                          decision: str,
                          reason_code: str,
                          reason: str) -> None:
    if server.audit_log is None:
        return

    audit_log = server.audit_log
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    caller = str(payload.get("caller", "")) or "unknown"
    job_id = str(payload.get("job_id", "")) or None
    out_path_raw = str(payload.get("out_path", ""))
    record_store_raw = str(payload.get("record_store_path", ""))
    out_path = Path(out_path_raw) if out_path_raw else None
    record_store_path = Path(record_store_raw) if record_store_raw else None
    filters = payload.get("filters", [])
    if not isinstance(filters, list):
        filters = []

    record = {
        "schema": "sse_record_recovery_service_audit/v1",
        "ts_utc": _utc_now_iso(),
        "event": "record_recovery_service_request",
        "service_id": server.service_id or (str(payload.get("service_id", "")) or None),
        "tenant_id": server.tenant_id or (str(payload.get("tenant_id", "")) or None),
        "dataset_id": server.dataset_id or (str(payload.get("dataset_id", "")) or None),
        "caller": caller,
        "correlation_id": job_id,
        "job_id": job_id,
        "role": str(payload.get("role", "")) or "unknown",
        "auth_mode": "env_token" if server.auth_token else "socket_acl_only",
        "socket_path": str(server.server_address),
        "authz_policy_config": server.authz_policy_path_value,
        "record_store_file": str(record_store_path.resolve()) if record_store_path else None,
        "record_store_sha256": _sha256_file(record_store_path),
        "output_file": str(out_path.resolve()) if out_path else None,
        "output_file_type": _path_file_type(out_path),
        "output_sha256": result.get("output_sha256") if result is not None else _sha256_file(out_path),
        "join_key_field": str(payload.get("join_key_field", "")) or None,
        "value_field": str(payload.get("value_field", "")) or None,
        "candidate_count": len(payload.get("candidate_ids", [])) if isinstance(payload.get("candidate_ids"), list) else None,
        "filters": [
            {
                "field": str(item[0]),
                "value_sha256": hashlib.sha256(str(item[1]).encode("utf-8")).hexdigest(),
            }
            for item in filters
            if isinstance(item, list) and len(item) == 2
        ],
        "input_rows": result.get("input_rows") if result is not None else None,
        "output_rows": result.get("output_rows") if result is not None else None,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
    }
    with audit_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_optional_env(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name)
    if not value:
        raise ValueError(f"environment variable {env_name} is not set")
    return value


def _parse_socket_mode(raw: str) -> int:
    try:
        return int(raw, 8)
    except ValueError as exc:
        raise ValueError(f"invalid socket mode {raw!r}; expected octal like 600") from exc


def _write_text_file(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _raise_keyboard_interrupt(_signum, _frame) -> None:
    raise KeyboardInterrupt()


def main() -> int:
    ap = argparse.ArgumentParser(description="Long-running Unix-socket service for controlled record-store recovery.")
    ap.add_argument("--service-id", default="")
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    ap.add_argument("--socket-path", required=True)
    ap.add_argument("--socket-mode", default="600")
    ap.add_argument("--auth-token-env", default="")
    ap.add_argument("--allowed-caller", action="append", default=[])
    ap.add_argument("--authz-config", default="")
    ap.add_argument("--allowed-output-root", action="append", default=[])
    ap.add_argument("--allowed-record-store-root", action="append", default=[])
    ap.add_argument("--audit-log", default="")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    args = ap.parse_args()

    socket_path = Path(args.socket_path)
    pid_file = Path(args.pid_file) if args.pid_file else None
    ready_file = Path(args.ready_file) if args.ready_file else None
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    server = RecordRecoveryUnixStreamServer(
        str(socket_path),
        RecordRecoveryRequestHandler,
        service_id=str(args.service_id or ""),
        tenant_id=str(args.tenant_id or ""),
        dataset_id=str(args.dataset_id or ""),
        auth_token=_read_optional_env(args.auth_token_env),
        allowed_callers={str(item) for item in args.allowed_caller},
        authz_policy=load_authz_policy(args.authz_config),
        authz_policy_path_value=authz_policy_path(args.authz_config),
        allowed_output_roots=[Path(root) for root in args.allowed_output_root],
        allowed_record_store_roots=[Path(root) for root in args.allowed_record_store_root],
        audit_log=Path(args.audit_log) if args.audit_log else None,
    )
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    os.chmod(socket_path, _parse_socket_mode(args.socket_mode))
    _write_text_file(pid_file, f"{os.getpid()}\n")
    _write_text_file(ready_file, str(socket_path.resolve()) + "\n")

    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        if socket_path.exists():
            socket_path.unlink()
        if ready_file is not None and ready_file.exists():
            ready_file.unlink()
        if pid_file is not None and pid_file.exists():
            pid_file.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
