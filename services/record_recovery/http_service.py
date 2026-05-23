# -*- coding:utf-8 _*-
import argparse
import hmac
import json
import os
import signal
import ssl
import threading
import time
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


class TokenBucket:
    """Thread-safe token bucket for per-caller rate limiting (H2-a)."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._tokens = float(capacity)
        self._rate = rate
        self._capacity = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                float(self._capacity),
                self._tokens + (now - self._last) * self._rate,
            )
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False


class ServiceMetrics:
    """In-memory Prometheus-compatible counters and histogram for /metrics (J3-a)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests_total: dict[tuple[str, str], int] = {}
        self._duration_sum: float = 0.0
        self._duration_count: int = 0
        self._duration_buckets: dict[float, int] = {
            0.05: 0, 0.1: 0, 0.25: 0, 0.5: 0, 1.0: 0, 2.0: 0, 5.0: 0,
        }

    def record(self, *, decision: str, op: str, duration_s: float) -> None:
        with self._lock:
            key = (decision, op)
            self._requests_total[key] = self._requests_total.get(key, 0) + 1
            self._duration_sum += duration_s
            self._duration_count += 1
            for le in self._duration_buckets:
                if duration_s <= le:
                    self._duration_buckets[le] += 1

    def prometheus_text(self) -> str:
        lines: list[str] = []
        with self._lock:
            lines.append("# HELP recovery_requests_total Total recovery requests by decision and op")
            lines.append("# TYPE recovery_requests_total counter")
            for (decision, op), count in sorted(self._requests_total.items()):
                lines.append(f'recovery_requests_total{{decision="{decision}",op="{op}"}} {count}')
            lines.append("# HELP recovery_request_duration_seconds Recovery request duration")
            lines.append("# TYPE recovery_request_duration_seconds histogram")
            for le, count in sorted(self._duration_buckets.items()):
                lines.append(
                    f'recovery_request_duration_seconds_bucket{{le="{le}"}} {count}'
                )
            lines.append(
                f'recovery_request_duration_seconds_bucket{{le="+Inf"}} {self._duration_count}'
            )
            lines.append(f"recovery_request_duration_seconds_sum {self._duration_sum:.6f}")
            lines.append(f"recovery_request_duration_seconds_count {self._duration_count}")
        return "\n".join(lines) + "\n"


class RecordRecoveryHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        handler_class,
        *,
        service_state: RecordRecoveryServiceState,
        rate_limit_per_caller: float = 0.0,
        rate_limit_burst: int = 0,
        max_request_body_bytes: int = 0,
    ) -> None:
        self.service_state = service_state
        self._rate_limit_per_caller = rate_limit_per_caller
        self._rate_limit_burst = rate_limit_burst
        self._rate_buckets: dict[str, TokenBucket] = {}
        self._rate_lock = threading.Lock()
        self.metrics = ServiceMetrics()
        self.max_request_body_bytes = max(0, int(max_request_body_bytes or 0))
        super().__init__(server_address, handler_class)

    def check_rate_limit(self, caller: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        if self._rate_limit_per_caller <= 0:
            return True
        with self._rate_lock:
            if caller not in self._rate_buckets:
                self._rate_buckets[caller] = TokenBucket(
                    self._rate_limit_per_caller,
                    max(1, self._rate_limit_burst),
                )
            return self._rate_buckets[caller].consume()


class RecordRecoveryHttpHandler(BaseHTTPRequestHandler):
    server: RecordRecoveryHttpServer

    def do_GET(self) -> None:
        started_at = start_timer()
        request_id = self.headers.get("X-Request-Id", "").strip() or new_request_id()
        status_code = 200
        op = "health"
        decision = "allow"
        reason_code = "ok"

        if self.path == "/metrics":
            body = self.server.metrics.prometheus_text().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return

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
        max_body = self.server.max_request_body_bytes
        if max_body > 0 and length > max_body:
            self._write_json(
                413,
                {
                    "schema": "sse_record_recovery_error/v1",
                    "error": f"request body {length} bytes exceeds limit {max_body}",
                },
                request_id=request_id,
            )
            self._log_request(
                request_id=request_id,
                method="POST",
                path=self.path,
                op=op,
                status_code=413,
                decision="deny",
                reason_code="request_body_too_large",
                started_at=started_at,
            )
            return
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
            # Rate-limit check (H2-a)
            if caller and not self.server.check_rate_limit(caller):
                status_code = 429
                decision = "deny"
                reason_code = "rate_limited"
                self._write_json(
                    status_code,
                    {"schema": "sse_record_recovery_error/v1", "error": "rate limit exceeded"},
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
                return
            # Promote headers into payload when the payload fields are absent
            header_ts = self.headers.get("X-Request-Timestamp", "").strip()
            if header_ts and not payload.get("request_timestamp_utc"):
                payload["request_timestamp_utc"] = header_ts
            header_sig = self.headers.get("X-Request-Signature", "").strip()
            if header_sig and not payload.get("request_signature"):
                payload["request_signature"] = header_sig
            header_payload_hash = self.headers.get("X-Request-Payload-SHA256", "").strip()
            if header_payload_hash and not payload.get("request_payload_sha256"):
                payload["request_payload_sha256"] = header_payload_hash
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
        if service_state.auth_token and hmac.compare_digest(token, service_state.auth_token):
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
        duration = elapsed_ms(started_at)
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
            duration_ms=duration,
            caller=caller,
            job_id=job_id,
            role=role,
            candidate_count=candidate_count,
        )
        self.server.metrics.record(
            decision=decision,
            op=op,
            duration_s=duration / 1000.0,
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
    ap.add_argument("--max-candidate-ids", type=int,
                    default=int(os.environ.get("RECORD_RECOVERY_MAX_CANDIDATE_IDS", "0") or "0"),
                    help="Hard cap on inbound candidate_ids length per request (0 = unlimited)")
    ap.add_argument("--suppress-min-rows-side-channel", action="store_true",
                    default=(os.environ.get("RECORD_RECOVERY_SUPPRESS_MIN_ROWS_SIDE_CHANNEL", "0") == "1"),
                    help=(
                        "Close the zero-rows vs below-min-rows side channel by collapsing "
                        "below-min results into a uniform zero-row success response. The "
                        "audit still records the distinction for the operator."
                    ))
    ap.add_argument("--max-request-body-bytes", type=int,
                    default=int(os.environ.get("RECORD_RECOVERY_MAX_BODY_BYTES", "0") or "0"),
                    help="Hard cap on HTTP request body size in bytes (0 = unlimited)")
    ap.add_argument("--rate-limit-per-caller", type=float, default=0.0,
                    help="Max requests/second per caller (0 = disabled)")
    ap.add_argument("--rate-limit-burst", type=int, default=0,
                    help="Burst capacity for the per-caller token bucket (0 = same as rate)")
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
        max_candidate_ids=args.max_candidate_ids,
        suppress_min_rows_side_channel=bool(args.suppress_min_rows_side_channel),
    )
    burst = args.rate_limit_burst or max(1, int(args.rate_limit_per_caller)) if args.rate_limit_per_caller > 0 else 0
    server = RecordRecoveryHttpServer(
        (args.bind_host, args.port),
        RecordRecoveryHttpHandler,
        service_state=service_state,
        rate_limit_per_caller=args.rate_limit_per_caller,
        rate_limit_burst=burst,
        max_request_body_bytes=args.max_request_body_bytes,
    )
    if tls_enabled:
        server.socket = _build_server_ssl_context(
            cert_file=args.tls_cert_file,
            key_file=args.tls_key_file,
            ca_cert=args.tls_ca_cert,
            require_client_cert=args.tls_require_client_cert,
        ).wrap_socket(server.socket, server_side=True)
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    def _reload_on_sighup(_sig: int, _frame) -> None:
        result = service_state.reload_authz_policy()
        emit_structured_service_log(
            "record_recovery_service_authz_reload",
            service_state,
            authz_reload_status=result.get("status"),
            authz_reload_path=result.get("path"),
            authz_reload_error=result.get("error"),
        )

    signal.signal(signal.SIGHUP, _reload_on_sighup)
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
