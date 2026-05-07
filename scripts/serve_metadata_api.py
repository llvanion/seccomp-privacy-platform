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

from api_identity import build_identity_resolution_payload, enforce_identity_scope, metadata_scope_filters, resolve_request_identity
from metadata_db import connect_read_db
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
        db_dsn: str,
        db_read_dsn: str,
        auth_token: str,
        identity_token_config: str,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.db_path = str(Path(db_path).resolve()) if db_path else ""
        self.db_dsn = db_dsn
        self.db_read_dsn = db_read_dsn
        self.auth_token = auth_token
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
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

    def _require_auth(self) -> dict[str, Any] | None:
        return resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.db_path,
            db_dsn=self.server.db_dsn,
            db_read_dsn=self.server.db_read_dsn,
            identity_token_config=self.server.identity_token_config,
            auth_failure_label="metadata API",
        )

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
                        "db_path": self.server.db_path or None,
                        "db_dsn": self.server.db_dsn or None,
                        "auth_required": bool(self.server.auth_token or self.server.identity_token_config),
                    },
                )
                return

            identity = self._require_auth()
            if path == "/v1/identity":
                if identity is None:
                    raise PermissionError("metadata identity endpoint requires identity-backed bearer token auth")
                payload = build_identity_resolution_payload(identity, resolution_mode="bearer_token")
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if path == "/v1/jobs":
                payload = self._query_jobs(params, identity=identity)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if path.startswith("/v1/jobs/"):
                job_id = unquote(path.removeprefix("/v1/jobs/"))
                if not job_id:
                    raise ValueError("job_id is required")
                with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                    payload = query_job_detail(conn, job_id)
                if identity is not None and not payload.get("job"):
                    raise PermissionError("job not found")
                if identity is not None and not payload.get("error") and payload.get("job"):
                    enforce_identity_scope(
                        identity,
                        caller=str(payload["job"].get("caller") or ""),
                        tenant_id=str(payload["job"].get("tenant_id") or ""),
                        access_label="job detail",
                    )
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if path.startswith("/v1/entities/"):
                entity = unquote(path.removeprefix("/v1/entities/"))
                payload = self._query_entities(entity, params, identity=identity)
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

    def _parse_offset(self, params: dict[str, list[str]]) -> int:
        raw = single_param(params, "offset", "0")
        try:
            offset = int(raw)
        except ValueError as exc:
            raise ValueError("offset must be an integer") from exc
        if offset < 0:
            raise ValueError("offset must be >= 0")
        return offset

    def _query_jobs(self, params: dict[str, list[str]], *, identity: dict[str, Any] | None) -> dict[str, Any]:
        stage_sort = single_param(params, "stage_sort", "recent")
        if stage_sort not in {"recent", "duration_desc", "duration_asc"}:
            raise ValueError("stage_sort must be one of recent, duration_desc, duration_asc")
        group_by = single_param(params, "group_by", "")
        if group_by not in {"", "stage", "status"}:
            raise ValueError("group_by must be stage or status when provided")
        scoped = {
            "caller": single_param(params, "caller"),
            "tenant_id": single_param(params, "tenant_id"),
        }
        if identity is not None:
            scoped = metadata_scope_filters(
                identity,
                caller=scoped["caller"],
                tenant_id=scoped["tenant_id"],
            )
        with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
            return query_jobs(
                conn,
                caller=scoped["caller"],
                tenant_id=scoped["tenant_id"],
                dataset_id=single_param(params, "dataset_id"),
                service_id=single_param(params, "service_id"),
                stage=single_param(params, "stage"),
                stage_status=single_param(params, "stage_status"),
                stage_sort=stage_sort,
                group_by=group_by,
                limit=self._parse_limit(params),
                offset=self._parse_offset(params),
            )

    def _query_entities(self, entity: str, params: dict[str, list[str]], *, identity: dict[str, Any] | None) -> dict[str, Any]:
        if entity not in LIST_ENTITY_CHOICES:
            raise ValueError(
                f"entity must be one of: {', '.join(LIST_ENTITY_CHOICES)}"
            )
        scoped = {
            "caller": single_param(params, "caller"),
            "tenant_id": single_param(params, "tenant_id"),
        }
        if identity is not None:
            scoped = metadata_scope_filters(
                identity,
                entity=entity,
                caller=scoped["caller"],
                tenant_id=scoped["tenant_id"],
            )
        with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
            return query_entities(
                conn,
                entity=entity,
                caller=scoped["caller"],
                tenant_id=scoped["tenant_id"],
                dataset_id=single_param(params, "dataset_id"),
                service_id=single_param(params, "service_id"),
                policy_id=single_param(params, "policy_id"),
                binding_kind=single_param(params, "binding_kind"),
                permission_key=single_param(params, "permission_key"),
                subject_type=single_param(params, "subject_type"),
                issuer=single_param(params, "issuer"),
                key_name=single_param(params, "key_name"),
                purpose=single_param(params, "purpose"),
                limit=self._parse_limit(params),
                offset=self._parse_offset(params),
            )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Serve a thin local read-only HTTP API over the metadata sidecar.")
    ap.add_argument("--db-path", default="", help="SQLite metadata DB path")
    ap.add_argument("--db-dsn", default="", help="Optional PostgreSQL DSN")
    ap.add_argument(
        "--db-dsn-read-replica",
        default="",
        help="Optional PostgreSQL replica DSN; preferred for read-only SELECTs (jobs/entities/identity)",
    )
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18090)
    ap.add_argument("--auth-token-env", default="", help="Optional bearer-token env var for non-health endpoints")
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if not args.db_path and not args.db_dsn:
        raise SystemExit("[ERROR] one of --db-path or --db-dsn is required")
    db_path = Path(args.db_path) if args.db_path else None
    if db_path is not None and not db_path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {db_path}")

    auth_token = read_auth_token(args.auth_token_env)
    server = MetadataApiServer(
        (args.bind_host, args.port),
        MetadataApiHandler,
        db_path=str(db_path) if db_path else "",
        db_dsn=args.db_dsn,
        db_read_dsn=args.db_dsn_read_replica,
        auth_token=auth_token,
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
