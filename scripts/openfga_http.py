#!/usr/bin/env python3
"""Minimal OpenFGA HTTP helpers.

These helpers intentionally keep the local SQLite tuple-store path as the
default. When an OpenFGA config or explicit endpoint/store flags are provided,
the same sync/check adapters can target a live OpenFGA-compatible service.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


OPENFGA_CONFIG_SCHEMA = "openfga_config/v1"


def load_openfga_config(path_value: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"OpenFGA config must be a JSON object: {path_value}")
    if payload.get("schema") != OPENFGA_CONFIG_SCHEMA:
        raise ValueError(f"OpenFGA config must use {OPENFGA_CONFIG_SCHEMA}: {path_value}")
    return payload


def resolve_openfga_runtime(
    *,
    config_path: str = "",
    endpoint: str = "",
    store_id: str = "",
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if config_path:
        config = load_openfga_config(config_path)
    resolved_endpoint = str(endpoint or config.get("endpoint_url") or "").strip().rstrip("/")
    resolved_store_id = str(store_id or config.get("store_id") or "").strip()
    if not resolved_endpoint:
        raise ValueError("OpenFGA endpoint is required")
    if not resolved_store_id:
        raise ValueError("OpenFGA store_id is required")
    return {
        "config_path": str(Path(config_path).resolve()) if config_path else None,
        "endpoint_url": resolved_endpoint,
        "store_id": resolved_store_id,
        "auth_token": _resolve_auth_token(config),
        "timeout_seconds": int(config.get("timeout_seconds") or 10),
    }


def openfga_locator(endpoint_url: str, store_id: str) -> str:
    return f"openfga://{store_id}@{endpoint_url.rstrip('/')}"


def _resolve_auth_token(config: dict[str, Any]) -> str:
    token_env = str(config.get("auth_token_env") or "").strip()
    if token_env:
        token = os.environ.get(token_env, "").strip()
        if token:
            return token
    return str(config.get("auth_token") or "").strip()


def _request(
    method: str,
    url: str,
    *,
    timeout_seconds: int,
    auth_token: str = "",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"OpenFGA response must be a JSON object: {url}")
            return payload
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace") if exc.fp else ""
        raise RuntimeError(f"OpenFGA HTTP {exc.code}: {body_text}") from exc


def _tuple_key(user: str, relation: str, object_ref: str) -> dict[str, str]:
    return {
        "user": user,
        "relation": relation,
        "object": object_ref,
    }


def read_all_tuples(
    *,
    endpoint_url: str,
    store_id: str,
    timeout_seconds: int,
    auth_token: str = "",
) -> list[tuple[str, str, str]]:
    tuples: list[tuple[str, str, str]] = []
    continuation_token = ""
    url = f"{endpoint_url}/stores/{store_id}/read"
    while True:
        body: dict[str, Any] = {"tuple_key": {}}
        if continuation_token:
            body["continuation_token"] = continuation_token
        payload = _request(
            "POST",
            url,
            timeout_seconds=timeout_seconds,
            auth_token=auth_token,
            body=body,
        )
        for item in payload.get("tuples") or []:
            key = item.get("key") if isinstance(item, dict) else None
            if not isinstance(key, dict):
                continue
            user = str(key.get("user") or "")
            relation = str(key.get("relation") or "")
            object_ref = str(key.get("object") or "")
            if user and relation and object_ref:
                tuples.append((user, relation, object_ref))
        continuation_token = str(payload.get("continuation_token") or "")
        if not continuation_token:
            return tuples


def write_tuples(
    *,
    endpoint_url: str,
    store_id: str,
    writes: list[tuple[str, str, str]],
    deletes: list[tuple[str, str, str]],
    timeout_seconds: int,
    auth_token: str = "",
) -> None:
    body = {
        "writes": {"tuple_keys": [_tuple_key(*item) for item in writes]},
        "deletes": {"tuple_keys": [_tuple_key(*item) for item in deletes]},
    }
    _request(
        "POST",
        f"{endpoint_url}/stores/{store_id}/write",
        timeout_seconds=timeout_seconds,
        auth_token=auth_token,
        body=body,
    )


def check_tuple(
    *,
    endpoint_url: str,
    store_id: str,
    user: str,
    relation: str,
    object_ref: str,
    timeout_seconds: int,
    auth_token: str = "",
) -> dict[str, Any]:
    return _request(
        "POST",
        f"{endpoint_url}/stores/{store_id}/check",
        timeout_seconds=timeout_seconds,
        auth_token=auth_token,
        body={"tuple_key": _tuple_key(user, relation, object_ref)},
    )
