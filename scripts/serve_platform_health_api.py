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

from check_platform_health import build_health_report


HEALTH_SCHEMA = "platform_health_api_health/v1"
RESPONSE_SCHEMA = "platform_health_api_response/v1"
ERROR_SCHEMA = "platform_health_api_error/v1"


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


class PlatformHealthApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        auth_token: str,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.auth_token = auth_token
        self.pid_file = pid_file
        self.ready_file = ready_file
        super().__init__(server_address, handler_cls)


class PlatformHealthApiHandler(BaseHTTPRequestHandler):
    server: PlatformHealthApiServer

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
            raise PermissionError("platform health API auth failed")

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
                        "auth_required": bool(self.server.auth_token),
                        "available_results": ["platform_health/v1"],
                    },
                )
                return

            self._require_auth()
            if parsed.path == "/v1/platform-health":
                payload = build_health_report(
                    record_recovery_configs=params.get("record_recovery_config", []),
                    record_recovery_socket=single_param(params, "record_recovery_socket"),
                    record_recovery_endpoint_url=single_param(params, "record_recovery_endpoint_url"),
                    record_recovery_auth_env=single_param(params, "record_recovery_auth_env"),
                    key_agent_socket=single_param(params, "key_agent_socket"),
                    key_agent_auth_env=single_param(params, "key_agent_auth_env"),
                    key_name=single_param(params, "key_name", "bridge-token"),
                    key_purpose=single_param(params, "key_purpose", "bridge_token"),
                    caller=single_param(params, "caller", "auto_demo"),
                    job_id=single_param(params, "job_id", "platform_health_check"),
                    external_kms_configs=params.get("external_kms_config", []),
                    out_bases=params.get("out_base", []),
                    metadata_dbs=params.get("metadata_db", []),
                )
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
    ap = argparse.ArgumentParser(description="Serve a thin local read-only HTTP API over the platform health sidecar.")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18093)
    ap.add_argument("--auth-token-env", default="", help="Optional bearer-token env var for non-health endpoints")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    auth_token = read_auth_token(args.auth_token_env)
    server = PlatformHealthApiServer(
        (args.bind_host, args.port),
        PlatformHealthApiHandler,
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
