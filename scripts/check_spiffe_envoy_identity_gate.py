#!/usr/bin/env python3
"""Verifier-facing gate for SPIFFE/SPIRE + Envoy identity/network-trust evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_spiffe_envoy_templates import run_lint


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "spiffe_envoy_identity_gate/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def parse_check(
    *,
    name: str,
    status: str,
    expected: Any,
    actual: Any,
    missing_prerequisites: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
    }
    if missing_prerequisites is not None:
        payload["missing_prerequisites"] = missing_prerequisites
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--templates-dir", default=str(REPO_ROOT / "deploy" / "spiffe_envoy"))
    ap.add_argument("--live-evidence-archive", default="")
    ap.add_argument("--live-positive-report", default="")
    ap.add_argument("--live-wrong-peer-report", default="")
    ap.add_argument("--live-expired-svid-report", default="")
    ap.add_argument("--live-trust-bundle-reject-report", default="")
    ap.add_argument("--live-envoy-access-log", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    allowlist_path = Path(args.templates_dir).resolve() / "peer_spiffe_allowlist.json"
    allowlist = load_json(allowlist_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_spiffe_peer_allowlist",
            status="ok" if allowlist.get("schema") == "spiffe_envoy_peer_allowlist/v1" else "fail",
            expected="peer SPIFFE allowlist is present and versioned as a frozen contract",
            actual=allowlist,
        )
    )
    artifacts.append(artifact(allowlist_path, schema="spiffe_envoy_peer_allowlist/v1"))

    template_report = run_lint(Path(args.templates_dir).resolve())
    template_report_path = out_dir / "spiffe_envoy_template_check.json"
    write_json(template_report_path, template_report)
    repo_side_checks.append(
        parse_check(
            name="repo_side_spiffe_envoy_template_lint",
            status="ok" if template_report.get("decision") == "allow" else "fail",
            expected="SPIFFE/SPIRE + Envoy templates remain structurally coherent and mutually consistent",
            actual=template_report,
        )
    )
    artifacts.append(artifact(template_report_path, schema="spiffe_envoy_template_check/v1"))

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is not None and archive_path.is_file():
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="spiffe_envoy_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_spiffe_envoy_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified SPIFFE/SPIRE + Envoy live evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        live_artifacts = archive.get("live_artifacts") if isinstance(archive.get("live_artifacts"), dict) else {}
        live_inputs = {
            "live_positive_run": live_artifacts.get("live_positive_run"),
            "live_wrong_peer_reject": live_artifacts.get("live_wrong_peer_reject"),
            "live_expired_svid_reject": live_artifacts.get("live_expired_svid_reject"),
            "live_trust_bundle_reject": live_artifacts.get("live_trust_bundle_reject"),
            "live_envoy_access_log": live_artifacts.get("live_envoy_access_log"),
        }
        for name, payload in live_inputs.items():
            if payload is None:
                live_checks.append(
                    parse_check(
                        name=name,
                        status="skipped",
                        expected=f"operator provides {name} evidence from a real SPIFFE/SPIRE + Envoy deployment",
                        actual=None,
                        missing_prerequisites=["archive missing artifact"],
                    )
                )
                continue
            actual = payload.get("payload") if isinstance(payload, dict) and payload.get("payload") is not None else payload
            live_checks.append(
                parse_check(
                    name=name,
                    status="ok",
                    expected=f"operator provides {name} evidence from a real SPIFFE/SPIRE + Envoy deployment",
                    actual=actual,
                )
            )
    else:
        if archive_path is not None:
            live_checks.append(
                parse_check(
                    name="live_spiffe_envoy_evidence_archive",
                    status="fail",
                    expected="operator provides a unified SPIFFE/SPIRE + Envoy live evidence archive",
                    actual={"path": str(archive_path), "exists": False},
                )
            )
        else:
            live_checks.append(
                parse_check(
                    name="live_spiffe_envoy_evidence_archive",
                    status="skipped",
                    expected="operator provides a unified SPIFFE/SPIRE + Envoy live evidence archive",
                    actual=None,
                    missing_prerequisites=["--live-evidence-archive"],
                )
            )
        live_inputs = {
            "live_positive_run": args.live_positive_report,
            "live_wrong_peer_reject": args.live_wrong_peer_report,
            "live_expired_svid_reject": args.live_expired_svid_report,
            "live_trust_bundle_reject": args.live_trust_bundle_reject_report,
            "live_envoy_access_log": args.live_envoy_access_log,
        }
        for name, raw in live_inputs.items():
            if not raw:
                live_checks.append(
                    parse_check(
                        name=name,
                        status="skipped",
                        expected=f"operator provides {name} evidence from a real SPIFFE/SPIRE + Envoy deployment",
                        actual=None,
                        missing_prerequisites=[f"--{name.replace('_', '-')}"],
                    )
                )
                continue
            path = Path(raw).resolve()
            if not path.is_file():
                live_checks.append(
                    parse_check(
                        name=name,
                        status="fail",
                        expected=f"operator provides {name} evidence from a real SPIFFE/SPIRE + Envoy deployment",
                        actual={"path": str(path), "exists": False},
                    )
                )
                continue
            payload = load_json(path) if path.suffix == ".json" else {"path": str(path), "exists": True}
            artifacts.append(artifact(path))
            live_checks.append(
                parse_check(
                    name=name,
                    status="ok",
                    expected=f"operator provides {name} evidence from a real SPIFFE/SPIRE + Envoy deployment",
                    actual=payload,
                )
            )

    repo_side_status = "ok" if all(item["status"] == "ok" for item in repo_side_checks) else "fail"
    concrete_live_names = {
        "live_positive_run",
        "live_wrong_peer_reject",
        "live_expired_svid_reject",
        "live_trust_bundle_reject",
        "live_envoy_access_log",
    }
    concrete_live = [item for item in live_checks if item["name"] in concrete_live_names]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in concrete_live)
        else "ok" if concrete_live and all(item["status"] == "ok" for item in concrete_live)
        else "skipped"
    )

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove the SPIFFE allowlist, SPIRE configs, Envoy templates, and rotation notes remain coherent as committed artifacts.",
            "They do not prove a real SPIFFE/SPIRE control plane exists, that Envoy SDS is live, or that peer SPIFFE ID enforcement succeeded on a real deployment.",
        ],
        "live_boundary": [
            "Live SPIFFE/SPIRE + Envoy readiness requires operator-provided evidence from a real deployment: positive run, wrong-peer reject, expired-SVID reject, trust-bundle reject, and Envoy access logs.",
            "When those artifacts are absent, this gate stays at live_status=skipped rather than claiming production-complete workload identity rollout.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "spiffe_envoy_identity_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
