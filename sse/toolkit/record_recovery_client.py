# -*- coding:utf-8 _*-
import json
import os
import socket
from pathlib import Path

from toolkit.record_recovery_common import ERROR_SCHEMA, HEALTH_SCHEMA, RESULT_SCHEMA


def _send_request(*, socket_path: Path, payload: dict) -> dict:
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
    if result.get("schema") == ERROR_SCHEMA:
        raise RuntimeError(str(result.get("error", "record recovery service failed")))
    return result


def _auth_token_from_env(auth_env: str) -> str:
    if not auth_env:
        return ""
    auth_token = os.environ.get(auth_env)
    if not auth_token:
        raise RuntimeError(f"environment variable {auth_env} is not set")
    return auth_token


def request_record_recovery(*,
                            socket_path: Path,
                            auth_env: str,
                            caller: str,
                            job_id: str,
                            tenant_id: str,
                            dataset_id: str,
                            service_id: str,
                            record_store_path: Path,
                            record_store_key_env: str,
                            out_path: Path,
                            out_format: str,
                            role: str,
                            join_key_field: str,
                            value_field: str,
                            filter_pairs: list[tuple[str, str]],
                            candidate_ids: set[str],
                            min_output_rows: int | None,
                            max_output_rows: int | None) -> dict:
    payload = {
        "op": "recover",
        "caller": caller,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "service_id": service_id,
        "record_store_path": str(record_store_path),
        "record_store_key_env": record_store_key_env,
        "out_path": str(out_path),
        "out_format": out_format,
        "role": role,
        "join_key_field": join_key_field,
        "value_field": value_field,
        "candidate_ids": sorted(candidate_ids),
        "filters": [[field, value] for field, value in filter_pairs],
    }
    if min_output_rows is not None:
        payload["min_output_rows"] = min_output_rows
    if max_output_rows is not None:
        payload["max_output_rows"] = max_output_rows
    auth_token = _auth_token_from_env(auth_env)
    if auth_token:
        payload["auth_token"] = auth_token

    result = _send_request(socket_path=socket_path, payload=payload)
    if result.get("schema") != RESULT_SCHEMA:
        raise RuntimeError(f"unexpected record recovery service schema: {result.get('schema')}")
    for key in ("input_rows", "output_rows", "output_sha256"):
        if key not in result:
            raise RuntimeError(f"record recovery service result missing {key}")
    return result


def request_record_recovery_health(*, socket_path: Path, auth_env: str = "") -> dict:
    payload = {"op": "health"}
    auth_token = _auth_token_from_env(auth_env)
    if auth_token:
        payload["auth_token"] = auth_token
    result = _send_request(socket_path=socket_path, payload=payload)
    if result.get("schema") != HEALTH_SCHEMA:
        raise RuntimeError(f"unexpected record recovery health schema: {result.get('schema')}")
    if result.get("ok") is not True:
        raise RuntimeError("record recovery service health check returned ok=false")
    return result
