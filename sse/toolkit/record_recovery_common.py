# -*- coding:utf-8 _*-
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


RESULT_SCHEMA = "sse_record_recovery_result/v1"
ERROR_SCHEMA = "sse_record_recovery_error/v1"
HEALTH_SCHEMA = "sse_record_recovery_health/v1"


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


def selected_bridge_row(*,
                        row: dict,
                        role: str,
                        join_key_field: str,
                        value_field: str,
                        filters: list[tuple[str, str]]) -> dict | None:
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


def write_selected_rows(*,
                        rows: list[dict],
                        out_path: Path,
                        out_format: str,
                        role: str,
                        join_key_field: str,
                        value_field: str) -> str:
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


def select_bridge_rows(*,
                       rows,
                       role: str,
                       join_key_field: str,
                       value_field: str,
                       filters: list[tuple[str, str]]) -> tuple[int, list[dict]]:
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


def parse_candidate_payload(payload: Any) -> tuple[set[str], list[tuple[str, str]]]:
    if not isinstance(payload, dict):
        raise ValueError("record recovery payload must be a JSON object")
    candidate_ids = payload.get("candidate_ids")
    if not isinstance(candidate_ids, list):
        raise ValueError("record recovery payload candidate_ids must be a list")
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


def build_health_result(*,
                        service_id: str,
                        tenant_id: str,
                        dataset_id: str,
                        socket_path: str,
                        auth_required: bool,
                        authz_policy_config: str | None,
                        allowed_callers: list[str],
                        allowed_output_roots: list[str],
                        allowed_record_store_roots: list[str],
                        audit_log: str | None,
                        pid: int) -> dict:
    return {
        "schema": HEALTH_SCHEMA,
        "ok": True,
        "service_id": service_id,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "socket_path": socket_path,
        "auth_required": auth_required,
        "authz_policy_config": authz_policy_config,
        "allowed_callers": allowed_callers,
        "allowed_output_roots": allowed_output_roots,
        "allowed_record_store_roots": allowed_record_store_roots,
        "audit_log": audit_log,
        "pid": pid,
    }
