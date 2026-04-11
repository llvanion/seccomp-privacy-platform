from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from ad_client.adapters.gateway.http_gateway_adapter import GatewayRequestError
from ad_client.app.bootstrap import build_advertiser_client_service


def _print_output(data: dict[str, Any], output: str) -> None:
    if output == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    if "user_id" not in record:
        raise ValueError("each exposure record must contain user_id")
    normalized = {"user_id": str(record["user_id"])}
    if record.get("timestamp") not in (None, ""):
        normalized["timestamp"] = int(record["timestamp"])
    if record.get("tag") not in (None, ""):
        normalized["tag"] = str(record["tag"])
    labels = record.get("labels")
    if isinstance(labels, dict) and labels:
        normalized["labels"] = labels
    for key, value in record.items():
        if key in {"user_id", "timestamp", "tag", "labels"} or value in (None, ""):
            continue
        normalized[key] = value
    return normalized


def _load_exposure_records(path_str: str) -> list[dict[str, Any]]:
    path = Path(path_str)
    if not path.exists():
        raise ValueError(f"exposure file not found: {path}")
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("JSON exposure file must contain an array")
        return [_normalize_record(item) for item in value]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [_normalize_record(row) for row in reader]
    raise ValueError("unsupported exposure file type, use .json or .csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ad-client-cli", description="Advertiser PSI client")
    parser.add_argument("--gateway-base-url", default=None, help="Gateway base URL")
    parser.add_argument("--timeout", type=int, default=None, help="Request timeout seconds")
    parser.add_argument("--output", choices=["json", "table"], default="json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")

    psi_run = sub.add_parser("psi-run")
    psi_run.add_argument("--job-id", required=True)
    psi_run.add_argument("--start-ts", required=True, type=int)
    psi_run.add_argument("--end-ts", required=True, type=int)
    psi_run.add_argument("--caller", required=True)
    psi_run.add_argument("--exposure-file", required=True, help="JSON or CSV file with exposure records")
    psi_run.add_argument("--bucket-by", default=None, help="Optional bucket field, e.g. tag")
    psi_run.add_argument("--k", type=int, default=20)
    psi_run.add_argument("--n", type=int, default=5)
    psi_run.add_argument("--value-mode", default="count")
    psi_run.add_argument("--out-dir", default=None)

    psi_result = sub.add_parser("psi-result")
    psi_result.add_argument("--job-id", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _, service = build_advertiser_client_service(
        gateway_base_url=args.gateway_base_url,
        timeout_seconds=args.timeout,
    )

    try:
        if args.command == "health":
            result = service.health()
        elif args.command == "psi-run":
            exposure_records = _load_exposure_records(args.exposure_file)
            psi_result = service.run_psi(
                job_id=args.job_id,
                start_ts=args.start_ts,
                end_ts=args.end_ts,
                caller=args.caller,
                exposure_records=exposure_records,
                k=args.k,
                n=args.n,
                value_mode=args.value_mode,
                bucket_by=args.bucket_by,
                out_dir=args.out_dir,
            )
            result = {
                "job_id": psi_result.job_id,
                "released": psi_result.released,
                "reason_code": psi_result.reason_code,
                "report": psi_result.report,
            }
        elif args.command == "psi-result":
            psi_result = service.get_result(args.job_id)
            result = {
                "job_id": psi_result.job_id,
                "released": psi_result.released,
                "reason_code": psi_result.reason_code,
                "report": psi_result.report,
            }
        else:
            parser.print_help()
            return 2
    except (GatewayRequestError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    _print_output(result, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
