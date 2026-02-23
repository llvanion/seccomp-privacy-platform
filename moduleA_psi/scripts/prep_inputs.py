import argparse
import csv
import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Optional, Iterable, Dict, Tuple

import pandas as pd


def hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_ts(ts) -> Optional[int]:
    """Return int timestamp (seconds) if possible, else None."""
    if ts is None:
        return None
    try:
        # Some datasets store as int already
        v = int(ts)
        return v
    except Exception:
        return None


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_server_csv(path: str, keys: Iterable[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k in keys:
            w.writerow([k])


def write_client_csv(path: str, rows: Iterable[Tuple[str, float]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k, v in rows:
            w.writerow([k, v])


def in_window(ts: Optional[int], start_ts: Optional[int], end_ts: Optional[int]) -> bool:
    if ts is None:
        return True  # if no ts, don't filter
    if start_ts is not None and ts < start_ts:
        return False
    if end_ts is not None and ts >= end_ts:
        return False
    return True


def build_from_criteo_tsv(
    infile: str,
    out_dir: str,
    start_ts: Optional[int],
    end_ts: Optional[int],
    value_mode: str,
    hmac_secret: Optional[str],
    bucket_field: Optional[str],
    use_conversion_ts_for_purchase: bool,
    chunksize: int = 2_000_000,
) -> Dict:
    """
    Criteo Sponsored Search Conversion Log Dataset:
    Tab-separated with header:
    Sale, SalesAmountInEuro, time_delay_for_conversion, click_timestamp, ..., partner_id, user_id
    """
    ensure_dir(out_dir)

    # We'll store exposure keys and purchase rows (key, value) in sets/dicts to dedup.
    # Dedup rule: within window, keep at most one per user (exposure and purchase separately).
    exposure_keys = set()
    purchase_map: Dict[str, float] = {}

    # Bucket support: simplest implementation -> write separate subfolders per bucket
    # If bucket_field is provided, we build per-bucket structures.
    bucket_exposure: Dict[str, set] = {}
    bucket_purchase: Dict[str, Dict[str, float]] = {}

    def normalize_key(uid: str) -> str:
        uid = str(uid)
        if hmac_secret:
            return hmac_sha256_hex(hmac_secret, uid)
        return uid

    # CriteoSearchData is tab-separated WITHOUT a header row.
    # Columns are documented as:
    # Sale, SalesAmountInEuro, time_delay_for_conversion, click_timestamp,
    # nb_clicks_1week, product_price, product_age_group, device_type,
    # audience_id, product_gender, product_brand, product_category(1-7),
    # product_country, product_id, product_title, partner_id, user_id
    colnames = [
        "Sale",
        "SalesAmountInEuro",
        "time_delay_for_conversion",
        "click_timestamp",
        "nb_clicks_1week",
        "product_price",
        "product_age_group",
        "device_type",
        "audience_id",
        "product_gender",
        "product_brand",
        "product_category1",
        "product_category2",
        "product_category3",
        "product_category4",
        "product_category5",
        "product_category6",
        "product_category7",
        "product_country",
        "product_id",
        "product_title",
        "partner_id",
        "user_id",
    ]

    reader = pd.read_csv(
        infile,
        sep="\t",
        header=None,          # IMPORTANT: no header row
        names=colnames,       # assign names manually
        dtype=str,
        chunksize=chunksize,
        engine="c",
    )

    total_rows = 0
    kept_exposure_rows = 0
    kept_purchase_rows = 0

    for chunk in reader:
        total_rows += len(chunk)

        # Required columns
        # user_id, click_timestamp, Sale, SalesAmountInEuro, time_delay_for_conversion
        for col in ["user_id", "click_timestamp", "Sale", "SalesAmountInEuro", "time_delay_for_conversion"]:
            if col not in chunk.columns:
                raise ValueError(f"Missing required column '{col}'. Found: {list(chunk.columns)[:20]}...")

        # Parse timestamps to int
        click_ts = pd.to_numeric(chunk["click_timestamp"], errors="coerce").astype("Int64")
        sale = pd.to_numeric(chunk["Sale"], errors="coerce").fillna(0).astype(int)
        delay = pd.to_numeric(chunk["time_delay_for_conversion"], errors="coerce").fillna(-1).astype(int)
        amount = pd.to_numeric(chunk["SalesAmountInEuro"], errors="coerce").fillna(-1)

        # Exposure window filter (by click_timestamp)
        # IMPORTANT: mask must be a boolean Series, not a python bool.
        in_win_mask = pd.Series(True, index=chunk.index)

        if start_ts is not None:
            in_win_mask &= (click_ts >= start_ts)
        if end_ts is not None:
            in_win_mask &= (click_ts < end_ts)

        chunk = chunk.loc[in_win_mask]
        click_ts = click_ts.loc[in_win_mask]
        sale = sale.loc[in_win_mask]
        delay = delay.loc[in_win_mask]
        amount = amount.loc[in_win_mask]

        # Iterate rows (vectorize would be faster but this is simpler + still ok with chunks)
        for idx, row in chunk.iterrows():
            uid = row["user_id"]
            if uid is None or uid == "" or uid == "-1":
                continue
            key = normalize_key(uid)

            # Exposure dedup: keep one per key
            if key not in exposure_keys:
                exposure_keys.add(key)
                kept_exposure_rows += 1

            # Purchase side: only Sale==1
            if int(sale.loc[idx]) == 1:
                # Optional purchase timestamp filter can be based on conversion_ts
                if use_conversion_ts_for_purchase:
                    cts = int(click_ts.loc[idx]) + int(delay.loc[idx]) if int(delay.loc[idx]) >= 0 else int(click_ts.loc[idx])
                    if not in_window(cts, start_ts, end_ts):
                        continue

                # value_mode
                if value_mode == "count":
                    v = 1
                elif value_mode == "amount":
                    v_raw = float(amount.loc[idx])
                    if v_raw < 0:
                        # Shouldn't happen for Sale=1, but keep robust
                        v_raw = 0.0
                    v = v_raw
                else:
                    raise ValueError(f"Unsupported value_mode: {value_mode}")

                # Purchase dedup: one per key; if multiple, keep max (or sum). Here choose max.
                # (You can switch to sum if you want "total order amount per user".)
                old = purchase_map.get(key)
                if old is None or v > old:
                    purchase_map[key] = v
                kept_purchase_rows += 1

            # Bucket handling
            if bucket_field:
                b = row.get(bucket_field, None)
                if b is None or b == "" or b == "-1":
                    b = "__MISSING__"
                b = str(b)

                bucket_exposure.setdefault(b, set()).add(key)

                if int(sale.loc[idx]) == 1:
                    bm = bucket_purchase.setdefault(b, {})
                    oldb = bm.get(key)
                    if oldb is None or v > oldb:
                        bm[key] = v

    # If bucket_field provided, write per bucket subdir; else write single pair
    outputs = []
    if bucket_field:
        for b, exp_set in bucket_exposure.items():
            sub = os.path.join(out_dir, f"bucket_{bucket_field}={b}")
            ensure_dir(sub)
            server_path = os.path.join(sub, "server.csv")
            client_path = os.path.join(sub, "client.csv")
            write_server_csv(server_path, sorted(exp_set))
            pur_map = bucket_purchase.get(b, {})
            write_client_csv(client_path, sorted(pur_map.items()))
            outputs.append({"bucket": b, "server_csv": server_path, "client_csv": client_path,
                            "exposure_n": len(exp_set), "purchase_n": len(pur_map)})
    else:
        server_path = os.path.join(out_dir, "server.csv")
        client_path = os.path.join(out_dir, "client.csv")
        write_server_csv(server_path, sorted(exposure_keys))
        write_client_csv(client_path, sorted(purchase_map.items()))
        outputs.append({"bucket": None, "server_csv": server_path, "client_csv": client_path,
                        "exposure_n": len(exposure_keys), "purchase_n": len(purchase_map)})

    meta = {
        "dataset": "criteo_sponsored_search_conversion_log",
        "input_file": os.path.abspath(infile),
        "window": {"start_ts": start_ts, "end_ts": end_ts},
        "window_semantics": {
            "exposure_ts": "click_timestamp",
            "purchase_ts": "conversion_ts(click_timestamp + time_delay_for_conversion)" if use_conversion_ts_for_purchase else "click_timestamp",
        },
        "dedup": {
            "exposure": "one_per_user_per_window",
            "purchase": "one_per_user_per_window_keep_max_value",
        },
        "value_mode": value_mode,
        "hmac": {"enabled": bool(hmac_secret)},
        "bucket": {"field": bucket_field, "outputs": outputs},
        "counts": {
            "total_rows_read": total_rows,
            "unique_exposure_users": len(exposure_keys),
            "unique_purchase_users": len(purchase_map),
        },
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    }

    with open(os.path.join(out_dir, "job_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteo-tsv", required=True, help="Path to CriteoSearchData (tab-separated) file.")
    ap.add_argument("--out", required=True, help="Output directory, e.g. runs/<job_id>")
    ap.add_argument("--start-ts", type=int, default=None, help="Window start timestamp (seconds).")
    ap.add_argument("--end-ts", type=int, default=None, help="Window end timestamp (seconds), exclusive.")
    ap.add_argument("--value-mode", choices=["count", "amount"], default="count")
    ap.add_argument("--hmac-secret", default=None, help="If set, HMAC-SHA256 anonymization applied to user_id.")
    ap.add_argument("--bucket-field", default=None, help="Optional bucket field, e.g. partner_id or product_category(1-7).")
    ap.add_argument("--purchase-use-conversion-ts", action="store_true",
                    help="If set, purchase window filtering uses conversion_ts = click_timestamp + delay.")
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
    )
    print("OK. Wrote job_meta.json and PJC inputs under:", args.out)
    print("Summary:", json.dumps(meta["counts"], indent=2))


if __name__ == "__main__":
    main()