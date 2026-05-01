#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.load(path.open("r", encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_mainline(tmp_dir: Path) -> None:
    payload = load(tmp_dir / "mainline_contract_check.json")
    require(payload.get("status") == "ok", f"mainline contract check unexpectedly failed: {payload}")
    handoff = payload.get("handoff_cleanup") or {}
    server = handoff.get("server") or {}
    client = handoff.get("client") or {}
    require(
        server.get("status") == "removed" and server.get("managed_by_out_base") is True,
        f"unexpected server handoff cleanup status: {server}",
    )
    require(
        client.get("status") == "cleaned" and client.get("managed_by_out_base") is True,
        f"unexpected client handoff cleanup status: {client}",
    )
    require(
        server.get("exists_after_run") is False and client.get("exists_after_run") is False,
        f"expected managed handoff artifacts to be absent after run: {handoff}",
    )


def validate_audit_chain(tmp_dir: Path) -> None:
    payload = load(tmp_dir / "audit_chain.json")
    paths = payload.get("paths") or {}
    artifacts = payload.get("artifacts") or {}
    mainline = payload.get("mainline_contract_check") or {}
    require(paths.get("mainline_contract_check"), f"audit chain missing mainline_contract_check path: {payload}")
    require(artifacts.get("mainline_contract_check_sha256"), f"audit chain missing mainline_contract_check sha256: {payload}")
    require(mainline.get("schema") == "mainline_contract_check/v1", f"audit chain missing embedded mainline_contract_check payload: {payload}")


def validate_observability(tmp_dir: Path) -> None:
    data = load(tmp_dir / "pipeline_observability.json")
    require(data.get("schema") == "pipeline_observability/v1", f"unexpected observability schema: {data}")
    require(data.get("job_id") == "contract-check", f"unexpected observability job_id: {data}")
    events = data.get("events") or []
    stages = {item.get("stage") for item in events}
    for expected in {"sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"}:
        require(expected in stages, f"observability output missing stage {expected}: {data}")
    handoff_events = [item for item in events if item.get("stage") == "handoff_cleanup"]
    require(len(handoff_events) == 2, f"observability output expected two handoff_cleanup events: {data}")
    expected_cleanup = {"server": "removed", "client": "cleaned"}
    for item in handoff_events:
        role = item.get("role")
        require(expected_cleanup.get(role) == item.get("reason_code"), f"observability handoff_cleanup reason_code mismatch: {item}")
        require(item.get("status") == "ok", f"observability handoff_cleanup returned non-ok status: {item}")
    service_consistency_events = [item for item in events if item.get("stage") == "service_audit_consistency"]
    require(
        len(service_consistency_events) == 2,
        f"observability output expected two service_audit_consistency events: {data}",
    )
    expected_service_consistency = {"server": "not_applicable", "client": "ok"}
    for item in service_consistency_events:
        role = item.get("role")
        require(
            expected_service_consistency.get(role) == item.get("reason_code"),
            f"observability service_audit_consistency reason_code mismatch: {item}",
        )
        require(item.get("status") == "ok", f"observability service_audit_consistency returned non-ok status: {item}")
    required = {"job_id", "correlation_id", "caller", "tenant_id", "dataset_id", "service_id", "stage", "status", "duration_ms", "row_count", "artifact_sha256"}
    for item in events:
        missing = required - set(item)
        require(not missing, f"observability event missing fields {missing}: {item}")
    require(
        not any(item.get("stage") not in {"handoff_cleanup", "service_audit_consistency"} and item.get("duration_ms") is None for item in events),
        f"observability output did not propagate duration_ms: {data}",
    )


def validate_catalog_lineage(tmp_dir: Path) -> None:
    data = load(tmp_dir / "catalog_lineage.json")
    require(data.get("schema") == "catalog_lineage/v1", f"unexpected catalog lineage schema: {data}")
    require(data.get("job_id") == "contract-check", f"unexpected catalog lineage job_id: {data}")
    mainline = data.get("mainline_contract_summary") or {}
    require(
        mainline.get("schema") == "mainline_contract_check/v1"
        and mainline.get("status") == "ok"
        and mainline.get("embedded_in_audit_chain") is True,
        f"catalog lineage missing embedded mainline contract summary: {data}",
    )
    service_consistency = mainline.get("service_audit_consistency") or {}
    require(
        service_consistency.get("server") == "not_applicable"
        and service_consistency.get("client") == "ok"
        and service_consistency.get("error_count") == 0,
        f"catalog lineage returned invalid service audit consistency summary: {data}",
    )
    privacy = data.get("privacy") or {}
    require(privacy.get("stores_sensitive_plaintext") is False, f"catalog lineage must not claim to store sensitive plaintext: {data}")
    require(privacy.get("paths_included") is False, f"catalog lineage should omit paths by default: {data}")
    require(bool(data.get("datasets")), f"catalog lineage missing dataset metadata: {data}")
    require(bool(data.get("services")), f"catalog lineage missing service metadata: {data}")
    require(bool(data.get("artifacts")), f"catalog lineage missing artifacts: {data}")
    artifact_stages = {item.get("stage") for item in data.get("artifacts", [])}
    for expected in {"sse_export", "record_recovery_service", "pjc", "policy_release"}:
        require(expected in artifact_stages, f"catalog lineage output missing artifact stage {expected}: {data}")
    edge_stages = {item.get("stage") for item in data.get("lineage_edges", [])}
    for expected in {"sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"}:
        require(expected in edge_stages, f"catalog lineage output missing edge stage {expected}: {data}")
    for item in data.get("artifacts", []):
        require("path" not in item, f"catalog lineage artifact leaked a path without --include-paths: {item}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate completed-run artifact smoke reports materialized by check_json_contracts.sh.")
    ap.add_argument("--tmp-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    tmp_dir = Path(args.tmp_dir).resolve()
    require(tmp_dir.is_dir(), f"tmp dir does not exist: {tmp_dir}")
    validate_mainline(tmp_dir)
    validate_audit_chain(tmp_dir)
    validate_observability(tmp_dir)
    validate_catalog_lineage(tmp_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
