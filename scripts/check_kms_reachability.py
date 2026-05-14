#!/usr/bin/env python3
"""
A3: KMS backend reachability probe.

Probes each configured KMS/secret backend to confirm reachability before
pipeline runs. Covers:
  - vault_kv_file: local vault_kv_backend/v1 JSON fixture (always reachable if file exists)
  - vault_http: live Vault HTTP endpoint (GET /v1/sys/health)
  - external_kms_http: external KMS HTTP service (/healthz)
  - keyring_file: local keyring/v1 JSON file (always reachable if file exists)
  - env_var: checks that named environment variables are set (non-empty)

Usage:
  python3 scripts/check_kms_reachability.py \
    --keyring config/keyring.example.json \
    --vault-kv-file config/vault_kv_backend.example.json \
    --env-var BRIDGE_TOKEN_SECRET \
    --env-var AUDIT_SEAL_KEY \
    --output /tmp/kms_reachability.json
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "kms_reachability_report/v1"
VAULT_KV_BACKEND_SCHEMA = "vault_kv_backend/v1"
KEYRING_SCHEMA = "keyring/v1"
EXTERNAL_KMS_SCHEMA = "external_kms_config/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_file_backend(name: str, path: str, kind: str, expected_schema: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        text = Path(path).read_text(encoding="utf-8")
        payload = json.loads(text)
        if payload.get("schema") != expected_schema:
            return {
                "backend_name": name,
                "backend_kind": kind,
                "status": "error",
                "reachable": False,
                "detail": f"expected schema {expected_schema}, got {payload.get('schema')!r}",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "checked_ref": path,
            }
        return {
            "backend_name": name,
            "backend_kind": kind,
            "status": "ok",
            "reachable": True,
            "detail": None,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "checked_ref": path,
        }
    except FileNotFoundError:
        return {
            "backend_name": name,
            "backend_kind": kind,
            "status": "unreachable",
            "reachable": False,
            "detail": f"file not found: {path}",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "checked_ref": path,
        }
    except Exception as exc:
        return {
            "backend_name": name,
            "backend_kind": kind,
            "status": "error",
            "reachable": False,
            "detail": str(exc),
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "checked_ref": path,
        }


def _check_http_endpoint(name: str, url: str, kind: str, *, timeout: int = 5) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, method="GET")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            _ = resp.read()
            return {
                "backend_name": name,
                "backend_kind": kind,
                "status": "ok",
                "reachable": True,
                "detail": f"HTTP {resp.status}",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "checked_ref": url,
            }
    except urllib.error.HTTPError as exc:
        # For Vault sealed/standby states, 5xx may still mean the host is up
        reachable = exc.code < 500
        return {
            "backend_name": name,
            "backend_kind": kind,
            "status": "ok" if reachable else "unreachable",
            "reachable": reachable,
            "detail": f"HTTP {exc.code}",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "checked_ref": url,
        }
    except Exception as exc:
        return {
            "backend_name": name,
            "backend_kind": kind,
            "status": "unreachable",
            "reachable": False,
            "detail": str(exc),
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "checked_ref": url,
        }


def _check_env_var(var_name: str) -> dict[str, Any]:
    t0 = time.monotonic()
    value = os.environ.get(var_name, "")
    if value:
        return {
            "backend_name": var_name,
            "backend_kind": "env_var",
            "status": "ok",
            "reachable": True,
            "detail": None,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "checked_ref": f"env:{var_name}",
        }
    return {
        "backend_name": var_name,
        "backend_kind": "env_var",
        "status": "unreachable",
        "reachable": False,
        "detail": f"environment variable {var_name!r} is not set",
        "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        "checked_ref": f"env:{var_name}",
    }


def _check_external_kms(path: str) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
        config = json.loads(text)
        if config.get("schema") != EXTERNAL_KMS_SCHEMA:
            return {
                "backend_name": path,
                "backend_kind": "external_kms_http",
                "status": "error",
                "reachable": False,
                "detail": f"expected schema {EXTERNAL_KMS_SCHEMA}",
                "latency_ms": None,
                "checked_ref": path,
            }
        base_url = str(config.get("base_url") or config.get("endpoint_url") or "").rstrip("/")
        if not base_url:
            return {
                "backend_name": path,
                "backend_kind": "external_kms_http",
                "status": "skipped",
                "reachable": None,
                "detail": "no base_url in config",
                "latency_ms": None,
                "checked_ref": path,
            }
        health_url = f"{base_url}/healthz"
        return _check_http_endpoint(path, health_url, "external_kms_http")
    except FileNotFoundError:
        return {
            "backend_name": path,
            "backend_kind": "external_kms_http",
            "status": "unreachable",
            "reachable": False,
            "detail": f"config file not found: {path}",
            "latency_ms": None,
            "checked_ref": path,
        }
    except Exception as exc:
        return {
            "backend_name": path,
            "backend_kind": "external_kms_http",
            "status": "error",
            "reachable": False,
            "detail": str(exc),
            "latency_ms": None,
            "checked_ref": path,
        }


def _check_vault_http(config_path: str) -> dict[str, Any]:
    try:
        text = Path(config_path).read_text(encoding="utf-8")
        config = json.loads(text)
        base_url = str(config.get("base_url") or "").rstrip("/")
        if not base_url:
            return {
                "backend_name": config_path,
                "backend_kind": "vault_http",
                "status": "skipped",
                "reachable": None,
                "detail": "no base_url in vault_http_client config",
                "latency_ms": None,
                "checked_ref": config_path,
            }
        health_url = f"{base_url}/v1/sys/health"
        return _check_http_endpoint(config_path, health_url, "vault_http")
    except FileNotFoundError:
        return {
            "backend_name": config_path,
            "backend_kind": "vault_http",
            "status": "unreachable",
            "reachable": False,
            "detail": f"config file not found: {config_path}",
            "latency_ms": None,
            "checked_ref": config_path,
        }
    except Exception as exc:
        return {
            "backend_name": config_path,
            "backend_kind": "vault_http",
            "status": "error",
            "reachable": False,
            "detail": str(exc),
            "latency_ms": None,
            "checked_ref": config_path,
        }


PRODUCTION_KEYRING_BACKEND_KINDS = {"vault_http", "aws_kms"}
PRODUCTION_REACHABLE_BACKEND_KINDS = {"vault_http", "external_kms_http"}


def _evaluate_production_findings(
    args: argparse.Namespace,
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """S2 production gate: secret material must be sourced from a real KMS backend.

    Constraints enforced when --production-mode is set:
      P1 — at least one live KMS/Vault HTTP reachability check must succeed.
           env_var, vault_kv_file, keyring-only, and skipped HTTP configs are
           local fixtures or references, not production reachability evidence.
      P2 — every keyring file passed via --keyring must reference at least one
           live-capable secret backend (vault_http / aws_kms) for its active
           key version. A keyring whose every active version still
           resolves to `secret_ref.kind=env` is a development fixture.
    """
    findings: list[dict[str, Any]] = []
    reachable_real_backend = [
        check
        for check in checks
        if check.get("backend_kind") in PRODUCTION_REACHABLE_BACKEND_KINDS
        and check.get("reachable") is True
    ]
    if not reachable_real_backend:
        findings.append(
            {
                "kind": "production_no_reachable_real_kms_backend",
                "message": (
                    "production-mode requires at least one reachable live KMS/Vault HTTP backend; "
                    "env_var, vault_kv_file, keyring-only, and skipped HTTP configs are local "
                    "fixtures or references"
                ),
                "ref": None,
            }
        )

    for check in checks:
        if (
            check.get("backend_kind") in PRODUCTION_REACHABLE_BACKEND_KINDS
            and check.get("status") == "skipped"
        ):
            findings.append(
                {
                    "kind": "production_real_kms_config_skipped",
                    "message": (
                        f"production-mode cannot accept skipped {check.get('backend_kind')} "
                        f"config: {check.get('detail')}"
                    ),
                    "ref": check.get("checked_ref"),
                }
            )

    for keyring_path in (args.keyring or []):
        try:
            payload = json.loads(Path(keyring_path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            findings.append(
                {
                    "kind": "production_keyring_unreadable",
                    "message": f"production-mode could not read keyring at {keyring_path}",
                    "ref": keyring_path,
                }
            )
            continue
        except Exception as exc:
            findings.append(
                {
                    "kind": "production_keyring_unreadable",
                    "message": f"production-mode could not parse keyring at {keyring_path}: {exc}",
                    "ref": keyring_path,
                }
            )
            continue

        keys = payload.get("keys") or {}
        if not isinstance(keys, dict) or not keys:
            findings.append(
                {
                    "kind": "production_keyring_no_real_kms_backed_key",
                    "message": f"production-mode keyring {keyring_path} has no keys",
                    "ref": keyring_path,
                }
            )
            continue

        real_backed = []
        for key_name, key_entry in keys.items():
            if not isinstance(key_entry, dict):
                continue
            active_version = key_entry.get("active_version")
            versions = key_entry.get("versions") or {}
            if not isinstance(versions, dict):
                continue
            version_entry = versions.get(active_version) if active_version else None
            if not isinstance(version_entry, dict):
                continue
            secret_ref = version_entry.get("secret_ref") or {}
            if not isinstance(secret_ref, dict):
                continue
            if secret_ref.get("kind") in PRODUCTION_KEYRING_BACKEND_KINDS:
                real_backed.append(key_name)

        if not real_backed:
            findings.append(
                {
                    "kind": "production_keyring_no_real_kms_backed_key",
                    "message": (
                        f"production-mode keyring {keyring_path} has no active key version "
                        f"with secret_ref.kind in {sorted(PRODUCTION_KEYRING_BACKEND_KINDS)}"
                    ),
                    "ref": keyring_path,
                }
            )

    return findings


def run_checks(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    for path in (args.keyring or []):
        checks.append(_check_file_backend(path, path, "keyring_file", KEYRING_SCHEMA))

    for path in (args.vault_kv_file or []):
        checks.append(_check_file_backend(path, path, "vault_kv_file", VAULT_KV_BACKEND_SCHEMA))

    for path in (args.vault_http_config or []):
        checks.append(_check_vault_http(path))

    for path in (args.external_kms_config or []):
        checks.append(_check_external_kms(path))

    for var in (args.env_var or []):
        checks.append(_check_env_var(var))

    reachable = sum(1 for c in checks if c.get("reachable") is True)
    unreachable = sum(1 for c in checks if c.get("reachable") is False)
    total = len(checks)

    if total == 0:
        overall = "ok"
    elif unreachable == 0:
        overall = "ok"
    elif reachable > 0:
        overall = "degraded"
    else:
        overall = "error"

    production_findings: list[dict[str, Any]] = []
    if args.production_mode:
        production_findings = _evaluate_production_findings(args, checks)
        if production_findings:
            overall = "error"

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "overall_status": overall,
        "checked_count": total,
        "reachable_count": reachable,
        "unreachable_count": unreachable,
        "checks": checks,
    }
    if args.production_mode:
        report["production_mode"] = True
        report["production_findings"] = production_findings
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="A3: KMS backend reachability probe — check each secret backend before pipeline runs")
    ap.add_argument("--keyring", action="append", default=[], metavar="PATH",
                    help="keyring/v1 JSON file to probe (can repeat)")
    ap.add_argument("--vault-kv-file", action="append", default=[], metavar="PATH",
                    help="vault_kv_backend/v1 JSON file to probe (can repeat)")
    ap.add_argument("--vault-http-config", action="append", default=[], metavar="PATH",
                    help="vault_http_client_config/v1 JSON file whose base_url to probe (can repeat)")
    ap.add_argument("--external-kms-config", action="append", default=[], metavar="PATH",
                    help="external_kms_config/v1 JSON file whose base_url to probe (can repeat)")
    ap.add_argument("--env-var", action="append", default=[], metavar="VAR",
                    help="Environment variable name that must be non-empty (can repeat)")
    ap.add_argument("--output", default="", help="Write JSON report to this path (default: stdout)")
    ap.add_argument("--assert-ok", action="store_true", help="Exit non-zero if overall_status is not ok")
    ap.add_argument(
        "--production-mode",
        action="store_true",
        help=(
            "S2 production gate: require a reachable live-capable KMS/Vault HTTP backend. "
            "Adds production_findings and forces overall_status=error on any production "
            "constraint violation (env/local-only fixtures, skipped HTTP configs, or keyrings "
            "whose active versions do not reference vault_http/aws_kms)."
        ),
    )
    return ap


def main() -> int:
    args = build_parser().parse_args()
    report = run_checks(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.assert_ok and report["overall_status"] != "ok":
        print(f"[error] KMS reachability check failed: overall_status={report['overall_status']}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
