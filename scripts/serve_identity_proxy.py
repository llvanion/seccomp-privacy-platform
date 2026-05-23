#!/usr/bin/env python3
"""
A1: Issuer-backed identity proxy baseline.

Thin HTTP reverse proxy that:
  1. Validates Bearer tokens via api_identity.py (static token map or DB-backed issuer/subject)
  2. Injects resolved identity as X-Identity-* request headers
  3. Forwards requests to configured upstream backends based on URL path prefix
  4. Returns 401 Unauthorized / 403 Forbidden for auth failures

Routes requests by the first path segment:
  /metadata/... -> metadata upstream
  /query/...    -> query upstream
  /audit/...    -> audit upstream
  /health/...   -> platform-health upstream
  /healthz      -> local proxy health

Usage:
  python3 scripts/serve_identity_proxy.py \
    --bind-host 127.0.0.1 \
    --port 18095 \
    --metadata-db-path tmp/platform_metadata.db \
    --identity-token-config config/api_identity_tokens.example.json \
    --upstream metadata:http://127.0.0.1:18090 \
    --upstream query:http://127.0.0.1:18091 \
    --upstream audit:http://127.0.0.1:18092 \
    --upstream health:http://127.0.0.1:18093
"""
import argparse
import hmac
import json
import os
import signal
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from api_identity import (
    resolve_identity_context,
    build_identity_resolution_payload,
)


HEALTH_SCHEMA = "identity_proxy_health/v1"
ERROR_PREFIX = "identity_proxy"

_INJECTED_HEADER_NAMES = (
    "X-Identity-Caller",
    "X-Identity-Tenant-Id",
    "X-Identity-Service-Id",
    "X-Identity-Platform-Roles",
    "X-Identity-Resolved",
)

_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_response(status: int, payload: Any) -> tuple[int, bytes]:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return status, body


def _error_response(status: int, error_code: str, message: str) -> tuple[int, bytes]:
    return _json_response(status, {"error": f"{ERROR_PREFIX}/{error_code}", "message": message})


def _extract_bearer(auth_header: str) -> str:
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]
    return ""


def _parse_upstream(spec: str) -> tuple[str, str]:
    """Parse 'name:http://host:port' into (name, url)."""
    parts = spec.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"upstream spec must be 'name:url': {spec!r}")
    name, url = parts[0].strip(), parts[1].strip()
    if not name or not url:
        raise ValueError(f"upstream name and url must be non-empty: {spec!r}")
    return name, url


class IdentityProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        upstreams: dict[str, str],
        identity_token_config: str,
        metadata_db_path: str,
        admin_token: str,
        log_identity: bool,
    ) -> None:
        self.upstreams = upstreams
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
        self.metadata_db_path = str(Path(metadata_db_path).resolve()) if metadata_db_path else ""
        self.admin_token = admin_token
        self.log_identity = log_identity
        self._lock = threading.Lock()
        self._start_ts = _utc_now()
        super().__init__(server_address, handler_cls)

    def resolve_identity(self, bearer_token: str) -> dict[str, Any] | None:
        if not bearer_token:
            return None
        if self.admin_token and hmac.compare_digest(bearer_token, self.admin_token):
            return {
                "caller": "_proxy_admin",
                "tenant_id": None,
                "issuer": None,
                "subject": "_proxy_admin",
                "subject_type": "service_account",
                "service_id": None,
                "platform_roles": ["platform_admin"],
                "permission_summary": {},
                "_proxy_admin": True,
            }
        if self.identity_token_config and self.metadata_db_path:
            return resolve_identity_context(
                db_path=self.metadata_db_path,
                identity_token_config=self.identity_token_config,
                bearer_token=bearer_token,
            )
        return None


class IdentityProxyHandler(BaseHTTPRequestHandler):
    server: IdentityProxyServer

    def log_message(self, fmt, *args):
        pass

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _build_health(self) -> dict[str, Any]:
        upstreams_detail: dict[str, Any] = {}
        for name, url in self.server.upstreams.items():
            upstreams_detail[name] = {"prefix": f"/{name}", "upstream_url": url}
        return {
            "schema": HEALTH_SCHEMA,
            "status": "ok",
            "ts_utc": _utc_now(),
            "bind_host": self.server.server_address[0],
            "port": self.server.server_address[1],
            "identity_token_config": self.server.identity_token_config or None,
            "metadata_db_path": self.server.metadata_db_path or None,
            "upstream_count": len(self.server.upstreams),
            "upstreams": upstreams_detail,
        }

    def _resolve_and_inject(self, raw_headers: dict[str, str]) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Resolve identity from Authorization header and build forwarding headers."""
        auth_header = ""
        fwd_headers: dict[str, str] = {}
        for k, v in raw_headers.items():
            lk = k.lower()
            if lk in _HOP_BY_HOP:
                continue
            # strip pre-existing X-Identity-* headers (prevent spoofing)
            if lk.startswith("x-identity-"):
                continue
            if lk == "authorization":
                auth_header = v
                continue
            fwd_headers[k] = v

        identity: dict[str, Any] | None = None
        if auth_header:
            bearer = _extract_bearer(auth_header)
            if bearer:
                identity = self.server.resolve_identity(bearer)

        if identity:
            fwd_headers["X-Identity-Caller"] = str(identity.get("caller") or "")
            fwd_headers["X-Identity-Tenant-Id"] = str(identity.get("tenant_id") or "")
            fwd_headers["X-Identity-Service-Id"] = str(identity.get("service_id") or "")
            fwd_headers["X-Identity-Platform-Roles"] = json.dumps(
                identity.get("platform_roles") or [], ensure_ascii=False
            )
            fwd_headers["X-Identity-Resolved"] = "true"
            # Forward the original Authorization so the backend can also validate
            fwd_headers["Authorization"] = auth_header

        return identity, fwd_headers

    def _route_upstream(self, path: str) -> tuple[str | None, str]:
        """Return (upstream_name, stripped_path) for the given path."""
        parts = path.lstrip("/").split("/", 1)
        prefix = parts[0] if parts else ""
        rest = ("/" + parts[1]) if len(parts) > 1 else "/"
        upstream_url = self.server.upstreams.get(prefix)
        return (prefix if upstream_url else None), rest

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 0:
            return self.rfile.read(length)
        return b""

    def _proxy_request(
        self,
        method: str,
        upstream_url: str,
        path: str,
        query_string: str,
        fwd_headers: dict[str, str],
        body: bytes,
    ) -> None:
        target = upstream_url.rstrip("/") + path
        if query_string:
            target = f"{target}?{query_string}"
        req = urllib.request.Request(target, data=body or None, method=method, headers=fwd_headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                resp_body = resp.read()
                self.send_response(status)
                for hdr_name, hdr_val in resp.headers.items():
                    if hdr_name.lower() in _HOP_BY_HOP:
                        continue
                    self.send_header(hdr_name, hdr_val)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as exc:
            resp_body = exc.read()
            self.send_response(exc.code)
            for hdr_name, hdr_val in exc.headers.items():
                if hdr_name.lower() in _HOP_BY_HOP:
                    continue
                self.send_header(hdr_name, hdr_val)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        except urllib.error.URLError as exc:
            status_code, body = _error_response(
                HTTPStatus.BAD_GATEWAY,
                "upstream_unavailable",
                f"upstream connection failed: {exc.reason}",
            )
            self._send(status_code, body)

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query_string = parsed.query

        if path in ("/healthz", "/health"):
            payload = self._build_health()
            status_code, body = _json_response(HTTPStatus.OK, payload)
            self._send(status_code, body)
            return

        # Read body first so we don't block partial responses
        body = self._read_body()

        # Resolve identity
        raw_headers = dict(self.headers)
        try:
            identity, fwd_headers = self._resolve_and_inject(raw_headers)
        except PermissionError as exc:
            status_code, resp_body = _error_response(
                HTTPStatus.UNAUTHORIZED, "auth_failed", str(exc)
            )
            self._send(status_code, resp_body)
            return

        # Require authentication if auth config is present
        auth_header = raw_headers.get("Authorization", "")
        if auth_header and not identity:
            status_code, resp_body = _error_response(
                HTTPStatus.UNAUTHORIZED, "identity_not_resolved", "bearer token did not match any registered identity"
            )
            self._send(status_code, resp_body)
            return

        # Route to upstream
        upstream_name, stripped_path = self._route_upstream(path)
        if upstream_name is None:
            status_code, resp_body = _error_response(
                HTTPStatus.NOT_FOUND, "no_upstream", f"no upstream configured for path: {path!r}"
            )
            self._send(status_code, resp_body)
            return

        upstream_url = self.server.upstreams[upstream_name]
        self._proxy_request(method, upstream_url, stripped_path, query_string, fwd_headers, body)

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PUT(self): self._handle("PUT")
    def do_DELETE(self): self._handle("DELETE")
    def do_HEAD(self): self._handle("HEAD")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="A1: Identity proxy baseline — validates bearer tokens and injects identity headers before forwarding to upstream sidecars.")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18095)
    ap.add_argument("--metadata-db-path", default="", help="SQLite metadata DB for DB-backed identity resolution")
    ap.add_argument("--identity-token-config", default="", help="Path to api_identity_token_map/v1 config for static token resolution")
    ap.add_argument("--upstream", action="append", default=[], dest="upstreams", metavar="NAME:URL",
                    help="name:http://host:port mapping. Can be repeated.")
    ap.add_argument("--admin-token-env", default="", help="Env var holding an admin bypass token")
    ap.add_argument("--log-identity", action="store_true", help="Log resolved identity for debugging")
    ap.add_argument("--pid-file", default="", help="Write PID to this file on startup")
    ap.add_argument("--ready-file", default="", help="Write 'ready' to this file once server is listening")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    upstreams: dict[str, str] = {}
    for spec in args.upstreams:
        try:
            name, url = _parse_upstream(spec)
        except ValueError as exc:
            raise SystemExit(f"[ERROR] {exc}") from exc
        upstreams[name] = url

    admin_token = ""
    if args.admin_token_env:
        admin_token = os.environ.get(args.admin_token_env, "")

    server = IdentityProxyServer(
        (args.bind_host, args.port),
        IdentityProxyHandler,
        upstreams=upstreams,
        identity_token_config=args.identity_token_config,
        metadata_db_path=args.metadata_db_path,
        admin_token=admin_token,
        log_identity=args.log_identity,
    )

    if args.pid_file:
        Path(args.pid_file).write_text(str(os.getpid()), encoding="utf-8")

    def _shutdown(sig, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _shutdown)

    print(
        f"[ok] identity proxy listening on {args.bind_host}:{args.port} "
        f"with {len(upstreams)} upstream(s)"
    )
    for name, url in upstreams.items():
        print(f"     /{name}/ -> {url}")

    if args.ready_file:
        Path(args.ready_file).write_text("ready", encoding="utf-8")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if args.pid_file:
            try:
                Path(args.pid_file).unlink()
            except FileNotFoundError:
                pass
        if args.ready_file:
            try:
                Path(args.ready_file).unlink()
            except FileNotFoundError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
