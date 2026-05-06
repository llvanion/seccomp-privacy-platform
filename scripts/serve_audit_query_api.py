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

from api_identity import enforce_audit_result_access, resolve_request_identity
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
        metadata_db_path: str,
        metadata_db_dsn: str,
        identity_token_config: str,
        pid_file: str,
        ready_file: str,
    ) -> None:
        self.out_base = str(Path(out_base).resolve())
        self.audit_chain_path = str(Path(self.out_base) / "audit_chain.json")
        self.public_report_path = str(Path(self.out_base) / "a_psi_run" / "public_report.json")
        self.auth_token = auth_token
        self.metadata_db_path = str(Path(metadata_db_path).resolve()) if metadata_db_path else ""
        self.metadata_db_dsn = metadata_db_dsn
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
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

    def _require_auth(self) -> dict[str, Any] | None:
        return resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.metadata_db_path,
            db_dsn=self.server.metadata_db_dsn,
            identity_token_config=self.server.identity_token_config,
            auth_failure_label="audit query API",
        )

    def _load_audit_chain(self) -> dict[str, Any]:
        return load_observability_json_object(observability_repo_path(self.server.audit_chain_path))

    def _load_public_report(self) -> dict[str, Any]:
        return load_catalog_json_object(catalog_repo_path(self.server.public_report_path))

    def _success_payload(
        self,
        *,
        parsed,
        payload: dict[str, Any],
        identity: dict[str, Any] | None,
        access_scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
        if access_scope:
            response["access_scope"] = access_scope
        return response

    def _audit_scope(self, chain: dict[str, Any]) -> dict[str, Any]:
        public_report = chain.get("public_report") if isinstance(chain.get("public_report"), dict) else {}
        records: list[dict[str, Any]] = []
        for key in (
            "sse_export_audit",
            "record_recovery_service_audit",
            "bridge_audit",
            "pjc_audit",
            "policy_audit",
            "key_access_audit",
        ):
            value = chain.get(key)
            if isinstance(value, list):
                records.extend(record for record in value if isinstance(record, dict))
        return {
            "job_id": chain.get("job_id") or public_report.get("job_id"),
            "correlation_id": chain.get("correlation_id") or public_report.get("correlation_id"),
            "caller": public_report.get("caller") or next((record.get("caller") for record in records if record.get("caller")), None),
            "tenant_id": next((record.get("tenant_id") for record in records if record.get("tenant_id")), None),
            "dataset_id": next((record.get("dataset_id") for record in records if record.get("dataset_id")), None),
            "service_id": next((record.get("service_id") for record in records if record.get("service_id")), None),
        }

    def _enforce_audit_scope(
        self,
        identity: dict[str, Any] | None,
        scope: dict[str, Any],
        *,
        include_paths: bool,
    ) -> dict[str, str] | None:
        if identity is None:
            return None
        return enforce_audit_result_access(
            identity,
            caller=str(scope.get("caller") or ""),
            tenant_id=str(scope.get("tenant_id") or ""),
            include_paths=include_paths,
        )

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
                        "auth_required": bool(self.server.auth_token or self.server.identity_token_config),
                        "metadata_db_path": self.server.metadata_db_path or None,
                        "metadata_db_dsn": self.server.metadata_db_dsn or None,
                        "available_results": [
                            "public_report/v2",
                            "audit_chain/v1",
                            "pipeline_observability/v1",
                            "catalog_lineage/v1",
                        ],
                    },
                )
                return

            identity = self._require_auth()
            chain = self._load_audit_chain()
            access_scope = self._audit_scope(chain)
            if parsed.path == "/v1/public-report":
                self._enforce_audit_scope(identity, access_scope, include_paths=False)
                self._send_json(
                    HTTPStatus.OK,
                    self._success_payload(
                        parsed=parsed,
                        payload=self._load_public_report(),
                        identity=identity,
                        access_scope=access_scope,
                    ),
                )
                return
            if parsed.path == "/v1/audit-chain":
                self._enforce_audit_scope(identity, access_scope, include_paths=False)
                self._send_json(
                    HTTPStatus.OK,
                    self._success_payload(
                        parsed=parsed,
                        payload=chain,
                        identity=identity,
                        access_scope=access_scope,
                    ),
                )
                return
            if parsed.path == "/v1/observability":
                self._enforce_audit_scope(identity, access_scope, include_paths=False)
                payload = build_observability(chain)
                self._send_json(
                    HTTPStatus.OK,
                    self._success_payload(
                        parsed=parsed,
                        payload=payload,
                        identity=identity,
                        access_scope=access_scope,
                    ),
                )
                return
            if parsed.path == "/v1/catalog-lineage":
                include_paths = parse_bool_param(params, "include_paths", False)
                self._enforce_audit_scope(identity, access_scope, include_paths=include_paths)
                payload = build_catalog_lineage(chain, include_paths=include_paths)
                self._send_json(
                    HTTPStatus.OK,
                    self._success_payload(
                        parsed=parsed,
                        payload=payload,
                        identity=identity,
                        access_scope=access_scope,
                    ),
                )
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
    ap.add_argument("--metadata-db-path", default="", help="Metadata DB path required when --identity-token-config is used")
    ap.add_argument("--metadata-db-dsn", default="", help="Metadata PostgreSQL DSN required when --identity-token-config is used")
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
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
    if args.identity_token_config and not args.metadata_db_path and not args.metadata_db_dsn:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path or --metadata-db-dsn")

    auth_token = read_auth_token(args.auth_token_env)
    server = AuditQueryApiServer(
        (args.bind_host, args.port),
        AuditQueryApiHandler,
        out_base=str(out_base),
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
