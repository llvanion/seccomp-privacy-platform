#!/usr/bin/env python3
"""Python SDK prototype for programmatic access to the seccomp-privacy-platform.

Provides a Python client that:
  - Submits jobs via the query adapter
  - Reads audit chains and public reports
  - Browses the catalog
  - Generates telemetry

The SDK only calls control-plane read APIs and adapter scripts.
It does NOT directly access encrypted record stores, bridge token secrets,
PJC raw binaries, or the raw recovery service.

Usage:
  from scripts.sdk_client import SeccompClient

  client = SeccompClient(out_base="tmp/sse_bridge_pipeline_demo")
  status = client.job_status()
  report = client.public_report()
  catalog = client.list_catalog()
  client.close()
"""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _repo_path(rel: str) -> str:
    return os.path.join(REPO_ROOT, rel)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _run_script(script: str, args: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
    cmd = [sys.executable, _repo_path(script)] + args
    result = subprocess.run(cmd, cwd=cwd or REPO_ROOT, capture_output=True, text=True, timeout=300)
    return {
        "success": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@dataclass
class JobInfo:
    """Structured job status information."""
    job_id: str = ""
    correlation_id: str = ""
    caller: str = ""
    generated_at: str = ""
    sse_audit_records: int = 0
    bridge_audit_records: int = 0
    policy_audit_records: int = 0
    released: bool = False
    reason_code: str = ""
    intersection_size: int = 0
    intersection_sum: int = 0
    k_threshold: int = 0

    @classmethod
    def from_chain(cls, chain: Dict[str, Any], report: Optional[Dict[str, Any]] = None,
                   pjc: Optional[Dict[str, Any]] = None) -> "JobInfo":
        counts = chain.get("counts", {})
        return cls(
            job_id=chain.get("job_id", ""),
            correlation_id=chain.get("correlation_id", ""),
            caller=(chain.get("sse_export_audit", [{}]) or [{}])[0].get("caller", "")
                    if chain.get("sse_export_audit") else "",
            generated_at=chain.get("generated_at_utc", ""),
            sse_audit_records=counts.get("sse_export_audit_records", 0),
            bridge_audit_records=counts.get("bridge_audit_records", 0),
            policy_audit_records=counts.get("policy_audit_records", 0),
            released=report.get("released", False) if report else False,
            reason_code=report.get("reason_code", "") if report else "",
            intersection_size=pjc.get("intersection_size", 0) if pjc else 0,
            intersection_sum=pjc.get("intersection_sum", 0) if pjc else 0,
            k_threshold=report.get("k_threshold", 0) if report else 0,
        )


@dataclass
class CatalogEntry:
    """Structured catalog entry."""
    entry_type: str = ""
    entry_id: str = ""
    display_name: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CatalogEntry":
        etype = d.get("entry_type", "")
        entry_id = d.get("entry_id", "")
        if etype == "dataset":
            ds = d.get("dataset", {})
            name = ds.get("display_name", entry_id)
        elif etype == "job":
            j = d.get("job", {})
            name = j.get("job_id", entry_id)
        elif etype == "public_report":
            r = d.get("public_report_entry", {})
            name = r.get("job_id", entry_id)
        else:
            name = entry_id
        return cls(entry_type=etype, entry_id=entry_id, display_name=name, details=d)


class SeccompClient:
    """Python SDK client for the seccomp privacy platform.

    All operations go through adapter scripts and control-plane APIs.
    No direct access to encrypted stores, token secrets, or PJC internals.
    """

    def __init__(self, out_base: str = "tmp/sdk_client",
                 tenant_id: str = "default_tenant",
                 policy_config: str = "",
                 caller: str = "sdk_client"):
        self.out_base = os.path.abspath(out_base)
        self.tenant_id = tenant_id
        self.policy_config = policy_config
        self.caller = caller
        os.makedirs(self.out_base, exist_ok=True)

    # ── Job API ──────────────────────────────────────────

    def job_status(self, job_id: str = "") -> Optional[JobInfo]:
        """Get the status of a completed job."""
        chain_path = os.path.join(self.out_base, "audit_chain.json")
        chain = _load_json(chain_path)
        if not chain:
            return None
        report = _load_json(os.path.join(self.out_base, "a_psi_run", "public_report.json"))
        pjc = _load_json(os.path.join(self.out_base, "a_psi_run", "attribution_result.json"))
        return JobInfo.from_chain(chain, report, pjc)

    def submit_internal_export(self, *, role: str = "server",
                                fields: List[str] = None,
                                join_key_field: str = "email",
                                value_field: str = "",
                                filters: List[Dict[str, str]] = None,
                                sse_keyword: str = "",
                                record_store_path: str = "",
                                record_id_field: str = "") -> Dict[str, Any]:
        """Submit an internal fine-grained export query.

        Returns only policy-validated fields. No raw PII.
        """
        query = {
            "schema": "query_template/v1",
            "query_type": "internal_fine_grained",
            "caller": self.caller,
            "job_id": f"sdk_internal_{_ts_short()}",
            "correlation_id": "",
            "tenant_id": self.tenant_id,
            "internal_fine_grained": {
                "role": role,
                "fields": fields or ["email", "amount"],
                "join_key_field": join_key_field,
                "value_field": value_field,
                "filters": filters or [],
                "sse_keyword": sse_keyword,
                "record_id_field": record_id_field,
                "record_store_path": record_store_path,
            },
        }
        query["correlation_id"] = query["job_id"]
        return self._submit_query(query)

    def submit_aggregate(self, *, group_by_field: str,
                          metrics: List[Dict[str, str]] = None,
                          filters: List[Dict[str, str]] = None,
                          k_threshold: int = 50) -> Dict[str, Any]:
        """Submit a merchant aggregate query.

        Returns k-anonymity-gated aggregates. No raw PII.
        """
        query = {
            "schema": "query_template/v1",
            "query_type": "merchant_aggregate",
            "caller": self.caller,
            "job_id": f"sdk_aggregate_{_ts_short()}",
            "correlation_id": "",
            "tenant_id": self.tenant_id,
            "merchant_aggregate": {
                "group_by_field": group_by_field,
                "metrics": metrics or [{"type": "count", "field": "*"}],
                "filters": filters or [],
                "k_threshold": k_threshold,
            },
        }
        query["correlation_id"] = query["job_id"]
        return self._submit_query(query)

    def submit_collaboration(self, *, server_filters: List[Dict[str, str]] = None,
                              client_filters: List[Dict[str, str]] = None,
                              join_key_field: str = "email",
                              value_field: str = "amount",
                              value_mode: str = "raw-int",
                              k_threshold: int = 20,
                              rate_limit: int = 5) -> Dict[str, Any]:
        """Submit an ad collaboration query via the full pipeline path.

        This is the strongest privacy path: SSE → Bridge → PJC → Release.
        Only thresholded intersection aggregates are returned.
        """
        query = {
            "schema": "query_template/v1",
            "query_type": "ad_collaboration",
            "caller": self.caller,
            "job_id": f"sdk_collab_{_ts_short()}",
            "correlation_id": "",
            "tenant_id": self.tenant_id,
            "ad_collaboration": {
                "server_filters": server_filters or [{"field": "campaign", "value": "demo"}],
                "client_filters": client_filters or [{"field": "campaign", "value": "demo"}],
                "join_key_field": join_key_field,
                "value_field": value_field,
                "value_mode": value_mode,
                "k_threshold": k_threshold,
                "rate_limit": rate_limit,
            },
        }
        query["correlation_id"] = query["job_id"]
        return self._submit_query(query)

    def _submit_query(self, query: Dict[str, Any]) -> Dict[str, Any]:
        qf = os.path.join(self.out_base, f"_sdk_query_{query['job_id']}.json")
        with open(qf, "w", encoding="utf-8") as f:
            json.dump(query, f)

        args = ["submit", "--query-file", qf, "--out-base", self.out_base,
                "--tenant-id", self.tenant_id]
        if self.policy_config:
            args += ["--policy-config", self.policy_config]

        result = _run_script("scripts/query_adapter.py", args)

        result_path = os.path.join(self.out_base, "query_result.json")
        if os.path.isfile(result_path):
            with open(result_path, "r") as f:
                return json.load(f)
        return {"submitted": False, "error": result["stderr"]}

    # ── Audit API ────────────────────────────────────────

    def audit_chain(self) -> Optional[Dict[str, Any]]:
        """Read the audit chain for the current out_base."""
        return _load_json(os.path.join(self.out_base, "audit_chain.json"))

    def audit_seal(self) -> Optional[Dict[str, Any]]:
        """Read the audit seal for integrity verification."""
        return _load_json(os.path.join(self.out_base, "audit_chain.seal.json"))

    def verify_audit_integrity(self) -> bool:
        """Verify the audit chain seal is present and valid."""
        seal = self.audit_seal()
        if not seal:
            return False
        return bool(seal.get("audit_chain_sha256"))

    # ── Report API ───────────────────────────────────────

    def public_report(self) -> Optional[Dict[str, Any]]:
        """Read the public report for the current out_base."""
        return _load_json(os.path.join(self.out_base, "a_psi_run", "public_report.json"))

    def pjc_result(self) -> Optional[Dict[str, Any]]:
        """Read the raw PJC result (intersection size/sum only, no raw data)."""
        return _load_json(os.path.join(self.out_base, "a_psi_run", "attribution_result.json"))

    # ── Catalog API ──────────────────────────────────────

    def list_catalog(self, entry_type: str = "") -> List[CatalogEntry]:
        """List catalog entries, optionally filtered by type."""
        catalog_path = os.path.join(self.out_base, "catalog.jsonl")
        if not os.path.isfile(catalog_path):
            _run_script("scripts/catalog_adapter.py",
                        ["--out-base", self.out_base, "--tenant-id", self.tenant_id])
        entries = _load_jsonl(catalog_path)
        if entry_type:
            entries = [e for e in entries if e.get("entry_type") == entry_type]
        return [CatalogEntry.from_dict(e) for e in entries]

    def get_datasets(self) -> List[CatalogEntry]:
        """List all dataset catalog entries."""
        return self.list_catalog("dataset")

    def get_jobs(self) -> List[CatalogEntry]:
        """List all job catalog entries."""
        return self.list_catalog("job")

    def get_lineage_dot(self) -> Optional[str]:
        """Get the lineage graph in DOT format."""
        dot_path = os.path.join(self.out_base, "catalog_lineage.dot")
        if os.path.isfile(dot_path):
            with open(dot_path, "r") as f:
                return f.read()
        return None

    # ── Telemetry API ────────────────────────────────────

    def generate_telemetry(self) -> Dict[str, Any]:
        """Generate telemetry from pipeline outputs."""
        result = _run_script("scripts/telemetry_pipeline.py",
                             ["--out-base", self.out_base, "--tenant-id", self.tenant_id,
                              "--format", "otlp-jsonl"])
        manifest = _load_json(os.path.join(self.out_base, "telemetry_manifest.json"))
        return manifest or {"error": result["stderr"]}

    def generate_runbook(self) -> str:
        """Generate a runbook and return it as markdown text."""
        runbook_path = os.path.join(self.out_base, "runbook.md")
        _run_script("scripts/generate_observability_runbook.py",
                    ["--out-base", self.out_base])
        if os.path.isfile(runbook_path):
            with open(runbook_path, "r") as f:
                return f.read()
        return ""

    # ── Lifecycle ────────────────────────────────────────

    def close(self) -> None:
        """No-op close for consistency with future remote SDK."""
        pass

    def __enter__(self) -> "SeccompClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _ts_short() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


# ── Demo / smoke test ────────────────────────────────────────────


def main() -> int:
    """Demo the SDK against a completed pipeline run."""
    import argparse
    ap = argparse.ArgumentParser(description="Seccomp SDK demo / smoke test")
    ap.add_argument("--out-base", default="tmp/sse_bridge_pipeline_demo")
    args = ap.parse_args()

    print(f"SeccompClient SDK Demo")
    print(f"  out_base: {os.path.abspath(args.out_base)}")
    print()

    with SeccompClient(out_base=args.out_base) as client:
        # Job status
        job = client.job_status()
        if job:
            print(f"Job: {job.job_id}")
            print(f"  Caller: {job.caller}")
            print(f"  SSE audit records: {job.sse_audit_records}")
            print(f"  Bridge audit records: {job.bridge_audit_records}")
            print(f"  Policy audit records: {job.policy_audit_records}")
            print()

        # Public report
        report = client.public_report()
        if report:
            released = "RELEASED" if report.get("released") else "WITHHELD"
            print(f"Public Report: {released}")
            print(f"  Reason: {report.get('reason_code', '?')}")
            print(f"  K threshold: {report.get('k_threshold', '?')}")
            print(f"  Intersection: {report.get('conversions', '?')}")
            print(f"  Value sum: {report.get('value_sum', '?')}")
            print()

        # PJC result
        pjc = client.pjc_result()
        if pjc:
            print(f"PJC: intersection_size={pjc.get('intersection_size')} "
                  f"intersection_sum={pjc.get('intersection_sum')}")
            print()

        # Audit integrity
        ok = client.verify_audit_integrity()
        print(f"Audit integrity: {'PASS' if ok else 'FAIL'}")
        print()

        # Catalog
        datasets = client.get_datasets()
        print(f"Datasets: {len(datasets)}")
        for ds in datasets:
            print(f"  - {ds.display_name}")
        jobs = client.get_jobs()
        print(f"Jobs: {len(jobs)}")
        for j in jobs:
            print(f"  - {j.display_name}")
        print()

        # Telemetry
        manifest = client.generate_telemetry()
        if manifest:
            print(f"Telemetry: {manifest.get('metric_count', 0)} metrics "
                  f"from {manifest.get('job_count', 0)} jobs")
        print()

        # Runbook
        runbook = client.generate_runbook()
        if runbook:
            print(f"Runbook: {len(runbook)} chars generated")
        print()

    print("SDK demo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
