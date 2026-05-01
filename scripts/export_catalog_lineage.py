#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_audit_bundle import summarize_mainline_contract


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def as_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def stable_id(prefix: str, *parts: Any) -> str:
    body = ":".join(str(part) for part in parts if part not in (None, ""))
    return f"{prefix}:{body or 'unknown'}"


def artifact_id(kind: str, stage: str, sha256: Any, index: int) -> str:
    if sha256:
        return stable_id("artifact", stage, kind, str(sha256)[:16])
    return stable_id("artifact", stage, kind, index)


def put_unique(items: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
    item_id = item.get("id")
    if not item_id:
        raise ValueError(f"catalog item is missing id: {item}")
    existing = items.get(str(item_id))
    if existing is None:
        items[str(item_id)] = item
        return
    for key, value in item.items():
        if existing.get(key) in (None, "", []) and value not in (None, "", []):
            existing[key] = value


def add_edge(edges: list[dict[str, Any]], *, source: str, target: str, relationship: str, stage: str) -> None:
    edge = {
        "source": source,
        "target": target,
        "relationship": relationship,
        "stage": stage,
    }
    if edge not in edges:
        edges.append(edge)


def base_scope(chain: dict[str, Any]) -> dict[str, Any]:
    public_report = chain.get("public_report") if isinstance(chain.get("public_report"), dict) else {}
    records: list[dict[str, Any]] = []
    for key in (
        "sse_export_audit",
        "record_recovery_service_audit",
        "bridge_audit",
        "pjc_audit",
        "policy_audit",
        "key_access_audit",
    ):
        records.extend(as_records(chain.get(key)))
    return {
        "job_id": first_non_empty(chain.get("job_id"), public_report.get("job_id")),
        "correlation_id": first_non_empty(chain.get("correlation_id"), public_report.get("correlation_id")),
        "caller": first_non_empty(public_report.get("caller"), *(record.get("caller") for record in records)),
        "tenant_id": first_non_empty(*(record.get("tenant_id") for record in records)),
        "dataset_id": first_non_empty(*(record.get("dataset_id") for record in records)),
        "service_id": first_non_empty(*(record.get("service_id") for record in records)),
    }


def release_summary(chain: dict[str, Any]) -> dict[str, Any]:
    public_report = chain.get("public_report") if isinstance(chain.get("public_report"), dict) else {}
    policy_records = as_records(chain.get("policy_audit"))
    latest_policy = policy_records[-1] if policy_records else {}
    released = public_report.get("released")
    if released is True:
        status = "released"
    elif released is False:
        status = "denied"
    else:
        status = first_non_empty(latest_policy.get("decision"), "imported")
    return {
        "status": status,
        "released": released if isinstance(released, bool) else None,
        "reason_code": first_non_empty(public_report.get("reason_code"), latest_policy.get("reason_code")),
        "policy_version": first_non_empty(public_report.get("policy_version"), latest_policy.get("policy_version")),
    }


def build_catalog_lineage(chain: dict[str, Any], *, include_paths: bool = False) -> dict[str, Any]:
    if chain.get("schema") != "audit_chain/v1":
        raise ValueError(f"unexpected audit chain schema: {chain.get('schema')}")

    scope = base_scope(chain)
    summary = release_summary(chain)
    datasets: dict[str, dict[str, Any]] = {}
    services: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    dataset_id = stable_id("dataset", scope.get("tenant_id"), scope.get("dataset_id"))
    put_unique(
        datasets,
        {
            "id": dataset_id,
            "tenant_id": scope.get("tenant_id"),
            "dataset_id": scope.get("dataset_id"),
            "schema_version": None,
            "source": "audit_chain",
        },
    )

    service_id = None
    if scope.get("service_id"):
        service_id = stable_id("service", scope.get("service_id"))
        transport = first_non_empty(
            *(record.get("transport") for record in as_records(chain.get("record_recovery_service_audit"))),
            "unix_socket",
        )
        put_unique(
            services,
            {
                "id": service_id,
                "service_id": scope.get("service_id"),
                "tenant_id": scope.get("tenant_id"),
                "dataset_id": scope.get("dataset_id"),
                "service_type": "record_recovery",
                "transport": transport,
            },
        )

    job_id = stable_id("job", scope.get("job_id"))

    def add_artifact(
        *,
        kind: str,
        stage: str,
        role: Any = None,
        sha256: Any = None,
        path: Any = None,
        row_count: Any = None,
        fmt: Any = None,
        source_event: Any = None,
    ) -> str:
        index = len(artifacts) + 1
        aid = artifact_id(kind, stage, sha256, index)
        item = {
            "id": aid,
            "artifact_type": kind,
            "stage": stage,
            "role": role,
            "sha256": sha256,
            "row_count": row_count,
            "format": fmt,
            "source_event": source_event,
        }
        if include_paths:
            item["path"] = path
        else:
            item["path_included"] = False
        put_unique(artifacts, item)
        return aid

    for record in as_records(chain.get("sse_export_audit")):
        record_dataset_id = stable_id(
            "dataset",
            first_non_empty(record.get("tenant_id"), scope.get("tenant_id")),
            first_non_empty(record.get("dataset_id"), scope.get("dataset_id")),
        )
        put_unique(
            datasets,
            {
                "id": record_dataset_id,
                "tenant_id": first_non_empty(record.get("tenant_id"), scope.get("tenant_id")),
                "dataset_id": first_non_empty(record.get("dataset_id"), scope.get("dataset_id")),
                "schema_version": record.get("schema"),
                "source": "sse_export_audit",
            },
        )
        output_id = add_artifact(
            kind="sse_export",
            stage="sse_export",
            role=record.get("role"),
            sha256=record.get("output_sha256"),
            path=record.get("output_file"),
            row_count=record.get("output_rows"),
            fmt=record.get("out_format"),
            source_event=record.get("event"),
        )
        add_edge(edges, source=record_dataset_id, target=output_id, relationship="exported_to", stage="sse_export")
        add_edge(edges, source=output_id, target=job_id, relationship="input_to", stage="bridge")

    for record in as_records(chain.get("record_recovery_service_audit")):
        if service_id:
            add_edge(edges, source=dataset_id, target=service_id, relationship="served_by", stage="record_recovery_service")
        store_id = add_artifact(
            kind="encrypted_record_store",
            stage="record_recovery_service",
            role=record.get("role"),
            sha256=record.get("record_store_sha256"),
            path=record.get("record_store_file"),
            row_count=record.get("input_rows"),
            fmt="jsonl",
            source_event=record.get("event"),
        )
        recovered_id = add_artifact(
            kind="recovered_bridge_input",
            stage="record_recovery_service",
            role=record.get("role"),
            sha256=record.get("output_sha256"),
            path=record.get("output_file"),
            row_count=record.get("output_rows"),
            fmt=record.get("out_format"),
            source_event=record.get("event"),
        )
        add_edge(edges, source=dataset_id, target=store_id, relationship="materialized_as", stage="record_recovery_service")
        if service_id:
            add_edge(edges, source=service_id, target=recovered_id, relationship="authorized_recovery", stage="record_recovery_service")
        add_edge(edges, source=store_id, target=recovered_id, relationship="recovered_to", stage="record_recovery_service")
        add_edge(edges, source=recovered_id, target=job_id, relationship="input_to", stage="bridge")

    for record in as_records(chain.get("bridge_audit")):
        for role, key in (("server", "server_input_sha256"), ("client", "client_input_sha256")):
            if record.get(key):
                input_id = add_artifact(
                    kind="bridge_input",
                    stage="bridge",
                    role=role,
                    sha256=record.get(key),
                    fmt="csv",
                    source_event=record.get("event"),
                )
                add_edge(edges, source=input_id, target=job_id, relationship="prepared_for", stage="bridge")

    for record in as_records(chain.get("pjc_audit")):
        result_id = add_artifact(
            kind="pjc_result",
            stage="pjc",
            sha256=record.get("result_sha256"),
            path=record.get("result_file"),
            fmt="json",
            source_event=record.get("event"),
        )
        add_edge(edges, source=job_id, target=result_id, relationship="computed", stage="pjc")

    for record in as_records(chain.get("policy_audit")):
        report_id = add_artifact(
            kind="public_report",
            stage="policy_release",
            sha256=record.get("release_sha256"),
            path=record.get("release_file"),
            fmt="json",
            source_event=record.get("event"),
        )
        pjc_input_id = add_artifact(
            kind="pjc_result",
            stage="policy_release",
            sha256=record.get("pjc_result_sha256"),
            path=record.get("pjc_result_file"),
            fmt="json",
            source_event=record.get("event"),
        )
        add_edge(edges, source=pjc_input_id, target=report_id, relationship="policy_released_as", stage="policy_release")
        add_edge(edges, source=job_id, target=report_id, relationship="released_as", stage="policy_release")

    return {
        "schema": "catalog_lineage/v1",
        "generated_at_utc": utc_now_iso(),
        **scope,
        "mainline_contract_summary": summarize_mainline_contract(chain),
        "privacy": {
            "stores_sensitive_plaintext": False,
            "paths_included": include_paths,
            "notes": "Default output records metadata, hashes, counts, and lineage only; full artifact paths require --include-paths.",
        },
        "job": {
            "id": job_id,
            **scope,
            **summary,
        },
        "datasets": list(datasets.values()),
        "services": list(services.values()),
        "artifacts": list(artifacts.values()),
        "lineage_edges": edges,
        "summary": {
            "dataset_count": len(datasets),
            "service_count": len(services),
            "artifact_count": len(artifacts),
            "lineage_edge_count": len(edges),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Export catalog and lineage metadata from audit_chain.json.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--audit-chain", default="")
    src.add_argument("--out-base", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--include-paths", action="store_true", help="Include full artifact paths; disabled by default to reduce metadata leakage.")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    audit_chain_path = repo_path(args.audit_chain) if args.audit_chain else repo_path(args.out_base) / "audit_chain.json"
    lineage = build_catalog_lineage(load_json_object(audit_chain_path), include_paths=args.include_paths)
    text = json.dumps(lineage, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
