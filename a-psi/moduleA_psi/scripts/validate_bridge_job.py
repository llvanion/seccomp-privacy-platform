#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import os
from typing import Any, Dict, NoReturn


REQUIRED_BRIDGE_KEYS = [
    "token_scheme",
    "token_scope",
    "token_key_version",
    "normalize_version",
    "normalizer_schema_version",
    "dedup_policy",
    "server",
    "client",
]

KNOWN_NORMALIZER_SCHEMA_VERSIONS = {"normalizer-schema/v1"}
KNOWN_NORMALIZERS = {"identity", "email", "phone"}


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def count_csv_rows(path: str) -> int:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.reader(f))


def summarize_client_csv_values(path: str) -> Dict[str, Any]:
    values: list[int] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row_no, row in enumerate(csv.reader(f), start=1):
            if not row:
                continue
            if len(row) < 2:
                die(f"client CSV row {row_no} missing value column")
            try:
                values.append(int(str(row[1]).strip()))
            except ValueError:
                die(f"client CSV row {row_no} value is not an integer: {row[1]!r}")
    return summarize_values(values)


def summarize_source_values(
    *,
    path: str,
    input_format: str,
    join_key_column: str,
    normalizer: str,
    value_column: str | None,
    value_mode: str | None,
) -> Dict[str, Any]:
    values: list[int] = []
    if input_format == "csv":
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row_no, row in enumerate(reader, start=2):
                if not normalize_join_key(str(row.get(join_key_column) or ""), normalizer):
                    continue
                values.append(source_row_value(row, value_column, value_mode, f"CSV row {row_no}"))
    elif input_format == "jsonl":
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    die(f"JSONL line {line_no} must be an object")
                if not normalize_join_key(str(row.get(join_key_column) or ""), normalizer):
                    continue
                values.append(source_row_value(row, value_column, value_mode, f"JSONL line {line_no}"))
    else:
        die(f"unsupported input commitment client.input_format: {input_format!r}")
    return summarize_values(values)


def source_row_value(row: Dict[str, Any], value_column: str | None, value_mode: str | None, label: str) -> int:
    if value_mode in (None, "count"):
        return 1
    if value_mode != "raw_int":
        die(f"unsupported client value_mode: {value_mode!r}")
    if not value_column:
        die("client value_column is required when value_mode=raw_int")
    raw = row.get(value_column)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        die(f"{label} value is not an integer: {raw!r}")


def normalize_join_key(raw: str, normalizer: str) -> str | None:
    trimmed = raw.strip()
    if not trimmed:
        return None
    if normalizer == "identity":
        return trimmed
    if normalizer == "email":
        return trimmed.lower()
    if normalizer == "phone":
        out = []
        for idx, ch in enumerate(trimmed):
            if ch.isdigit():
                out.append(ch)
            elif ch == "+" and idx == 0:
                out.append(ch)
        text = "".join(out)
        if text.startswith("00"):
            text = "+" + text[2:]
        digits = text[1:] if text.startswith("+") else text
        if not digits or len(digits) > 15:
            return None
        if text.startswith("+") and digits.startswith("0"):
            return None
        return text
    die(f"unsupported normalizer: {normalizer!r}")


def summarize_values(values: list[int]) -> Dict[str, Any]:
    return {
        "sum": sum(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "non_negative": all(value >= 0 for value in values),
    }


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_file(path: str) -> None:
    if not os.path.isfile(path):
        die(f"missing file: {path}")


def _normalize_policy(policy: Any, *, value_mode: Any) -> Dict[str, Any] | None:
    if policy is None:
        if value_mode == "raw_int":
            return {"min_value": 0, "max_value": None, "allow_negative": False}
        return None
    if not isinstance(policy, dict):
        die("input commitment client.value_policy must be an object or null")
    allow_negative = bool(policy.get("allow_negative", False))
    min_value = policy.get("min_value")
    max_value = policy.get("max_value")
    for label, value in (("min_value", min_value), ("max_value", max_value)):
        if value is not None and not isinstance(value, int):
            die(f"input commitment client.value_policy.{label} must be an integer or null")
    if min_value is not None and max_value is not None and min_value > max_value:
        die("input commitment client.value_policy min_value > max_value")
    if not allow_negative and min_value is not None and min_value < 0:
        die("input commitment client.value_policy min_value is negative while allow_negative=false")
    return {
        "min_value": min_value,
        "max_value": max_value,
        "allow_negative": allow_negative,
    }


def _validate_value_summary_against_policy(summary: Dict[str, Any], policy: Dict[str, Any], label: str) -> None:
    if not policy["allow_negative"] and summary.get("non_negative") is False:
        die(f"{label} violates value policy: negative values are not allowed")
    min_value = policy.get("min_value")
    max_value = policy.get("max_value")
    actual_min = summary.get("min")
    actual_max = summary.get("max")
    if min_value is not None and actual_min is not None and actual_min < min_value:
        die(f"{label} violates value policy: min {actual_min} < {min_value}")
    if max_value is not None and actual_max is not None and actual_max > max_value:
        die(f"{label} violates value policy: max {actual_max} > {max_value}")


def _compare_summary(actual: Dict[str, Any], expected: Any, label: str) -> None:
    if not isinstance(expected, dict):
        die(f"input commitment {label} must be an object")
    for field in ("sum", "min", "max", "non_negative"):
        if actual.get(field) != expected.get(field):
            die(
                f"input commitment {label}.{field} mismatch: "
                f"commitment={expected.get(field)!r} actual={actual.get(field)!r}"
            )


def validate_bridge_meta(meta: Dict[str, Any], job_dir: str) -> None:
    schema = meta.get("schema")
    if schema is not None and schema != "bridge_job_meta/v1":
        die(f"unsupported job_meta schema: {schema}")

    bridge = meta.get("bridge")
    if not isinstance(bridge, dict):
        die("job_meta.json missing bridge section")

    for key in REQUIRED_BRIDGE_KEYS:
        if key not in bridge:
            die(f"bridge section missing required key: {key}")

    server = bridge.get("server")
    client = bridge.get("client")
    if not isinstance(server, dict):
        die("bridge.server must be an object")
    if not isinstance(client, dict):
        die("bridge.client must be an object")

    if not bridge.get("token_scope"):
        die("bridge.token_scope must be non-empty")
    if not bridge.get("token_scheme"):
        die("bridge.token_scheme must be non-empty")
    if not bridge.get("token_key_version"):
        die("bridge.token_key_version must be non-empty")
    if not bridge.get("normalize_version"):
        die("bridge.normalize_version must be non-empty")

    nsv = bridge.get("normalizer_schema_version", "")
    if not nsv:
        die("bridge.normalizer_schema_version must be non-empty")
    if nsv not in KNOWN_NORMALIZER_SCHEMA_VERSIONS:
        die(
            f"bridge.normalizer_schema_version {nsv!r} is not a recognized version; "
            f"known: {sorted(KNOWN_NORMALIZER_SCHEMA_VERSIONS)}"
        )

    server_normalizer = server.get("normalizer", "")
    if server_normalizer not in KNOWN_NORMALIZERS:
        die(
            f"bridge.server.normalizer {server_normalizer!r} is not a recognized normalizer; "
            f"known: {sorted(KNOWN_NORMALIZERS)}"
        )
    client_normalizer = client.get("normalizer", "")
    if client_normalizer not in KNOWN_NORMALIZERS:
        die(
            f"bridge.client.normalizer {client_normalizer!r} is not a recognized normalizer; "
            f"known: {sorted(KNOWN_NORMALIZERS)}"
        )

    if not server.get("join_key_column"):
        die("bridge.server.join_key_column must be non-empty")
    if not client.get("join_key_column"):
        die("bridge.client.join_key_column must be non-empty")

    client_value_mode = client.get("value_mode")
    if client_value_mode == "raw_int" and not client.get("value_column"):
        die("bridge.client.value_column required when value_mode=raw_int")
    client_value_policy = client.get("value_policy")
    if client_value_policy is not None:
        _normalize_policy(client_value_policy, value_mode=client_value_mode)

    server_csv = os.path.join(job_dir, "server.csv")
    client_csv = os.path.join(job_dir, "client.csv")
    ensure_file(server_csv)
    ensure_file(client_csv)

    sizes = meta.get("input_sizes")
    if not isinstance(sizes, dict):
        die("job_meta.json missing input_sizes")
    exposure_n = sizes.get("exposure_n")
    purchase_n = sizes.get("purchase_n")
    if exposure_n is None or purchase_n is None:
        die("input_sizes.exposure_n and input_sizes.purchase_n are required")

    actual_exposure_n = count_csv_rows(server_csv)
    actual_purchase_n = count_csv_rows(client_csv)
    if int(exposure_n) != actual_exposure_n:
        die(f"input_sizes.exposure_n mismatch: meta={exposure_n} actual={actual_exposure_n}")
    if int(purchase_n) != actual_purchase_n:
        die(f"input_sizes.purchase_n mismatch: meta={purchase_n} actual={actual_purchase_n}")

    inputs = meta.get("inputs")
    if not isinstance(inputs, dict):
        die("job_meta.json missing inputs section")
    commitment_file = inputs.get("input_commitment_file")
    commitment_sha256 = inputs.get("input_commitment_sha256")
    if not commitment_file or not commitment_sha256:
        die("job_meta.inputs missing input_commitment_file/input_commitment_sha256")
    if not os.path.isabs(str(commitment_file)):
        commitment_file = os.path.join(job_dir, str(commitment_file))
    ensure_file(str(commitment_file))
    actual_commitment_sha256 = sha256_file(str(commitment_file))
    if actual_commitment_sha256 != commitment_sha256:
        die(
            "input_commitment_sha256 mismatch: "
            f"meta={commitment_sha256} actual={actual_commitment_sha256}"
        )
    validate_input_commitment(
        commitment=load_json(str(commitment_file)),
        meta=meta,
        server_csv=server_csv,
        client_csv=client_csv,
        actual_exposure_n=actual_exposure_n,
        actual_purchase_n=actual_purchase_n,
    )


def validate_input_commitment(
    *,
    commitment: Dict[str, Any],
    meta: Dict[str, Any],
    server_csv: str,
    client_csv: str,
    actual_exposure_n: int,
    actual_purchase_n: int,
) -> None:
    if commitment.get("schema") != "pjc_input_commitment/v1":
        die(f"unsupported input commitment schema: {commitment.get('schema')}")
    for field in (
        "job_id",
        "token_scheme",
        "token_scope",
        "token_key_version",
        "normalize_version",
        "normalizer_schema_version",
        "dedup_policy",
    ):
        expected = meta.get("job_id") if field == "job_id" else (meta.get("bridge") or {}).get(field)
        if commitment.get(field) != expected:
            die(f"input commitment {field} mismatch: commitment={commitment.get(field)!r} meta={expected!r}")
    parties = commitment.get("parties")
    if not isinstance(parties, dict):
        die("input commitment missing parties")
    bridge = meta.get("bridge") or {}
    expected = {
        "server": {
            "csv": server_csv,
            "rows": actual_exposure_n,
            "bridge_role": bridge.get("server") or {},
            "value_mode": None,
            "value_column": None,
        },
        "client": {
            "csv": client_csv,
            "rows": actual_purchase_n,
            "bridge_role": bridge.get("client") or {},
            "value_mode": (bridge.get("client") or {}).get("value_mode"),
            "value_column": (bridge.get("client") or {}).get("value_column"),
        },
    }
    for role, role_expected in expected.items():
        party = parties.get(role)
        if not isinstance(party, dict):
            die(f"input commitment missing party: {role}")
        if party.get("role") != role:
            die(f"input commitment role mismatch for {role}: {party.get('role')!r}")
        source_input = party.get("input_file")
        source_sha256 = party.get("source_input_sha256")
        if isinstance(source_input, str) and os.path.isfile(source_input) and source_sha256:
            actual_source_sha256 = sha256_file(source_input)
            if source_sha256 != actual_source_sha256:
                die(
                    f"input commitment {role}.source_input_sha256 mismatch: "
                    f"commitment={source_sha256} actual={actual_source_sha256}"
                )
        actual_hash = sha256_file(str(role_expected["csv"]))
        if party.get("output_csv_sha256") != actual_hash:
            die(
                f"input commitment {role} output_csv_sha256 mismatch: "
                f"commitment={party.get('output_csv_sha256')} actual={actual_hash}"
            )
        if int(party.get("output_row_count", -1)) != int(role_expected["rows"]):
            die(
                f"input commitment {role} output_row_count mismatch: "
                f"commitment={party.get('output_row_count')} actual={role_expected['rows']}"
            )
        bridge_role = role_expected["bridge_role"]
        for field in ("join_key_column", "normalizer"):
            if party.get(field) != bridge_role.get(field):
                die(
                    f"input commitment {role}.{field} mismatch: "
                    f"commitment={party.get(field)!r} meta={bridge_role.get(field)!r}"
                )
        if role == "client":
            if party.get("value_mode") != role_expected["value_mode"]:
                die(
                    "input commitment client.value_mode mismatch: "
                    f"commitment={party.get('value_mode')!r} meta={role_expected['value_mode']!r}"
                )
            if party.get("value_column") != role_expected["value_column"]:
                die(
                    "input commitment client.value_column mismatch: "
                    f"commitment={party.get('value_column')!r} meta={role_expected['value_column']!r}"
                )
            commitment_policy = _normalize_policy(party.get("value_policy"), value_mode=party.get("value_mode"))
            meta_policy = _normalize_policy(bridge_role.get("value_policy"), value_mode=bridge_role.get("value_mode"))
            if commitment_policy != meta_policy:
                die(
                    "input commitment client.value_policy mismatch: "
                    f"commitment={commitment_policy!r} meta={meta_policy!r}"
                )
            if commitment_policy is not None:
                actual_output_summary = summarize_client_csv_values(str(role_expected["csv"]))
                _compare_summary(actual_output_summary, party.get("value_summary"), "client.value_summary")
                _validate_value_summary_against_policy(
                    actual_output_summary,
                    commitment_policy,
                    "client output value summary",
                )
                source_summary = party.get("source_value_summary")
                if source_summary is not None:
                    if not isinstance(source_summary, dict):
                        die("input commitment client.source_value_summary must be an object or null")
                    source_input = party.get("input_file")
                    input_format = party.get("input_format")
                    if isinstance(source_input, str) and os.path.isfile(source_input):
                        actual_source_summary = summarize_source_values(
                            path=source_input,
                            input_format=str(input_format or ""),
                            join_key_column=str(party.get("join_key_column") or ""),
                            normalizer=str(party.get("normalizer") or ""),
                            value_column=party.get("value_column"),
                            value_mode=party.get("value_mode"),
                        )
                        _compare_summary(
                            actual_source_summary,
                            source_summary,
                            "client.source_value_summary",
                        )
                    _validate_value_summary_against_policy(
                        source_summary,
                        commitment_policy,
                        "client source value summary",
                    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate bridge-generated job metadata before running PJC.")
    ap.add_argument("--job-dir", required=True, help="Path to the prepared job directory")
    args = ap.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    meta_path = os.path.join(job_dir, "job_meta.json")
    ensure_file(meta_path)
    meta = load_json(meta_path)
    validate_bridge_meta(meta, job_dir)
    print(f"[ok] bridge job metadata validated: {job_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
