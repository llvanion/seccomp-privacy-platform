#!/usr/bin/env python3
"""Catalog adapter: reads existing pipeline outputs and builds privacy-safe catalog entries.

Generates catalog entries for datasets, schema versions, policy bindings, jobs,
artifacts, and public report lineage.

Does NOT save:
  - Raw join keys (email, phone, device ID)
  - Full phone numbers or home addresses
  - Recovery secrets or bridge token secrets
  - Raw record contents

Usage:
  python3 scripts/catalog_adapter.py \
    --out-base tmp/sse_bridge_pipeline_demo \
    --catalog-out tmp/catalog.jsonl
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    if not path or not os.path.isfile(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


class CatalogBuilder:
    def __init__(self, out_base: str, tenant_id: str = "default_tenant"):
        self.out_base = os.path.abspath(out_base)
        self.tenant_id = tenant_id
        self.entries: List[Dict[str, Any]] = []
        self.entry_ids: set = set()
        self.now = utc_now_iso()

    def _add_entry(self, entry: Dict[str, Any]) -> None:
        eid = entry.get("entry_id", "")
        if eid in self.entry_ids:
            return
        self.entry_ids.add(eid)
        self.entries.append(entry)

    def _base_entry(self, entry_type: str, entry_id: str) -> Dict[str, Any]:
        return {
            "schema": "catalog_entry/v1",
            "entry_type": entry_type,
            "entry_id": entry_id,
            "created_at_utc": self.now,
            "updated_at_utc": self.now,
            "tenant_id": self.tenant_id,
        }

    def collect(self) -> None:
        sse_audit_path = os.path.join(self.out_base, "sse_exports", "export_audit.jsonl")
        bridge_meta_path = os.path.join(self.out_base, "bridge_job", "job_meta.json")
        pjc_result_path = os.path.join(self.out_base, "a_psi_run", "attribution_result.json")
        public_report_path = os.path.join(self.out_base, "a_psi_run", "public_report.json")
        audit_chain_path = os.path.join(self.out_base, "audit_chain.json")

        sse_audit = load_jsonl(sse_audit_path)
        bridge_meta = load_json(bridge_meta_path)
        pjc_result = load_json(pjc_result_path)
        public_report = load_json(public_report_path)
        audit_chain = load_json(audit_chain_path)

        self._collect_dataset_entries(sse_audit)
        self._collect_schema_version_entries(sse_audit)
        self._collect_policy_binding_entries(sse_audit)
        self._collect_job_entries(bridge_meta, audit_chain, public_report)
        self._collect_artifact_entries(audit_chain)
        self._collect_public_report_entries(public_report, audit_chain)

    def _collect_dataset_entries(self, sse_audit: List[Dict[str, Any]]) -> None:
        for r in sse_audit:
            source = r.get("source_file") or ""
            if not source:
                continue
            dataset_id = sha256_str(f"dataset:{self.tenant_id}:{source}")
            role = r.get("role", "unknown")
            entry = self._base_entry("dataset", dataset_id)
            entry["dataset"] = {
                "dataset_id": dataset_id,
                "display_name": os.path.basename(source),
                "description": f"Dataset for role={role}, source={os.path.basename(source)}",
                "owner": r.get("caller", "unknown"),
                "source_type": r.get("source_format", "jsonl"),
                "record_count": r.get("input_rows") or 0,
                "fields": [
                    {
                        "field_name": r.get("join_key_field", ""),
                        "field_type": "join_key",
                        "is_sensitive": True,
                    }
                ],
                "source_sha256": r.get("source_sha256") or sha256_file(source) or "",
                "current_schema_version": sha256_str(f"v1:{source}")[:16],
            }
            if r.get("value_field"):
                entry["dataset"]["fields"].append({
                    "field_name": r["value_field"],
                    "field_type": "value",
                    "is_sensitive": False,
                })
            self._add_entry(entry)

    def _collect_schema_version_entries(self, sse_audit: List[Dict[str, Any]]) -> None:
        for r in sse_audit:
            source = r.get("source_file") or ""
            if not source:
                continue
            dataset_id = sha256_str(f"dataset:{self.tenant_id}:{source}")
            version_id = sha256_str(f"schema_version:{dataset_id}:v1")
            entry = self._base_entry("schema_version", version_id)
            entry["schema_version_entry"] = {
                "version_id": version_id,
                "dataset_id": dataset_id,
                "version_number": 1,
                "fields_snapshot": [
                    {"field_name": r.get("join_key_field", ""), "field_type": "join_key"},
                ],
                "checksum": sha256_str(f"v1:{r.get('join_key_field','')}:{r.get('value_field','')}"),
                "backward_compatible": True,
            }
            self._add_entry(entry)

    def _collect_policy_binding_entries(self, sse_audit: List[Dict[str, Any]]) -> None:
        seen_policies: set = set()
        for r in sse_audit:
            policy_config = r.get("policy_config") or ""
            if not policy_config or policy_config in seen_policies:
                continue
            seen_policies.add(policy_config)
            source = r.get("source_file") or ""
            dataset_id = sha256_str(f"dataset:{self.tenant_id}:{source}")
            binding_id = sha256_str(f"binding:{dataset_id}:{os.path.basename(policy_config)}")
            entry = self._base_entry("policy_binding", binding_id)
            entry["policy_binding"] = {
                "binding_id": binding_id,
                "dataset_id": dataset_id,
                "policy_config_sha256": sha256_file(policy_config) or "",
                "policy_config_path": policy_config,
                "allowed_roles": [r.get("role", "unknown")],
                "allowed_join_key_fields": [r.get("join_key_field", "")],
                "allowed_value_fields": [r.get("value_field", "")] if r.get("value_field") else [],
                "required_filters": [],
                "min_export_rows": 1,
                "max_export_rows": 1000000,
                "bound_at_utc": self.now,
            }
            self._add_entry(entry)

    def _collect_job_entries(self, bridge_meta: Optional[Dict[str, Any]],
                              audit_chain: Optional[Dict[str, Any]],
                              public_report: Optional[Dict[str, Any]]) -> None:
        job_id = ""
        if audit_chain:
            job_id = audit_chain.get("job_id", "")
        elif bridge_meta:
            job_id = bridge_meta.get("job_id", "")
        elif public_report:
            job_id = public_report.get("job_id", "")
        if not job_id:
            return

        entry = self._base_entry("job", f"job:{job_id}")
        stages = []
        if audit_chain:
            for stage_name in ["sse_export_audit", "bridge_audit", "policy_audit"]:
                records = audit_chain.get(stage_name, [])
                for r in (records or []):
                    stages.append({
                        "stage": stage_name,
                        "decision": r.get("decision", "unknown"),
                        "reason_code": r.get("reason_code", "unknown"),
                        "timestamp_utc": r.get("ts_utc") or r.get("timestamp_utc") or self.now,
                    })

        caller = "unknown"
        if audit_chain:
            sse_records = audit_chain.get("sse_export_audit", []) or []
            if sse_records:
                caller = sse_records[0].get("caller", "unknown")

        released = public_report.get("released", False) if public_report else False

        entry["job"] = {
            "job_id": job_id,
            "caller": caller,
            "status": "completed" if released else "completed_withheld",
            "stages": stages,
            "input_datasets": [],
            "output_artifacts": [],
            "started_at_utc": stages[0]["timestamp_utc"] if stages else self.now,
            "completed_at_utc": stages[-1]["timestamp_utc"] if stages else self.now,
        }
        self._add_entry(entry)

    def _collect_artifact_entries(self, audit_chain: Optional[Dict[str, Any]]) -> None:
        if not audit_chain:
            return
        job_id = audit_chain.get("job_id", "unknown")
        paths = audit_chain.get("paths", {})

        artifact_map = {
            "sse_audit": ("sse_export", "sse_export"),
            "bridge_job_meta": ("bridge_output", "bridge"),
            "pjc_result": ("pjc_result", "pjc"),
            "public_report": ("public_report", "policy_release"),
            "policy_audit": ("public_report", "policy_release"),
        }

        for path_key, (artifact_type, stage) in artifact_map.items():
            file_path = paths.get(path_key)
            if not file_path:
                continue
            artifact_id = sha256_str(f"artifact:{job_id}:{path_key}")
            fsize = 0
            try:
                fsize = os.path.getsize(file_path)
            except OSError:
                pass
            entry = self._base_entry("artifact", artifact_id)
            entry["artifact"] = {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "job_id": job_id,
                "stage": stage,
                "file_path": file_path,
                "sha256": sha256_file(file_path) or "",
                "size_bytes": fsize,
                "row_count": 0,
                "generated_at_utc": self.now,
            }
            self._add_entry(entry)

    def _collect_public_report_entries(self, public_report: Optional[Dict[str, Any]],
                                        audit_chain: Optional[Dict[str, Any]]) -> None:
        if not public_report:
            return
        job_id = public_report.get("job_id", "unknown")
        report_id = sha256_str(f"report:{job_id}")
        entry = self._base_entry("public_report", report_id)
        entry["public_report_entry"] = {
            "report_id": report_id,
            "job_id": job_id,
            "released": public_report.get("released", False),
            "reason_code": public_report.get("reason_code", "unknown"),
            "intersection_size": public_report.get("conversions") or 0,
            "intersection_sum": (public_report.get("value_sum") or 0) if isinstance(public_report.get("value_sum"), (int, float)) else 0,
            "k_threshold": public_report.get("k_threshold", 0),
            "rate_limit_used": public_report.get("rate_limit_used", 0),
            "policy_version": public_report.get("policy_version", ""),
            "audit_chain_sha256": sha256_file(os.path.join(self.out_base, "audit_chain.json")) or "",
        }
        self._add_entry(entry)

    def write(self, output_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for entry in self.entries:
                json.dump(entry, f, ensure_ascii=False)
                f.write("\n")
        print(f"[ok] catalog entries ({len(self.entries)}): {os.path.abspath(output_path)}")

    def write_lineage_graph(self, output_path: str) -> None:
        """Write a simple lineage graph in DOT format for visualization."""
        lines = ["digraph catalog_lineage {", '  rankdir="LR";',
                 '  node [shape=box, style=filled, fillcolor=lightyellow];']
        for entry in self.entries:
            eid = entry["entry_id"]
            etype = entry["entry_type"]
            label = eid[:24]
            color = {
                "dataset": "lightblue",
                "schema_version": "lightgreen",
                "policy_binding": "lightyellow",
                "job": "lightcoral",
                "artifact": "lightgray",
                "public_report": "lightpink",
            }.get(etype, "white")
            lines.append(f'  "{eid}" [label="{etype}\\n{label}", fillcolor={color}];')

        job_id = ""
        for entry in self.entries:
            if entry["entry_type"] == "job":
                job_id = entry.get("job", {}).get("job_id", "")
                break

        for entry in self.entries:
            eid = entry["entry_id"]
            if entry["entry_type"] == "dataset" and job_id:
                job_entry_id = f"job:{job_id}"
                if job_entry_id in self.entry_ids:
                    lines.append(f'  "{eid}" -> "{job_entry_id}";')
            if entry["entry_type"] == "policy_binding" and job_id:
                job_entry_id = f"job:{job_id}"
                if job_entry_id in self.entry_ids:
                    lines.append(f'  "{eid}" -> "{job_entry_id}";')

        prev_artifact = None
        for entry in self.entries:
            if entry["entry_type"] == "artifact":
                if prev_artifact:
                    lines.append(f'  "{prev_artifact}" -> "{entry["entry_id"]}";')
                prev_artifact = entry["entry_id"]

        if prev_artifact and self.entries:
            last_report = None
            for entry in reversed(self.entries):
                if entry["entry_type"] == "public_report":
                    last_report = entry["entry_id"]
                    break
            if last_report:
                lines.append(f'  "{prev_artifact}" -> "{last_report}";')

        lines.append("}")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"[ok] lineage graph (DOT): {os.path.abspath(output_path)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build privacy-safe catalog entries from pipeline outputs."
    )
    ap.add_argument("--out-base", required=True,
                    help="Pipeline output directory")
    ap.add_argument("--tenant-id", default="default_tenant")
    ap.add_argument("--catalog-out", default="",
                    help="Output catalog JSONL path; defaults to <out-base>/catalog.jsonl")
    ap.add_argument("--lineage-out", default="",
                    help="Output lineage DOT graph path; defaults to <out-base>/catalog_lineage.dot")
    args = ap.parse_args()

    if not os.path.isdir(args.out_base):
        print(f"[ERROR] out-base directory not found: {args.out_base}", file=sys.stderr)
        return 1

    catalog_out = args.catalog_out or os.path.join(args.out_base, "catalog.jsonl")
    lineage_out = args.lineage_out or os.path.join(args.out_base, "catalog_lineage.dot")

    builder = CatalogBuilder(args.out_base, args.tenant_id)
    try:
        builder.collect()
    except Exception as e:
        print(f"[ERROR] catalog collection failed: {e}", file=sys.stderr)
        return 1

    builder.write(catalog_out)
    builder.write_lineage_graph(lineage_out)

    entry_types = {}
    for e in builder.entries:
        t = e["entry_type"]
        entry_types[t] = entry_types.get(t, 0) + 1
    for t, c in sorted(entry_types.items()):
        print(f"  {t}: {c} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
