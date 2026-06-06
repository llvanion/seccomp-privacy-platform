#!/usr/bin/env python3
"""Build a typed live e-commerce TLS/network-policy report from live probes and policy evidence."""
from __future__ import annotations

import argparse
import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ecommerce_live_tls_network_policy_report/v1"
NETWORK_POLICY_SCHEMA = "k8s_network_policy_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path_value: str, payload: dict[str, Any]) -> None:
    path = Path(path_value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_schema(payload: dict[str, Any], *, expected: str, label: str) -> None:
    actual = str(payload.get("schema") or "")
    if actual != expected:
        raise ValueError(f"{label} must use {expected}; got {actual!r}")


def probe_json(url: str, *, insecure_https: bool) -> tuple[bool, dict[str, Any] | None, str | None]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    context = ssl._create_unverified_context() if insecure_https and url.startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=5, context=context) as resp:
            body = resp.read().decode("utf-8")
        payload = json.loads(body)
        if isinstance(payload, dict):
            return True, payload, None
        return False, None, f"non-object JSON response from {url}"
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, None, f"HTTP {exc.code} from {url}: {body}"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def probe_text(url: str, *, insecure_https: bool) -> tuple[bool, str | None, str | None]:
    req = urllib.request.Request(url)
    context = ssl._create_unverified_context() if insecure_https and url.startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=5, context=context) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return True, body, None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, body, f"HTTP {exc.code} from {url}: {body}"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metadata-api-base-url", required=True)
    ap.add_argument("--metadata-api-health-path", default="/healthz")
    ap.add_argument("--metadata-api-transport", default="https")
    ap.add_argument("--metadata-api-auth-mode", default="oidc_bearer_or_cookie")
    ap.add_argument("--operator-dashboard-base-url", required=True)
    ap.add_argument("--operator-dashboard-transport", default="https")
    ap.add_argument("--operator-dashboard-path", default="/")
    ap.add_argument("--network-policy-report", required=True)
    ap.add_argument("--envoy-admin-url", default="")
    ap.add_argument("--envoy-listener-port", type=int, default=18443)
    ap.add_argument("--insecure-https", action="store_true")
    ap.add_argument("--output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    findings: list[str] = []

    network_policy_report = load_json(args.network_policy_report)
    require_schema(network_policy_report, expected=NETWORK_POLICY_SCHEMA, label="--network-policy-report")
    network_policy_status = "ok" if network_policy_report.get("status") == "ok" else "fail"
    if network_policy_status != "ok":
        findings.append("network policy report status is not ok")

    metadata_url = args.metadata_api_base_url.rstrip("/") + args.metadata_api_health_path
    metadata_ok, metadata_payload, metadata_error = probe_json(metadata_url, insecure_https=args.insecure_https)
    metadata_status = "ok" if metadata_ok and metadata_payload and metadata_payload.get("ok") is True else "fail"
    if metadata_status != "ok":
        findings.append(f"metadata API health probe failed: {metadata_error or metadata_payload}")

    dashboard_url = args.operator_dashboard_base_url.rstrip("/") + args.operator_dashboard_path
    dashboard_ok, dashboard_body, dashboard_error = probe_text(dashboard_url, insecure_https=args.insecure_https)
    dashboard_status = "ok" if dashboard_ok else "fail"
    if dashboard_status != "ok":
        findings.append(f"operator dashboard probe failed: {dashboard_error}")

    if args.envoy_admin_url:
        listener_url = args.envoy_admin_url.rstrip("/") + "/listeners?format=json"
        listeners_ok, listeners_payload, listeners_error = probe_json(listener_url, insecure_https=False)
        if listeners_ok and isinstance(listeners_payload, dict):
            listener_statuses = listeners_payload.get("listener_statuses")
            if isinstance(listener_statuses, list):
                has_listener = any(
                    isinstance(item, dict)
                    and isinstance(item.get("local_address"), dict)
                    and isinstance(item["local_address"].get("socket_address"), dict)
                    and int(item["local_address"]["socket_address"].get("port_value") or 0) == args.envoy_listener_port
                    for item in listener_statuses
                )
                if has_listener:
                    findings.append(f"envoy admin confirms listener on port {args.envoy_listener_port}")
                else:
                    findings.append(f"envoy admin did not show listener on port {args.envoy_listener_port}")
            else:
                findings.append("envoy admin listener payload was missing listener_statuses")
        else:
            findings.append(f"envoy admin probe failed: {listeners_error}")

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if metadata_status == "ok" and dashboard_status == "ok" and network_policy_status == "ok" else "fail",
        "metadata_api": {
            "base_url": args.metadata_api_base_url,
            "transport": args.metadata_api_transport,
            "auth_mode": args.metadata_api_auth_mode,
            "status": metadata_status,
        },
        "operator_dashboard": {
            "base_url": args.operator_dashboard_base_url,
            "transport": args.operator_dashboard_transport,
            "status": dashboard_status,
        },
        "network_policy": {
            "schema": network_policy_report["schema"],
            "status": network_policy_status,
            "report_path": str(Path(args.network_policy_report).resolve()),
        },
        "findings": findings,
    }
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
