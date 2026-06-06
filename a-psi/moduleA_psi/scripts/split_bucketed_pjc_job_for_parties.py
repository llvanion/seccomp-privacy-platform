#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _client_value_summary(path: Path) -> dict[str, Any]:
    values: list[int] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            if len(row) < 2:
                raise SystemExit(f"[ERROR] malformed client CSV row in {path}")
            values.append(int(str(row[1]).strip()))
    return {
        "sum": sum(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "non_negative": all(value >= 0 for value in values),
    }


def copy_role(job_dir: Path, out_dir: Path, role: str) -> None:
    meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
    commitment_path = job_dir / "input_commitments.json"
    commitment = json.loads(commitment_path.read_text(encoding="utf-8")) if commitment_path.is_file() else None
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
        if commitment is not None:
            sub_meta = _deepcopy_json(meta)
            sub_meta["bucket"]["outputs"] = [role_item]
            sub_meta["party_role"] = role
            sub_meta["split_from"] = str(job_dir)
            sub_meta["input_sizes"] = {
                "exposure_n": int(item.get("exposure_n") or 0),
                "purchase_n": int(item.get("purchase_n") or 0),
            }
            sub_commitment = _deepcopy_json(commitment)
            server_csv_src = src_sub / "server.csv"
            client_csv_src = src_sub / "client.csv"
            server_party = sub_commitment["parties"]["server"]
            client_party = sub_commitment["parties"]["client"]
            server_party["output_row_count"] = int(item.get("exposure_n") or 0)
            server_party["output_csv_sha256"] = sha256_file(server_csv_src)
            client_party["output_row_count"] = int(item.get("purchase_n") or 0)
            client_party["output_csv_sha256"] = sha256_file(client_csv_src)
            client_party["value_summary"] = _client_value_summary(client_csv_src)
            if role == "server":
                server_party["output_csv"] = str(dst_sub / "server.csv")
                client_party["output_csv"] = str(client_csv_src)
            else:
                server_party["output_csv"] = str(server_csv_src)
                client_party["output_csv"] = str(dst_sub / "client.csv")
            sub_commitment_path = dst_sub / "input_commitments.json"
            sub_meta["inputs"] = {
                "server_csv": str(dst_sub / "server.csv") if role == "server" else str(server_csv_src),
                "client_csv": str(dst_sub / "client.csv") if role == "client" else str(client_csv_src),
                "input_commitment_file": str(sub_commitment_path),
                "input_commitment_sha256": None,
            }
            sub_commitment_path.write_text(json.dumps(sub_commitment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            sub_meta["inputs"]["input_commitment_sha256"] = sha256_file(sub_commitment_path)
            (dst_sub / "job_meta.json").write_text(json.dumps(sub_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta["bucket"]["outputs"] = role_outputs
    meta["party_role"] = role
    meta["split_from"] = str(job_dir)
    if commitment is not None:
        flat_csv_name = "server.csv" if role == "server" else "client.csv"
        flat_csv_path = out_dir / flat_csv_name
        shutil.copy2(job_dir / flat_csv_name, flat_csv_path)
        role_commitment = _deepcopy_json(commitment)
        (out_dir / "input_commitments.json").write_text(json.dumps(role_commitment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        inputs = meta.get("inputs") if isinstance(meta.get("inputs"), dict) else {}
        inputs["input_commitment_file"] = str(out_dir / "input_commitments.json")
        inputs["input_commitment_sha256"] = sha256_file(out_dir / "input_commitments.json")
        inputs[f"{role}_csv"] = str(flat_csv_path)
        meta["inputs"] = inputs
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
