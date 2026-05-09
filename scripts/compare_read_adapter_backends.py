#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_MODES = ("metadata_http_job",)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] expected JSON object: {path}")
    return payload


def mode_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("mode")): item for item in payload.get("modes") or [] if isinstance(item, dict)}


def p95(entry: dict[str, Any]) -> float | None:
    duration = ((entry.get("summary") or {}).get("duration_ms") or {}).get("p95")
    return float(duration) if isinstance(duration, (int, float)) else None


def successful(entry: dict[str, Any]) -> bool:
    summary = entry.get("summary") or {}
    return int(summary.get("failed_iterations") or 0) == 0 and int(summary.get("successful_iterations") or 0) > 0


def compare_reports(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    ratio_threshold: float,
    gate_modes: set[str],
) -> dict[str, Any]:
    if baseline.get("schema") != "read_adapter_benchmark/v1":
        raise SystemExit("[ERROR] baseline report is not read_adapter_benchmark/v1")
    if candidate.get("schema") != "read_adapter_benchmark/v1":
        raise SystemExit("[ERROR] candidate report is not read_adapter_benchmark/v1")

    baseline_modes = mode_map(baseline)
    candidate_modes = mode_map(candidate)
    common_modes = sorted(set(baseline_modes) & set(candidate_modes))
    missing_in_candidate = sorted(set(baseline_modes) - set(candidate_modes))
    missing_in_baseline = sorted(set(candidate_modes) - set(baseline_modes))

    comparisons: list[dict[str, Any]] = []
    exceeded_modes: list[str] = []
    failed_modes: list[str] = []
    for mode in common_modes:
        base_entry = baseline_modes[mode]
        cand_entry = candidate_modes[mode]
        base_p95 = p95(base_entry)
        cand_p95 = p95(cand_entry)
        ratio = round(cand_p95 / base_p95, 3) if base_p95 and cand_p95 is not None else None
        ok = (
            successful(base_entry)
            and successful(cand_entry)
            and ratio is not None
            and (mode not in gate_modes or ratio <= ratio_threshold)
        )
        if not successful(base_entry) or not successful(cand_entry) or ratio is None:
            failed_modes.append(mode)
        elif mode in gate_modes and ratio > ratio_threshold:
            exceeded_modes.append(mode)
        comparisons.append(
            {
                "mode": mode,
                "family": cand_entry.get("family") or base_entry.get("family"),
                "baseline_p95_ms": base_p95,
                "candidate_p95_ms": cand_p95,
                "p95_ratio": ratio,
                "ratio_threshold": ratio_threshold if mode in gate_modes else None,
                "gate_mode": mode in gate_modes,
                "within_threshold": ok,
                "baseline_successful": successful(base_entry),
                "candidate_successful": successful(cand_entry),
            }
        )

    missing_gate_modes = sorted(mode for mode in gate_modes if mode not in common_modes)
    if missing_gate_modes or failed_modes:
        status = "fail"
    elif exceeded_modes:
        status = "warn"
    else:
        status = "ok"

    return {
        "schema": "read_adapter_backend_comparison/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "baseline": {
            "backend": baseline.get("db_backend") or "unknown",
            "db_dsn_present": bool(baseline.get("db_dsn")),
            "fixture_profile": baseline.get("fixture_profile"),
            "fixture_job_id": baseline.get("fixture_job_id"),
            "iterations": baseline.get("iterations"),
        },
        "candidate": {
            "backend": candidate.get("db_backend") or "unknown",
            "db_dsn_present": bool(candidate.get("db_dsn")),
            "db_dsn_read_replica_present": bool(candidate.get("db_dsn_read_replica")),
            "fixture_profile": candidate.get("fixture_profile"),
            "fixture_job_id": candidate.get("fixture_job_id"),
            "iterations": candidate.get("iterations"),
        },
        "summary": {
            "status": status,
            "ratio_threshold": ratio_threshold,
            "gate_modes": sorted(gate_modes),
            "compared_mode_count": len(common_modes),
            "missing_in_candidate": missing_in_candidate,
            "missing_in_baseline": missing_in_baseline,
            "missing_gate_modes": missing_gate_modes,
            "failed_modes": failed_modes,
            "threshold_exceeded_modes": exceeded_modes,
            "missing_indexes_required": bool(exceeded_modes),
        },
        "comparisons": comparisons,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Compare read_adapter_benchmark/v1 reports across database backends.")
    ap.add_argument("--baseline", required=True, help="Baseline read_adapter_benchmark/v1 report, normally SQLite")
    ap.add_argument("--candidate", required=True, help="Candidate read_adapter_benchmark/v1 report, normally PostgreSQL")
    ap.add_argument("--ratio-threshold", type=float, default=2.0)
    ap.add_argument(
        "--gate-mode",
        action="append",
        default=[],
        help="Mode whose candidate p95 must stay within threshold. Defaults to metadata_http_job.",
    )
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.ratio_threshold <= 0:
        raise SystemExit("[ERROR] --ratio-threshold must be positive")
    gate_modes = set(args.gate_mode or DEFAULT_GATE_MODES)
    report = compare_reports(
        baseline=load_json(Path(args.baseline)),
        candidate=load_json(Path(args.candidate)),
        ratio_threshold=args.ratio_threshold,
        gate_modes=gate_modes,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = REPO_ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_ok and report["summary"]["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
