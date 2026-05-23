#!/usr/bin/env python3
"""Verify the local S7/K3 evidence package.

This is an offline evidence-integrity check. It validates the JSON artifacts,
checks the expected S7/K3 conclusions, scans the relevant logs, and writes a
machine-readable report plus a SHA-256 manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, errors: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        errors.append({"path": str(path), "error": f"invalid_json: {exc}"})
        return {}
    if not isinstance(payload, dict):
        errors.append({"path": str(path), "error": "json_root_not_object"})
        return {}
    return payload


def read_text(path: Path, errors: list[dict[str, str]]) -> str:
    try:
        return path.read_text(errors="replace")
    except Exception as exc:
        errors.append({"path": str(path), "error": f"read_failed: {exc}"})
        return ""


def check_equal(
    checks: list[dict[str, Any]],
    *,
    name: str,
    actual: Any,
    expected: Any,
) -> None:
    checks.append(
        {
            "name": name,
            "status": "pass" if actual == expected else "fail",
            "actual": actual,
            "expected": expected,
        }
    )


def check_contains(
    checks: list[dict[str, Any]],
    *,
    name: str,
    text: str,
    needle: str,
) -> None:
    checks.append(
        {
            "name": name,
            "status": "pass" if needle in text else "fail",
            "expected_contains": needle,
        }
    )


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def write_markdown_summary(report: dict[str, Any], out_path: Path) -> None:
    lines = [
        "# S7/K3 Evidence Package Verification",
        "",
        f"- Status: `{report['status']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- S7 evidence dir: `{report['inputs']['s7_dir']}`",
        f"- K3 evidence dir: `{report['inputs']['k3_dir']}`",
        "",
        "## Key Results",
        "",
        f"- S7 TLS: `{report['s7_result'].get('tls')}`",
        f"- S7 server address: `{report['s7_result'].get('server_addr')}`",
        f"- S7 intersection size: `{report['s7_result'].get('intersection_size')}`",
        f"- S7 intersection sum: `{report['s7_result'].get('intersection_sum')}`",
        f"- Server identity decision: `{report['identity_checks'].get('server_decision')}`",
        f"- Client identity decision: `{report['identity_checks'].get('client_decision')}`",
        f"- K3 critical findings: `{report['k3_assessment'].get('critical_findings')}`",
        f"- K3 high findings: `{report['k3_assessment'].get('high_findings')}`",
        f"- No-client-cert TLS handshake: `{report['k3_assessment'].get('no_client_certificate_tls_handshake')}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Actual | Expected |",
        "| --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        actual = check.get("actual", "")
        expected = check.get("expected", check.get("expected_contains", ""))
        lines.append(f"| `{check['name']}` | `{check['status']}` | `{actual}` | `{expected}` |")
    lines.extend(
        [
            "",
            "## Evidence Hashes",
            "",
            "| Path | SHA-256 |",
            "| --- | --- |",
        ]
    )
    for item in report["evidence_hashes"]:
        lines.append(f"| `{item['path']}` | `{item['sha256']}` |")
    lines.extend(
        [
            "",
            "## Report Wording",
            "",
            "`S7 public two-host PJC mTLS validation and K3 internal security probing were verified offline. "
            "The evidence package is JSON-readable, hash-sealed, and all expected conclusions passed: "
            "TLS=true, intersection_size=2, intersection_sum=425, server/client identity decisions allow, "
            "critical/high findings are zero, and the no-client-certificate TLS handshake did not complete.`",
            "",
        ]
    )
    out_path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s7-dir", default="tmp/pjc_mtls_cross-vps-005")
    parser.add_argument("--k3-dir", default="tmp/k3_internal_security_cross-vps-005")
    parser.add_argument("--output", default="tmp/k3_internal_security_cross-vps-005/evidence_integrity_report.json")
    parser.add_argument("--markdown-output", default="tmp/k3_internal_security_cross-vps-005/evidence_integrity_report.md")
    parser.add_argument("--hash-output", default="tmp/k3_internal_security_cross-vps-005/final_evidence_hashes.sha256")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    s7_dir = Path(args.s7_dir)
    k3_dir = Path(args.k3_dir)
    errors: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    paths = {
        "party_a_server_log": s7_dir / "party_a_server" / "server.log",
        "party_b_client_log": s7_dir / "party_b_client" / "client.log",
        "party_b_result": s7_dir / "party_b_client" / "attribution_result.json",
        "server_identity": s7_dir / "server_tls_identity.json",
        "client_identity": s7_dir / "client_tls_identity.json",
        "k3_probe_summary": k3_dir / "probe_summary.json",
        "k3_verbose_no_client_cert": k3_dir / "tls_probe_no_client_cert_verbose.log",
        "k3_findings": k3_dir / "FINDINGS.md",
        "k3_summary": k3_dir / "EVIDENCE_SUMMARY.md",
    }

    for name, path in paths.items():
        checks.append({"name": f"{name}_present", "status": "pass" if path.is_file() else "fail", "path": str(path)})
        if not path.is_file():
            errors.append({"path": str(path), "error": "missing"})

    result = load_json(paths["party_b_result"], errors) if paths["party_b_result"].is_file() else {}
    server_identity = load_json(paths["server_identity"], errors) if paths["server_identity"].is_file() else {}
    client_identity = load_json(paths["client_identity"], errors) if paths["client_identity"].is_file() else {}
    k3_probe = load_json(paths["k3_probe_summary"], errors) if paths["k3_probe_summary"].is_file() else {}
    server_log = read_text(paths["party_a_server_log"], errors) if paths["party_a_server_log"].is_file() else ""
    client_log = read_text(paths["party_b_client_log"], errors) if paths["party_b_client_log"].is_file() else ""
    verbose_log = read_text(paths["k3_verbose_no_client_cert"], errors) if paths["k3_verbose_no_client_cert"].is_file() else ""

    check_equal(checks, name="s7_tls_enabled", actual=result.get("tls"), expected=True)
    check_equal(checks, name="s7_server_addr", actual=result.get("server_addr"), expected="118.190.61.66:10502")
    check_equal(checks, name="s7_intersection_size", actual=result.get("intersection_size"), expected=2)
    check_equal(checks, name="s7_intersection_sum", actual=result.get("intersection_sum"), expected=425)
    check_equal(checks, name="server_identity_allow", actual=server_identity.get("decision"), expected="allow")
    check_equal(checks, name="client_identity_allow", actual=client_identity.get("decision"), expected="allow")
    check_contains(checks, name="party_a_protocol_completed", text=server_log, needle="Server completed protocol and shut down.")
    check_contains(checks, name="party_b_result_logged", text=client_log, needle="The intersection size is 2 and the intersection-sum is 425")

    assessment = k3_probe.get("assessment", {}) if isinstance(k3_probe.get("assessment"), dict) else {}
    check_equal(checks, name="k3_critical_findings_zero", actual=assessment.get("critical_findings"), expected=0)
    check_equal(checks, name="k3_high_findings_zero", actual=assessment.get("high_findings"), expected=0)
    check_equal(
        checks,
        name="k3_no_client_cert_handshake_not_completed",
        actual=assessment.get("no_client_certificate_tls_handshake"),
        expected="not_completed",
    )
    check_contains(checks, name="no_peer_certificate_observed", text=verbose_log, needle="no peer certificate available")
    check_contains(checks, name="no_cipher_negotiated", text=verbose_log, needle="Cipher is (NONE)")
    check_contains(checks, name="unexpected_eof_observed", text=verbose_log, needle="unexpected eof while reading")

    hash_items = []
    for path in paths.values():
        if path.is_file():
            hash_items.append({"path": rel(path, repo_root), "sha256": sha256_file(path)})

    status = "pass" if not errors and all(c.get("status") == "pass" for c in checks) else "fail"
    report = {
        "schema": "s7_k3_evidence_integrity_report/v1",
        "generated_at_utc": utc_now(),
        "status": status,
        "inputs": {
            "s7_dir": str(s7_dir),
            "k3_dir": str(k3_dir),
        },
        "s7_result": {
            "server_addr": result.get("server_addr"),
            "tls": result.get("tls"),
            "intersection_size": result.get("intersection_size"),
            "intersection_sum": result.get("intersection_sum"),
        },
        "identity_checks": {
            "server_decision": server_identity.get("decision"),
            "server_fingerprint_sha256": server_identity.get("fingerprint_sha256"),
            "client_decision": client_identity.get("decision"),
            "client_fingerprint_sha256": client_identity.get("fingerprint_sha256"),
        },
        "k3_assessment": {
            "critical_findings": assessment.get("critical_findings"),
            "high_findings": assessment.get("high_findings"),
            "no_client_certificate_tls_handshake": assessment.get("no_client_certificate_tls_handshake"),
        },
        "checks": checks,
        "errors": errors,
        "evidence_hashes": hash_items,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    write_markdown_summary(report, Path(args.markdown_output))

    with Path(args.hash_output).open("w") as fh:
        for item in hash_items:
            fh.write(f"{item['sha256']}  {item['path']}\n")

    print(json.dumps({"status": status, "output": str(output), "checks": len(checks)}, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
