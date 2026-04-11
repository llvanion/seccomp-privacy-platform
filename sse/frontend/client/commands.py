# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: commands.py 
@time: 2022/03/18
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description: Non-interactive command processing module
This module needs to be responsible for processing commands
and converting data structures into structures that the service can understand
@todo need to wrap service
"""
import asyncio
import csv
import functools
import hashlib
import json
import os
import pickle
import socket
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import schemes
from frontend.client.services import service_name_handler
from frontend.client.services.service import Service
from toolkit.bytes_utils import BytesConverter
from toolkit.config_manager import write_config, read_config
from toolkit.database_utils import convert_database_keyword_to_bytes
from toolkit.encrypted_record_store import build_record_store
from toolkit.record_recovery_service import main as record_recovery_service_main

__client_service = None


def generate_default_config(scheme_name: str, config_save_path: str):
    try:
        sse_module_loader = schemes.load_sse_module(scheme_name)
    except ValueError:
        print(f">>> Unsupported SSE Scheme {scheme_name}.")
        return

    default_config = sse_module_loader.SSEConfig.get_default_config()
    write_config(default_config, config_save_path)
    print(f">>> Create default config of {scheme_name} successfully.")


def create_service(config_path: str, sname: str):
    global __client_service

    try:
        config = read_config(config_path)
        __client_service = Service()
        sid = __client_service.handle_create_config(config)
        service_name_handler.record_sname_id_pair(sname, sid)
        print(f">>> Create service {sid} successfully.")
        print(f">>> sid: {sid}")
        print(f">>> sname: {sname}")

    except Exception as e:
        print(f">>> Create service error: {e}")


def export_bridge_records(*,
                          source_path: str,
                          out_path: str,
                          role: str,
                          source_format: str = "jsonl",
                          out_format: str = "csv",
                          join_key_field: str = "",
                          value_field: str = "",
                          filters: list | None = None,
                          caller: str = "",
                          policy_config: str = "",
                          audit_log: str = "",
                          job_id: str = "",
                          unsafe_allow_no_policy: bool = False,
                          candidate_ids: set | None = None,
                          record_id_field: str = "",
                          candidate_source: str = "local_filter",
                          record_store_path: str = "",
                          record_store_key_env: str = "",
                          record_recovery_socket: str = "",
                          record_recovery_auth_env: str = ""):
    """
    Local controlled export for bridge input preparation.
    Reads plaintext local records and writes a bridge-ready subset containing:
    - join key only for server role
    - join key + value for client role
    """
    try:
        caller = caller or "local_demo"
        if role not in {"server", "client"}:
            raise ValueError("role must be server or client")
        if source_format not in {"jsonl", "csv"}:
            raise ValueError("source_format must be jsonl or csv")
        if out_format not in {"jsonl", "csv"}:
            raise ValueError("out_format must be jsonl or csv")
        if not join_key_field:
            raise ValueError("join_key_field is required")
        if role == "client" and not value_field:
            raise ValueError("value_field is required for client role")

        source = Path(source_path) if source_path else None
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        filter_pairs = []
        for raw in filters or []:
            if "=" not in raw:
                raise ValueError(f"invalid filter {raw}, expected field=value")
            key, value = raw.split("=", 1)
            filter_pairs.append((key.strip(), value.strip()))

        if not policy_config and not unsafe_allow_no_policy:
            raise PermissionError("missing export policy config; pass --policy-config or explicit --unsafe-allow-no-policy")

        policy = _load_export_policy(policy_config)
        caller_policy = _policy_for_caller(policy, caller)
        _enforce_export_policy(
            caller_policy=caller_policy,
            caller=caller,
            role=role,
            join_key_field=join_key_field,
            value_field=value_field,
            filter_pairs=filter_pairs,
        )

        if record_store_path:
            if candidate_ids is None:
                raise ValueError("record_store_path requires an SSE candidate set")
            if record_recovery_socket:
                worker_result = _run_record_recovery_service(
                    socket_path=Path(record_recovery_socket),
                    auth_env=record_recovery_auth_env,
                    caller=caller,
                    job_id=job_id,
                    record_store_path=Path(record_store_path),
                    record_store_key_env=record_store_key_env,
                    out_path=out,
                    out_format=out_format,
                    role=role,
                    join_key_field=join_key_field,
                    value_field=value_field if role == "client" else "",
                    filter_pairs=filter_pairs,
                    candidate_ids=candidate_ids,
                    caller_policy=caller_policy,
                )
                record_recovery_boundary = "service_socket"
            else:
                worker_result = _run_record_recovery_worker(
                    record_store_path=Path(record_store_path),
                    record_store_key_env=record_store_key_env,
                    out_path=out,
                    out_format=out_format,
                    role=role,
                    join_key_field=join_key_field,
                    value_field=value_field if role == "client" else "",
                    filter_pairs=filter_pairs,
                    candidate_ids=candidate_ids,
                    caller_policy=caller_policy,
                )
                record_recovery_boundary = "worker_subprocess"
            rows = None
            selected_rows = None
            input_rows = int(worker_result["input_rows"])
            output_rows = int(worker_result["output_rows"])
            output_sha256 = str(worker_result["output_sha256"])
        else:
            record_recovery_boundary = None
            rows = list(_iter_plaintext_rows(source, source_format))
            selected_rows = _select_bridge_export_rows(
                rows=rows,
                filter_pairs=filter_pairs,
                join_key_field=join_key_field,
                value_field=value_field,
                role=role,
                candidate_ids=candidate_ids,
                record_id_field=record_id_field,
            )

            _enforce_export_row_limits(caller_policy, len(selected_rows))

            input_rows = len(rows)
            output_rows = len(selected_rows)
            output_sha256 = _write_export_rows(
                selected_rows,
                out,
                out_format,
                join_key_field=join_key_field,
                value_field=value_field if role == "client" else "",
            )

        if audit_log:
            _append_export_audit(
                audit_log=Path(audit_log),
                caller=caller,
                job_id=job_id,
                role=role,
                source_path=source,
                out_path=out,
                source_format=source_format,
                out_format=out_format,
                join_key_field=join_key_field,
                value_field=value_field if role == "client" else "",
                filters=filter_pairs,
                input_rows=input_rows,
                output_rows=output_rows,
                policy_config=policy_config,
                candidate_source=candidate_source,
                record_id_field=record_id_field,
                candidate_count=len(candidate_ids) if candidate_ids is not None else None,
                record_store_path=record_store_path,
                record_recovery_boundary=record_recovery_boundary,
                output_sha256=output_sha256,
                decision="allow",
                reason_code="ok",
                reason="ok",
            )

        print(f">>> Exported {output_rows} bridge rows to {out}.")
    except Exception as e:
        if audit_log:
            try:
                _append_export_audit(
                    audit_log=Path(audit_log),
                    caller=caller or "unknown",
                    job_id=job_id,
                    role=role or "unknown",
                    source_path=Path(source_path) if source_path else None,
                    out_path=Path(out_path) if out_path else Path(""),
                    source_format=source_format,
                    out_format=out_format,
                    join_key_field=join_key_field or "",
                    value_field=value_field or "",
                    filters=filter_pairs if "filter_pairs" in locals() else [],
                    input_rows=None,
                    output_rows=None,
                    policy_config=policy_config,
                    candidate_source=candidate_source,
                    record_id_field=record_id_field,
                    candidate_count=len(candidate_ids) if candidate_ids is not None else None,
                    record_store_path=record_store_path,
                    record_recovery_boundary="service_socket" if record_recovery_socket and record_store_path else "worker_subprocess" if record_store_path else None,
                    output_sha256=None,
                    decision="deny",
                    reason_code="export_failed",
                    reason=str(e),
                )
            except Exception:
                pass
        raise


async def export_bridge_records_from_sse(*,
                                         source_path: str,
                                         out_path: str,
                                         role: str,
                                         source_format: str = "jsonl",
                                         out_format: str = "csv",
                                         join_key_field: str = "",
                                         value_field: str = "",
                                         filters: list | None = None,
                                         caller: str = "",
                                         policy_config: str = "",
                                         audit_log: str = "",
                                         job_id: str = "",
                                         sse_keyword: str = "",
                                         record_id_field: str = "",
                                         record_id_format: str = "utf8",
                                         record_store_path: str = "",
                                         record_store_key_env: str = "",
                                         record_recovery_socket: str = "",
                                         record_recovery_auth_env: str = "",
                                         sid: str = "",
                                         sname: str = ""):
    if not sse_keyword:
        raise ValueError("sse_keyword is required for SSE-backed export")
    if not record_id_field:
        raise ValueError("record_id_field is required for SSE-backed export")
    candidate_ids = await _search_sse_candidate_ids(
        sse_keyword=sse_keyword,
        sid=sid,
        sname=sname,
        record_id_format=record_id_format,
    )
    export_bridge_records(
        source_path=source_path,
        out_path=out_path,
        role=role,
        source_format=source_format,
        out_format=out_format,
        join_key_field=join_key_field,
        value_field=value_field,
        filters=filters,
        caller=caller,
        policy_config=policy_config,
        audit_log=audit_log,
        job_id=job_id,
        unsafe_allow_no_policy=False,
        candidate_ids=candidate_ids,
        record_id_field=record_id_field,
        candidate_source="sse_query",
        record_store_path=record_store_path,
        record_store_key_env=record_store_key_env,
        record_recovery_socket=record_recovery_socket,
        record_recovery_auth_env=record_recovery_auth_env,
    )


def create_encrypted_record_store(*,
                                  source_path: str,
                                  out_path: str,
                                  source_format: str = "jsonl",
                                  record_id_field: str = "",
                                  key_env: str = ""):
    if source_format not in {"jsonl", "csv"}:
        raise ValueError("source_format must be jsonl or csv")
    count = build_record_store(
        rows=_iter_plaintext_rows(Path(source_path), source_format),
        out_path=Path(out_path),
        record_id_field=record_id_field,
        key_env=key_env,
    )
    print(f">>> Encrypted {count} records to {out_path}.")


async def _search_sse_candidate_ids(*,
                                    sse_keyword: str,
                                    sid: str = "",
                                    sname: str = "",
                                    record_id_format: str = "utf8") -> set:
    if record_id_format not in BytesConverter.supported_format:
        raise ValueError(f"unsupported record_id_format {record_id_format}")
    if not sid:
        sid = service_name_handler.get_service_id_by_sname(sname)
    service = Service(sid)
    try:
        result_bytes = await service.handle_keyword_search(
            bytes(sse_keyword, encoding="utf-8"),
            wait=True,
        )
        result = service.sse_module_loader.SSEResult.deserialize(result_bytes, service.config_object)
        return {
            _stringify_record_id(BytesConverter.convert_bytes(identifier_bytes, record_id_format))
            for identifier_bytes in result.get_result_list()
        }
    finally:
        await service.close_service()


def _select_bridge_export_rows(*,
                               rows: list[dict],
                               filter_pairs: list[tuple[str, str]],
                               join_key_field: str,
                               value_field: str,
                               role: str,
                               candidate_ids: set | None = None,
                               record_id_field: str = "") -> list[dict]:
    selected_rows = []
    for row in rows:
        if candidate_ids is not None:
            record_id = row.get(record_id_field)
            if record_id is None or _stringify_record_id(record_id) not in candidate_ids:
                continue
        if not _row_matches_filters(row, filter_pairs):
            continue

        join_value = row.get(join_key_field)
        if join_value in (None, ""):
            continue

        selected = {join_key_field: join_value}
        if role == "client":
            metric = row.get(value_field)
            if metric in (None, ""):
                continue
            selected[value_field] = metric
        selected_rows.append(selected)
    return selected_rows


def _stringify_record_id(value) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return str(value)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str | None:
    if not path or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_export_policy(policy_config: str) -> dict:
    if not policy_config:
        return {}
    path = Path(policy_config)
    with path.open("r", encoding="utf-8") as f:
        policy = json.load(f)
    if not isinstance(policy, dict):
        raise ValueError("export policy config must be a JSON object")
    schema = policy.get("schema")
    if schema is not None and schema != "sse_export_policy/v1":
        raise ValueError(f"unsupported export policy schema: {schema}")
    return policy


def _policy_for_caller(policy: dict, caller: str) -> dict:
    if not policy:
        return {}
    callers = policy.get("callers")
    if not isinstance(callers, dict):
        raise ValueError("export policy config must contain a callers object")
    caller_policy = callers.get(caller)
    if not isinstance(caller_policy, dict):
        raise PermissionError(f"caller {caller} is not allowed to export bridge records")
    if caller_policy.get("enabled", True) is False:
        raise PermissionError(f"caller {caller} is disabled")
    return caller_policy


def _as_set(policy: dict, key: str) -> set:
    raw = policy.get(key, [])
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    return {str(item) for item in raw}


def _enforce_export_policy(*,
                           caller_policy: dict,
                           caller: str,
                           role: str,
                           join_key_field: str,
                           value_field: str,
                           filter_pairs: list[tuple[str, str]]) -> None:
    if not caller_policy:
        return

    allowed_roles = _as_set(caller_policy, "allowed_roles")
    if allowed_roles and role not in allowed_roles:
        raise PermissionError(f"caller {caller} cannot export role {role}")

    allowed_join_key_fields = _as_set(caller_policy, "allowed_join_key_fields")
    if allowed_join_key_fields and join_key_field not in allowed_join_key_fields:
        raise PermissionError(f"caller {caller} cannot export join key field {join_key_field}")

    allowed_value_fields = _as_set(caller_policy, "allowed_value_fields")
    if value_field and allowed_value_fields and value_field not in allowed_value_fields:
        raise PermissionError(f"caller {caller} cannot export value field {value_field}")

    allowed_fields = _as_set(caller_policy, "allowed_fields")
    if allowed_fields:
        requested_fields = {join_key_field}
        if value_field:
            requested_fields.add(value_field)
        disallowed = sorted(requested_fields - allowed_fields)
        if disallowed:
            raise PermissionError(f"caller {caller} cannot export fields {disallowed}")

    required_filters = _as_set(caller_policy, "required_filters")
    present_filters = {field for field, _ in filter_pairs}
    missing_filters = sorted(required_filters - present_filters)
    if missing_filters:
        raise PermissionError(f"caller {caller} must include filters {missing_filters}")

    allowed_filter_fields = _as_set(caller_policy, "allowed_filter_fields")
    if allowed_filter_fields:
        disallowed_filters = sorted(present_filters - allowed_filter_fields)
        if disallowed_filters:
            raise PermissionError(f"caller {caller} cannot filter on fields {disallowed_filters}")

    allowed_filter_values = caller_policy.get("allowed_filter_values", {})
    if allowed_filter_values is None:
        allowed_filter_values = {}
    if not isinstance(allowed_filter_values, dict):
        raise ValueError("allowed_filter_values must be an object")
    for field, value in filter_pairs:
        allowed_values = allowed_filter_values.get(field)
        if allowed_values is None:
            continue
        if not isinstance(allowed_values, list):
            raise ValueError(f"allowed_filter_values.{field} must be a list")
        if str(value) not in {str(item) for item in allowed_values}:
            raise PermissionError(f"caller {caller} cannot use filter {field}={value}")


def _enforce_export_row_limits(caller_policy: dict, row_count: int) -> None:
    if not caller_policy:
        return
    max_rows = caller_policy.get("max_export_rows")
    if max_rows is not None and row_count > int(max_rows):
        raise PermissionError(f"export row count {row_count} exceeds max_export_rows {max_rows}")
    min_rows = caller_policy.get("min_export_rows")
    if min_rows is not None and row_count < int(min_rows):
        raise PermissionError(f"export row count {row_count} is below min_export_rows {min_rows}")


def _optional_policy_int(caller_policy: dict, key: str) -> int | None:
    if not caller_policy or caller_policy.get(key) is None:
        return None
    return int(caller_policy[key])


def _run_record_recovery_worker(*,
                                record_store_path: Path,
                                record_store_key_env: str,
                                out_path: Path,
                                out_format: str,
                                role: str,
                                join_key_field: str,
                                value_field: str,
                                filter_pairs: list[tuple[str, str]],
                                candidate_ids: set,
                                caller_policy: dict) -> dict:
    sse_root = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        "-m",
        "toolkit.record_recovery_worker",
        "--record-store-path",
        str(record_store_path),
        "--record-store-key-env",
        record_store_key_env,
        "--out-path",
        str(out_path),
        "--out-format",
        out_format,
        "--role",
        role,
        "--join-key-field",
        join_key_field,
    ]
    if value_field:
        cmd.extend(["--value-field", value_field])
    min_rows = _optional_policy_int(caller_policy, "min_export_rows")
    max_rows = _optional_policy_int(caller_policy, "max_export_rows")
    if min_rows is not None:
        cmd.extend(["--min-output-rows", str(min_rows)])
    if max_rows is not None:
        cmd.extend(["--max-output-rows", str(max_rows)])

    payload = {
        "candidate_ids": sorted(_stringify_record_id(item) for item in candidate_ids),
        "filters": [[field, value] for field, value in filter_pairs],
    }
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=sse_root,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "record recovery worker failed")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"record recovery worker returned invalid JSON: {e}") from e
    if not isinstance(result, dict):
        raise RuntimeError("record recovery worker returned a non-object result")
    if result.get("schema") != "sse_record_recovery_result/v1":
        raise RuntimeError(f"unexpected record recovery worker schema: {result.get('schema')}")
    for key in ("input_rows", "output_rows", "output_sha256"):
        if key not in result:
            raise RuntimeError(f"record recovery worker result missing {key}")
    return result


def _run_record_recovery_service(*,
                                 socket_path: Path,
                                 auth_env: str,
                                 caller: str,
                                 job_id: str,
                                 record_store_path: Path,
                                 record_store_key_env: str,
                                 out_path: Path,
                                 out_format: str,
                                 role: str,
                                 join_key_field: str,
                                 value_field: str,
                                 filter_pairs: list[tuple[str, str]],
                                 candidate_ids: set,
                                 caller_policy: dict) -> dict:
    payload = {
        "caller": caller,
        "job_id": job_id,
        "record_store_path": str(record_store_path),
        "record_store_key_env": record_store_key_env,
        "out_path": str(out_path),
        "out_format": out_format,
        "role": role,
        "join_key_field": join_key_field,
        "value_field": value_field,
        "candidate_ids": sorted(_stringify_record_id(item) for item in candidate_ids),
        "filters": [[field, value] for field, value in filter_pairs],
    }
    min_rows = _optional_policy_int(caller_policy, "min_export_rows")
    max_rows = _optional_policy_int(caller_policy, "max_export_rows")
    if min_rows is not None:
        payload["min_output_rows"] = min_rows
    if max_rows is not None:
        payload["max_output_rows"] = max_rows
    if auth_env:
        auth_token = os.environ.get(auth_env)
        if not auth_token:
            raise RuntimeError(f"environment variable {auth_env} is not set")
        payload["auth_token"] = auth_token

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = client.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as e:
        raise RuntimeError(f"record recovery service request failed: {e}") from e
    finally:
        client.close()

    raw = b"".join(chunks)
    if not raw:
        raise RuntimeError("record recovery service returned an empty response")
    try:
        result = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"record recovery service returned invalid JSON: {e}") from e
    if not isinstance(result, dict):
        raise RuntimeError("record recovery service returned a non-object result")
    if result.get("schema") == "sse_record_recovery_error/v1":
        raise RuntimeError(str(result.get("error", "record recovery service failed")))
    if result.get("schema") != "sse_record_recovery_result/v1":
        raise RuntimeError(f"unexpected record recovery service schema: {result.get('schema')}")
    for key in ("input_rows", "output_rows", "output_sha256"):
        if key not in result:
            raise RuntimeError(f"record recovery service result missing {key}")
    return result


def _append_export_audit(*,
                         audit_log: Path,
                         caller: str,
                         job_id: str,
                         role: str,
                         source_path: Path | None,
                         out_path: Path,
                         source_format: str,
                         out_format: str,
                         join_key_field: str,
                         value_field: str,
                         filters: list[tuple[str, str]],
                         input_rows: int | None,
                         output_rows: int | None,
                         policy_config: str,
                         candidate_source: str,
                         record_id_field: str,
                         candidate_count: int | None,
                         record_store_path: str,
                         record_recovery_boundary: str | None,
                         output_sha256: str | None,
                         decision: str,
                         reason_code: str,
                         reason: str) -> None:
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_utc": _utc_now_iso(),
        "event": "sse_bridge_export",
        "schema": "sse_bridge_export_audit/v1",
        "caller": caller,
        "correlation_id": job_id or None,
        "job_id": job_id or None,
        "role": role,
        "source_file": str(source_path.resolve()) if source_path is not None else None,
        "source_sha256": _sha256_file(source_path),
        "output_file": str(out_path.resolve()) if out_path else "",
        "output_file_type": _path_file_type(out_path),
        "output_sha256": output_sha256 or _sha256_file(out_path),
        "source_format": source_format,
        "out_format": out_format,
        "join_key_field": join_key_field,
        "value_field": value_field or None,
        "filters": [{"field": field, "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()} for field, value in filters],
        "input_rows": input_rows,
        "output_rows": output_rows,
        "policy_config": str(Path(policy_config).resolve()) if policy_config else None,
        "candidate_source": candidate_source,
        "record_id_field": record_id_field or None,
        "candidate_count": candidate_count,
        "record_store_file": str(Path(record_store_path).resolve()) if record_store_path else None,
        "record_store_sha256": _sha256_file(Path(record_store_path)) if record_store_path else None,
        "record_recovery_boundary": record_recovery_boundary,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
    }
    with audit_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def serve_record_recovery_service(*,
                                  socket_path: str,
                                  socket_mode: str = "600",
                                  auth_token_env: str = "",
                                  authz_config: str = "",
                                  allowed_callers: list[str] | None = None,
                                  allowed_output_roots: list[str] | None = None,
                                  allowed_record_store_roots: list[str] | None = None,
                                  audit_log: str = "",
                                  pid_file: str = "",
                                  ready_file: str = ""):
    argv = [
        "record_recovery_service",
        "--socket-path",
        socket_path,
        "--socket-mode",
        socket_mode,
    ]
    if authz_config:
        argv.extend(["--authz-config", authz_config])
    for caller in allowed_callers or []:
        argv.extend(["--allowed-caller", caller])
    for root in allowed_output_roots or []:
        argv.extend(["--allowed-output-root", root])
    for root in allowed_record_store_roots or []:
        argv.extend(["--allowed-record-store-root", root])
    if auth_token_env:
        argv.extend(["--auth-token-env", auth_token_env])
    if audit_log:
        argv.extend(["--audit-log", audit_log])
    if pid_file:
        argv.extend(["--pid-file", pid_file])
    if ready_file:
        argv.extend(["--ready-file", ready_file])
    previous_argv = sys.argv
    try:
        sys.argv = argv
        raise SystemExit(record_recovery_service_main())
    finally:
        sys.argv = previous_argv


def _path_file_type(path: Path | None) -> str:
    if not path:
        return "missing"
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISFIFO(mode):
        return "fifo"
    return "other"


def _iter_plaintext_rows(source: Path, source_format: str):
    if source_format == "jsonl":
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("each JSONL line must be an object")
                yield row
        return

    with source.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield dict(row)


def _row_matches_filters(row: dict, filters: list[tuple[str, str]]) -> bool:
    for field, expected in filters:
        actual = row.get(field)
        if actual is None:
            return False
        if str(actual) != expected:
            return False
    return True


class _HashingTextWriter:
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


def _write_export_rows(rows: list[dict], out: Path, out_format: str, *, join_key_field: str, value_field: str) -> str:
    fieldnames = [join_key_field]
    if value_field:
        fieldnames.append(value_field)

    if out_format == "jsonl":
        with out.open("w", encoding="utf-8") as f:
            hashing_writer = _HashingTextWriter(f)
            for row in rows:
                hashing_writer.write(json.dumps(row, ensure_ascii=False) + "\n")
            hashing_writer.flush()
            return hashing_writer.hexdigest()

    with out.open("w", encoding="utf-8", newline="") as f:
        hashing_writer = _HashingTextWriter(f)
        writer = csv.DictWriter(hashing_writer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
        hashing_writer.flush()
        return hashing_writer.hexdigest()


def __upload_config_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Upload config error, reason: {reason}.")
        return
    print(f">>> Upload config successfully.")


def __upload_encrypted_database_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Upload encrypted database error, reason: {reason}.")
        return
    print(f">>> Upload encrypted database successfully.")


def __search_echo_handler(fut: asyncio.Future, output_format="raw"):
    global __client_service

    if isinstance(__client_service, Service):
        content = fut.result()
        result = __client_service.sse_module_loader.SSEResult.deserialize(
            content, __client_service.config_object)
        result_list = result.get_result_list()
        output_result_list = [BytesConverter.convert_bytes(identifier_bytes, output_format)
                              for identifier_bytes in result_list]

        print(f">>> The result is {output_result_list}.")


def __multi_search_echo_handler(fut: asyncio.Future, output_format="raw"):
    global __client_service

    if isinstance(__client_service, Service):
        content = pickle.loads(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            print(f">>> Multi-search error, reason: {reason}.")
            return
        results = content.get("results", [])
        for i, r in enumerate(results):
            result_obj = __client_service.sse_module_loader.SSEResult.deserialize(
                r["result"], __client_service.config_object)
            result_list = result_obj.get_result_list()
            output_result_list = [BytesConverter.convert_bytes(identifier_bytes, output_format)
                                  for identifier_bytes in result_list]
            print(f">>> Keyword {i + 1} result: {output_result_list}")


def __delete_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Delete error, reason: {reason}.")
        return
    deleted_count = content.get("deleted_count", 0)
    print(f">>> Delete successfully, deleted {deleted_count} items.")


def __update_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Update error, reason: {reason}.")
        return
    updated_count = content.get("updated_count", 0)
    print(f">>> Update successfully, updated {updated_count} items.")


async def upload_config(*, sid: str = '', sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)

        try:
            await __client_service.handle_upload_config(
                wait=True, wait_callback_func=__upload_config_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Upload config error: {e}")


def generate_key(*, sid: str = '', sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        __client_service.handle_create_key()
        print(f">>> Generate key successfully.")
    except Exception as e:
        print(f">>> Generate key error: {e}")


def encrypt_database(db: dict = {},
                        db_path : str= "",
                     sid: str = '',
                     sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        if not db:
            with open(db_path, "r") as f:
                db = json.load(f)


        db = convert_database_keyword_to_bytes(db)
        __client_service.handle_encrypt_database(db)
        print(f">>> Encrypted Database successfully.")
    except Exception as e:
        print(f">>> Create service error: {e}")


def encrypt_database_multi_key(multi_key_db: list = None,
                               db_path: str = "",
                               sid: str = '',
                               sname: str = ''):
    """
    多key索引加密：同一组数据可绑定多个keyword，搜索任意一个keyword都能找到该数据。

    多key数据库格式（JSON list）:
        [
            {"keys": ["keyword1", "keyword2"], "values": ["hex_id1", "hex_id2"]},
            ...
        ]
    """
    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        if not multi_key_db:
            with open(db_path, "r") as f:
                multi_key_db = json.load(f)

        __client_service.handle_encrypt_database_multi_key(multi_key_db)
        print(f">>> Encrypted multi-key database successfully.")
    except Exception as e:
        print(f">>> Encrypt multi-key database error: {e}")


async def upload_encrypted_database(*, sid: str = '', sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        try:
            await __client_service.handle_upload_encrypted_database(
                wait=True,
                wait_callback_func=__upload_encrypted_database_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Upload Encrypted Database error: {e}")


async def search(keyword: str, output_format="raw", *, sid: str = '', sname: str = ''):
    if output_format not in BytesConverter.supported_format:
        print(f">>> Unsupported output format {output_format}.")
        return

    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes = bytes(keyword, encoding="utf-8")
            await __client_service.handle_keyword_search(
                keyword_bytes, wait=True, wait_callback_func=functools.partial(__search_echo_handler,
                                                                               output_format=output_format))
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Search error: {e}")


async def multi_search(keywords: list, output_format="raw", *, sid: str = '', sname: str = ''):
    """多key检索命令"""
    if output_format not in BytesConverter.supported_format:
        print(f">>> Unsupported output format {output_format}.")
        return

    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes_list = [bytes(kw, encoding="utf-8") for kw in keywords]
            await __client_service.handle_multi_keyword_search(
                keyword_bytes_list, wait=True,
                wait_callback_func=functools.partial(__multi_search_echo_handler,
                                                     output_format=output_format))
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Multi-search error: {e}")


async def delete_data(keyword: str = '', indices: list = None, *, sid: str = '', sname: str = ''):
    """删除数据命令"""
    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes = bytes(keyword, encoding="utf-8") if keyword else None
            await __client_service.handle_delete(
                keyword=keyword_bytes, indices=indices,
                wait=True, wait_callback_func=__delete_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Delete error: {e}")


async def update_data(keyword: str = '', entries: list = None,
                      encrypted_data=None, *, sid: str = '', sname: str = ''):
    """更新数据命令"""
    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes = bytes(keyword, encoding="utf-8") if keyword else None
            await __client_service.handle_update(
                keyword=keyword_bytes, encrypted_data=encrypted_data,
                entries=entries,
                wait=True, wait_callback_func=__update_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Update error: {e}")
