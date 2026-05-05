# -*- coding:utf-8 _*-
import argparse
import json
import os
import signal
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from services.record_recovery.bootstrap import ensure_repo_paths
from services.record_recovery.common import utc_now_iso, validate_request_timestamp
from services.record_recovery.observability import (
    elapsed_ms,
    emit_structured_service_log,
    new_request_id,
    start_timer,
)
from services.record_recovery.runtime import (
    RecordRecoveryServiceState,
    build_service_state,
    write_text_file,
)
from services.record_recovery.service import (
    append_record_recovery_service_audit,
    handle_record_recovery_service_payload,
)


ensure_repo_paths()


class RecordRecoveryHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, service_state: RecordRecoveryServiceState):
        self.service_state = service_state
        super().__init__(server_address, handler_class)


class RecordRecoveryHttpHandler(BaseHTTPRequestHandler):
    server: RecordRecoveryHttpServer

    def do_GET(self) -> None:
        started_at = start_timer()
        request_id = self.headers.get("X-Request-Id", "").strip() or new_request_id()
        status_code = 200
        op = "health"
        decision = "allow"
        reason_code = "ok"
        if self.path != "/healthz":
            status_code = 404
            decision = "deny"
            reason_code = "not_found"
            self._write_json(
                status_code,
                {"schema": "sse_record_recovery_error/v1", "error": "not found"},
                request_id=request_id,
            )
            self._log_request(
                request_id=request_id,
                method="GET",
                path=self.path,
                op=op,
                status_code=status_code,
                decision=decision,
                reason_code=reason_code,
                started_at=started_at,
            )
            return
        payload = {"op": "health"}
        self._apply_bearer_token(payload)
        try:
            result = handle_record_recovery_service_payload(payload, self.server.service_state)
            self._write_json(status_code, result, request_id=request_id)
        except Exception as e:
            status_code = 400
            decision = "deny"
            reason_code = "service_request_failed"
            self._write_json(
                status_code,
                {"schema": "sse_record_recovery_error/v1", "error": str(e)},
                request_id=request_id,
            )
        self._log_request(
            request_id=request_id,
            method="GET",
            path=self.path,
            op=op,
            status_code=status_code,
            decision=decision,
            reason_code=reason_code,
            started_at=started_at,
        )

    def do_POST(self) -> None:
        started_at = start_timer()
        request_id = self.headers.get("X-Request-Id", "").strip() or new_request_id()
        status_code = 200
        op = "recover" if self.path == "/recover" else "health" if self.path == "/health" else "unknown"
        decision = "allow"
        reason_code = "ok"
        caller = None
        job_id = None
        role = None
        candidate_count = None
        if self.path not in {"/recover", "/health"}:
            status_code = 404
            decision = "deny"
            reason_code = "not_found"
            self._write_json(
                status_code,
                {"schema": "sse_record_recovery_error/v1", "error": "not found"},
                request_id=request_id,
            )
            self._log_request(
                request_id=request_id,
                method="POST",
                path=self.path,
                op=op,
                status_code=status_code,
                decision=decision,
                reason_code=reason_code,
                started_at=started_at,
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("HTTP request payload must be a JSON object")
            if self.path == "/health":
                payload["op"] = "health"
            elif self.path == "/recover":
                payload["op"] = "recover"
            op = str(payload.get("op", op) or op)
            caller = str(payload.get("caller", "")) or None
            job_id = str(payload.get("job_id", "")) or None
            role = str(payload.get("role", "")) or None
            if isinstance(payload.get("candidate_ids"), list):
                candidate_count = len(payload.get("candidate_ids", []))
            self._apply_bearer_token(payload)
            # Promote headers into payload when the payload fields are absent
            header_ts = self.headers.get("X-Request-Timestamp", "").strip()
            if header_ts and not payload.get("request_timestamp_utc"):
                payload["request_timestamp_utc"] = header_ts
            header_sig = self.headers.get("X-Request-Signature", "").strip()
            if header_sig and not payload.get("request_signature"):
                payload["request_signature"] = header_sig
            header_sig_algo = self.headers.get("X-Request-Signature-Algorithm", "").strip()
            if header_sig_algo and not payload.get("signature_algorithm"):
                payload["signature_algorithm"] = header_sig_algo
            result = handle_record_recovery_service_payload(payload, self.server.service_state)
            if payload.get("op") == "recover":
                append_record_recovery_service_audit(
                    service_state=self.server.service_state,
                    payload=payload,
                    result=result,
                    duration_ms=elapsed_ms(started_at),
                    decision="allow",
                    reason_code="ok",
                    reason="ok",
                )
            self._write_json(status_code, result, request_id=request_id)
        except Exception as e:
            status_code = 400
            decision = "deny"
            reason_code = "service_request_failed"
            payload_for_audit = payload if "payload" in locals() and isinstance(payload, dict) else {}
            caller = caller or (str(payload_for_audit.get("caller", "")) or None)
            job_id = job_id or (str(payload_for_audit.get("job_id", "")) or None)
            role = role or (str(payload_for_audit.get("role", "")) or None)
            if candidate_count is None and isinstance(payload_for_audit.get("candidate_ids"), list):
                candidate_count = len(payload_for_audit.get("candidate_ids", []))
            if payload_for_audit.get("op") == "recover":
                append_record_recovery_service_audit(
                    service_state=self.server.service_state,
                    payload=payload_for_audit,
                    result=None,
                    duration_ms=elapsed_ms(started_at),
                    decision="deny",
                    reason_code="service_request_failed",
                    reason=str(e),
                )
            self._write_json(
                status_code,
                {"schema": "sse_record_recovery_error/v1", "error": str(e)},
                request_id=request_id,
            )
        self._log_request(
            request_id=request_id,
            method="POST",
            path=self.path,
            op=op,
            status_code=status_code,
            decision=decision,
            reason_code=reason_code,
            started_at=started_at,
            caller=caller,
            job_id=job_id,
            role=role,
            candidate_count=candidate_count,
        )

    def log_message(self, format, *args):
        return

    def _auth_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):].strip()
        return self.headers.get("X-Record-Recovery-Token", "").strip()

    def _apply_bearer_token(self, payload: dict) -> None:
        token = self._auth_token()
        if not token:
            return
        service_state = self.server.service_state
        if service_state.auth_token and token == service_state.auth_token:
            if not payload.get("auth_token"):
                payload["auth_token"] = token
            return
        if service_state.identity_token_config and not payload.get("identity_bearer_token"):
            payload["identity_bearer_token"] = token
            return
        if not payload.get("auth_token"):
            payload["auth_token"] = token

    def _write_json(self, status: int, payload: dict, *, request_id: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if request_id:
            self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _log_request(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        op: str,
        status_code: int,
        decision: str,
        reason_code: str,
        started_at: float,
        caller: str | None = None,
        job_id: str | None = None,
        role: str | None = None,
        candidate_count: int | None = None,
    ) -> None:
        emit_structured_service_log(
            "record_recovery_service_request",
            self.server.service_state,
            request_id=request_id,
            method=method,
            path=path,
            op=op,
            status_code=status_code,
            decision=decision,
            reason_code=reason_code,
            duration_ms=elapsed_ms(started_at),
            caller=caller,
            job_id=job_id,
            role=role,
            candidate_count=candidate_count,
        )


def _raise_keyboard_interrupt(_signum, _frame) -> None:
    raise KeyboardInterrupt()


def _build_server_ssl_context(*, cert_file: str, key_file: str, ca_cert: str, require_client_cert: bool) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    if require_client_cert:
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=ca_cert)
    else:
        context.verify_mode = ssl.CERT_NONE
    return context


def main() -> int:
    ap = argparse.ArgumentParser(description="HTTP service for controlled record-store recovery.")
    ap.add_argument("--service-id", default="")
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    ap.add_argument("--bind-host", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--endpoint-url", default="")
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
    ap.add_argument("--tls-cert-file", default="")
    ap.add_argument("--tls-key-file", default="")
    ap.add_argument("--tls-ca-cert", default="")
    ap.add_argument("--tls-require-client-cert", action="store_true")
    ap.add_argument("--max-rows-per-request", type=int, default=0,
                    help="Hard cap on rows returned per recovery request (0 = unlimited)")
    args = ap.parse_args()
    if args.identity_token_config and not args.metadata_db_path:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path")

    pid_file = Path(args.pid_file) if args.pid_file else None
    ready_file = Path(args.ready_file) if args.ready_file else None
    tls_enabled = bool(args.tls_cert_file or args.tls_key_file)
    if tls_enabled and (not args.tls_cert_file or not args.tls_key_file):
        raise SystemExit("[ERROR] mTLS/HTTPS requires both --tls-cert-file and --tls-key-file")
    if args.tls_require_client_cert and not args.tls_ca_cert:
        raise SystemExit("[ERROR] --tls-require-client-cert requires --tls-ca-cert")
    scheme = "https" if tls_enabled else "http"
    endpoint_url = args.endpoint_url or f"{scheme}://{args.bind_host}:{args.port}"
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
        transport="http",
        socket_path=None,
        endpoint_url=endpoint_url,
        max_rows_per_request=args.max_rows_per_request,
    )
    server = RecordRecoveryHttpServer((args.bind_host, args.port), RecordRecoveryHttpHandler, service_state=service_state)
    if tls_enabled:
        server.socket = _build_server_ssl_context(
            cert_file=args.tls_cert_file,
            key_file=args.tls_key_file,
            ca_cert=args.tls_ca_cert,
            require_client_cert=args.tls_require_client_cert,
        ).wrap_socket(server.socket, server_side=True)
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    write_text_file(pid_file, f"{os.getpid()}\n")
    write_text_file(ready_file, endpoint_url + "\n")
    emit_structured_service_log(
        "record_recovery_service_start",
        service_state,
        bind_host=args.bind_host,
        port=args.port,
        endpoint_url=endpoint_url,
        tls_enabled=tls_enabled,
        tls_require_client_cert=bool(args.tls_require_client_cert),
    )

    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        emit_structured_service_log("record_recovery_service_stop", service_state)
        server.server_close()
        if ready_file is not None and ready_file.exists():
            ready_file.unlink()
        if pid_file is not None and pid_file.exists():
            pid_file.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
