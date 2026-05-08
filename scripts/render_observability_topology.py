#!/usr/bin/env python3
"""Validate and report on the observability stack topology (I1).

This script does not generate compose / dashboard files dynamically — those are
checked-in static artifacts under ``config/observability/``. Instead it inspects
those artifacts, asserts that the moving parts line up (Tempo OTLP listeners,
Prometheus alert-rules mount, Grafana datasource UIDs, dashboard count), and
emits ``observability_topology_report/v1``.

This is the same shape as ``render_postgres_ha_topology.py`` and friends: a
contract surface that proves the artifacts are coherent without launching the
real stack.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "observability_topology_report/v1"
DEFAULT_TOPOLOGY_ROOT = REPO_ROOT / "config" / "observability"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"[ERROR] missing required artifact: {path}")
    return path.read_text(encoding="utf-8")


def parse_yaml_minimal(text: str) -> dict[str, Any]:
    """Best-effort YAML loader that handles the limited shapes this script needs.

    The real config is parsed by docker-compose / Tempo / Grafana at runtime; we
    only need to confirm that key strings/sections appear. PyYAML may be absent
    in restricted environments, so we use a substring-based reader for the
    structural assertions.
    """
    return {"_raw": text}


def assert_compose_services(compose_text: str) -> list[str]:
    expected = ["tempo", "prometheus", "grafana"]
    missing = [name for name in expected if not re.search(rf"^\s{{2}}{re.escape(name)}:\s*$", compose_text, flags=re.MULTILINE)]
    if missing:
        raise SystemExit(f"[ERROR] docker-compose.observability.yml missing services: {missing}")
    return expected


def tempo_listeners(tempo_text: str) -> tuple[bool, bool, list[dict[str, str]]]:
    grpc_match = re.search(r"grpc:\s*\n\s*endpoint:\s*([^\n]+)", tempo_text)
    http_match = re.search(r"http:\s*\n\s*endpoint:\s*([^\n]+)", tempo_text)
    endpoints: list[dict[str, str]] = []
    if grpc_match:
        endpoints.append({"protocol": "grpc", "address": grpc_match.group(1).strip()})
    if http_match:
        endpoints.append({"protocol": "http", "address": http_match.group(1).strip()})
    return bool(grpc_match), bool(http_match), endpoints


def prometheus_targets(prom_text: str) -> tuple[bool, list[dict[str, Any]]]:
    alert_rules_mounted = "/etc/prometheus/alert-rules.yml" in prom_text
    targets: list[dict[str, Any]] = []
    job_pattern = re.compile(r"-\s*job_name:\s*\"?([^\"\n]+)\"?\s*\n((?:\s{4,}.*\n?)+)", re.MULTILINE)
    for match in job_pattern.finditer(prom_text):
        job_name = match.group(1).strip()
        body = match.group(2)
        metrics_path_match = re.search(r"metrics_path:\s*\"?([^\"\n]+)\"?", body)
        target_lines = re.findall(r"-\s*\"?([^\"\n#]+:\d+)\"?", body)
        targets.append(
            {
                "job_name": job_name,
                "metrics_path": (metrics_path_match.group(1).strip() if metrics_path_match else "/metrics"),
                "targets": [t.strip() for t in target_lines],
            }
        )
    return alert_rules_mounted, targets


def datasource_uids(datasource_text: str) -> list[str]:
    return re.findall(r"^\s*uid:\s*([\w-]+)", datasource_text, flags=re.MULTILINE)


def load_dashboard(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] {path} is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] {path} must contain a JSON object")
    return payload


def list_dashboards(dash_dir: Path) -> list[dict[str, Any]]:
    if not dash_dir.is_dir():
        raise SystemExit(f"[ERROR] dashboards dir missing: {dash_dir}")
    entries = []
    for path in sorted(dash_dir.glob("*.json")):
        payload = load_dashboard(path)
        uid = str(payload.get("uid") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not uid or not title:
            raise SystemExit(f"[ERROR] dashboard {path} must have uid and title")
        panels = payload.get("panels") or []
        if not isinstance(panels, list) or not panels:
            raise SystemExit(f"[ERROR] dashboard {path} must define panels")
        entries.append(
            {
                "uid": uid,
                "title": title,
                "path": str(path.relative_to(REPO_ROOT)),
                "panel_count": len(panels),
                "tags": list(payload.get("tags") or []),
            }
        )
    return entries


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate the observability stack topology (Grafana + Tempo + Prometheus) and emit observability_topology_report/v1.")
    ap.add_argument("--topology-root", default=str(DEFAULT_TOPOLOGY_ROOT))
    ap.add_argument("--output", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.topology_root).resolve()
    compose_path = root / "docker-compose.observability.yml"
    tempo_path = root / "tempo.yaml"
    prom_path = root / "prometheus.yml"
    datasource_path = root / "grafana-datasources.yaml"
    dashboards_dir = root / "grafana-dashboards"
    dashboards_provider = dashboards_dir / "dashboards.yaml"

    compose_text = read_text(compose_path)
    tempo_text = read_text(tempo_path)
    prom_text = read_text(prom_path)
    datasource_text = read_text(datasource_path)
    read_text(dashboards_provider)

    services = assert_compose_services(compose_text)
    tempo_grpc, tempo_http, otlp_endpoints = tempo_listeners(tempo_text)
    if not (tempo_grpc and tempo_http):
        raise SystemExit("[ERROR] tempo.yaml must declare both grpc and http OTLP receivers")
    rules_mounted, prom_jobs = prometheus_targets(prom_text)
    if not rules_mounted:
        raise SystemExit("[ERROR] prometheus.yml must mount /etc/prometheus/alert-rules.yml")
    datasource_uid_list = datasource_uids(datasource_text)
    required_datasource_uids = {"seccomp-tempo", "seccomp-prometheus"}
    if not required_datasource_uids.issubset(set(datasource_uid_list)):
        raise SystemExit(f"[ERROR] grafana-datasources.yaml must include datasources with uids: {sorted(required_datasource_uids)}")
    dashboard_entries = list_dashboards(dashboards_dir)
    if not dashboard_entries:
        raise SystemExit("[ERROR] no Grafana dashboards found under grafana-dashboards/")

    summary_status = "ok" if (
        services
        and tempo_grpc
        and tempo_http
        and rules_mounted
        and required_datasource_uids.issubset(set(datasource_uid_list))
        and dashboard_entries
    ) else "fail"

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "topology_root": str(root),
        "compose_file": str(compose_path),
        "tempo_config": str(tempo_path),
        "prometheus_config": str(prom_path),
        "grafana_datasources": str(datasource_path),
        "grafana_dashboards_config": str(dashboards_provider),
        "grafana_dashboards": dashboard_entries,
        "tempo_otlp_endpoints": otlp_endpoints,
        "prometheus_targets": prom_jobs,
        "summary": {
            "status": summary_status,
            "compose_services_present": services,
            "tempo_grpc_listener_present": tempo_grpc,
            "tempo_http_listener_present": tempo_http,
            "prometheus_alert_rules_mounted": rules_mounted,
            "datasources_present": datasource_uid_list,
            "dashboard_count": len(dashboard_entries),
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if summary_status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
