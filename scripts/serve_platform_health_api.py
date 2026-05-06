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

from api_identity import PLATFORM_HEALTH_PLATFORM_ROLES, identity_has_any_role, require_identity_roles, resolve_request_identity
from check_platform_health import build_health_report
from services.record_recovery.config import load_resolved_record_recovery_service_config


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
        metadata_db_path: str,
        metadata_db_dsn: str,
        identity_token_config: str,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.auth_token = auth_token
        self.metadata_db_path = str(Path(metadata_db_path).resolve()) if metadata_db_path else ""
        self.metadata_db_dsn = metadata_db_dsn
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
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

    def _require_auth(self) -> dict[str, Any] | None:
        return resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.metadata_db_path,
            db_dsn=self.server.metadata_db_dsn,
            identity_token_config=self.server.identity_token_config,
            auth_failure_label="platform health API",
        )

    def _success_payload(self, *, parsed, payload: dict[str, Any], identity: dict[str, Any] | None) -> dict[str, Any]:
        response = {
            "schema": RESPONSE_SCHEMA,
            "method": self.command,
            "path": parsed.path,
            "query": {key: values if len(values) > 1 else values[0] for key, values in parse_qs(parsed.query).items()},
            "result_schema": payload.get("schema"),
            "result": payload,
        }
        if identity is not None:
            response["authenticated_identity"] = identity
        return response

    def _validate_service_operator_health_scope(
        self,
        identity: dict[str, Any],
        params: dict[str, list[str]],
        bearer_token: str,
    ) -> dict[str, Any]:
        require_identity_roles(
            identity,
            "service_operator",
            error_message="platform health API requires platform_admin, platform_auditor, or service_operator role",
        )
        service_id = str(identity.get("service_id") or "")
        if not service_id:
            raise PermissionError("service_operator identity is missing service_id")
        if params.get("out_base") or params.get("metadata_db") or params.get("external_kms_config"):
            raise PermissionError("service_operator platform health access cannot query pipeline, metadata DB, or external KMS state")
        if single_param(params, "record_recovery_socket") or single_param(params, "record_recovery_endpoint_url"):
            raise PermissionError("service_operator platform health access must use record_recovery_config rather than arbitrary socket/endpoint targets")
        config_paths = params.get("record_recovery_config", [])
        if not config_paths:
            raise PermissionError("service_operator platform health access requires record_recovery_config")
        for config_path in config_paths:
            config = load_resolved_record_recovery_service_config(config_path)
            if str(config.get("service_id") or "") != service_id:
                raise PermissionError("record recovery config does not match authenticated service_operator service_id")
            identity_tenant_id = str(identity.get("tenant_id") or "")
            config_tenant_id = str(config.get("tenant_id") or "")
            if identity_tenant_id and config_tenant_id and identity_tenant_id != config_tenant_id:
                raise PermissionError("record recovery config does not match authenticated service_operator tenant_id")
        caller = single_param(params, "caller")
        if caller and caller != identity["caller"]:
            raise PermissionError("platform health caller does not match authenticated identity")
        return {
            "record_recovery_configs": config_paths,
            "record_recovery_socket": single_param(params, "record_recovery_socket"),
            "record_recovery_endpoint_url": single_param(params, "record_recovery_endpoint_url"),
            "record_recovery_auth_env": single_param(params, "record_recovery_auth_env"),
            "record_recovery_identity_auth_env": "",
            "record_recovery_identity_bearer_token": bearer_token,
            "key_agent_socket": single_param(params, "key_agent_socket"),
            "key_agent_auth_env": single_param(params, "key_agent_auth_env"),
            "key_agent_identity_token_env": "",
            "key_agent_identity_bearer_token": bearer_token,
            "key_name": single_param(params, "key_name", "bridge-token"),
            "key_purpose": single_param(params, "key_purpose", "bridge_token"),
            "caller": identity["caller"],
            "job_id": single_param(params, "job_id", "platform_health_check"),
            "external_kms_configs": [],
            "out_bases": [],
            "metadata_dbs": [],
        }

    def _build_health_kwargs(
        self,
        *,
        params: dict[str, list[str]],
        identity: dict[str, Any] | None,
        bearer_token: str,
    ) -> dict[str, Any]:
        if identity is not None:
            if identity_has_any_role(identity, *PLATFORM_HEALTH_PLATFORM_ROLES):
                return {
                    "record_recovery_configs": params.get("record_recovery_config", []),
                    "record_recovery_socket": single_param(params, "record_recovery_socket"),
                    "record_recovery_endpoint_url": single_param(params, "record_recovery_endpoint_url"),
                    "record_recovery_auth_env": single_param(params, "record_recovery_auth_env"),
                    "record_recovery_identity_auth_env": single_param(params, "record_recovery_identity_auth_env"),
                    "record_recovery_identity_bearer_token": "",
                    "key_agent_socket": single_param(params, "key_agent_socket"),
                    "key_agent_auth_env": single_param(params, "key_agent_auth_env"),
                    "key_agent_identity_token_env": single_param(params, "key_agent_identity_token_env"),
                    "key_agent_identity_bearer_token": "",
                    "key_name": single_param(params, "key_name", "bridge-token"),
                    "key_purpose": single_param(params, "key_purpose", "bridge_token"),
                    "caller": single_param(params, "caller", "auto_demo"),
                    "job_id": single_param(params, "job_id", "platform_health_check"),
                    "external_kms_configs": params.get("external_kms_config", []),
                    "out_bases": params.get("out_base", []),
                    "metadata_dbs": params.get("metadata_db", []),
                }
            return self._validate_service_operator_health_scope(identity, params, bearer_token)
        return {
            "record_recovery_configs": params.get("record_recovery_config", []),
            "record_recovery_socket": single_param(params, "record_recovery_socket"),
            "record_recovery_endpoint_url": single_param(params, "record_recovery_endpoint_url"),
            "record_recovery_auth_env": single_param(params, "record_recovery_auth_env"),
            "record_recovery_identity_auth_env": single_param(params, "record_recovery_identity_auth_env"),
            "record_recovery_identity_bearer_token": "",
            "key_agent_socket": single_param(params, "key_agent_socket"),
            "key_agent_auth_env": single_param(params, "key_agent_auth_env"),
            "key_agent_identity_token_env": single_param(params, "key_agent_identity_token_env"),
            "key_agent_identity_bearer_token": "",
            "key_name": single_param(params, "key_name", "bridge-token"),
            "key_purpose": single_param(params, "key_purpose", "bridge_token"),
            "caller": single_param(params, "caller", "auto_demo"),
            "job_id": single_param(params, "job_id", "platform_health_check"),
            "external_kms_configs": params.get("external_kms_config", []),
            "out_bases": params.get("out_base", []),
            "metadata_dbs": params.get("metadata_db", []),
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
                        "auth_required": bool(self.server.auth_token or self.server.identity_token_config),
                        "available_results": ["platform_health/v1"],
                    },
                )
                return

            header = self.headers.get("Authorization", "")
            bearer_token = header[len("Bearer "):] if header.startswith("Bearer ") else ""
            identity = self._require_auth()
            if parsed.path == "/v1/platform-health":
                payload = build_health_report(**self._build_health_kwargs(params=params, identity=identity, bearer_token=bearer_token))
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload, identity=identity))
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
    ap.add_argument("--metadata-db-path", default="", help="Metadata DB path required when --identity-token-config is used")
    ap.add_argument("--metadata-db-dsn", default="", help="Metadata PostgreSQL DSN required when --identity-token-config is used")
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.identity_token_config and not args.metadata_db_path and not args.metadata_db_dsn:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path or --metadata-db-dsn")
    auth_token = read_auth_token(args.auth_token_env)
    server = PlatformHealthApiServer(
        (args.bind_host, args.port),
        PlatformHealthApiHandler,
        auth_token=auth_token,
        metadata_db_path=args.metadata_db_path,
        metadata_db_dsn=args.metadata_db_dsn,
        identity_token_config=args.identity_token_config,
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
