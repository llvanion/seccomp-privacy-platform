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

from api_identity import bind_query_request_to_identity, enforce_identity_scope, resolve_request_identity
from submit_query_workflow import REPO_ROOT, load_query_workflow_status, query_workflow_sidecar_paths, submit_request_payload


HEALTH_SCHEMA = "query_workflow_api_health/v1"
RESPONSE_SCHEMA = "query_workflow_api_response/v1"
STATUS_RESPONSE_SCHEMA = "query_workflow_status_api_response/v1"
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


class EndpointDisabledError(PermissionError):
    pass


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
        metadata_db_dsn: str,
        metadata_db_read_dsn: str,
        identity_token_config: str,
        allow_execute: bool,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.auth_token = auth_token
        self.metadata_db_path = str(Path(metadata_db_path).resolve()) if metadata_db_path else ""
        self.metadata_db_dsn = metadata_db_dsn
        self.metadata_db_read_dsn = metadata_db_read_dsn
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

    def _error(self, status: int, message: str, *, error_class: str) -> None:
        self._send_json(
            status,
            {
                "schema": ERROR_SCHEMA,
                "method": self.command,
                "path": self.path,
                "error_class": error_class,
                "error": message,
            },
        )

    def _require_auth(self) -> dict[str, Any] | None:
        return resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            cookie_header=self.headers.get("Cookie", ""),
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.metadata_db_path,
            db_dsn=self.server.metadata_db_dsn,
            db_read_dsn=self.server.metadata_db_read_dsn,
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
        try:
            if parsed.path == "/healthz":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "schema": HEALTH_SCHEMA,
                        "ok": True,
                        "auth_required": bool(self.server.auth_token or self.server.identity_token_config),
                        "allow_execute": self.server.allow_execute,
                        "metadata_db_path": self.server.metadata_db_path or None,
                        "metadata_db_dsn": self.server.metadata_db_dsn or None,
                        "request_base_dir_default": str(REPO_ROOT),
                    },
                )
                return
            if parsed.path == "/v1/query-workflows/status":
                identity = self._require_auth()
                payload = self._handle_status(identity=identity, raw_query=parsed.query)
                self._send_json(
                    HTTPStatus.OK,
                    self._success_payload(parsed.path, payload, response_schema=STATUS_RESPONSE_SCHEMA),
                )
                return
            self._error(HTTPStatus.NOT_FOUND, "not found", error_class="not_found")
        except EndpointDisabledError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc), error_class="endpoint_disabled")
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc), error_class="authz_rejected")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), error_class="validation_rejected")
        except FileNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc), error_class="not_found")
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), error_class="internal_error")

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
                    raise EndpointDisabledError("query workflow execute endpoint is disabled")
                payload = self._handle_submit(execute=True, identity=identity)
                status = HTTPStatus.OK if payload.get("manifest", {}).get("exit_code") in (None, 0) else HTTPStatus.BAD_GATEWAY
                self._send_json(status, self._success_payload(parsed.path, payload))
                return
            self._error(HTTPStatus.NOT_FOUND, "not found", error_class="not_found")
        except EndpointDisabledError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc), error_class="endpoint_disabled")
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc), error_class="authz_rejected")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), error_class="validation_rejected")
        except SystemExit as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), error_class="validation_rejected")
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), error_class="internal_error")

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

        manifest, exit_code, receipt, status = submit_request_payload(
            raw_payload=payload,
            request_source="http_request_body",
            request_dir=request_dir,
            execute=execute,
        )
        request_summary = manifest.get("request_summary") or {}
        out_base = str(request_summary.get("out_base") or "")
        sidecar_paths = query_workflow_sidecar_paths(out_base) if out_base else {}
        return {
            "request_base_dir": str(request_dir),
            "authenticated_identity": identity,
            "manifest": manifest,
            "receipt": receipt,
            "status": status,
            "submission_manifest_path": str(sidecar_paths["submission_manifest"]) if sidecar_paths else "",
            "execution_receipts_path": str(sidecar_paths["execution_receipts"]) if sidecar_paths else "",
            "status_path": str(sidecar_paths["status"]) if sidecar_paths else "",
            "exit_code": exit_code,
        }

    def _handle_status(self, *, identity: dict[str, Any] | None, raw_query: str) -> dict[str, Any]:
        params = parse_qs(raw_query, keep_blank_values=False)
        out_base = str((params.get("out_base") or [""])[0]).strip()
        if not out_base:
            raise ValueError("out_base query parameter is required")
        out_path = Path(out_base).expanduser()
        if not out_path.is_absolute():
            raise ValueError("out_base must be an absolute path")
        status = load_query_workflow_status(str(out_path.resolve()))
        requested_job_id = str((params.get("job_id") or [""])[0]).strip()
        if requested_job_id and requested_job_id != str(status.get("job_id") or ""):
            raise FileNotFoundError(f"query workflow status did not match requested job_id: {requested_job_id}")
        if identity is not None:
            enforce_identity_scope(
                identity,
                caller=str(status.get("caller") or ""),
                tenant_id=str(status.get("tenant_id") or ""),
                access_label="query workflow status",
            )
        sidecar_paths = query_workflow_sidecar_paths(str(out_path.resolve()))
        return {
            "authenticated_identity": identity,
            "out_base": str(out_path.resolve()),
            "submission_manifest_path": str(sidecar_paths["submission_manifest"]),
            "execution_receipts_path": str(sidecar_paths["execution_receipts"]),
            "status_path": str(sidecar_paths["status"]),
            "status": status,
        }

    def _success_payload(self, path: str, result: dict[str, Any], *, response_schema: str = RESPONSE_SCHEMA) -> dict[str, Any]:
        return {
            "schema": response_schema,
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
    ap.add_argument("--metadata-db-dsn", default="", help="Metadata PostgreSQL DSN required when --identity-token-config is used")
    ap.add_argument(
        "--metadata-db-dsn-read-replica",
        default="",
        help="Optional PostgreSQL replica DSN; preferred for identity-resolution SELECTs when set",
    )
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
    ap.add_argument("--allow-execute", action="store_true", help="Enable the /v1/query-workflows/execute endpoint")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.identity_token_config and not args.metadata_db_path and not args.metadata_db_dsn:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path or --metadata-db-dsn")
    auth_token = read_auth_token(args.auth_token_env)
    server = QueryWorkflowApiServer(
        (args.bind_host, args.port),
        QueryWorkflowApiHandler,
        auth_token=auth_token,
        metadata_db_path=args.metadata_db_path,
        metadata_db_dsn=args.metadata_db_dsn,
        metadata_db_read_dsn=args.metadata_db_dsn_read_replica,
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
