# -*- coding:utf-8 _*-
import csv
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESULT_SCHEMA = "sse_record_recovery_result/v1"
ERROR_SCHEMA = "sse_record_recovery_error/v1"
HEALTH_SCHEMA = "sse_record_recovery_health/v1"

REQUEST_TIMESTAMP_MAX_SKEW_SEC = 30
REQUEST_SIGNATURE_ALGORITHM = "hmac-sha256"
REQUEST_PAYLOAD_HASH_ALGORITHM = "sha256"
REQUEST_PAYLOAD_HASH_EXCLUDED_FIELDS = {
    "auth_token",
    "identity_bearer_token",
    "request_payload_sha256",
    "request_signature",
    "signature_algorithm",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_request_timestamp(
    ts_str: str | None,
    *,
    max_skew_sec: int = REQUEST_TIMESTAMP_MAX_SKEW_SEC,
) -> tuple[bool, str, str]:
    """Validate a request timestamp against the current time.

    Returns (valid, reason_code, reason). A missing timestamp is accepted
    (returns True) so the check is opt-in for backward compatibility.
    A present but malformed or stale timestamp is always rejected.
    """
    if not ts_str:
        return True, "ok", "no timestamp provided"
    try:
        s = ts_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        req_dt = datetime.fromisoformat(s)
        if req_dt.tzinfo is None:
            req_dt = req_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        skew = abs((now_dt - req_dt).total_seconds())
        if skew > max_skew_sec:
            return (
                False,
                "request_timestamp_expired",
                f"request_timestamp_utc is {skew:.1f}s from server time (max {max_skew_sec}s)",
            )
    except Exception:
        return False, "request_timestamp_invalid", f"request_timestamp_utc could not be parsed: {ts_str!r}"
    return True, "ok", "timestamp ok"


def _canonical_payload_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _canonical_payload_for_hash(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k) not in REQUEST_PAYLOAD_HASH_EXCLUDED_FIELDS and not str(k).startswith("_")
        }
    if isinstance(value, list):
        return [_canonical_payload_for_hash(item) for item in value]
    return value


def canonical_request_payload_sha256(payload: dict[str, Any]) -> str:
    """Return a stable SHA-256 over the signed request payload fields."""
    canonical_payload = _canonical_payload_for_hash(payload)
    encoded = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_request_message(
    request_id: str,
    request_timestamp_utc: str,
    op: str,
    request_payload_sha256: str,
) -> str:
    """Produce the canonical string that is HMAC-signed per request.

    Format: "{request_id}:{request_timestamp_utc}:{op}:{request_payload_sha256}"
    Tying the signature to these fields prevents:
    - Reuse of a valid signature for a different request (request_id)
    - Replay of old requests (request_timestamp_utc)
    - Cross-operation misuse (op)
    - Payload tampering after the client signs the request (request_payload_sha256)
    """
    return f"{request_id}:{request_timestamp_utc}:{op}:{request_payload_sha256}"


def sign_request(
    auth_token: str,
    *,
    request_id: str,
    request_timestamp_utc: str,
    op: str,
    request_payload_sha256: str,
) -> str:
    """Return HMAC-SHA256 hex signature for a recovery service request."""
    msg = _canonical_request_message(request_id, request_timestamp_utc, op, request_payload_sha256)
    return hmac.new(
        auth_token.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_request_signature(
    auth_token: str,
    *,
    request_id: str,
    request_timestamp_utc: str,
    op: str,
    request_payload_sha256: str,
    provided_sig: str,
) -> bool:
    """Constant-time verify of an HMAC-SHA256 request signature."""
    expected = sign_request(
        auth_token,
        request_id=request_id,
        request_timestamp_utc=request_timestamp_utc,
        op=op,
        request_payload_sha256=request_payload_sha256,
    )
    return hmac.compare_digest(expected, provided_sig)


class HashingTextWriter:
    def __init__(self, sink):
        self._sink = sink
        self._hash = hashlib.sha256()

    def write(self, data: str):
        self._hash.update(data.encode("utf-8"))
        return self._sink.write(data)

    def flush(self):
        return self._sink.flush()

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def stringify_record_id(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return str(value)


def row_matches_filters(row: dict, filters: list[tuple[str, str]]) -> bool:
    for field, expected in filters:
        actual = row.get(field)
        if actual is None or str(actual) != expected:
            return False
    return True


def selected_bridge_row(
    *,
    row: dict,
    role: str,
    join_key_field: str,
    value_field: str,
    filters: list[tuple[str, str]],
) -> dict | None:
    if not row_matches_filters(row, filters):
        return None

    join_value = row.get(join_key_field)
    if join_value in (None, ""):
        return None

    selected = {join_key_field: join_value}
    if role == "client":
        metric = row.get(value_field)
        if metric in (None, ""):
            return None
        selected[value_field] = metric
    return selected


def write_selected_rows(
    *,
    rows: list[dict],
    out_path: Path,
    out_format: str,
    role: str,
    join_key_field: str,
    value_field: str,
) -> str:
    fieldnames = [join_key_field]
    if role == "client":
        fieldnames.append(value_field)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="" if out_format == "csv" else None) as f:
        hashing_writer = HashingTextWriter(f)
        if out_format == "csv":
            writer = csv.DictWriter(hashing_writer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
        else:
            for row in rows:
                hashing_writer.write(json.dumps(row, ensure_ascii=False) + "\n")
        hashing_writer.flush()
        return hashing_writer.hexdigest()


def select_bridge_rows(
    *,
    rows,
    role: str,
    join_key_field: str,
    value_field: str,
    filters: list[tuple[str, str]],
) -> tuple[int, list[dict]]:
    input_rows = 0
    selected_rows = []
    for row in rows:
        input_rows += 1
        selected = selected_bridge_row(
            row=row,
            role=role,
            join_key_field=join_key_field,
            value_field=value_field,
            filters=filters,
        )
        if selected is not None:
            selected_rows.append(selected)
    return input_rows, selected_rows


def enforce_row_limits(*, output_rows: int, min_rows: int | None, max_rows: int | None) -> None:
    if max_rows is not None and output_rows > max_rows:
        raise ValueError(f"record recovery output row count {output_rows} exceeds max rows {max_rows}")
    if min_rows is not None and output_rows < min_rows:
        raise ValueError(f"record recovery output row count {output_rows} is below min rows {min_rows}")


def evaluate_min_rows_suppression(
    *,
    output_rows: int,
    min_rows: int | None,
) -> bool:
    """Return True when output is below ``min_rows`` and should be suppressed.

    Companion to :func:`enforce_row_limits`. Callers that want to close the
    "zero rows vs below-min rows" side channel (A.10) ask the server to
    *suppress* the below-min case instead of raising. The response shape and
    output file then match the legitimate zero-match case exactly, so a
    membership-probing caller cannot distinguish "no candidates matched" from
    "candidates matched but the cohort was too small to release".
    """
    if min_rows is None:
        return False
    return output_rows < int(min_rows)


def parse_candidate_payload(
    payload: Any,
    *,
    max_candidate_ids: int = 0,
) -> tuple[set[str], list[tuple[str, str]]]:
    if not isinstance(payload, dict):
        raise ValueError("record recovery payload must be a JSON object")
    candidate_ids = payload.get("candidate_ids")
    if not isinstance(candidate_ids, list):
        raise ValueError("record recovery payload candidate_ids must be a list")
    if max_candidate_ids > 0 and len(candidate_ids) > max_candidate_ids:
        # Reject before materializing the set so a hostile caller cannot pin RSS
        # by streaming an oversized candidate list. The cap is enforced before
        # any per-item work runs.
        raise PermissionError(
            f"candidate_ids length {len(candidate_ids)} exceeds max_candidate_ids {max_candidate_ids}"
        )
    filters = payload.get("filters", [])
    if not isinstance(filters, list):
        raise ValueError("record recovery payload filters must be a list")
    parsed_filters = []
    for item in filters:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("record recovery filters must be [field, value] pairs")
        parsed_filters.append((str(item[0]), str(item[1])))
    return {stringify_record_id(item) for item in candidate_ids}, parsed_filters


def build_result(*, input_rows: int, output_rows: int, output_sha256: str, candidate_count: int) -> dict:
    return {
        "schema": RESULT_SCHEMA,
        "input_rows": input_rows,
        "output_rows": output_rows,
        "output_sha256": output_sha256,
        "candidate_count": candidate_count,
    }


def build_error(*, message: str) -> dict:
    return {
        "schema": ERROR_SCHEMA,
        "error": message,
    }


def build_health_result(
    *,
    service_id: str,
    tenant_id: str,
    dataset_id: str,
    socket_path: str | None,
    transport: str = "unix_socket",
    endpoint_url: str | None = None,
    auth_required: bool,
    authz_policy_config: str | None,
    allowed_callers: list[str],
    allowed_output_roots: list[str],
    allowed_record_store_roots: list[str],
    audit_log: str | None,
    pid: int,
) -> dict:
    return {
        "schema": HEALTH_SCHEMA,
        "ok": True,
        "service_id": service_id,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "transport": transport,
        "socket_path": socket_path,
        "endpoint_url": endpoint_url,
        "auth_required": auth_required,
        "authz_policy_config": authz_policy_config,
        "allowed_callers": allowed_callers,
        "allowed_output_roots": allowed_output_roots,
        "allowed_record_store_roots": allowed_record_store_roots,
        "audit_log": audit_log,
        "pid": pid,
    }
