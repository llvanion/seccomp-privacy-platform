#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def copy_role(job_dir: Path, out_dir: Path, role: str) -> None:
    meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
    bucket = meta.get("bucket") or {}
    field = bucket.get("field")
    outputs = bucket.get("outputs") or []
    if not field or not outputs:
        raise SystemExit(f"[ERROR] {job_dir} is not a bucketed PJC job")
    out_dir.mkdir(parents=True, exist_ok=True)
    role_outputs: list[dict[str, Any]] = []
    for item in outputs:
        value = str(item.get("bucket"))
        src_sub = job_dir / f"bucket_{field}={value}"
        dst_sub = out_dir / f"bucket_{field}={value}"
        dst_sub.mkdir(parents=True, exist_ok=True)
        role_item = {k: v for k, v in item.items() if k not in {"server_csv", "client_csv"}}
        if role == "server":
            shutil.copy2(src_sub / "server.csv", dst_sub / "server.csv")
            role_item["server_csv"] = str(dst_sub / "server.csv")
        else:
            shutil.copy2(src_sub / "client.csv", dst_sub / "client.csv")
            role_item["client_csv"] = str(dst_sub / "client.csv")
        role_outputs.append(role_item)
    meta["bucket"]["outputs"] = role_outputs
    meta["party_role"] = role
    meta["split_from"] = str(job_dir)
    (out_dir / "job_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("expected_result.json",):
        src = job_dir / name
        if src.is_file():
            shutil.copy2(src, out_dir / name)


def main() -> int:
    ap = argparse.ArgumentParser(description="Split a synthetic bucketed PJC job into Party A and Party B role directories.")
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--party-a-out", default="")
    ap.add_argument("--party-b-out", default="")
    args = ap.parse_args()
    job_dir = Path(args.job_dir).expanduser().resolve()
    party_a = Path(args.party_a_out).expanduser().resolve() if args.party_a_out else job_dir / "party_a_job"
    party_b = Path(args.party_b_out).expanduser().resolve() if args.party_b_out else job_dir / "party_b_job"
    copy_role(job_dir, party_a, "server")
    copy_role(job_dir, party_b, "client")
    print(f"[ok] Party A job dir: {party_a}")
    print(f"[ok] Party B job dir: {party_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
