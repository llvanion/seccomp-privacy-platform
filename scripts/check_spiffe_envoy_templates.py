#!/usr/bin/env python3
"""Structural lint for the SPIFFE/SPIRE + Envoy deploy templates.

Runs without a real cluster:

- `peer_spiffe_allowlist.json` must validate against
  `schemas/spiffe_envoy_peer_allowlist.schema.json` and contain mutually
  consistent server/client peers.
- Envoy YAML-ish templates must mention the loopback PJC upstream, the SPIRE
  agent SDS cluster, a TLS 1.3 minimum, and the matching peer SPIFFE ID.
- SPIRE HCL-ish configs must mention the trust domain and the SVID TTL.
- `rotation_notes.md` must list TTL, rotation, and audit storage sections so
  the documentation cannot silently drift away from the configs.

A typed `spiffe_envoy_template_check/v1` report is written to `--output` and
returned on stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_json_contract import load_json, validate_value  # noqa: E402


SCHEMA = "spiffe_envoy_template_check/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_allowlist(path: Path) -> tuple[dict, list[dict]]:
    findings: list[dict] = []
    if not path.is_file():
        return (
            {"file": str(path), "kind": "json", "status": "deny",
             "found_keys": [], "missing_keys": ["<file>"], "message": "missing"},
            [{"kind": "missing_file", "message": f"missing: {path}", "file": str(path)}],
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            {"file": str(path), "kind": "json", "status": "deny",
             "found_keys": [], "missing_keys": ["<parse>"], "message": f"json decode failed: {exc}"},
            [{"kind": "invalid_json", "message": str(exc), "file": str(path)}],
        )
    schema = load_json(str(REPO_ROOT / "schemas" / "spiffe_envoy_peer_allowlist.schema.json"))
    try:
        validate_value(data, schema)
    except Exception as exc:  # noqa: BLE001
        return (
            {"file": str(path), "kind": "json", "status": "deny",
             "found_keys": list(data.keys()) if isinstance(data, dict) else [],
             "missing_keys": ["<schema>"], "message": f"schema rejected: {exc}"},
            [{"kind": "schema_violation", "message": str(exc), "file": str(path)}],
        )
    # Mutual-allowlist consistency
    peers = data.get("peers", [])
    role_index = {p.get("role"): p for p in peers if isinstance(p, dict)}
    consistent_findings: list[dict] = []
    server = role_index.get("server")
    client = role_index.get("client")
    if not server or not client:
        consistent_findings.append({"kind": "missing_role", "message": "peers must include both server and client", "file": str(path)})
    elif server["spiffe_id"] not in client["allowed_peers"] or client["spiffe_id"] not in server["allowed_peers"]:
        consistent_findings.append({"kind": "allowlist_inconsistent", "message": "server/client SPIFFE IDs must reference each other in allowed_peers", "file": str(path)})
    status = "deny" if consistent_findings else "ok"
    return (
        {"file": str(path), "kind": "json", "status": status,
         "found_keys": list(data.keys()) if isinstance(data, dict) else [],
         "missing_keys": [], "message": None if status == "ok" else "mutual allowlist is not consistent"},
        consistent_findings,
    )


def _yaml_envoy_check(path: Path, *, required_phrases: list[str]) -> tuple[dict, list[dict]]:
    if not path.is_file():
        return (
            {"file": str(path), "kind": "yaml-ish", "status": "deny",
             "found_keys": [], "missing_keys": ["<file>"], "message": "missing"},
            [{"kind": "missing_file", "message": f"missing: {path}", "file": str(path)}],
        )
    text = path.read_text(encoding="utf-8")
    found, missing = [], []
    for phrase in required_phrases:
        (found if phrase in text else missing).append(phrase)
    status = "ok" if not missing else "deny"
    findings = [{"kind": "missing_envoy_key", "message": f"missing {m}", "file": str(path)} for m in missing]
    return (
        {"file": str(path), "kind": "yaml-ish", "status": status,
         "found_keys": found, "missing_keys": missing,
         "message": None if status == "ok" else "required key fragments missing"},
        findings,
    )


def _hcl_spire_check(path: Path, *, required_phrases: list[str]) -> tuple[dict, list[dict]]:
    if not path.is_file():
        return (
            {"file": str(path), "kind": "hcl-ish", "status": "deny",
             "found_keys": [], "missing_keys": ["<file>"], "message": "missing"},
            [{"kind": "missing_file", "message": f"missing: {path}", "file": str(path)}],
        )
    text = path.read_text(encoding="utf-8")
    found, missing = [], []
    for phrase in required_phrases:
        (found if phrase in text else missing).append(phrase)
    status = "ok" if not missing else "deny"
    findings = [{"kind": "missing_spire_key", "message": f"missing {m}", "file": str(path)} for m in missing]
    return (
        {"file": str(path), "kind": "hcl-ish", "status": status,
         "found_keys": found, "missing_keys": missing,
         "message": None if status == "ok" else "required SPIRE keys missing"},
        findings,
    )


def _markdown_check(path: Path, *, required_phrases: list[str]) -> tuple[dict, list[dict]]:
    if not path.is_file():
        return (
            {"file": str(path), "kind": "markdown", "status": "deny",
             "found_keys": [], "missing_keys": ["<file>"], "message": "missing"},
            [{"kind": "missing_file", "message": f"missing: {path}", "file": str(path)}],
        )
    text = path.read_text(encoding="utf-8")
    found, missing = [], []
    for phrase in required_phrases:
        (found if phrase.lower() in text.lower() else missing).append(phrase)
    status = "ok" if not missing else "deny"
    findings = [{"kind": "missing_docs_section", "message": f"missing {m}", "file": str(path)} for m in missing]
    return (
        {"file": str(path), "kind": "markdown", "status": status,
         "found_keys": found, "missing_keys": missing,
         "message": None if status == "ok" else "rotation_notes.md is missing required sections"},
        findings,
    )


def run_lint(templates_dir: Path) -> dict:
    checks: list[dict] = []
    findings: list[dict] = []

    allow_check, allow_findings = _check_allowlist(templates_dir / "peer_spiffe_allowlist.json")
    checks.append(allow_check); findings.extend(allow_findings)

    envoy_a, envoy_a_f = _yaml_envoy_check(
        templates_dir / "envoy_party_a.yaml",
        required_phrases=[
            "DownstreamTlsContext",
            "tls_minimum_protocol_version: TLSv1_3",
            "require_client_certificate: true",
            "spiffe://example.org/pjc-server",
            "pjc_loopback_a",
            "spire_agent",
        ],
    )
    checks.append(envoy_a); findings.extend(envoy_a_f)

    envoy_b, envoy_b_f = _yaml_envoy_check(
        templates_dir / "envoy_party_b.yaml",
        required_phrases=[
            "UpstreamTlsContext",
            "tls_minimum_protocol_version: TLSv1_3",
            "spiffe://example.org/pjc-client",
            "match_typed_subject_alt_names",
            "spiffe://example.org/pjc-server",
            "spire_agent",
        ],
    )
    checks.append(envoy_b); findings.extend(envoy_b_f)

    spire_server, spire_server_f = _hcl_spire_check(
        templates_dir / "spire_server.conf",
        required_phrases=["trust_domain", "default_x509_svid_ttl", "NodeAttestor", "KeyManager"],
    )
    checks.append(spire_server); findings.extend(spire_server_f)

    spire_agent, spire_agent_f = _hcl_spire_check(
        templates_dir / "spire_agent.conf",
        required_phrases=["trust_domain", "server_address", "WorkloadAttestor"],
    )
    checks.append(spire_agent); findings.extend(spire_agent_f)

    notes, notes_f = _markdown_check(
        templates_dir / "rotation_notes.md",
        required_phrases=["TTL", "Rotation", "Audit"],
    )
    checks.append(notes); findings.extend(notes_f)

    decision = "allow" if all(c["status"] == "ok" for c in checks) else "deny"
    reason_code = "ok" if decision == "allow" else (findings[0]["kind"] if findings else "deny")
    reason = None if decision == "allow" else (findings[0]["message"] if findings else None)

    return {
        "schema": SCHEMA,
        "generated_at_utc": _utc_now(),
        "templates_dir": str(templates_dir),
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "checks": checks,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Structural lint for SPIFFE/SPIRE + Envoy templates")
    parser.add_argument("--templates-dir", default=str(REPO_ROOT / "deploy" / "spiffe_envoy"))
    parser.add_argument("--output", help="Write the report to this path as JSON")
    parser.add_argument("--assert-allow", action="store_true", help="Exit non-zero if decision != allow")
    args = parser.parse_args(argv)

    templates_dir = Path(args.templates_dir).resolve()
    report = run_lint(templates_dir)
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_allow and report["decision"] != "allow":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
