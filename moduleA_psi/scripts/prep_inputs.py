import argparse
import csv
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd


def hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def sha256_hex_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_server_csv(path: str, keys: Iterable[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k in keys:
            w.writerow([k])


def write_client_csv(path: str, rows: Iterable[Tuple[str, int]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k, v in rows:
            w.writerow([k, int(v)])


def in_window(ts: Optional[int], start_ts: Optional[int], end_ts: Optional[int]) -> bool:
    if ts is None:
        return True
    if start_ts is not None and ts < start_ts:
        return False
    if end_ts is not None and ts >= end_ts:
        return False
    return True


def euro_to_cents(v: float) -> int:
    dec = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(dec * 100)


def canonical_query_signature(payload: Dict) -> str:
    return sha256_hex_str(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def build_from_criteo_tsv(
    infile: str,
    out_dir: str,
    start_ts: Optional[int],
    end_ts: Optional[int],
    value_mode: str,
    hmac_secret: Optional[str],
    bucket_field: Optional[str],
    use_conversion_ts_for_purchase: bool,
    job_id: Optional[str],
    chunksize: int = 2_000_000,
) -> Dict:
    ensure_dir(out_dir)

    exposure_keys = set()
    purchase_map: Dict[str, int] = {}
    bucket_exposure: Dict[str, set] = {}
    bucket_purchase: Dict[str, Dict[str, int]] = {}

    def normalize_key(uid: str) -> str:
        uid = str(uid)
        return hmac_sha256_hex(hmac_secret, uid) if hmac_secret else uid

    colnames = [
        "Sale", "SalesAmountInEuro", "time_delay_for_conversion", "click_timestamp",
        "nb_clicks_1week", "product_price", "product_age_group", "device_type",
        "audience_id", "product_gender", "product_brand", "product_category1",
        "product_category2", "product_category3", "product_category4", "product_category5",
        "product_category6", "product_category7", "product_country", "product_id",
        "product_title", "partner_id", "user_id",
    ]

    reader = pd.read_csv(
        infile,
        sep="\t",
        header=None,
        names=colnames,
        dtype=str,
        chunksize=chunksize,
        engine="c",
    )

    total_rows = 0
    kept_exposure_rows = 0
    kept_purchase_rows = 0

    for chunk in reader:
        total_rows += len(chunk)
        click_ts = pd.to_numeric(chunk["click_timestamp"], errors="coerce").astype("Int64")
        sale = pd.to_numeric(chunk["Sale"], errors="coerce").fillna(0).astype(int)
        delay = pd.to_numeric(chunk["time_delay_for_conversion"], errors="coerce").fillna(-1).astype(int)
        amount = pd.to_numeric(chunk["SalesAmountInEuro"], errors="coerce").fillna(-1)

        mask = pd.Series(True, index=chunk.index)
        if start_ts is not None:
            mask &= (click_ts >= start_ts)
        if end_ts is not None:
            mask &= (click_ts < end_ts)

        chunk = chunk.loc[mask]
        click_ts = click_ts.loc[mask]
        sale = sale.loc[mask]
        delay = delay.loc[mask]
        amount = amount.loc[mask]

        for idx, row in chunk.iterrows():
            uid = row["user_id"]
            if uid is None or uid == "" or uid == "-1":
                continue
            key = normalize_key(uid)

            if key not in exposure_keys:
                exposure_keys.add(key)
                kept_exposure_rows += 1

            v: Optional[int] = None
            if int(sale.loc[idx]) == 1:
                if use_conversion_ts_for_purchase:
                    cts = int(click_ts.loc[idx]) + int(delay.loc[idx]) if int(delay.loc[idx]) >= 0 else int(click_ts.loc[idx])
                    if not in_window(cts, start_ts, end_ts):
                        continue

                if value_mode == "count":
                    v = 1
                elif value_mode == "amount":
                    v_raw = float(amount.loc[idx])
                    if v_raw < 0:
                        v_raw = 0.0
                    v = euro_to_cents(v_raw)
                else:
                    raise ValueError(f"Unsupported value_mode: {value_mode}")

                old = purchase_map.get(key)
                if old is None or v > old:
                    purchase_map[key] = v
                kept_purchase_rows += 1

            if bucket_field:
                b = row.get(bucket_field, None)
                if b is None or b == "" or b == "-1":
                    b = "__MISSING__"
                b = str(b)
                bucket_exposure.setdefault(b, set()).add(key)
                if v is not None:
                    bm = bucket_purchase.setdefault(b, {})
                    oldb = bm.get(key)
                    if oldb is None or v > oldb:
                        bm[key] = v

    outputs = []
    if bucket_field:
        for b, exp_set in bucket_exposure.items():
            sub = os.path.join(out_dir, f"bucket_{bucket_field}={b}")
            ensure_dir(sub)
            server_path = os.path.join(sub, "server.csv")
            client_path = os.path.join(sub, "client.csv")
            pur_map = bucket_purchase.get(b, {})
            write_server_csv(server_path, sorted(exp_set))
            write_client_csv(client_path, sorted(pur_map.items()))
            outputs.append({
                "bucket": b,
                "server_csv": server_path,
                "client_csv": client_path,
                "exposure_n": len(exp_set),
                "purchase_n": len(pur_map),
            })
    else:
        server_path = os.path.join(out_dir, "server.csv")
        client_path = os.path.join(out_dir, "client.csv")
        write_server_csv(server_path, sorted(exposure_keys))
        write_client_csv(client_path, sorted(purchase_map.items()))
        outputs.append({
            "bucket": None,
            "server_csv": server_path,
            "client_csv": client_path,
            "exposure_n": len(exposure_keys),
            "purchase_n": len(purchase_map),
        })

    resolved_job_id = job_id or os.path.basename(os.path.abspath(out_dir))
    sig_payload = {
        "dataset": "criteo_sponsored_search_conversion_log",
        "input_file": os.path.abspath(infile),
        "window_start": start_ts,
        "window_end": end_ts,
        "value_mode": value_mode,
        "bucket_field": bucket_field,
        "purchase_use_conversion_ts": use_conversion_ts_for_purchase,
        "dedup_exposure": "one_per_user_per_window",
        "dedup_purchase": "one_per_user_per_window_keep_max_value",
    }

    meta = {
        "job_id": resolved_job_id,
        "dataset": "criteo_sponsored_search_conversion_log",
        "input_file": os.path.abspath(infile),
        "window": {"start_ts": start_ts, "end_ts": end_ts},
        "window_start": start_ts,
        "window_end": end_ts,
        "window_semantics": {
            "exposure_ts": "click_timestamp",
            "purchase_ts": "conversion_ts(click_timestamp + time_delay_for_conversion)" if use_conversion_ts_for_purchase else "click_timestamp",
        },
        "dedup": {
            "exposure": "one_per_user_per_window",
            "purchase": "one_per_user_per_window_keep_max_value",
        },
        "value_mode": value_mode,
        "value_unit": "count" if value_mode == "count" else "euro_cent",
        "hmac": {"enabled": bool(hmac_secret)},
        "bucket_field": bucket_field,
        "bucket_count": len(outputs),
        "bucket": {"field": bucket_field, "outputs": outputs},
        "input_sizes": {
            "exposure_n": len(exposure_keys),
            "purchase_n": len(purchase_map),
        },
        "counts": {
            "total_rows_read": total_rows,
            "kept_exposure_rows": kept_exposure_rows,
            "kept_purchase_rows": kept_purchase_rows,
            "unique_exposure_users": len(exposure_keys),
            "unique_purchase_users": len(purchase_map),
        },
        "canonical_query_signature": canonical_query_signature(sig_payload),
        "generated_at_utc": utc_now_iso(),
    }

    with open(os.path.join(out_dir, "job_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteo-tsv", required=True, help="Path to CriteoSearchData TSV file.")
    ap.add_argument("--out", required=True, help="Output directory, e.g. runs/<job_id>")
    ap.add_argument("--start-ts", type=int, default=None, help="Window start timestamp (seconds).")
    ap.add_argument("--end-ts", type=int, default=None, help="Window end timestamp (seconds), exclusive.")
    ap.add_argument("--value-mode", choices=["count", "amount"], default="count")
    ap.add_argument("--hmac-secret", default=None, help="If set, HMAC-SHA256 anonymization is applied to user_id.")
    ap.add_argument("--bucket-field", default=None, help="Optional bucket field, e.g. partner_id.")
    ap.add_argument("--purchase-use-conversion-ts", action="store_true",
                    help="Use conversion_ts = click_timestamp + delay for purchase window filtering.")
    ap.add_argument("--job-id", default=None, help="Optional job identifier for metadata.")
    args = ap.parse_args()

    ensure_dir(args.out)
    meta = build_from_criteo_tsv(
        infile=args.criteo_tsv,
        out_dir=args.out,
        start_ts=args.start_ts,
        end_ts=args.end_ts,
        value_mode=args.value_mode,
        hmac_secret=args.hmac_secret,
        bucket_field=args.bucket_field,
        use_conversion_ts_for_purchase=args.purchase_use_conversion_ts,
        job_id=args.job_id,
    )
    print("OK. Wrote job_meta.json and PJC inputs under:", args.out)
    print("Summary:", json.dumps(meta["counts"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
