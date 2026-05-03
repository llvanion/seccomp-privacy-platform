# -*- coding:utf-8 _*-
import argparse
import hmac
import hashlib
import json
import os
import signal
import socketserver
import stat
from datetime import datetime, timezone
from pathlib import Path

from services.record_recovery.bootstrap import ensure_repo_paths
from services.record_recovery.common import (
    REQUEST_SIGNATURE_ALGORITHM,
    validate_request_timestamp,
    verify_request_signature,
)
from services.record_recovery.observability import (
    elapsed_ms,
    emit_structured_service_log,
    new_request_id,
    start_timer,
)
from services.record_recovery.runtime import (
    RecordRecoveryServiceState,
    build_service_state,
    parse_socket_mode,
    write_text_file,
)
from api_identity import resolve_identity_context


ensure_repo_paths()

from services.record_recovery.encrypted_record_store import iter_candidate_rows  # noqa: E402
from services.record_recovery.authz import authorize_record_recovery_request  # noqa: E402
from services.record_recovery.common import (  # noqa: E402
    build_error,
    build_health_result,
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

    def __init__(
        self,
        socket_path: str,
        handler,
        *,
        service_state: RecordRecoveryServiceState,
    ):
        self.service_id = service_state.service_id
        self.tenant_id = service_state.tenant_id
        self.dataset_id = service_state.dataset_id
        self.auth_token = service_state.auth_token
        self.metadata_db_path = service_state.metadata_db_path
        self.identity_token_config = service_state.identity_token_config
        self.allowed_callers = service_state.allowed_callers
        self.authz_policy = service_state.authz_policy
        self.authz_policy_path_value = service_state.authz_policy_path_value
        self.allowed_output_roots = service_state.allowed_output_roots
        self.allowed_record_store_roots = service_state.allowed_record_store_roots
        self.audit_log = service_state.audit_log
        self.transport = service_state.transport
        self.endpoint_url = service_state.endpoint_url
        self.socket_path = service_state.socket_path or socket_path
        self.max_rows_per_request = service_state.max_rows_per_request
        super().__init__(socket_path, handler)


class RecordRecoveryRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        started_at = start_timer()
        request_id = new_request_id()
        op = "recover"
        decision = "allow"
        reason_code = "ok"
        caller = None
        job_id = None
        role = None
        candidate_count = None
        raw = self.rfile.read()
        if not raw:
            emit_structured_service_log(
                "record_recovery_service_request",
                self.server,
                request_id=request_id,
                op="empty",
                decision="deny",
                reason_code="empty_request",
                duration_ms=elapsed_ms(started_at),
            )
            return

        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                op = str(payload.get("op", "recover") or "recover")
                caller = str(payload.get("caller", "")) or None
                job_id = str(payload.get("job_id", "")) or None
                role = str(payload.get("role", "")) or None
                if isinstance(payload.get("candidate_ids"), list):
                    candidate_count = len(payload.get("candidate_ids", []))
            result = handle_record_recovery_service_payload(payload, self.server)
            if str(payload.get("op", "recover") or "recover") == "recover":
                append_record_recovery_service_audit(
                    service_state=self.server,
                    payload=payload,
                    result=result,
                    duration_ms=elapsed_ms(started_at),
                    decision="allow",
                    reason_code="ok",
                    reason="ok",
                )
        except Exception as e:
            decision = "deny"
            reason_code = "service_request_failed"
            result = build_error(message=str(e))
            payload_for_audit = payload if "payload" in locals() and isinstance(payload, dict) else {}
            caller = caller or (str(payload_for_audit.get("caller", "")) or None)
            job_id = job_id or (str(payload_for_audit.get("job_id", "")) or None)
            role = role or (str(payload_for_audit.get("role", "")) or None)
            if candidate_count is None and isinstance(payload_for_audit.get("candidate_ids"), list):
                candidate_count = len(payload_for_audit.get("candidate_ids", []))
            if str(payload_for_audit.get("op", "recover") or "recover") == "recover":
                append_record_recovery_service_audit(
                    service_state=self.server,
                    payload=payload_for_audit,
                    result=None,
                    duration_ms=elapsed_ms(started_at),
                    decision="deny",
                    reason_code="service_request_failed",
                    reason=str(e),
                )

        self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        self.wfile.flush()
        emit_structured_service_log(
            "record_recovery_service_request",
            self.server,
            request_id=request_id,
            op=op,
            decision=decision,
            reason_code=reason_code,
            duration_ms=elapsed_ms(started_at),
            caller=caller,
            job_id=job_id,
            role=role,
            candidate_count=candidate_count,
        )


def _authenticate_request(
    payload: dict,
    service_state: RecordRecoveryServiceState | RecordRecoveryUnixStreamServer,
) -> dict | None:
    provided_auth_token = str(payload.get("auth_token", "") or "")
    if service_state.auth_token and provided_auth_token:
        if hmac.compare_digest(provided_auth_token, service_state.auth_token):
            return None
    identity_bearer_token = str(payload.get("identity_bearer_token", "") or "").strip()
    if service_state.identity_token_config:
        if not identity_bearer_token:
            if service_state.auth_token:
                raise PermissionError("record recovery service auth failed")
            raise PermissionError("record recovery service identity auth failed")
        return resolve_identity_context(
            db_path=service_state.metadata_db_path,
            identity_token_config=service_state.identity_token_config,
            bearer_token=identity_bearer_token,
        )
    if service_state.auth_token:
        raise PermissionError("record recovery service auth failed")
    return None


def _apply_authenticated_identity(
    payload: dict,
    service_state: RecordRecoveryServiceState | RecordRecoveryUnixStreamServer,
    identity: dict | None,
) -> tuple[str, str, str, str]:
    caller = str(payload.get("caller", ""))
    tenant_id = str(payload.get("tenant_id", "")).strip()
    dataset_id = str(payload.get("dataset_id", "")).strip()
    service_id = str(payload.get("service_id", "")).strip()
    if identity is None:
        return caller, tenant_id, dataset_id, service_id

    identity_caller = str(identity.get("caller") or "")
    if caller and caller != identity_caller:
        raise PermissionError("record recovery caller does not match authenticated identity")
    caller = identity_caller

    identity_tenant_id = str(identity.get("tenant_id") or "")
    if identity_tenant_id:
        if tenant_id and tenant_id != identity_tenant_id:
            raise PermissionError("record recovery tenant_id does not match authenticated identity")
        tenant_id = identity_tenant_id

    identity_service_id = str(identity.get("service_id") or "")
    if identity_service_id:
        if service_id and service_id != identity_service_id:
            raise PermissionError("record recovery service_id does not match authenticated identity")
        if service_state.service_id and service_state.service_id != identity_service_id:
            raise PermissionError("record recovery identity is not bound to this service instance")
        service_id = identity_service_id

    payload["caller"] = caller
    if tenant_id:
        payload["tenant_id"] = tenant_id
    if service_id:
        payload["service_id"] = service_id
    payload["auth_subject"] = identity.get("subject")
    payload["auth_issuer"] = identity.get("issuer")
    payload["auth_entity_type"] = identity.get("subject_type")
    payload["auth_platform_roles"] = identity.get("platform_roles") or []
    return caller, tenant_id, dataset_id, service_id


def handle_record_recovery_service_payload(
    payload: dict,
    service_state: RecordRecoveryServiceState | RecordRecoveryUnixStreamServer,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("record recovery service request must be a JSON object")

    op = str(payload.get("op", "recover") or "recover")
    identity = _authenticate_request(payload, service_state)
    if op == "health":
        return build_health_result(
            service_id=service_state.service_id,
            tenant_id=service_state.tenant_id,
            dataset_id=service_state.dataset_id,
            transport=service_state.transport,
            socket_path=str(service_state.server_address)
            if service_state.transport == "unix_socket" and service_state.server_address
            else None,
            endpoint_url=service_state.endpoint_url,
            auth_required=bool(service_state.auth_token or service_state.identity_token_config),
            authz_policy_config=service_state.authz_policy_path_value,
            allowed_callers=sorted(service_state.allowed_callers),
            allowed_output_roots=[str(root.resolve()) for root in service_state.allowed_output_roots],
            allowed_record_store_roots=[str(root.resolve()) for root in service_state.allowed_record_store_roots],
            audit_log=str(service_state.audit_log.resolve()) if service_state.audit_log is not None else None,
            pid=os.getpid(),
        )
    if op != "recover":
        raise ValueError(f"unsupported record recovery service op: {op}")

    ts_valid, ts_reason_code, ts_reason = validate_request_timestamp(
        payload.get("request_timestamp_utc")
    )
    if not ts_valid:
        raise PermissionError(f"record recovery request rejected: {ts_reason}")

    provided_sig = str(payload.get("request_signature", "") or "").strip()
    if service_state.auth_token and provided_sig:
        request_id = str(payload.get("request_id", "") or "").strip()
        request_ts = str(payload.get("request_timestamp_utc", "") or "").strip()
        sig_algo = str(payload.get("signature_algorithm", "") or "").strip()
        if sig_algo and sig_algo != REQUEST_SIGNATURE_ALGORITHM:
            raise PermissionError(
                f"unsupported request signature algorithm: {sig_algo!r}"
            )
        if not verify_request_signature(
            service_state.auth_token,
            request_id=request_id,
            request_timestamp_utc=request_ts,
            op="recover",
            provided_sig=provided_sig,
        ):
            raise PermissionError("record recovery request signature verification failed")

    caller, tenant_id, dataset_id, service_id = _apply_authenticated_identity(payload, service_state, identity)
    if service_state.allowed_callers and caller not in service_state.allowed_callers:
        raise PermissionError(f"caller {caller or '<missing>'} is not allowed to use record recovery service")
    if service_state.service_id and service_id and service_id != service_state.service_id:
        raise PermissionError(f"service_id {service_id} does not match service instance {service_state.service_id}")
    if service_state.service_id and not service_id:
        service_id = service_state.service_id
    if service_state.tenant_id and tenant_id and tenant_id != service_state.tenant_id:
        raise PermissionError(f"tenant_id {tenant_id} does not match service tenant {service_state.tenant_id}")
    if service_state.tenant_id and not tenant_id:
        tenant_id = service_state.tenant_id
    if service_state.dataset_id and dataset_id and dataset_id != service_state.dataset_id:
        raise PermissionError(f"dataset_id {dataset_id} does not match service dataset {service_state.dataset_id}")
    if service_state.dataset_id and not dataset_id:
        dataset_id = service_state.dataset_id

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
    if service_state.allowed_output_roots and not _path_within_roots(out_path, service_state.allowed_output_roots):
        raise PermissionError(f"output path {out_path} is outside allowed output roots")
    if service_state.allowed_record_store_roots and not _path_within_roots(
        record_store_path,
        service_state.allowed_record_store_roots,
    ):
        raise PermissionError(f"record store path {record_store_path} is outside allowed record-store roots")
    effective_min_rows, effective_max_rows = authorize_record_recovery_request(
        policy=service_state.authz_policy,
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
    # Apply global service-level row cap (--max-rows-per-request) on top of authz limit
    if service_state.max_rows_per_request > 0:
        if effective_max_rows is None:
            effective_max_rows = service_state.max_rows_per_request
        else:
            effective_max_rows = min(effective_max_rows, service_state.max_rows_per_request)

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


def append_record_recovery_service_audit(
    *,
    service_state: RecordRecoveryServiceState | RecordRecoveryUnixStreamServer,
    payload: dict,
    result: dict | None,
    duration_ms: int | None,
    decision: str,
    reason_code: str,
    reason: str,
) -> None:
    if service_state.audit_log is None:
        return

    audit_log = service_state.audit_log
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
        "service_id": service_state.service_id or (str(payload.get("service_id", "")) or None),
        "tenant_id": service_state.tenant_id or (str(payload.get("tenant_id", "")) or None),
        "dataset_id": service_state.dataset_id or (str(payload.get("dataset_id", "")) or None),
        "caller": caller,
        "correlation_id": job_id,
        "job_id": job_id,
        "role": str(payload.get("role", "")) or "unknown",
        "auth_mode": (
            "identity_bearer"
            if str(payload.get("identity_bearer_token", "") or "").strip() or str(payload.get("auth_subject", "") or "").strip()
            else "env_token" if service_state.auth_token else "socket_acl_only"
        ),
        "auth_subject": str(payload.get("auth_subject", "") or "") or None,
        "auth_issuer": str(payload.get("auth_issuer", "") or "") or None,
        "auth_entity_type": str(payload.get("auth_entity_type", "") or "") or None,
        "transport": service_state.transport,
        "socket_path": str(service_state.server_address)
        if service_state.transport == "unix_socket" and service_state.server_address
        else None,
        "endpoint_url": service_state.endpoint_url,
        "authz_policy_config": service_state.authz_policy_path_value,
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
        "request_timestamp_utc": str(payload.get("request_timestamp_utc", "")) or None,
        "request_signature_verified": bool(str(payload.get("request_signature", "") or "").strip()) if service_state.auth_token else None,
        "signature_algorithm": str(payload.get("signature_algorithm", "") or "") or None,
        "input_rows": result.get("input_rows") if result is not None else None,
        "output_rows": result.get("output_rows") if result is not None else None,
        "duration_ms": duration_ms,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
    }
    with audit_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
    ap.add_argument("--metadata-db-path", default="")
    ap.add_argument("--identity-token-config", default="")
    ap.add_argument("--allowed-caller", action="append", default=[])
    ap.add_argument("--authz-config", default="")
    ap.add_argument("--allowed-output-root", action="append", default=[])
    ap.add_argument("--allowed-record-store-root", action="append", default=[])
    ap.add_argument("--audit-log", default="")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    ap.add_argument("--max-rows-per-request", type=int, default=0,
                    help="Hard cap on rows returned per recovery request (0 = unlimited)")
    args = ap.parse_args()
    if args.identity_token_config and not args.metadata_db_path:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path")

    socket_path = Path(args.socket_path)
    pid_file = Path(args.pid_file) if args.pid_file else None
    ready_file = Path(args.ready_file) if args.ready_file else None
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    service_state = build_service_state(
        service_id=str(args.service_id or ""),
        tenant_id=str(args.tenant_id or ""),
        dataset_id=str(args.dataset_id or ""),
        auth_token_env=args.auth_token_env,
        metadata_db_path=args.metadata_db_path,
        identity_token_config=args.identity_token_config,
        allowed_callers=list(args.allowed_caller),
        authz_config=args.authz_config,
        allowed_output_roots=list(args.allowed_output_root),
        allowed_record_store_roots=list(args.allowed_record_store_root),
        audit_log=args.audit_log,
        transport="unix_socket",
        socket_path=str(socket_path),
        endpoint_url=None,
        max_rows_per_request=args.max_rows_per_request,
    )
    server = RecordRecoveryUnixStreamServer(
        str(socket_path),
        RecordRecoveryRequestHandler,
        service_state=service_state,
    )
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    os.chmod(socket_path, parse_socket_mode(args.socket_mode))
    write_text_file(pid_file, f"{os.getpid()}\n")
    write_text_file(ready_file, str(socket_path.resolve()) + "\n")
    emit_structured_service_log(
        "record_recovery_service_start",
        service_state,
        socket_path=str(socket_path.resolve()),
        socket_mode=args.socket_mode,
    )

    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        emit_structured_service_log("record_recovery_service_stop", service_state)
        server.server_close()
        if socket_path.exists():
            socket_path.unlink()
        if ready_file is not None and ready_file.exists():
            ready_file.unlink()
        if pid_file is not None and pid_file.exists():
            pid_file.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
