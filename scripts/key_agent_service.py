#!/usr/bin/env python3
import argparse
import json
import os
import socketserver
from pathlib import Path

from keyring_lib import (
    append_key_access_audit,
    ensure_key_access_allowed,
    load_json_object,
)


RESULT_SCHEMA = "key_agent_result/v1"
ERROR_SCHEMA = "key_agent_error/v1"


def build_error(message: str) -> dict:
    return {
        "schema": ERROR_SCHEMA,
        "error": message,
    }


class KeyAgentUnixStreamServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self,
                 socket_path: str,
                 handler,
                 *,
                 keyring_path: str,
                 auth_token: str,
                 allowed_callers: set[str],
                 audit_log: str,
                 pid_file: str,
                 ready_file: str):
        self.keyring_path = keyring_path
        self.auth_token = auth_token
        self.allowed_callers = allowed_callers
        self.audit_log = audit_log
        self.pid_file = pid_file
        self.ready_file = ready_file
        super().__init__(socket_path, handler)


class KeyAgentRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.read()
        if not raw:
            return

        payload = {}
        try:
            payload = json.loads(raw.decode("utf-8"))
            result = _handle_request(payload, self.server)
        except Exception as e:
            key_name = str(payload.get("key_name", "")) if isinstance(payload, dict) else ""
            append_key_access_audit(
                path=self.server.audit_log,
                caller=str(payload.get("caller", "")) if isinstance(payload, dict) else "unknown",
                job_id=str(payload.get("job_id", "")) if isinstance(payload, dict) else "",
                key_id=key_name or "unknown",
                key_version="unknown",
                purpose=str(payload.get("purpose", "")) if isinstance(payload, dict) else "bridge_token",
                decision="deny",
                reason_code="request_failed",
                config_file=self.server.keyring_path,
                secret_source_kind="key_agent",
                secret_source_name=str(self.server.server_address),
                resolver_kind="key_agent",
                socket_path=str(self.server.server_address),
                reason=str(e),
            )
            result = build_error(str(e))

        self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        self.wfile.flush()


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


def _handle_request(payload: dict, server: KeyAgentUnixStreamServer) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("key agent request must be a JSON object")

    caller = str(payload.get("caller", ""))
    if server.allowed_callers and caller not in server.allowed_callers:
        raise PermissionError(f"caller {caller or '<missing>'} is not allowed to use key agent")

    if server.auth_token:
        provided = str(payload.get("auth_token", ""))
        if not provided or provided != server.auth_token:
            raise PermissionError("key agent auth failed")

    key_name = str(payload.get("key_name", ""))
    purpose = str(payload.get("purpose", ""))
    job_id = str(payload.get("job_id", ""))
    if not key_name:
        raise ValueError("key_name is required")
    if not purpose:
        raise ValueError("purpose is required")

    keyring = load_json_object(server.keyring_path)
    key_version, _key_value, _version_value, env_name = ensure_key_access_allowed(
        keyring=keyring,
        key_name=key_name,
        purpose=purpose,
        caller=caller,
    )
    secret = os.environ.get(env_name, "")
    append_key_access_audit(
        path=server.audit_log,
        caller=caller,
        job_id=job_id,
        key_id=key_name,
        key_version=key_version,
        purpose=purpose,
        decision="allow",
        reason_code="ok",
        config_file=server.keyring_path,
        secret_source_kind="key_agent",
        secret_source_name=str(server.server_address),
        resolver_kind="key_agent",
        socket_path=str(server.server_address),
    )
    return {
        "schema": RESULT_SCHEMA,
        "key_id": key_name,
        "key_version": key_version,
        "secret": secret,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Long-running Unix-socket key agent that resolves active keys from a local keyring.")
    ap.add_argument("--socket-path", required=True)
    ap.add_argument("--keyring", required=True)
    ap.add_argument("--auth-token-env", default="")
    ap.add_argument("--allowed-caller", action="append", default=[])
    ap.add_argument("--audit-log", required=True)
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    args = ap.parse_args()

    socket_path = Path(args.socket_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    server = KeyAgentUnixStreamServer(
        str(socket_path),
        KeyAgentRequestHandler,
        keyring_path=os.path.abspath(args.keyring),
        auth_token=_read_optional_env(args.auth_token_env),
        allowed_callers={str(item) for item in args.allowed_caller},
        audit_log=os.path.abspath(args.audit_log),
        pid_file=args.pid_file,
        ready_file=args.ready_file,
    )

    _write_text_file(args.pid_file, f"{os.getpid()}\n")
    _write_text_file(args.ready_file, str(socket_path.resolve()) + "\n")

    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        if socket_path.exists():
            socket_path.unlink()
        if args.ready_file and os.path.exists(args.ready_file):
            os.unlink(args.ready_file)
        if args.pid_file and os.path.exists(args.pid_file):
            os.unlink(args.pid_file)


if __name__ == "__main__":
    raise SystemExit(main())
