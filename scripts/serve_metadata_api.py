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
from urllib.parse import parse_qs, urlparse, unquote

from metadata_db import connect_db
from query_metadata import LIST_ENTITY_CHOICES, query_entities, query_job_detail, query_jobs


HEALTH_SCHEMA = "metadata_api_health/v1"
RESPONSE_SCHEMA = "metadata_api_response/v1"
ERROR_SCHEMA = "metadata_api_error/v1"


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


class MetadataApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        db_path: str,
        auth_token: str,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.db_path = str(Path(db_path).resolve())
        self.auth_token = auth_token
        self.pid_file = pid_file
        self.ready_file = ready_file
        self.state_lock = threading.Lock()
        super().__init__(server_address, handler_cls)


class MetadataApiHandler(BaseHTTPRequestHandler):
    server: MetadataApiServer

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
            raise PermissionError("metadata API auth failed")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query, keep_blank_values=False)
        try:
            if path == "/healthz":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "schema": HEALTH_SCHEMA,
                        "ok": True,
                        "db_path": self.server.db_path,
                        "auth_required": bool(self.server.auth_token),
                    },
                )
                return

            self._require_auth()
            if path == "/v1/jobs":
                payload = self._query_jobs(params)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if path.startswith("/v1/jobs/"):
                job_id = unquote(path.removeprefix("/v1/jobs/"))
                if not job_id:
                    raise ValueError("job_id is required")
                with connect_db(self.server.db_path) as conn:
                    payload = query_job_detail(conn, job_id)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if path.startswith("/v1/entities/"):
                entity = unquote(path.removeprefix("/v1/entities/"))
                payload = self._query_entities(entity, params)
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

    def _success_payload(self, *, parsed, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": RESPONSE_SCHEMA,
            "method": self.command,
            "path": parsed.path,
            "query": {key: values if len(values) > 1 else values[0] for key, values in parse_qs(parsed.query).items()},
            "result": payload,
        }

    def _parse_limit(self, params: dict[str, list[str]]) -> int:
        raw = single_param(params, "limit", "50")
        try:
            limit = int(raw)
        except ValueError as exc:
            raise ValueError("limit must be an integer") from exc
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        if limit > 1000:
            raise ValueError("limit must be <= 1000")
        return limit

    def _query_jobs(self, params: dict[str, list[str]]) -> dict[str, Any]:
        stage_sort = single_param(params, "stage_sort", "recent")
        if stage_sort not in {"recent", "duration_desc", "duration_asc"}:
            raise ValueError("stage_sort must be one of recent, duration_desc, duration_asc")
        group_by = single_param(params, "group_by", "")
        if group_by not in {"", "stage", "status"}:
            raise ValueError("group_by must be stage or status when provided")
        with connect_db(self.server.db_path) as conn:
            return query_jobs(
                conn,
                caller=single_param(params, "caller"),
                tenant_id=single_param(params, "tenant_id"),
                dataset_id=single_param(params, "dataset_id"),
                service_id=single_param(params, "service_id"),
                stage=single_param(params, "stage"),
                stage_status=single_param(params, "stage_status"),
                stage_sort=stage_sort,
                group_by=group_by,
                limit=self._parse_limit(params),
            )

    def _query_entities(self, entity: str, params: dict[str, list[str]]) -> dict[str, Any]:
        if entity not in LIST_ENTITY_CHOICES:
            raise ValueError(
                f"entity must be one of: {', '.join(LIST_ENTITY_CHOICES)}"
            )
        with connect_db(self.server.db_path) as conn:
            return query_entities(
                conn,
                entity=entity,
                caller=single_param(params, "caller"),
                tenant_id=single_param(params, "tenant_id"),
                dataset_id=single_param(params, "dataset_id"),
                service_id=single_param(params, "service_id"),
                policy_id=single_param(params, "policy_id"),
                binding_kind=single_param(params, "binding_kind"),
                permission_key=single_param(params, "permission_key"),
                limit=self._parse_limit(params),
            )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Serve a thin local read-only HTTP API over the metadata sidecar.")
    ap.add_argument("--db-path", required=True, help="SQLite metadata DB path")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18090)
    ap.add_argument("--auth-token-env", default="", help="Optional bearer-token env var for non-health endpoints")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    db_path = Path(args.db_path)
    if not db_path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {db_path}")

    auth_token = read_auth_token(args.auth_token_env)
    server = MetadataApiServer(
        (args.bind_host, args.port),
        MetadataApiHandler,
        db_path=str(db_path),
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
