#!/usr/bin/env python3
"""J3-b: structurally validate a Prometheus alert-rules YAML file.

The validator does not connect to a running Prometheus or Alertmanager. It
parses the YAML (using PyYAML when available, otherwise a minimal indent-based
parser sufficient for the recovery-service rules format), confirms the presence
of required alert names, summarises group / alert / severity layout, and emits
a `prometheus_alert_rules_report/v1` report.

Operators still run `promtool check rules <file>` against the same file as part
of their Prometheus deployment workflow. This script is the cheap repo-side
check that runs in default contract smoke without any Prometheus install.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "prometheus_alert_rules_report/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_with_pyyaml(text: str) -> tuple[Any, str]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, "skipped"
    try:
        return yaml.safe_load(text), "ok"
    except Exception as exc:  # pragma: no cover - YAML parse errors are operator-side
        return None, f"fail: {exc}"


def parse_minimal_alert_rules(text: str) -> dict[str, Any]:
    """Indent-based parser tuned for the alert-rules.yml shape we emit.

    The full Prometheus rule file format is broader than this; the parser only
    extracts the fields we want to validate (groups[].name / interval / rules[]
    -> alert / for / labels.severity). Anything else is left alone.
    """
    groups: list[dict[str, Any]] = []
    current_group: dict[str, Any] | None = None
    current_rule: dict[str, Any] | None = None
    in_labels = False
    label_indent = -1
    for raw_line in text.splitlines():
        # Drop trailing comments unless inside a quoted string (we do not need
        # quoted-string handling for our limited grammar).
        if "#" in raw_line:
            in_string = False
            cleaned_chars: list[str] = []
            for ch in raw_line:
                if ch in ("'", '"'):
                    in_string = not in_string
                if ch == "#" and not in_string:
                    break
                cleaned_chars.append(ch)
            line = "".join(cleaned_chars).rstrip()
        else:
            line = raw_line.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if in_labels and indent <= label_indent:
            in_labels = False
            label_indent = -1
        if stripped.startswith("- alert:") and current_group is not None:
            if current_rule:
                current_group.setdefault("rules", []).append(current_rule)
            name = stripped[len("- alert:"):].strip()
            current_rule = {"name": name, "for": None, "severity": None}
            in_labels = False
            continue
        if stripped.startswith("- name:") and indent <= 2:
            if current_rule and current_group is not None:
                current_group.setdefault("rules", []).append(current_rule)
                current_rule = None
            if current_group:
                groups.append(current_group)
            current_group = {"name": stripped[len("- name:"):].strip(), "rules": [], "interval": None}
            in_labels = False
            continue
        if stripped.startswith("interval:") and current_group is not None and current_rule is None:
            current_group["interval"] = stripped[len("interval:"):].strip() or None
            continue
        if stripped.startswith("for:") and current_rule is not None:
            current_rule["for"] = stripped[len("for:"):].strip() or None
            continue
        if stripped.startswith("labels:") and current_rule is not None:
            in_labels = True
            label_indent = indent
            continue
        if in_labels and stripped.startswith("severity:") and current_rule is not None:
            current_rule["severity"] = stripped[len("severity:"):].strip() or None
            continue
    if current_rule and current_group is not None:
        current_group.setdefault("rules", []).append(current_rule)
    if current_group:
        groups.append(current_group)
    return {"groups": groups}


def required_alert_names() -> list[str]:
    return [
        "RecoveryServiceErrorRateHigh",
        "RecoveryServiceLatencyHigh",
        "RecoveryServiceNoTraffic",
        "RecoveryServiceRateLimitedSpike",
    ]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Structurally validate a Prometheus alert-rules YAML file (J3-b).")
    ap.add_argument("--rules", required=True, help="Path to the alert-rules.yml file")
    ap.add_argument(
        "--require-alert",
        action="append",
        default=[],
        help="Required alert name (repeatable); defaults to the recovery-service SLO alert set",
    )
    ap.add_argument("--output", default="", help="Optional output path for the JSON report")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    rules_path = Path(args.rules).resolve()
    if not rules_path.is_file():
        raise SystemExit(f"[ERROR] alert rules file not found: {rules_path}")

    text = rules_path.read_text(encoding="utf-8")
    yaml_doc, yaml_status = parse_with_pyyaml(text)

    errors: list[str] = []
    if yaml_doc is not None:
        if not isinstance(yaml_doc, dict) or "groups" not in yaml_doc:
            errors.append("YAML root must be a mapping with a 'groups' key")
            parsed = {"groups": []}
        else:
            groups_list = yaml_doc.get("groups") or []
            normalised_groups: list[dict[str, Any]] = []
            for group in groups_list:
                if not isinstance(group, dict):
                    errors.append("each group must be a mapping")
                    continue
                rules = group.get("rules") or []
                normalised_rules: list[dict[str, Any]] = []
                for rule in rules:
                    if not isinstance(rule, dict):
                        errors.append("each rule must be a mapping")
                        continue
                    if "alert" not in rule:
                        # Recording rules are valid but we only summarise alerts.
                        continue
                    severity = None
                    labels = rule.get("labels") if isinstance(rule.get("labels"), dict) else {}
                    severity = str(labels.get("severity") or "") or None
                    normalised_rules.append(
                        {
                            "name": str(rule.get("alert") or ""),
                            "for": str(rule.get("for") or "") or None,
                            "severity": severity,
                        }
                    )
                normalised_groups.append(
                    {
                        "name": str(group.get("name") or ""),
                        "interval": str(group.get("interval") or "") or None,
                        "rules": normalised_rules,
                    }
                )
            parsed = {"groups": normalised_groups}
    else:
        parsed = parse_minimal_alert_rules(text)
        if not parsed["groups"]:
            errors.append("no groups parsed from rules file")

    alerts: list[dict[str, Any]] = []
    groups_summary: list[dict[str, Any]] = []
    for group in parsed["groups"]:
        rule_alerts = [r for r in group.get("rules") or [] if r.get("name")]
        groups_summary.append(
            {
                "name": group.get("name") or "",
                "rule_count": len(rule_alerts),
                "interval": group.get("interval"),
            }
        )
        for rule in rule_alerts:
            alerts.append(
                {
                    "name": rule.get("name") or "",
                    "group": group.get("name") or "",
                    "severity": rule.get("severity"),
                    "for_window": rule.get("for"),
                }
            )

    required = list(args.require_alert) if args.require_alert else required_alert_names()
    alert_names = {a["name"] for a in alerts}
    missing = [name for name in required if name not in alert_names]

    # Check for obvious labels.severity gaps for any alerts that did get parsed.
    severity_gaps = [a["name"] for a in alerts if not a.get("severity")]
    if severity_gaps:
        errors.append(f"alerts missing labels.severity: {severity_gaps}")
    # Check for obvious for: window gaps.
    for_gaps = [a["name"] for a in alerts if not a.get("for_window")]
    if for_gaps:
        errors.append(f"alerts missing 'for' window: {for_gaps}")
    if missing:
        errors.append(f"required alerts missing from rules file: {missing}")

    status = "ok" if not errors else "fail"
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "status": status,
        "rules_path": str(rules_path),
        "yaml_round_trip": "ok" if yaml_status == "ok" else ("skipped" if yaml_status == "skipped" else "fail"),
        "groups": groups_summary,
        "alerts": alerts,
        "missing_alerts": missing,
        "errors": errors,
    }
    if not yaml_status.startswith(("ok", "skipped")):
        report["yaml_round_trip"] = "fail"

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

    if args.assert_ok and status != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
