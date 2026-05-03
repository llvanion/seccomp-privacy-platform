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
from urllib.parse import urlparse

from api_identity import bind_query_request_to_identity, resolve_request_identity
from submit_query_workflow import REPO_ROOT, submit_request_payload


HEALTH_SCHEMA = "query_workflow_api_health/v1"
RESPONSE_SCHEMA = "query_workflow_api_response/v1"
ERROR_SCHEMA = "query_workflow_api_error/v1"


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


class QueryWorkflowApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        auth_token: str,
        metadata_db_path: str,
        identity_token_config: str,
        allow_execute: bool,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.auth_token = auth_token
        self.metadata_db_path = str(Path(metadata_db_path).resolve()) if metadata_db_path else ""
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
        self.allow_execute = allow_execute
        self.pid_file = pid_file
        self.ready_file = ready_file
        super().__init__(server_address, handler_cls)


class QueryWorkflowApiHandler(BaseHTTPRequestHandler):
    server: QueryWorkflowApiServer

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

    def _require_auth(self) -> dict[str, Any] | None:
        return resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.metadata_db_path,
            identity_token_config=self.server.identity_token_config,
            auth_failure_label="query workflow API",
        )

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            raise ValueError("request body is required")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/healthz":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        self._send_json(
            HTTPStatus.OK,
            {
                "schema": HEALTH_SCHEMA,
                "ok": True,
                "auth_required": bool(self.server.auth_token or self.server.identity_token_config),
                "allow_execute": self.server.allow_execute,
                "request_base_dir_default": str(REPO_ROOT),
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            identity = self._require_auth()
            if parsed.path == "/v1/query-workflows/dry-run":
                payload = self._handle_submit(execute=False, identity=identity)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed.path, payload))
                return
            if parsed.path == "/v1/query-workflows/execute":
                if not self.server.allow_execute:
                    raise PermissionError("query workflow execute endpoint is disabled")
                payload = self._handle_submit(execute=True, identity=identity)
                status = HTTPStatus.OK if payload.get("manifest", {}).get("exit_code") in (None, 0) else HTTPStatus.BAD_GATEWAY
                self._send_json(status, self._success_payload(parsed.path, payload))
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

    def _handle_submit(self, *, execute: bool, identity: dict[str, Any] | None) -> dict[str, Any]:
        payload = self._read_json_body()
        if identity is not None:
            payload = bind_query_request_to_identity(identity, payload, execute=execute)
        request_base_dir = self.headers.get("X-Request-Base-Dir", "").strip()
        if request_base_dir:
            request_dir = Path(request_base_dir).expanduser()
            if not request_dir.is_absolute():
                raise ValueError("X-Request-Base-Dir must be an absolute path")
        else:
            request_dir = REPO_ROOT

        manifest, exit_code = submit_request_payload(
            raw_payload=payload,
            request_source="http_request_body",
            request_dir=request_dir,
            execute=execute,
        )
        return {
            "request_base_dir": str(request_dir),
            "authenticated_identity": identity,
            "manifest": manifest,
            "exit_code": exit_code,
        }

    def _success_payload(self, path: str, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": RESPONSE_SCHEMA,
            "method": self.command,
            "path": path,
            "result": result,
        }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Serve a local HTTP API for the query/workflow submission adapter.")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18091)
    ap.add_argument("--auth-token-env", default="", help="Optional bearer-token env var for non-health endpoints")
    ap.add_argument("--metadata-db-path", default="", help="Metadata DB path required when --identity-token-config is used")
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
    ap.add_argument("--allow-execute", action="store_true", help="Enable the /v1/query-workflows/execute endpoint")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.identity_token_config and not args.metadata_db_path:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path")
    auth_token = read_auth_token(args.auth_token_env)
    server = QueryWorkflowApiServer(
        (args.bind_host, args.port),
        QueryWorkflowApiHandler,
        auth_token=auth_token,
        metadata_db_path=args.metadata_db_path,
        identity_token_config=args.identity_token_config,
        allow_execute=args.allow_execute,
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
