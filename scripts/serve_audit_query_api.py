#!/usr/bin/env python3
import argparse
import json
import os
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from export_catalog_lineage import build_catalog_lineage, load_json_object as load_catalog_json_object, repo_path as catalog_repo_path
from export_observability_events import build_observability, load_json_object as load_observability_json_object, repo_path as observability_repo_path


HEALTH_SCHEMA = "audit_query_api_health/v1"
RESPONSE_SCHEMA = "audit_query_api_response/v1"
ERROR_SCHEMA = "audit_query_api_error/v1"


def write_text_file(path: str, content: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def remove_file(path: str) -> None:
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        return


def read_auth_token(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if not value:
        raise SystemExit(f"[ERROR] environment variable {env_name} is not set")
    return value


def single_param(params: dict[str, list[str]], name: str, default: str = "") -> str:
    values = params.get(name)
    if not values:
        return default
    return values[0]


def parse_bool_param(params: dict[str, list[str]], name: str, default: bool = False) -> bool:
    raw = single_param(params, name, "")
    if not raw:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of true,false,1,0,yes,no,on,off")


class AuditQueryApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        out_base: str,
        auth_token: str,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.out_base = str(Path(out_base).resolve())
        self.audit_chain_path = str(Path(self.out_base) / "audit_chain.json")
        self.public_report_path = str(Path(self.out_base) / "a_psi_run" / "public_report.json")
        self.auth_token = auth_token
        self.pid_file = pid_file
        self.ready_file = ready_file
        super().__init__(server_address, handler_cls)


class AuditQueryApiHandler(BaseHTTPRequestHandler):
    server: AuditQueryApiServer

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, message: str) -> None:
        self._send_json(
            status,
            {
                "schema": ERROR_SCHEMA,
                "method": self.command,
                "path": self.path,
                "error": message,
            },
        )

    def _require_auth(self) -> None:
        expected = self.server.auth_token
        if not expected:
            return
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise PermissionError("missing bearer token")
        provided = header[len("Bearer "):]
        if provided != expected:
            raise PermissionError("audit query API auth failed")

    def _load_audit_chain(self) -> dict[str, Any]:
        return load_observability_json_object(observability_repo_path(self.server.audit_chain_path))

    def _load_public_report(self) -> dict[str, Any]:
        return load_catalog_json_object(catalog_repo_path(self.server.public_report_path))

    def _success_payload(self, *, parsed, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": RESPONSE_SCHEMA,
            "method": self.command,
            "path": parsed.path,
            "query": {key: values if len(values) > 1 else values[0] for key, values in parse_qs(parsed.query).items()},
            "result_schema": payload.get("schema"),
            "result": payload,
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query, keep_blank_values=False)
        try:
            if parsed.path == "/healthz":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "schema": HEALTH_SCHEMA,
                        "ok": True,
                        "out_base": self.server.out_base,
                        "auth_required": bool(self.server.auth_token),
                        "available_results": [
                            "public_report/v2",
                            "audit_chain/v1",
                            "pipeline_observability/v1",
                            "catalog_lineage/v1",
                        ],
                    },
                )
                return

            self._require_auth()
            if parsed.path == "/v1/public-report":
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=self._load_public_report()))
                return
            if parsed.path == "/v1/audit-chain":
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=self._load_audit_chain()))
                return
            if parsed.path == "/v1/observability":
                payload = build_observability(self._load_audit_chain())
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if parsed.path == "/v1/catalog-lineage":
                payload = build_catalog_lineage(self._load_audit_chain(), include_paths=parse_bool_param(params, "include_paths", False))
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except SystemExit as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Serve a thin local read-only HTTP API over completed run audit/public-report artifacts.")
    ap.add_argument("--out-base", required=True, help="Completed pipeline output base directory")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18092)
    ap.add_argument("--auth-token-env", default="", help="Optional bearer-token env var for non-health endpoints")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_base = Path(args.out_base)
    audit_chain_path = out_base / "audit_chain.json"
    public_report_path = out_base / "a_psi_run" / "public_report.json"
    if not out_base.is_dir():
        raise SystemExit(f"[ERROR] completed run directory does not exist: {out_base}")
    if not audit_chain_path.is_file():
        raise SystemExit(f"[ERROR] audit chain does not exist: {audit_chain_path}")
    if not public_report_path.is_file():
        raise SystemExit(f"[ERROR] public report does not exist: {public_report_path}")

    auth_token = read_auth_token(args.auth_token_env)
    server = AuditQueryApiServer(
        (args.bind_host, args.port),
        AuditQueryApiHandler,
        out_base=str(out_base),
        auth_token=auth_token,
        pid_file=args.pid_file,
        ready_file=args.ready_file,
    )

    def handle_signal(_signum, _frame) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    write_text_file(args.pid_file, f"{os.getpid()}\n")
    write_text_file(args.ready_file, "ready\n")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        remove_file(args.ready_file)
        remove_file(args.pid_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
