#!/usr/bin/env python3
"""Thin Vault HTTP KV v2 client for the seccomp-privacy-platform keyring.

Supports two modes:
  real   — makes HTTP calls to a live Vault instance (token auth, KV v2 API)
  mock   — reads from a local vault_kv_backend/v1 file (no network required)

The mock mode is the default when no base_url is configured, allowing local
dev and CI to exercise the vault_http secret_ref kind without a running Vault.

Adds a new secret_ref kind "vault_http" to keyring_lib's resolve_secret_ref:
  {
    "kind": "vault_http",
    "name": "secret/my-key",   # KV v2 path without mount prefix
    "field": "value",
    "version": "1"             # optional; omit to get current version
  }

Used directly as a CLI for smoke-testing:
  python3 scripts/vault_http_client.py get --path secret/my-key --field value
  python3 scripts/vault_http_client.py status

Outputs vault_http_client_result/v1.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import utc_now  # noqa: E402
from scripts.keyring_lib import load_vault_kv_backend, VAULT_KV_BACKEND_SCHEMA  # noqa: E402

RESULT_SCHEMA = "vault_http_client_result/v1"
CONFIG_SCHEMA = "vault_http_client_config/v1"


def load_client_config(config_path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"vault_http_client config must be a JSON object: {config_path}")
    if payload.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"vault_http_client config must use {CONFIG_SCHEMA}: {config_path}")
    return payload


def _vault_request(
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    """Make a single Vault HTTP API call. Returns parsed JSON response."""
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "X-Vault-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace") if exc.fp else ""
        raise RuntimeError(f"Vault HTTP {exc.code}: {body_text}") from exc


def resolve_from_real_vault(
    *,
    base_url: str,
    token: str,
    mount: str,
    path: str,
    field: str,
    version: str | None,
    timeout: int = 10,
) -> tuple[str, str]:
    """Resolve a secret field from a live Vault KV v2 endpoint.
    Returns (secret_value, resolved_version).
    """
    url = f"{base_url.rstrip('/')}/v1/{mount}/data/{path}"
    if version:
        url += f"?version={version}"
    resp = _vault_request("GET", url, token=token, timeout=timeout)
    data = resp.get("data", {})
    kv_data = data.get("data") or {}
    metadata = data.get("metadata") or {}
    resolved_version = str(metadata.get("version") or version or "")
    secret = kv_data.get(field)
    if not isinstance(secret, str):
        raise PermissionError(f"vault field '{field}' not found at {path}")
    return secret, resolved_version


def resolve_from_mock(
    *,
    mock_file: str,
    path: str,
    field: str,
    version: str | None,
) -> tuple[str, str]:
    """Resolve a secret field from the local vault_kv_backend mock file."""
    backend = load_vault_kv_backend(mock_file)
    secrets = backend.get("secrets", {})
    full_path = path if path.startswith("secret/data/") else f"secret/data/{path}"
    entry = secrets.get(full_path)
    if not isinstance(entry, dict):
        # Try without prefix
        entry = secrets.get(path)
    if not isinstance(entry, dict):
        raise PermissionError(f"mock vault path not found: {path}")
    versions = entry.get("versions") or {}
    resolved_version = str(version or entry.get("current_version") or "")
    if not resolved_version:
        raise ValueError(f"no current_version for mock path {path}")
    ver_entry = versions.get(resolved_version)
    if not isinstance(ver_entry, dict):
        raise PermissionError(f"mock vault version not found: {path}#{resolved_version}")
    fields = ver_entry.get("fields") or {}
    secret = fields.get(field)
    if not isinstance(secret, str):
        raise PermissionError(f"mock vault field '{field}' not found at {path}#{resolved_version}")
    return secret, resolved_version


def resolve_vault_http_secret_ref(
    *,
    secret_ref: dict[str, Any],
    client_config: dict[str, Any] | None = None,
    mock_file: str = "",
    token_env: str = "",
) -> tuple[str, str]:
    """Resolve a vault_http secret_ref to (secret_value, resolved_version).

    Falls back to mock mode if base_url is absent or client_config is not given.
    """
    path = str(secret_ref.get("name") or "")
    field = str(secret_ref.get("field") or "value")
    version = secret_ref.get("version")
    version_str = str(version).strip() if version else None

    if client_config:
        base_url = str(client_config.get("base_url") or "").strip()
        mount = str(client_config.get("mount") or "secret").strip()
        token = ""
        token_env_name = str(client_config.get("token_env") or token_env or "").strip()
        if token_env_name:
            token = os.environ.get(token_env_name, "")
        if not token:
            token = str(client_config.get("token") or "").strip()
        if base_url and token:
            return resolve_from_real_vault(
                base_url=base_url,
                token=token,
                mount=mount,
                path=path,
                field=field,
                version=version_str,
                timeout=int(client_config.get("timeout_seconds") or 10),
            )
        # Fall through to mock if no token or base_url
        fallback_mock = str(client_config.get("mock_file") or mock_file).strip()
        if fallback_mock:
            return resolve_from_mock(mock_file=fallback_mock, path=path, field=field, version=version_str)
    if mock_file:
        return resolve_from_mock(mock_file=mock_file, path=path, field=field, version=version_str)
    raise PermissionError("vault_http secret_ref requires either a live Vault config or a mock_file")


def cmd_status(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("base_url") or "").strip()
    mode = "real" if base_url else "mock"
    mock_file = str(config.get("mock_file") or "").strip()
    reachable: bool | None = None
    vault_version: str | None = None
    if base_url:
        token_env = str(config.get("token_env") or "").strip()
        token = os.environ.get(token_env, "") if token_env else str(config.get("token") or "")
        try:
            resp = _vault_request(
                "GET",
                f"{base_url.rstrip('/')}/v1/sys/health",
                token=token,
                timeout=int(config.get("timeout_seconds") or 5),
            )
            reachable = True
            vault_version = str(resp.get("version") or "")
        except Exception as exc:
            reachable = False
            vault_version = str(exc)[:120]
    mock_secrets_count: int | None = None
    if mock_file and Path(mock_file).exists():
        try:
            backend = load_vault_kv_backend(mock_file)
            mock_secrets_count = len(backend.get("secrets") or {})
        except Exception:
            pass
    return {
        "schema": RESULT_SCHEMA,
        "generated_at_utc": utc_now(),
        "mode": mode,
        "base_url": base_url or None,
        "mount": str(config.get("mount") or "secret"),
        "mock_file": mock_file or None,
        "reachable": reachable,
        "vault_version": vault_version,
        "mock_secrets_count": mock_secrets_count,
    }


def cmd_get(
    config: dict[str, Any],
    *,
    path: str,
    field: str,
    version: str | None,
    redact: bool,
) -> dict[str, Any]:
    secret_ref = {"kind": "vault_http", "name": path, "field": field}
    if version:
        secret_ref["version"] = version
    mock_file = str(config.get("mock_file") or "").strip()
    token_env = str(config.get("token_env") or "").strip()
    try:
        value, resolved_version = resolve_vault_http_secret_ref(
            secret_ref=secret_ref,
            client_config=config,
            mock_file=mock_file,
            token_env=token_env,
        )
        return {
            "schema": RESULT_SCHEMA,
            "generated_at_utc": utc_now(),
            "operation": "get",
            "path": path,
            "field": field,
            "resolved_version": resolved_version,
            "value": "REDACTED" if redact else value,
            "ok": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "schema": RESULT_SCHEMA,
            "generated_at_utc": utc_now(),
            "operation": "get",
            "path": path,
            "field": field,
            "resolved_version": None,
            "value": None,
            "ok": False,
            "error": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Vault HTTP KV v2 client")
    parser.add_argument("--config", help="Path to vault_http_client_config/v1 JSON")
    parser.add_argument("--mock-file", help="Path to vault_kv_backend/v1 mock file")
    parser.add_argument("--output", help="Write JSON to file")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Check Vault connectivity / mock status")

    get_p = sub.add_parser("get", help="Resolve a secret field")
    get_p.add_argument("--path", required=True, help="KV path (e.g. secret/my-key)")
    get_p.add_argument("--field", default="value", help="Field name within the secret")
    get_p.add_argument("--version", default=None, help="Secret version (omit for current)")
    get_p.add_argument("--redact", action="store_true", help="Replace value with REDACTED in output")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    config: dict[str, Any] = {}
    if args.config:
        config = load_client_config(args.config)
    if getattr(args, "mock_file", None):
        config["mock_file"] = args.mock_file

    if args.cmd == "status":
        result = cmd_status(config)
    else:
        result = cmd_get(
            config,
            path=args.path,
            field=args.field,
            version=args.version,
            redact=args.redact,
        )

    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.cmd == "get" and not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
