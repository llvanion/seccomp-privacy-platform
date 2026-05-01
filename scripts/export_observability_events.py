#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_optional_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return load_json_object(path)


def repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def status_from_decision(decision: Any, *, exit_code: Any = None, released: Any = None) -> str:
    if exit_code not in (None, 0):
        return "error"
    if decision == "allow":
        return "ok"
    if decision == "deny":
        return "error"
    if released is True:
        return "ok"
    if released is False:
        return "error"
    return "unknown"


def base_scope(chain: dict[str, Any]) -> dict[str, Any]:
    public_report = chain.get("public_report") if isinstance(chain.get("public_report"), dict) else {}
    records: list[dict[str, Any]] = []
    for key in (
        "sse_export_audit",
        "record_recovery_service_audit",
        "bridge_audit",
        "pjc_audit",
        "policy_audit",
    ):
        value = chain.get(key)
        if isinstance(value, list):
            records.extend(record for record in value if isinstance(record, dict))
    return {
        "job_id": first_non_empty(chain.get("job_id"), public_report.get("job_id")),
        "correlation_id": first_non_empty(chain.get("correlation_id"), public_report.get("correlation_id")),
        "caller": first_non_empty(public_report.get("caller"), *(record.get("caller") for record in records)),
        "tenant_id": first_non_empty(*(record.get("tenant_id") for record in records)),
        "dataset_id": first_non_empty(*(record.get("dataset_id") for record in records)),
        "service_id": first_non_empty(*(record.get("service_id") for record in records)),
    }


def event(scope: dict[str, Any], *,
          stage: str,
          status: str,
          ts_utc: Any = None,
          role: Any = None,
          decision: Any = None,
          reason_code: Any = None,
          duration_ms: Any = None,
          row_count: Any = None,
          artifact_sha256: Any = None,
          source_event: Any = None) -> dict[str, Any]:
    return {
        **scope,
        "stage": stage,
        "status": status,
        "ts_utc": ts_utc,
        "role": role,
        "decision": decision,
        "reason_code": reason_code,
        "duration_ms": duration_ms,
        "row_count": row_count,
        "artifact_sha256": artifact_sha256,
        "source_event": source_event,
    }


def sse_events(chain: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    records = chain.get("sse_export_audit") or []
    events = []
    for record in records:
        if not isinstance(record, dict):
            continue
        events.append(event(
            {**scope, **{k: first_non_empty(record.get(k), scope.get(k)) for k in ("caller", "tenant_id", "dataset_id", "service_id")}},
            stage="sse_export",
            status=status_from_decision(record.get("decision")),
            ts_utc=record.get("ts_utc"),
            role=record.get("role"),
            decision=record.get("decision"),
            reason_code=record.get("reason_code"),
            duration_ms=record.get("duration_ms"),
            row_count=record.get("output_rows"),
            artifact_sha256=record.get("output_sha256"),
            source_event=record.get("event"),
        ))
    return events


def recovery_events(chain: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    records = chain.get("record_recovery_service_audit") or []
    events = []
    for record in records:
        if not isinstance(record, dict):
            continue
        events.append(event(
            {**scope, **{k: first_non_empty(record.get(k), scope.get(k)) for k in ("caller", "tenant_id", "dataset_id", "service_id")}},
            stage="record_recovery_service",
            status=status_from_decision(record.get("decision")),
            ts_utc=record.get("ts_utc"),
            role=record.get("role"),
            decision=record.get("decision"),
            reason_code=record.get("reason_code"),
            duration_ms=record.get("duration_ms"),
            row_count=record.get("output_rows"),
            artifact_sha256=record.get("output_sha256"),
            source_event=record.get("event"),
        ))
    return events


def bridge_events(chain: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    records = chain.get("bridge_audit") or []
    events = []
    for record in records:
        if not isinstance(record, dict):
            continue
        ts_utc = None
        if isinstance(record.get("ts_unix_ms"), int):
            ts_utc = datetime.fromtimestamp(record["ts_unix_ms"] / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
        events.append(event(
            {**scope, "job_id": first_non_empty(record.get("job_id"), scope.get("job_id")), "correlation_id": first_non_empty(record.get("correlation_id"), scope.get("correlation_id"))},
            stage="bridge",
            status=status_from_decision(record.get("decision")),
            ts_utc=ts_utc,
            decision=record.get("decision"),
            reason_code=record.get("reason_code"),
            duration_ms=record.get("duration_ms"),
            row_count=None,
            artifact_sha256=first_non_empty(record.get("server_input_sha256"), record.get("client_input_sha256"), record.get("input_sha256")),
            source_event=record.get("event"),
        ))
    return events


def pjc_events(chain: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    records = chain.get("pjc_audit") or []
    events = []
    for record in records:
        if not isinstance(record, dict):
            continue
        events.append(event(
            {**scope, "job_id": first_non_empty(record.get("job_id"), scope.get("job_id")), "correlation_id": first_non_empty(record.get("correlation_id"), scope.get("correlation_id"))},
            stage="pjc",
            status=status_from_decision(record.get("decision"), exit_code=record.get("exit_code")),
            ts_utc=record.get("ts_utc"),
            decision=record.get("decision"),
            reason_code=record.get("reason_code"),
            duration_ms=record.get("duration_ms"),
            row_count=None,
            artifact_sha256=record.get("result_sha256"),
            source_event=record.get("event"),
        ))
    return events


def policy_events(chain: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    records = chain.get("policy_audit") or []
    events = []
    for record in records:
        if not isinstance(record, dict):
            continue
        metrics = record.get("parsed_metrics") if isinstance(record.get("parsed_metrics"), dict) else {}
        row_count = first_non_empty(metrics.get("intersection_size"), metrics.get("conversions"))
        events.append(event(
            {**scope, "job_id": first_non_empty(record.get("job_id"), scope.get("job_id")), "correlation_id": first_non_empty(record.get("correlation_id"), scope.get("correlation_id")), "caller": first_non_empty(record.get("caller"), scope.get("caller"))},
            stage="policy_release",
            status=status_from_decision(record.get("decision"), released=bool(record.get("released")) if record.get("released") is not None else None),
            ts_utc=record.get("ts_utc"),
            decision=record.get("decision"),
            reason_code=record.get("reason_code"),
            duration_ms=record.get("duration_ms"),
            row_count=row_count,
            artifact_sha256=record.get("release_sha256"),
            source_event=record.get("event"),
        ))
    return events


def handoff_cleanup_events(mainline_contract_check: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    if mainline_contract_check.get("schema") != "mainline_contract_check/v1":
        return []
    generated_at = mainline_contract_check.get("generated_at_utc")
    mainline_status = mainline_contract_check.get("status")
    handoff_cleanup = (
        mainline_contract_check.get("handoff_cleanup")
        if isinstance(mainline_contract_check.get("handoff_cleanup"), dict)
        else {}
    )
    events = []
    for role_name in ("server", "client"):
        entry = handoff_cleanup.get(role_name)
        if not isinstance(entry, dict):
            continue
        cleanup_status = entry.get("status")
        if cleanup_status in {"cleaned", "removed"}:
            status = "ok"
        elif cleanup_status == "retained" and mainline_status == "ok":
            status = "ok"
        elif cleanup_status in {"retained", "missing_output_file"}:
            status = "error"
        else:
            status = "unknown"
        events.append(
            event(
                scope,
                stage="handoff_cleanup",
                status=status,
                ts_utc=generated_at,
                role=role_name,
                decision=None,
                reason_code=cleanup_status,
                duration_ms=None,
                row_count=None,
                artifact_sha256=None,
                source_event="mainline_contract_check",
            )
        )
    return events


def service_audit_consistency_events(chain: dict[str, Any], mainline_contract_check: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    if mainline_contract_check.get("schema") != "mainline_contract_check/v1":
        return []
    generated_at = mainline_contract_check.get("generated_at_utc")
    findings = mainline_contract_check.get("findings") if isinstance(mainline_contract_check.get("findings"), list) else []
    findings_by_kind = {
        str(item.get("kind", ""))
        for item in findings
        if isinstance(item, dict)
    }
    sse_records = chain.get("sse_export_audit") if isinstance(chain.get("sse_export_audit"), list) else []
    service_boundary_by_role = {
        str(record.get("role")): str(record.get("record_recovery_boundary"))
        for record in sse_records
        if isinstance(record, dict)
        and record.get("role") in {"server", "client"}
        and record.get("record_recovery_boundary") in {"service_socket", "service_http"}
    }
    events = []
    for role_name in ("server", "client"):
        if role_name not in service_boundary_by_role:
            status = "ok"
            reason_code = "not_applicable"
        else:
            has_role_service_findings = any(
                kind == f"missing_{role_name}_service_audit" or kind.startswith(f"{role_name}_service_")
                for kind in findings_by_kind
            )
            has_global_service_findings = any(
                kind in {"missing_service_audit", "service_transport_mismatch"}
                for kind in findings_by_kind
            )
            if has_role_service_findings or has_global_service_findings:
                status = "error"
                reason_code = "fail"
            else:
                status = "ok"
                reason_code = "ok"
        events.append(
            event(
                scope,
                stage="service_audit_consistency",
                status=status,
                ts_utc=generated_at,
                role=role_name,
                decision=None,
                reason_code=reason_code,
                duration_ms=None,
                row_count=None,
                artifact_sha256=None,
                source_event="mainline_contract_check",
            )
        )
    return events


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, dict[str, int]] = {}
    for item in events:
        stage = str(item.get("stage") or "unknown")
        status = str(item.get("status") or "unknown")
        by_stage.setdefault(stage, {})
        by_stage[stage][status] = by_stage[stage].get(status, 0) + 1
    return {
        "event_count": len(events),
        "by_stage": by_stage,
        "status": "error" if any(item.get("status") == "error" for item in events) else ("ok" if events else "unknown"),
    }


def build_observability(chain: dict[str, Any]) -> dict[str, Any]:
    if chain.get("schema") != "audit_chain/v1":
        raise ValueError(f"unexpected audit chain schema: {chain.get('schema')}")
    scope = base_scope(chain)
    mainline_contract_check = (
        chain.get("mainline_contract_check")
        if isinstance(chain.get("mainline_contract_check"), dict)
        else {}
    )
    if not mainline_contract_check:
        out_base = repo_path(chain.get("paths", {}).get("out_base")) if isinstance(chain.get("paths"), dict) and chain.get("paths", {}).get("out_base") else None
        mainline_contract_check = load_optional_json_object(out_base / "mainline_contract_check.json") if out_base else {}
    events: list[dict[str, Any]] = []
    events.extend(sse_events(chain, scope))
    events.extend(recovery_events(chain, scope))
    events.extend(bridge_events(chain, scope))
    events.extend(pjc_events(chain, scope))
    events.extend(policy_events(chain, scope))
    events.extend(handoff_cleanup_events(mainline_contract_check, scope))
    events.extend(service_audit_consistency_events(chain, mainline_contract_check, scope))
    return {
        "schema": "pipeline_observability/v1",
        "generated_at_utc": utc_now_iso(),
        **scope,
        "summary": summarize_events(events),
        "events": events,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Export stage-level observability events from audit_chain.json.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--audit-chain", default="")
    src.add_argument("--out-base", default="")
    ap.add_argument("--out", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    audit_chain_path = repo_path(args.audit_chain) if args.audit_chain else repo_path(args.out_base) / "audit_chain.json"
    observability = build_observability(load_json_object(audit_chain_path))
    text = json.dumps(observability, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
