#!/usr/bin/env python3
import argparse
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from api_identity import resolve_identity_context
from external_kms_lib import endpoint_url_from_parts
from keyring_lib import (
    append_key_lifecycle_audit,
    ensure_key_access_allowed,
    key_entry,
    load_json_object,
    normalize_secret_ref,
    resolve_secret_ref,
    rotate_key,
    save_json_object,
    set_version_status,
)


RESULT_SCHEMA = "external_kms_result/v1"
ADMIN_RESULT_SCHEMA = "external_kms_admin_result/v1"
HEALTH_SCHEMA = "external_kms_health/v1"
ERROR_SCHEMA = "external_kms_error/v1"
ADMIN_PLATFORM_ROLES = {"platform_admin"}
SERVICE_OPERATOR_PLATFORM_ROLES = {"service_operator"}


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


def _identity_has_any_role(identity: Dict[str, Any] | None, *roles: str) -> bool:
    if not identity:
        return False
    current = set(identity.get("platform_roles") or [])
    return any(role in current for role in roles)


class ExternalKmsHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self,
                 server_address,
                 handler_cls,
                 *,
                 state_file: str,
                 auth_token: str,
                 admin_auth_token: str,
                 metadata_db_path: str,
                 identity_token_config: str,
                 vault_kv_file: str,
                 lifecycle_audit_log: str,
                 pid_file: str,
                 ready_file: str):
        self.state_file = state_file
        self.auth_token = auth_token
        self.admin_auth_token = admin_auth_token
        self.metadata_db_path = metadata_db_path
        self.identity_token_config = identity_token_config
        self.vault_kv_file = vault_kv_file
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

    def _require_auth(self, *, admin: bool) -> Dict[str, Any] | None:
        expected = self.server.admin_auth_token if admin else self.server.auth_token
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if expected:
            if not header.startswith(prefix):
                raise PermissionError("missing bearer token")
            provided = header[len(prefix):]
            if provided == expected:
                return None
        if self.server.identity_token_config:
            if not header.startswith(prefix):
                raise PermissionError("missing bearer token")
            provided = header[len(prefix):]
            return resolve_identity_context(
                db_path=self.server.metadata_db_path,
                identity_token_config=self.server.identity_token_config,
                bearer_token=provided,
            )
        if expected:
            raise PermissionError("external KMS auth failed")
        return None

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self._send_json(HTTPStatus.NOT_FOUND, build_error("not found"))
            return
        self._send_json(HTTPStatus.OK, {"schema": HEALTH_SCHEMA, "ok": True})

    def do_POST(self) -> None:
        try:
            if self.path == "/v1/resolve":
                identity = self._require_auth(admin=False)
                payload = self._read_json_body()
                result = self._handle_resolve(payload, identity=identity)
                self._send_json(HTTPStatus.OK, result)
                return
            if self.path == "/v1/admin/rotate":
                identity = self._require_auth(admin=True)
                payload = self._read_json_body()
                result = self._handle_rotate(payload, identity=identity)
                self._send_json(HTTPStatus.OK, result)
                return
            if self.path == "/v1/admin/set-status":
                identity = self._require_auth(admin=True)
                payload = self._read_json_body()
                result = self._handle_set_status(payload, identity=identity)
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_json(HTTPStatus.NOT_FOUND, build_error("not found"))
        except PermissionError as e:
            self._send_json(HTTPStatus.FORBIDDEN, build_error(str(e)))
        except ValueError as e:
            self._send_json(HTTPStatus.BAD_REQUEST, build_error(str(e)))
        except Exception as e:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, build_error(str(e)))

    def _handle_resolve(self, payload: Dict[str, Any], *, identity: Dict[str, Any] | None) -> Dict[str, Any]:
        key_name = str(payload.get("key_name", ""))
        purpose = str(payload.get("purpose", ""))
        caller = str(payload.get("caller", ""))
        if identity is not None:
            if caller and caller != identity["caller"]:
                raise PermissionError("external KMS caller does not match authenticated identity")
            caller = identity["caller"]
        if not key_name:
            raise ValueError("key_name is required")
        if not purpose:
            raise ValueError("purpose is required")

        with self.server.state_lock:
            keyring = load_json_object(self.server.state_file)
            key_version, _key_value, _version_value, secret_ref = ensure_key_access_allowed(
                keyring=keyring,
                key_name=key_name,
                purpose=purpose,
                caller=caller,
            )
        secret = resolve_secret_ref(secret_ref=secret_ref, vault_kv_file=self.server.vault_kv_file)
        return {
            "schema": RESULT_SCHEMA,
            "key_id": key_name,
            "key_version": key_version,
            "secret": secret,
        }

    def _authorize_admin_identity(
        self,
        *,
        identity: Dict[str, Any] | None,
        keyring: Dict[str, Any],
        key_name: str,
        caller: str,
        create_key: bool,
    ) -> str:
        if identity is None:
            return caller
        if caller and caller != identity["caller"]:
            raise PermissionError("external KMS admin caller does not match authenticated identity")
        resolved_caller = identity["caller"]
        if _identity_has_any_role(identity, *ADMIN_PLATFORM_ROLES):
            return resolved_caller
        if not _identity_has_any_role(identity, *SERVICE_OPERATOR_PLATFORM_ROLES):
            raise PermissionError("external KMS admin requires platform_admin or service_operator role")
        if create_key:
            raise PermissionError("service_operator cannot create new external KMS keys")
        try:
            entry = key_entry(keyring, key_name)
        except ValueError as exc:
            raise PermissionError(str(exc)) from exc
        allowed_callers = entry.get("allowed_callers", [])
        if not isinstance(allowed_callers, list) or resolved_caller not in {str(item) for item in allowed_callers}:
            raise PermissionError(f"service_operator caller {resolved_caller} is not allowed to manage key {key_name}")
        return resolved_caller

    def _handle_rotate(self, payload: Dict[str, Any], *, identity: Dict[str, Any] | None) -> Dict[str, Any]:
        key_name = str(payload.get("key_name", ""))
        purpose = str(payload.get("purpose", ""))
        new_version = str(payload.get("new_version", ""))
        secret_env = str(payload.get("secret_env", ""))
        secret_ref_kind = str(payload.get("secret_ref_kind", ""))
        secret_ref_name = str(payload.get("secret_ref_name", ""))
        secret_ref_version = str(payload.get("secret_ref_version", ""))
        secret_ref_field = str(payload.get("secret_ref_field", ""))
        caller = str(payload.get("caller", ""))
        activate = bool(payload.get("activate", False))
        create_key = bool(payload.get("create_key", False))
        if not key_name:
            raise ValueError("key_name is required")
        if not purpose:
            raise ValueError("purpose is required")
        if not new_version:
            raise ValueError("new_version is required")
        if not caller:
            raise ValueError("caller is required")
        if secret_ref_kind or secret_ref_name:
            if not secret_ref_kind or not secret_ref_name:
                raise ValueError("secret_ref_kind and secret_ref_name must be provided together")
            secret_ref = normalize_secret_ref(
                {
                    "kind": secret_ref_kind,
                    "name": secret_ref_name,
                    "version": secret_ref_version or None,
                    "field": secret_ref_field or None,
                }
            )
        else:
            if not secret_env:
                raise ValueError("secret_env or secret_ref_kind/secret_ref_name is required")
            secret_ref = normalize_secret_ref({"kind": "env", "name": secret_env})

        with self.server.state_lock:
            keyring = load_json_object(self.server.state_file)
            caller = self._authorize_admin_identity(
                identity=identity,
                keyring=keyring,
                key_name=key_name,
                caller=caller,
                create_key=create_key,
            )
            rotate_key(
                keyring=keyring,
                key_name=key_name,
                purpose=purpose,
                new_version=new_version,
                caller=caller,
                activate=activate,
                secret_ref=secret_ref,
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
            secret_source_kind=str(secret_ref["kind"]),
            secret_source_name=str(secret_ref["name"]),
        )
        return {
            "schema": ADMIN_RESULT_SCHEMA,
            "action": "rotate",
            "key_name": key_name,
            "key_version": new_version,
            "status": "active" if activate else "inactive",
            "active_version": active_version,
        }

    def _handle_set_status(self, payload: Dict[str, Any], *, identity: Dict[str, Any] | None) -> Dict[str, Any]:
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
            caller = self._authorize_admin_identity(
                identity=identity,
                keyring=keyring,
                key_name=key_name,
                caller=caller,
                create_key=False,
            )
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
    ap.add_argument("--metadata-db-path", default="", help="Metadata DB path required when --identity-token-config is used")
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
    ap.add_argument("--vault-kv-file", default="")
    ap.add_argument("--lifecycle-audit-log", required=True)
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    args = ap.parse_args()
    if args.identity_token_config and not args.metadata_db_path:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path")

    server = ExternalKmsHttpServer(
        (args.bind_host, args.port),
        ExternalKmsHandler,
        state_file=os.path.abspath(args.state_file),
        auth_token=_read_optional_env(args.auth_token_env),
        admin_auth_token=_read_optional_env(args.admin_auth_token_env),
        metadata_db_path=os.path.abspath(args.metadata_db_path) if args.metadata_db_path else "",
        identity_token_config=os.path.abspath(args.identity_token_config) if args.identity_token_config else "",
        vault_kv_file=os.path.abspath(args.vault_kv_file) if args.vault_kv_file else "",
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
