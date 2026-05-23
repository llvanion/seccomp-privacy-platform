# -*- coding:utf-8 _*-
import argparse
import json
import os
import sys
from pathlib import Path

from services.record_recovery.bootstrap import ensure_repo_paths
from services.record_recovery.common import (
    build_result,
    enforce_row_limits,
    parse_candidate_payload,
    select_bridge_rows,
    write_selected_rows,
)


ensure_repo_paths()

from services.record_recovery.encrypted_record_store import iter_candidate_rows  # noqa: E402


def parse_stdin_payload(*, max_candidate_ids: int = 0) -> tuple[set[str], list[tuple[str, str]]]:
    return parse_candidate_payload(json.load(sys.stdin), max_candidate_ids=max_candidate_ids)


def main() -> int:
    ap = argparse.ArgumentParser(description="Controlled encrypted record-store recovery worker for bridge handoff.")
    ap.add_argument("--record-store-path", required=True)
    ap.add_argument("--record-store-key-env", required=True)
    ap.add_argument("--out-path", required=True)
    ap.add_argument("--out-format", choices=["jsonl", "csv"], default="csv")
    ap.add_argument("--role", choices=["server", "client"], required=True)
    ap.add_argument("--join-key-field", required=True)
    ap.add_argument("--value-field", default="")
    ap.add_argument("--min-output-rows", type=int, default=None)
    ap.add_argument("--max-output-rows", type=int, default=None)
    ap.add_argument("--max-candidate-ids", type=int,
                    default=int(os.environ.get("RECORD_RECOVERY_MAX_CANDIDATE_IDS", "0") or "0"),
                    help="Hard cap on inbound candidate_ids length (0 = unlimited)")
    args = ap.parse_args()

    if args.role == "client" and not args.value_field:
        raise SystemExit("[ERROR] --value-field is required for client role")

    try:
        candidate_ids, filters = parse_stdin_payload(max_candidate_ids=args.max_candidate_ids)
        rows = iter_candidate_rows(
            store_path=Path(args.record_store_path),
            key_env=args.record_store_key_env,
            candidate_ids=candidate_ids,
        )
        input_rows, selected_rows = select_bridge_rows(
            rows=rows,
            role=args.role,
            join_key_field=args.join_key_field,
            value_field=args.value_field,
            filters=filters,
        )
        enforce_row_limits(
            output_rows=len(selected_rows),
            min_rows=args.min_output_rows,
            max_rows=args.max_output_rows,
        )
        output_sha256 = write_selected_rows(
            rows=selected_rows,
            out_path=Path(args.out_path),
            out_format=args.out_format,
            role=args.role,
            join_key_field=args.join_key_field,
            value_field=args.value_field,
        )
        result = build_result(
            input_rows=input_rows,
            output_rows=len(selected_rows),
            output_sha256=output_sha256,
            candidate_count=len(candidate_ids),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        raise SystemExit(f"[ERROR] record recovery worker failed: {e}") from e


if __name__ == "__main__":
    raise SystemExit(main())
