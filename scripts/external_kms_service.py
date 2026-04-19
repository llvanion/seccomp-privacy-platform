#!/usr/bin/env python3
import argparse
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from external_kms_lib import endpoint_url_from_parts
from keyring_lib import (
    append_key_lifecycle_audit,
    ensure_key_access_allowed,
    load_json_object,
    rotate_key,
    save_json_object,
    set_version_status,
)


RESULT_SCHEMA = "external_kms_result/v1"
ADMIN_RESULT_SCHEMA = "external_kms_admin_result/v1"
HEALTH_SCHEMA = "external_kms_health/v1"
ERROR_SCHEMA = "external_kms_error/v1"


def build_error(message: str) -> Dict[str, Any]:
    return {"schema": ERROR_SCHEMA, "error": message}


def _read_optional_env(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name)
    if not value:
        raise ValueError(f"environment variable {env_name} is not set")
    return value


def _write_text_file(path: str, content: str) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class ExternalKmsHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self,
                 server_address,
                 handler_cls,
                 *,
                 state_file: str,
                 auth_token: str,
                 admin_auth_token: str,
                 lifecycle_audit_log: str,
                 pid_file: str,
                 ready_file: str):
        self.state_file = state_file
        self.auth_token = auth_token
        self.admin_auth_token = admin_auth_token
        self.lifecycle_audit_log = lifecycle_audit_log
        self.pid_file = pid_file
        self.ready_file = ready_file
        self.state_lock = threading.Lock()
        super().__init__(server_address, handler_cls)


class ExternalKmsHandler(BaseHTTPRequestHandler):
    server: ExternalKmsHttpServer

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON body: {e}") from e
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _require_auth(self, *, admin: bool) -> None:
        expected = self.server.admin_auth_token if admin else self.server.auth_token
        if not expected:
            return
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            raise PermissionError("missing bearer token")
        provided = header[len(prefix):]
        if provided != expected:
            raise PermissionError("external KMS auth failed")

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self._send_json(HTTPStatus.NOT_FOUND, build_error("not found"))
            return
        self._send_json(HTTPStatus.OK, {"schema": HEALTH_SCHEMA, "ok": True})

    def do_POST(self) -> None:
        try:
            if self.path == "/v1/resolve":
                self._require_auth(admin=False)
                payload = self._read_json_body()
                result = self._handle_resolve(payload)
                self._send_json(HTTPStatus.OK, result)
                return
            if self.path == "/v1/admin/rotate":
                self._require_auth(admin=True)
                payload = self._read_json_body()
                result = self._handle_rotate(payload)
                self._send_json(HTTPStatus.OK, result)
                return
            if self.path == "/v1/admin/set-status":
                self._require_auth(admin=True)
                payload = self._read_json_body()
                result = self._handle_set_status(payload)
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_json(HTTPStatus.NOT_FOUND, build_error("not found"))
        except PermissionError as e:
            self._send_json(HTTPStatus.FORBIDDEN, build_error(str(e)))
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, build_error(str(e)))
        except Exception as e:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, build_error(str(e)))

    def _handle_resolve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key_name = str(payload.get("key_name", ""))
        purpose = str(payload.get("purpose", ""))
        caller = str(payload.get("caller", ""))
        if not key_name:
            raise ValueError("key_name is required")
        if not purpose:
            raise ValueError("purpose is required")

        with self.server.state_lock:
            keyring = load_json_object(self.server.state_file)
            key_version, _key_value, _version_value, env_name = ensure_key_access_allowed(
                keyring=keyring,
                key_name=key_name,
                purpose=purpose,
                caller=caller,
            )
        secret = os.environ.get(env_name, "")
        return {
            "schema": RESULT_SCHEMA,
            "key_id": key_name,
            "key_version": key_version,
            "secret": secret,
        }

    def _handle_rotate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key_name = str(payload.get("key_name", ""))
        purpose = str(payload.get("purpose", ""))
        new_version = str(payload.get("new_version", ""))
        secret_env = str(payload.get("secret_env", ""))
        caller = str(payload.get("caller", ""))
        activate = bool(payload.get("activate", False))
        create_key = bool(payload.get("create_key", False))
        if not key_name:
            raise ValueError("key_name is required")
        if not purpose:
            raise ValueError("purpose is required")
        if not new_version:
            raise ValueError("new_version is required")
        if not secret_env:
            raise ValueError("secret_env is required")
        if not caller:
            raise ValueError("caller is required")

        with self.server.state_lock:
            keyring = load_json_object(self.server.state_file)
            rotate_key(
                keyring=keyring,
                key_name=key_name,
                purpose=purpose,
                new_version=new_version,
                secret_env=secret_env,
                caller=caller,
                activate=activate,
                create_key=create_key,
            )
            save_json_object(self.server.state_file, keyring)
            active_version = keyring["keys"][key_name].get("active_version")

        append_key_lifecycle_audit(
            path=self.server.lifecycle_audit_log,
            caller=caller,
            keyring_file=self.server.state_file,
            key_name=key_name,
            key_version=new_version,
            action="rotate",
            status="active" if activate else "inactive",
            decision="allow",
            reason_code="ok",
            secret_env=secret_env,
        )
        return {
            "schema": ADMIN_RESULT_SCHEMA,
            "action": "rotate",
            "key_name": key_name,
            "key_version": new_version,
            "status": "active" if activate else "inactive",
            "active_version": active_version,
        }

    def _handle_set_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        key_name = str(payload.get("key_name", ""))
        version = str(payload.get("version", ""))
        status = str(payload.get("status", ""))
        caller = str(payload.get("caller", ""))
        if not key_name:
            raise ValueError("key_name is required")
        if not version:
            raise ValueError("version is required")
        if not status:
            raise ValueError("status is required")
        if not caller:
            raise ValueError("caller is required")

        with self.server.state_lock:
            keyring = load_json_object(self.server.state_file)
            set_version_status(keyring=keyring, key_name=key_name, version=version, status=status)
            save_json_object(self.server.state_file, keyring)
            active_version = keyring["keys"][key_name].get("active_version")

        append_key_lifecycle_audit(
            path=self.server.lifecycle_audit_log,
            caller=caller,
            keyring_file=self.server.state_file,
            key_name=key_name,
            key_version=version,
            action="set_status",
            status=status,
            decision="allow",
            reason_code="ok",
            secret_env=None,
        )
        return {
            "schema": ADMIN_RESULT_SCHEMA,
            "action": "set_status",
            "key_name": key_name,
            "key_version": version,
            "status": status,
            "active_version": active_version,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mock external HTTP KMS service for secret resolution and key lifecycle changes.")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--state-file", required=True)
    ap.add_argument("--auth-token-env", default="")
    ap.add_argument("--admin-auth-token-env", default="")
    ap.add_argument("--lifecycle-audit-log", required=True)
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    args = ap.parse_args()

    server = ExternalKmsHttpServer(
        (args.bind_host, args.port),
        ExternalKmsHandler,
        state_file=os.path.abspath(args.state_file),
        auth_token=_read_optional_env(args.auth_token_env),
        admin_auth_token=_read_optional_env(args.admin_auth_token_env),
        lifecycle_audit_log=os.path.abspath(args.lifecycle_audit_log),
        pid_file=args.pid_file,
        ready_file=args.ready_file,
    )

    endpoint = endpoint_url_from_parts(args.bind_host, args.port)
    _write_text_file(args.pid_file, f"{os.getpid()}\n")
    _write_text_file(args.ready_file, endpoint + "\n")

    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        if args.ready_file and os.path.exists(args.ready_file):
            os.unlink(args.ready_file)
        if args.pid_file and os.path.exists(args.pid_file):
            os.unlink(args.pid_file)


if __name__ == "__main__":
    raise SystemExit(main())
