#!/usr/bin/env python3
import argparse
import json
import os
import signal
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, unquote

from api_identity import (
    build_identity_resolution_payload,
    enforce_identity_scope,
    identity_has_any_role,
    metadata_scope_filters,
    resolve_request_identity,
)
from check_business_access_policy import build_report as build_business_access_report, load_json_object as load_business_policy
from metadata_db import connect_read_db, row_to_dict, table_exists
from query_metadata import LIST_ENTITY_CHOICES, query_entities, query_job_detail, query_jobs


HEALTH_SCHEMA = "metadata_api_health/v1"
RESPONSE_SCHEMA = "metadata_api_response/v1"
ERROR_SCHEMA = "metadata_api_error/v1"
DEFAULT_BUSINESS_ACCESS_POLICY = Path(__file__).resolve().parents[1] / "config" / "business_access_policy.ecommerce.example.json"
BUSINESS_READ_FIELD_MAP: dict[str, dict[str, str]] = {
    "orders": {
        "orders.order_id": "order_id",
        "orders.platform_id": "platform_id",
        "orders.campaign_id": "campaign_id",
        "orders.currency": "currency",
        "orders.total_amount_cents": "total_amount_cents",
        "orders.placed_at_utc": "placed_at_utc",
        "orders.status": "status",
        "orders.buyer_email": "buyer_email",
    },
    "order_items": {
        "order_items.sku_id": "sku_id",
        "order_items.category_id": "category_id",
        "order_items.quantity": "quantity",
        "order_items.unit_price_cents": "unit_price_cents",
        "order_items.line_total_cents": "line_total_cents",
    },
    "order_attribution": {
        "order_attribution.attribution_type": "attribution_type",
        "order_attribution.channel": "channel",
        "order_attribution.campaign_id": "campaign_id",
        "order_attribution.creative_id": "creative_id",
        "order_attribution.attribution_weight": "attribution_weight",
    },
    "order_payment": {
        "order_payment.payment_method": "payment_method",
        "order_payment.provider_id": "provider_id",
        "order_payment.paid_amount_cents": "paid_amount_cents",
        "order_payment.paid_at_utc": "paid_at_utc",
        "order_payment.risk_score": "risk_score",
        "order_payment.is_disputed": "is_disputed",
    },
    "order_fulfillment": {
        "order_fulfillment.carrier_id": "carrier_id",
        "order_fulfillment.warehouse_id": "warehouse_id",
        "order_fulfillment.shipped_at_utc": "shipped_at_utc",
        "order_fulfillment.delivered_at_utc": "delivered_at_utc",
        "order_fulfillment.status": "status",
        "order_fulfillment.delivery_latency_minutes": "delivery_latency_minutes",
    },
    "delivery_route_legs": {
        "delivery_route.leg_id": "leg_id",
        "delivery_route.route_id": "route_id",
        "delivery_route.leg_sequence": "leg_sequence",
        "delivery_route.leg_kind": "leg_kind",
        "delivery_route.assigned_courier_id": "assigned_courier_id",
        "delivery_route.assigned_station_id": "assigned_station_id",
        "delivery_route.assigned_region_id": "assigned_region_id",
        "delivery_route.origin_node_label": "origin_node_label",
        "delivery_route.destination_node_label": "destination_node_label",
        "delivery_route.destination_city": "destination_city",
        "delivery_route.destination_district": "destination_district",
        "delivery_route.next_stop_label": "next_stop_label",
        "delivery_route.next_stop_window": "next_stop_window",
        "delivery_route.next_stop_geohash_prefix": "next_stop_geohash_prefix",
        "delivery_route.pickup_station_label": "pickup_station_label",
        "delivery_route.pickup_station_geohash_prefix": "pickup_station_geohash_prefix",
        "delivery_route.final_recipient_zone": "final_recipient_zone",
        "delivery_route.final_address_token": "final_address_token",
        "delivery_route.final_address_line1": "final_address_line1",
        "delivery_route.final_address_line2": "final_address_line2",
        "delivery_route.recipient_phone": "recipient_phone",
        "delivery_route.status": "status",
        "delivery_route.started_at_utc": "started_at_utc",
        "delivery_route.completed_at_utc": "completed_at_utc",
    },
    "customer_service_interactions": {
        "customer_service_interactions.interaction_type": "interaction_type",
        "customer_service_interactions.channel": "channel",
        "customer_service_interactions.agent_id": "agent_id",
        "customer_service_interactions.opened_at_utc": "opened_at_utc",
        "customer_service_interactions.closed_at_utc": "closed_at_utc",
        "customer_service_interactions.resolution_status": "resolution_status",
    },
}
BUSINESS_READ_FILTER_COLUMNS: dict[str, set[str]] = {
    "orders": {"tenant_id", "dataset_id", "order_id", "platform_id", "campaign_id", "status"},
    "order_items": {"tenant_id", "dataset_id", "order_id", "sku_id", "category_id"},
    "order_attribution": {"tenant_id", "dataset_id", "order_id", "attribution_type", "channel", "campaign_id"},
    "order_payment": {"tenant_id", "dataset_id", "order_id", "payment_method", "provider_id", "is_disputed"},
    "order_fulfillment": {"tenant_id", "dataset_id", "order_id", "carrier_id", "warehouse_id", "status"},
    "delivery_route_legs": {
        "tenant_id",
        "dataset_id",
        "service_id",
        "order_id",
        "route_id",
        "leg_id",
        "leg_sequence",
        "leg_kind",
        "assigned_courier_id",
        "assigned_station_id",
        "assigned_region_id",
        "destination_city",
        "destination_district",
        "status",
    },
    "customer_service_interactions": {
        "tenant_id",
        "dataset_id",
        "order_id",
        "interaction_type",
        "channel",
        "agent_id",
        "resolution_status",
    },
}

METADATA_OPERATOR_ONLY_KEYS = {
    "out_base",
    "public_report_path",
    "audit_chain_path",
    "artifact_path",
    "path",
    "sha256",
    "source_file",
    "binding_json",
    "details",
    "details_json",
    "metadata_json",
    "counts_json",
    "payload",
    "query_fingerprint",
    "query_payload_sha256",
    "ledger_path",
    "public_report_sha256",
    "source_event_id",
    "key_id",
    "key_version",
    "secret_ref_name",
    "backend_key_version",
    "backend_ref",
    "config_path",
    "imported_at_utc",
    "created_at_utc",
    "updated_at_utc",
    "effective_at_utc",
    "ts_utc",
    "duration_ms",
    "total_stage_duration_ms",
    "stage_duration_summary",
    "missing_duration_stages",
    "intersection_size",
    "intersection_sum",
    "budget_used_before",
    "budget_used_after",
    "budget_cost",
    "budget_limit",
}

METADATA_SAFE_ENTITY_FIELDS: dict[str, set[str]] = {
    "tenants": {"tenant_id", "source", "job_count"},
    "datasets": {"dataset_id", "tenant_id", "source", "job_count"},
    "services": {"service_id", "tenant_id", "dataset_id", "service_type", "transport", "job_count"},
    "callers": {"caller", "tenant_id", "source", "job_count", "identity_count", "enabled_identity_count"},
    "caller-identities": {"caller", "subject_type", "service_id", "display_name", "platform_roles", "enabled"},
    "policy-bindings": {"policy_id", "binding_kind", "caller", "tenant_id", "dataset_id", "service_id"},
    "caller-permissions": {"policy_id", "caller", "permission_key", "permission_value"},
    "business-identities": {
        "business_identity_id",
        "tenant_id",
        "dataset_id",
        "identity_kind",
        "caller_id",
        "display_label",
        "enabled",
    },
    "catalog-lineage-read-model": {
        "job_id",
        "correlation_id",
        "caller",
        "tenant_id",
        "dataset_id",
        "service_id",
        "lineage_kind",
        "node_type",
        "display_name",
        "role",
        "stage",
        "path_redacted",
    },
}

METADATA_SAFE_JOB_FIELDS = {
    "job_id",
    "correlation_id",
    "caller",
    "tenant_id",
    "dataset_id",
    "service_id",
    "status",
    "release_reason_code",
    "public_report_released",
    "mainline_contract_summary",
    "matched_stage",
}

METADATA_SAFE_STAGE_FIELDS = {"stage", "status"}
METADATA_SAFE_EVENT_FIELDS = {
    "stage",
    "event_type",
    "caller",
    "tenant_id",
    "dataset_id",
    "service_id",
    "decision",
    "reason_code",
}


def _redact_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_metadata_value(child)
            for key, child in value.items()
            if key not in METADATA_OPERATOR_ONLY_KEYS
        }
    if isinstance(value, list):
        return [_redact_metadata_value(item) for item in value]
    return value


def _pick_safe_fields(row: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: _redact_metadata_value(row.get(key)) for key in allowed if key in row}


def _coarse_count(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if number <= 0:
        return "0"
    if number == 1:
        return "1"
    if number <= 5:
        return "2-5"
    if number <= 20:
        return "6-20"
    return "20+"


def _redact_permission_summary(summary: Any) -> Any:
    if not isinstance(summary, dict):
        return summary
    return {
        "caller_count": summary.get("caller_count"),
        "callers": summary.get("callers") or [],
        "tenant_ids": summary.get("tenant_ids") or [],
        "allowed_dataset_ids": summary.get("allowed_dataset_ids") or [],
        "allowed_service_ids": summary.get("allowed_service_ids") or [],
        "enabled_counts": summary.get("enabled_counts") or {},
        "platform_role_counts": summary.get("platform_role_counts") or {},
        "permissions": summary.get("permissions") or {},
    }


def redact_metadata_for_public_identity(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_metadata_value(payload)
    if isinstance(redacted.get("jobs"), list):
        redacted["jobs"] = [_pick_safe_fields(job, METADATA_SAFE_JOB_FIELDS) for job in redacted["jobs"] if isinstance(job, dict)]
    if isinstance(redacted.get("job"), dict):
        redacted["job"] = _pick_safe_fields(redacted["job"], METADATA_SAFE_JOB_FIELDS)
    if isinstance(redacted.get("items"), list):
        entity = str(redacted.get("entity") or "")
        allowed = METADATA_SAFE_ENTITY_FIELDS.get(entity)
        if allowed is not None:
            redacted["items"] = [_pick_safe_fields(item, allowed) for item in redacted["items"] if isinstance(item, dict)]
    if isinstance(redacted.get("stage_status"), list):
        redacted["stage_status"] = [_pick_safe_fields(item, METADATA_SAFE_STAGE_FIELDS) for item in redacted["stage_status"] if isinstance(item, dict)]
    if isinstance(redacted.get("audit_events"), list):
        redacted["audit_events"] = [_pick_safe_fields(item, METADATA_SAFE_EVENT_FIELDS) for item in redacted["audit_events"] if isinstance(item, dict)]
    if isinstance(redacted.get("key_access_events"), list):
        redacted["key_access_events"] = []
    if isinstance(redacted.get("privacy_budget_ledger_events"), list):
        redacted["privacy_budget_ledger_events"] = []
    if isinstance(redacted.get("permission_summary"), dict):
        redacted["permission_summary"] = _redact_permission_summary(redacted["permission_summary"])
    if isinstance(redacted.get("pagination"), dict):
        pagination = dict(redacted["pagination"])
        if "total_matching_count" in pagination:
            pagination["total_matching_count_bucket"] = _coarse_count(pagination.pop("total_matching_count"))
        redacted["pagination"] = pagination
    for key in ("stage_summary", "grouped_stage_summary", "grouped_status_summary", "timing_summary", "artifacts", "audit_chain", "audit_seal"):
        redacted.pop(key, None)
    redacted["redaction"] = {
        "view": "caller_safe_metadata_summary",
        "operator_fields_redacted": True,
        "paths_redacted": True,
        "hashes_redacted": True,
        "total_matching_count_redacted": True,
        "timing_redacted": True,
    }
    return redacted


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


def _query_business_identity_rows(
    *,
    db_path: str,
    db_dsn: str,
    db_read_dsn: str,
    caller: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    with connect_read_db(db_path, dsn=db_dsn, read_dsn=db_read_dsn) as conn:
        if not table_exists(conn, "business_identities"):
            return []
        rows = conn.execute(
            """
            SELECT
              business_identity_id,
              tenant_id,
              dataset_id,
              identity_kind,
              caller_id,
              subject_external_id,
              display_label,
              enabled
            FROM business_identities
            WHERE caller_id = ? AND tenant_id = ? AND enabled = 1
            ORDER BY updated_at_utc DESC, id DESC
            """,
            (caller, tenant_id),
        ).fetchall()
    return [row_to_dict(row) for row in rows if row_to_dict(row) is not None]


class _RateLimited(Exception):
    """Raised when a caller has exceeded the per-caller token bucket."""


class _TokenBucket:
    """Thread-safe token bucket. Identical algorithm to the recovery service."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._tokens = float(capacity)
        self._rate = rate
        self._capacity = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                float(self._capacity),
                self._tokens + (now - self._last) * self._rate,
            )
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False


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
        business_access_policy: str,
        pid_file: str,
        ready_file: str,
        rate_limit_per_caller: float = 0.0,
        rate_limit_burst: int = 0,
    ) -> None:
        self.db_path = str(Path(db_path).resolve()) if db_path else ""
        self.db_dsn = db_dsn
        self.db_read_dsn = db_read_dsn
        self.auth_token = auth_token
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
        self.business_access_policy = str(Path(business_access_policy).resolve()) if business_access_policy else ""
        self.pid_file = pid_file
        self.ready_file = ready_file
        self.state_lock = threading.Lock()
        self._rate_limit_per_caller = float(rate_limit_per_caller or 0.0)
        self._rate_limit_burst = max(0, int(rate_limit_burst or 0))
        self._rate_buckets: dict[str, _TokenBucket] = {}
        self._rate_lock = threading.Lock()
        super().__init__(server_address, handler_cls)

    def check_rate_limit(self, caller: str) -> bool:
        if self._rate_limit_per_caller <= 0:
            return True
        key = caller or "_anonymous"
        with self._rate_lock:
            bucket = self._rate_buckets.get(key)
            if bucket is None:
                bucket = _TokenBucket(
                    self._rate_limit_per_caller,
                    max(1, self._rate_limit_burst or int(self._rate_limit_per_caller)),
                )
                self._rate_buckets[key] = bucket
        return bucket.consume()


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

    def _read_json_body(self, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length in (None, ""):
            raise ValueError("missing JSON request body")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if length < 0 or length > max_bytes:
            raise ValueError("request body is too large")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object")
        return payload

    def _require_auth(self) -> dict[str, Any] | None:
        identity = resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            cookie_header=self.headers.get("Cookie", ""),
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.db_path,
            db_dsn=self.server.db_dsn,
            db_read_dsn=self.server.db_read_dsn,
            identity_token_config=self.server.identity_token_config,
            auth_failure_label="metadata API",
        )
        caller_key = str(identity.get("caller") or "") if isinstance(identity, dict) else ""
        if not self.server.check_rate_limit(caller_key):
            # Raise a PermissionError-like signal but with a distinct type so the
            # caller can map it to HTTP 429 instead of 403.
            raise _RateLimited(caller_key)
        return identity

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
                        "business_access_policy": self.server.business_access_policy or None,
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
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=self._public_metadata_payload(payload, identity=identity)))
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
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=self._public_metadata_payload(payload, identity=identity)))
                return
            if path.startswith("/v1/entities/"):
                entity = unquote(path.removeprefix("/v1/entities/"))
                payload = self._query_entities(entity, params, identity=identity)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=self._public_metadata_payload(payload, identity=identity)))
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except _RateLimited as exc:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, f"rate limit exceeded for caller {exc}")
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except SystemExit as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            identity = self._require_auth()
            if path == "/v1/business-access/check":
                payload = self._business_access_check(self._read_json_body(), identity=identity)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            if path == "/v1/business-data/read-preview":
                payload = self._business_data_read_preview(self._read_json_body(), identity=identity)
                self._send_json(HTTPStatus.OK, self._success_payload(parsed=parsed, payload=payload))
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except _RateLimited as exc:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, f"rate limit exceeded for caller {exc}")
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

    def _public_metadata_payload(self, payload: dict[str, Any], *, identity: dict[str, Any] | None) -> dict[str, Any]:
        if identity is None or identity_has_any_role(identity, "platform_admin", "platform_auditor"):
            return payload
        return redact_metadata_for_public_identity(payload)

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

    def _business_roles_for_identity(self, identity: dict[str, Any]) -> set[str]:
        roles: set[str] = set()
        summary = identity.get("permission_summary") if isinstance(identity.get("permission_summary"), dict) else {}
        access_profile = str(summary.get("access_profile") or "").strip()
        if access_profile:
            roles.add(access_profile)
        metadata = identity.get("metadata") if isinstance(identity.get("metadata"), dict) else {}
        for key in ("business_role", "identity_kind", "access_profile"):
            value = str(metadata.get(key) or "").strip()
            if value:
                roles.add(value)
        caller = str(identity.get("caller") or "")
        tenant_id = str(identity.get("tenant_id") or "")
        if caller and (self.server.db_path or self.server.db_dsn):
            rows = _query_business_identity_rows(
                db_path=self.server.db_path,
                db_dsn=self.server.db_dsn,
                db_read_dsn=self.server.db_read_dsn,
                caller=caller,
                tenant_id=tenant_id,
            )
            for row in rows:
                kind = str(row.get("identity_kind") or "").strip()
                if kind:
                    roles.add(kind)
        return roles

    def _business_identity_scope(self, identity: dict[str, Any]) -> dict[str, set[str]]:
        caller = str(identity.get("caller") or "")
        tenant_id = str(identity.get("tenant_id") or "")
        if not caller or not tenant_id:
            return {}
        result: dict[str, set[str]] = {}
        rows = _query_business_identity_rows(
            db_path=self.server.db_path,
            db_dsn=self.server.db_dsn,
            db_read_dsn=self.server.db_read_dsn,
            caller=caller,
            tenant_id=tenant_id,
        )
        for row in rows:
            kind = str(row.get("identity_kind") or "").strip()
            identity_id = str(row.get("business_identity_id") or "").strip()
            if not kind or not identity_id:
                continue
            result.setdefault(kind, set()).add(identity_id)
        return result

    def _enforce_business_relationship(
        self,
        *,
        identity: dict[str, Any] | None,
        role: str,
        entity: str,
        relationship: str | None,
        scope: dict[str, str],
    ) -> dict[str, Any]:
        if identity is None:
            raise PermissionError("business access check requires resolved identity")
        if identity_has_any_role(identity, "platform_admin", "platform_auditor"):
            return {"status": "bypassed_for_platform_role"}

        tenant_id = str(scope.get("tenant_id") or identity.get("tenant_id") or "").strip()
        if not tenant_id:
            raise PermissionError("business access tenant_id is required")
        if relationship in (None, ""):
            raise PermissionError("business access relationship is required")

        business_scope = self._business_identity_scope(identity)
        allowed_identity_ids = set(business_scope.get(role) or [])
        if not allowed_identity_ids:
            raise PermissionError(f"authenticated caller has no bound business identities for role {role}")

        if relationship == "assigned_delivery_leg":
            leg_id = str(scope.get("leg_id") or "").strip()
            courier_id = str(scope.get("assigned_courier_id") or "").strip()
            if not leg_id or not courier_id:
                raise PermissionError("assigned_delivery_leg requires leg_id and assigned_courier_id")
            if courier_id not in allowed_identity_ids:
                raise PermissionError("assigned_delivery_leg scope is not bound to the authenticated courier identity")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                row = conn.execute(
                    "SELECT assigned_courier_id FROM delivery_route_legs WHERE tenant_id = ? AND leg_id = ?",
                    (tenant_id, leg_id),
                ).fetchone()
            if row is None or str(row["assigned_courier_id"] or "") != courier_id:
                raise PermissionError("delivery leg is not assigned to the authenticated courier identity")
            if scope.get("assigned_courier_id") and str(scope.get("assigned_courier_id") or "") != courier_id:
                raise PermissionError("assigned_delivery_leg scope does not match the bound courier identity")
            return {"status": "ok", "bound_identity_id": courier_id, "bound_leg_id": leg_id}

        if relationship == "assigned_station_leg":
            leg_id = str(scope.get("leg_id") or "").strip()
            station_id = str(scope.get("assigned_station_id") or "").strip()
            if not leg_id or not station_id:
                raise PermissionError("assigned_station_leg requires leg_id and assigned_station_id")
            if station_id not in allowed_identity_ids:
                raise PermissionError("assigned_station_leg scope is not bound to the authenticated station identity")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                row = conn.execute(
                    "SELECT assigned_station_id FROM delivery_route_legs WHERE tenant_id = ? AND leg_id = ?",
                    (tenant_id, leg_id),
                ).fetchone()
            if row is None or str(row["assigned_station_id"] or "") != station_id:
                raise PermissionError("delivery leg is not assigned to the authenticated station identity")
            if scope.get("assigned_station_id") and str(scope.get("assigned_station_id") or "") != station_id:
                raise PermissionError("assigned_station_leg scope does not match the bound station identity")
            return {"status": "ok", "bound_identity_id": station_id, "bound_leg_id": leg_id}

        if relationship == "assigned_last_mile_leg":
            leg_id = str(scope.get("leg_id") or "").strip()
            courier_id = str(scope.get("assigned_courier_id") or "").strip()
            if not leg_id or not courier_id:
                raise PermissionError("assigned_last_mile_leg requires leg_id and assigned_courier_id")
            if courier_id not in allowed_identity_ids:
                raise PermissionError("assigned_last_mile_leg scope is not bound to the authenticated last-mile identity")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                row = conn.execute(
                    "SELECT assigned_courier_id, leg_kind FROM delivery_route_legs WHERE tenant_id = ? AND leg_id = ?",
                    (tenant_id, leg_id),
                ).fetchone()
            if row is None or str(row["assigned_courier_id"] or "") != courier_id or str(row["leg_kind"] or "") != "last_mile":
                raise PermissionError("delivery leg is not the authenticated last-mile courier's terminal leg")
            if scope.get("assigned_courier_id") and str(scope.get("assigned_courier_id") or "") != courier_id:
                raise PermissionError("assigned_last_mile_leg scope does not match the bound courier identity")
            return {"status": "ok", "bound_identity_id": courier_id, "bound_leg_id": leg_id}

        if relationship == "merchant_of_order":
            order_id = str(scope.get("order_id") or "").strip()
            if not order_id:
                raise PermissionError("merchant_of_order requires order_id")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                row = conn.execute(
                    "SELECT merchant_business_identity_id FROM orders WHERE tenant_id = ? AND order_id = ?",
                    (tenant_id, order_id),
                ).fetchone()
            order_identity_id = "" if row is None else str(row["merchant_business_identity_id"] or "")
            if not order_identity_id or order_identity_id not in allowed_identity_ids:
                raise PermissionError("order is not bound to the authenticated merchant identity")
            requested_identity_id = str(scope.get("merchant_business_identity_id") or "").strip()
            if requested_identity_id and requested_identity_id != order_identity_id:
                raise PermissionError("merchant_of_order scope does not match the bound merchant identity")
            return {"status": "ok", "bound_identity_id": order_identity_id, "bound_order_id": order_id}

        if relationship == "self":
            order_id = str(scope.get("order_id") or "").strip()
            buyer_id = str(scope.get("buyer_id") or "").strip()
            if not order_id or not buyer_id:
                raise PermissionError("self relationship requires order_id and buyer_id")
            if buyer_id not in allowed_identity_ids:
                raise PermissionError("buyer scope is not bound to the authenticated buyer identity")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                row = conn.execute(
                    "SELECT buyer_business_identity_id FROM orders WHERE tenant_id = ? AND order_id = ?",
                    (tenant_id, order_id),
                ).fetchone()
            order_buyer_id = "" if row is None else str(row["buyer_business_identity_id"] or "")
            if not order_buyer_id or order_buyer_id != buyer_id:
                raise PermissionError("order is not bound to the authenticated buyer identity")
            requested_buyer_id = str(scope.get("buyer_id") or "").strip()
            if requested_buyer_id and requested_buyer_id != order_buyer_id:
                raise PermissionError("self scope does not match the bound buyer identity")
            return {"status": "ok", "bound_identity_id": buyer_id, "bound_order_id": order_id}

        if relationship == "assigned_support_case":
            order_id = str(scope.get("order_id") or "").strip()
            case_id = str(scope.get("case_id") or "").strip()
            if not order_id or not case_id:
                raise PermissionError("assigned_support_case requires order_id and case_id")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                rows = conn.execute(
                    "SELECT agent_id FROM customer_service_interactions WHERE tenant_id = ? AND order_id = ? AND case_id = ?",
                    (tenant_id, order_id, case_id),
                ).fetchall()
            agent_ids = {str(row["agent_id"] or "") for row in rows if str(row["agent_id"] or "")}
            if not agent_ids or not (agent_ids & allowed_identity_ids):
                raise PermissionError("support case is not assigned to the authenticated support identity")
            bound = sorted(agent_ids & allowed_identity_ids)[0]
            requested_case_id = str(scope.get("case_id") or "").strip()
            if requested_case_id and requested_case_id != case_id:
                raise PermissionError("assigned_support_case scope does not match the bound case identity")
            return {"status": "ok", "bound_identity_id": bound, "bound_order_id": order_id, "bound_case_id": case_id}

        if relationship == "fraud_review_queue":
            order_id = str(scope.get("order_id") or "").strip()
            case_id = str(scope.get("case_id") or "").strip()
            if not order_id or not case_id:
                raise PermissionError("fraud_review_queue requires order_id and case_id")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                row = conn.execute(
                    "SELECT assigned_fraud_analyst_business_identity_id, fraud_case_id FROM order_payment WHERE tenant_id = ? AND order_id = ?",
                    (tenant_id, order_id),
                ).fetchone()
            analyst_id = "" if row is None else str(row["assigned_fraud_analyst_business_identity_id"] or "")
            fraud_case_id = "" if row is None else str(row["fraud_case_id"] or "")
            if not analyst_id or analyst_id not in allowed_identity_ids or fraud_case_id != case_id:
                raise PermissionError("fraud review scope is not bound to the authenticated fraud identity")
            requested_case_id = str(scope.get("case_id") or "").strip()
            if requested_case_id and requested_case_id != fraud_case_id:
                raise PermissionError("fraud_review_queue scope does not match the bound fraud case")
            return {"status": "ok", "bound_identity_id": analyst_id, "bound_order_id": order_id, "bound_case_id": case_id}

        if relationship == "campaign_assignee":
            order_id = str(scope.get("order_id") or "").strip()
            campaign_id = str(scope.get("campaign_id") or "").strip()
            if not order_id or not campaign_id:
                raise PermissionError("campaign_assignee requires order_id and campaign_id")
            with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
                rows = conn.execute(
                    "SELECT assigned_marketer_business_identity_id FROM order_attribution WHERE tenant_id = ? AND order_id = ? AND campaign_id = ?",
                    (tenant_id, order_id, campaign_id),
                ).fetchall()
            marketer_ids = {str(row["assigned_marketer_business_identity_id"] or "") for row in rows if str(row["assigned_marketer_business_identity_id"] or "")}
            if not marketer_ids or not (marketer_ids & allowed_identity_ids):
                raise PermissionError("campaign scope is not bound to the authenticated marketer identity")
            bound = sorted(marketer_ids & allowed_identity_ids)[0]
            requested_campaign_id = str(scope.get("campaign_id") or "").strip()
            if requested_campaign_id and requested_campaign_id != campaign_id:
                raise PermissionError("campaign_assignee scope does not match the bound campaign")
            return {"status": "ok", "bound_identity_id": bound, "bound_order_id": order_id, "bound_campaign_id": campaign_id}

        if relationship == "tenant_auditor":
            return {"status": "ok", "tenant_id": tenant_id}

        raise PermissionError(f"unsupported business relationship binding: {relationship}")

    def _assert_business_role_allowed(self, identity: dict[str, Any] | None, requested_role: str) -> None:
        if identity is None:
            raise PermissionError("business access check requires resolved identity")
        if identity_has_any_role(identity, "platform_admin", "platform_auditor"):
            return
        allowed_roles = self._business_roles_for_identity(identity)
        if requested_role not in allowed_roles:
            raise PermissionError(f"authenticated caller cannot check business role {requested_role}")

    def _business_access_check(self, payload: dict[str, Any], *, identity: dict[str, Any] | None) -> dict[str, Any]:
        role = str(payload.get("role") or "").strip()
        entity = str(payload.get("entity") or "").strip()
        fields = payload.get("fields")
        if not role:
            raise ValueError("role is required")
        if not entity:
            raise ValueError("entity is required")
        if not isinstance(fields, list) or not fields or not all(isinstance(item, str) and item for item in fields):
            raise ValueError("fields must be a non-empty string array")
        self._assert_business_role_allowed(identity, role)
        scope = payload.get("scope")
        if scope is None:
            scope = {}
        if not isinstance(scope, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in scope.items()):
            raise ValueError("scope must be an object of string values")
        if identity is not None:
            identity_tenant = str(identity.get("tenant_id") or "")
            requested_tenant = str(scope.get("tenant_id") or "")
            if identity_tenant:
                if requested_tenant and requested_tenant != identity_tenant:
                    raise PermissionError("business access tenant_id does not match authenticated identity")
                scope = {**scope, "tenant_id": identity_tenant}
        policy_path = self.server.business_access_policy or str(DEFAULT_BUSINESS_ACCESS_POLICY)
        policy = load_business_policy(policy_path)
        relationship = str(payload.get("relationship") or "").strip() or None
        relationship_binding = self._enforce_business_relationship(
            identity=identity,
            role=role,
            entity=entity,
            relationship=relationship,
            scope=scope,
        )
        report = build_business_access_report(
            policy=policy,
            role=role,
            entity=entity,
            fields=[str(item) for item in fields],
            purpose=str(payload.get("purpose") or "").strip() or None,
            scope=scope,
            relationship=relationship,
        )
        report["relationship_binding"] = relationship_binding
        return report

    def _business_data_read_preview(self, payload: dict[str, Any], *, identity: dict[str, Any] | None) -> dict[str, Any]:
        entity = str(payload.get("entity") or "").strip()
        if entity not in BUSINESS_READ_FIELD_MAP:
            raise ValueError(f"entity must be one of: {', '.join(sorted(BUSINESS_READ_FIELD_MAP))}")
        access_report = self._business_access_check(payload, identity=identity)
        field_decisions = access_report.get("field_decisions")
        if not isinstance(field_decisions, list):
            raise ValueError("business access report is missing field_decisions")
        denied = [
            str(item.get("field") or "")
            for item in field_decisions
            if isinstance(item, dict) and item.get("decision") == "deny"
        ]
        if denied:
            raise PermissionError(f"business field access denied: {', '.join(denied)}")

        requested_fields = [str(item) for item in payload.get("fields") or []]
        field_to_decision = {
            str(item.get("field") or ""): item
            for item in field_decisions
            if isinstance(item, dict)
        }
        readable_fields: list[str] = []
        masked_fields: list[str] = []
        for field in requested_fields:
            decision = field_to_decision.get(field)
            if not isinstance(decision, dict):
                raise ValueError(f"missing business access decision for field {field!r}")
            if decision.get("decision") == "mask":
                masked_fields.append(field)
                continue
            if decision.get("decision") != "allow":
                raise PermissionError(f"business field access denied: {field}")
            if field not in BUSINESS_READ_FIELD_MAP[entity]:
                raise ValueError(f"field {field!r} is not readable from entity {entity!r}")
            readable_fields.append(field)

        scope = access_report.get("request", {}).get("scope") if isinstance(access_report.get("request"), dict) else {}
        if not isinstance(scope, dict):
            scope = {}
        filters = payload.get("filters")
        if filters is None:
            filters = {}
        if not isinstance(filters, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in filters.items()):
            raise ValueError("filters must be an object of string values")
        effective_scope = {str(k): str(v) for k, v in scope.items() if v not in (None, "")}
        effective_filters = {
            key: value
            for key, value in effective_scope.items()
            if key in BUSINESS_READ_FILTER_COLUMNS[entity]
        }
        for key, value in filters.items():
            text = str(value)
            if text in ("", "None"):
                continue
            if key not in BUSINESS_READ_FILTER_COLUMNS[entity]:
                raise ValueError(f"unsupported business data filter for {entity}: {key}")
            if key in effective_scope and effective_scope[key] != text:
                raise PermissionError(f"business data filter conflicts with authorized scope: {key}")
            effective_filters[key] = text
        tenant_id = str(effective_filters.get("tenant_id") or "").strip()
        if not tenant_id:
            raise ValueError("scope.tenant_id is required for business data read-preview")

        limit = self._parse_body_limit(payload.get("limit"), default=25, max_limit=100)
        rows = self._read_business_rows(
            entity=entity,
            fields=readable_fields,
            masked_fields=masked_fields,
            field_to_decision=field_to_decision,
            filters=effective_filters,
            limit=limit,
        )
        return {
            "schema": "business_data_read_preview/v1",
            "entity": entity,
            "decision": access_report.get("decision"),
            "policy_id": access_report.get("policy_id"),
            "policy_version": access_report.get("policy_version"),
            "scope": effective_scope,
            "filters": effective_filters,
            "fields": requested_fields,
            "field_decisions": field_decisions,
            "relationship_binding": access_report.get("relationship_binding"),
            "rows": rows,
            "count": len(rows),
            "limit": limit,
        }

    def _parse_body_limit(self, value: Any, *, default: int, max_limit: int) -> int:
        if value in (None, ""):
            return default
        if isinstance(value, bool):
            raise ValueError("limit must be an integer")
        try:
            limit = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        if limit > max_limit:
            raise ValueError(f"limit must be <= {max_limit}")
        return limit

    def _read_business_rows(
        self,
        *,
        entity: str,
        fields: list[str],
        masked_fields: list[str],
        field_to_decision: dict[str, Any],
        filters: dict[str, str],
        limit: int,
    ) -> list[dict[str, Any]]:
        columns_by_field = BUSINESS_READ_FIELD_MAP[entity]
        selected_columns = [columns_by_field[field] for field in fields]
        select_columns = ["id", *selected_columns]
        where_clauses = ["tenant_id = ?"]
        params: list[Any] = [filters["tenant_id"]]
        allowed_filter_columns = BUSINESS_READ_FILTER_COLUMNS[entity]
        for key in ("dataset_id", "order_id"):
            value = str(filters.get(key) or "").strip()
            if value:
                where_clauses.append(f"{key} = ?")
                params.append(value)
        for key, value in sorted(filters.items()):
            if key in {"tenant_id", "dataset_id", "order_id"}:
                continue
            if key not in allowed_filter_columns:
                raise ValueError(f"unsupported business data filter for {entity}: {key}")
            text = str(value).strip()
            if text:
                where_clauses.append(f"{key} = ?")
                params.append(text)
        sql = (
            f"SELECT {', '.join(select_columns)} FROM {entity} "
            f"WHERE {' AND '.join(where_clauses)} ORDER BY id ASC LIMIT ?"
        )
        params.append(limit)
        with connect_read_db(self.server.db_path, dsn=self.server.db_dsn, read_dsn=self.server.db_read_dsn) as conn:
            if not table_exists(conn, entity):
                raise ValueError(f"business data table does not exist: {entity}")
            raw_rows = conn.execute(sql, tuple(params)).fetchall()
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            db_row = row_to_dict(raw)
            if db_row is None:
                continue
            item: dict[str, Any] = {}
            for field in fields:
                item[field] = db_row.get(columns_by_field[field])
            for field in masked_fields:
                decision = field_to_decision.get(field) if isinstance(field_to_decision.get(field), dict) else {}
                item[field] = {
                    "masked": True,
                    "masking": str(decision.get("masking") or "mask") if isinstance(decision, dict) else "mask",
                    "value": None,
                }
            rows.append(item)
        return rows


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
    ap.add_argument(
        "--business-access-policy",
        default=str(DEFAULT_BUSINESS_ACCESS_POLICY),
        help="business_access_policy/v1 config for POST /v1/business-access/check",
    )
    ap.add_argument("--pid-file", default="")
    ap.add_argument("--ready-file", default="")
    ap.add_argument(
        "--rate-limit-per-caller",
        type=float,
        default=float(os.environ.get("METADATA_API_RATE_LIMIT_PER_CALLER", "0") or "0"),
        help="Max requests/second per caller for auth-required endpoints (0 = disabled)",
    )
    ap.add_argument(
        "--rate-limit-burst",
        type=int,
        default=int(os.environ.get("METADATA_API_RATE_LIMIT_BURST", "0") or "0"),
        help="Burst capacity for the per-caller token bucket (0 = same as rate)",
    )
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
        business_access_policy=args.business_access_policy,
        pid_file=args.pid_file,
        ready_file=args.ready_file,
        rate_limit_per_caller=args.rate_limit_per_caller,
        rate_limit_burst=args.rate_limit_burst,
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
