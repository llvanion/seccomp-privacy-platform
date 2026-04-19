import argparse
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple


# ---------- basic utils ----------

def ensure_dir(path: str) -> None:
    if path:
        os.makedirs(path, exist_ok=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_iso8601_utc(ts: str) -> datetime:
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sha256_hex_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_hex_str(s: str) -> str:
    return sha256_hex_bytes(s.encode("utf-8"))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json_if_exists(path: Optional[str]) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    return load_json(path)


def try_get(d: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        if k in d:
            return d[k]
    return default


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def cents_to_eur_str(cents: int) -> str:
    eur = (Decimal(int(cents)) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(eur, "f")


# ---------- path resolution ----------

def resolve_paths(args: argparse.Namespace) -> Dict[str, str]:
    if args.job_dir:
        job_dir = os.path.abspath(args.job_dir)
        return {
            "job_dir": job_dir,
            "input": os.path.join(job_dir, "attribution_result.json"),
            "job_meta": os.path.join(job_dir, "job_meta.json"),
            "out": os.path.join(job_dir, "public_report.json"),
            "audit_log": args.audit_log or os.path.join(job_dir, "audit_log.jsonl"),
        }

    if not args.input or not args.out:
        raise SystemExit("Either --job-dir OR both --input and --out must be provided")

    return {
        "job_dir": os.path.dirname(os.path.abspath(args.out)) or ".",
        "input": os.path.abspath(args.input),
        "job_meta": os.path.abspath(args.job_meta) if args.job_meta else "",
        "out": os.path.abspath(args.out),
        "audit_log": os.path.abspath(args.audit_log or "runs/audit_log.jsonl"),
    }


# ---------- parse PJC result ----------

def parse_pjc_result(result: Dict[str, Any]) -> Dict[str, Optional[int]]:
    size = try_get(result, "intersection_size", "size", default=None)
    total = try_get(result, "intersection_sum", "sum", default=None)

    if size is None or total is None:
        payload = try_get(result, "result", "output", "metrics", default={})
        if isinstance(payload, dict):
            if size is None:
                size = try_get(payload, "intersection_size", "size", default=None)
            if total is None:
                total = try_get(payload, "intersection_sum", "sum", default=None)

    def to_int(x):
        if x is None:
            return None
        try:
            return int(x)
        except Exception:
            return None

    return {
        "intersection_size": to_int(size),
        "intersection_sum": to_int(total),
    }


# ---------- metadata ----------

def normalize_window(job_meta: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "start": try_get(job_meta, "window_start", "start", "start_ts", default=None),
        "end": try_get(job_meta, "window_end", "end", "end_ts", default=None),
    }


def extract_input_sizes(job_meta: Dict[str, Any]) -> Dict[str, Optional[int]]:
    def to_int(x):
        if x is None:
            return None
        try:
            return int(x)
        except Exception:
            return None

    nested = try_get(job_meta, "input_sizes", default={})
    if not isinstance(nested, dict):
        nested = {}

    exposure_n = try_get(
        nested,
        "exposure_n",
        default=try_get(job_meta, "exposure_n", "server_input_size", "server_size", default=None),
    )
    purchase_n = try_get(
        nested,
        "purchase_n",
        default=try_get(job_meta, "purchase_n", "client_input_size", "client_size", default=None),
    )

    return {
        "exposure_n": to_int(exposure_n),
        "purchase_n": to_int(purchase_n),
    }


def extract_bridge_meta(job_meta: Dict[str, Any]) -> Dict[str, Any]:
    bridge = try_get(job_meta, "bridge", default={})
    if not isinstance(bridge, dict):
        bridge = {}

    server = bridge.get("server", {})
    client = bridge.get("client", {})
    if not isinstance(server, dict):
        server = {}
    if not isinstance(client, dict):
        client = {}

    return {
        "enabled": bool(bridge),
        "token_scheme": bridge.get("token_scheme"),
        "token_scope": bridge.get("token_scope"),
        "token_key_version": bridge.get("token_key_version"),
        "normalize_version": bridge.get("normalize_version"),
        "dedup_policy": bridge.get("dedup_policy"),
        "server_join_key_column": server.get("join_key_column"),
        "client_join_key_column": client.get("join_key_column"),
        "client_value_column": client.get("value_column"),
        "client_value_mode": client.get("value_mode"),
        "server_normalizer": server.get("normalizer"),
        "client_normalizer": client.get("normalizer"),
    }


def extract_value_mode(job_meta: Dict[str, Any]) -> Optional[str]:
    value_mode = try_get(job_meta, "value_mode", default=None)
    if value_mode:
        return value_mode
    bridge = try_get(job_meta, "bridge", default={})
    if isinstance(bridge, dict):
        client = bridge.get("client", {})
        if isinstance(client, dict):
            bridge_value_mode = client.get("value_mode")
            value_column = str(client.get("value_column") or "").strip().lower()
            if bridge_value_mode == "raw_int" and value_column in {"amount", "amount_cents"}:
                return "amount"
            if bridge_value_mode == "raw_int":
                return "raw_int"
            if bridge_value_mode == "count":
                return "count"
    return None


def canonical_query_payload(
    caller: str,
    job_id: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    threshold_k: int,
    max_queries: int,
) -> Dict[str, Any]:
    return {
        "caller": caller,
        "job_id": job_id,
        "window_start": window.get("start"),
        "window_end": window.get("end"),
        "bucket": bucket,
        "threshold_k": threshold_k,
        "max_queries": max_queries,
    }


def canonical_query_signature(payload: Dict[str, Any]) -> str:
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex_str(msg)


# ---------- auth and anti-replay ----------

@dataclass
class AuthResult:
    ok: bool
    caller: Optional[str]
    key_id: Optional[str]
    reason_code: str
    reason: str
    signed_message: Optional[str] = None


def load_auth_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    cfg = load_json(path)
    if not isinstance(cfg, dict):
        raise ValueError("auth config must be a JSON object")
    return cfg


def build_signed_message(
    *,
    key_id: str,
    caller: str,
    timestamp: str,
    nonce: str,
    job_id: Optional[str],
    query_sig: str,
) -> str:
    parts = [
        "policy_release_v1",
        key_id,
        caller,
        timestamp,
        nonce,
        job_id or "",
        query_sig,
    ]
    return "\n".join(parts)


def seen_nonce_before(audit_log_path: str, key_id: str, nonce: str) -> bool:
    if not os.path.exists(audit_log_path):
        return False
    with open(audit_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            auth = rec.get("auth", {})
            if auth.get("key_id") == key_id and auth.get("nonce") == nonce:
                return True
    return False


def authenticate_request(
    *,
    caller_arg: Optional[str],
    auth_required: bool,
    auth_config: Dict[str, Any],
    key_id: Optional[str],
    timestamp: Optional[str],
    nonce: Optional[str],
    signature: Optional[str],
    audit_log_path: str,
    max_clock_skew_sec: int,
    job_id: Optional[str],
    query_sig: str,
) -> AuthResult:
    if not auth_required and not auth_config:
        caller = caller_arg or "local_demo"
        return AuthResult(True, caller, None, "auth_disabled", "authentication disabled for local/demo mode")

    if not key_id or not timestamp or not nonce or not signature:
        return AuthResult(False, None, key_id, "missing_auth_fields", "missing one of key-id/timestamp/nonce/signature")

    principal = auth_config.get(key_id)
    if not isinstance(principal, dict):
        return AuthResult(False, None, key_id, "unknown_key_id", "unknown key id")

    if not principal.get("enabled", True):
        return AuthResult(False, None, key_id, "key_disabled", "key disabled")

    caller = principal.get("caller")
    secret = principal.get("secret")
    if not caller or not secret:
        return AuthResult(False, None, key_id, "bad_auth_config", "auth config missing caller/secret")

    if caller_arg and caller_arg != caller:
        return AuthResult(False, None, key_id, "caller_mismatch", f"caller mismatch: arg={caller_arg} config={caller}")

    try:
        ts_dt = parse_iso8601_utc(timestamp)
    except Exception:
        return AuthResult(False, None, key_id, "bad_timestamp", "timestamp is not valid ISO8601 UTC")

    skew = abs((utc_now() - ts_dt).total_seconds())
    if skew > max_clock_skew_sec:
        return AuthResult(False, None, key_id, "timestamp_out_of_window", f"timestamp skew too large: {int(skew)}s > {max_clock_skew_sec}s")

    if seen_nonce_before(audit_log_path, key_id, nonce):
        return AuthResult(False, None, key_id, "replay_detected", "nonce already seen for this key id")

    msg = build_signed_message(
        key_id=key_id,
        caller=caller,
        timestamp=timestamp,
        nonce=nonce,
        job_id=job_id,
        query_sig=query_sig,
    )
    expected = hmac_sha256_hex(secret, msg)
    if not hmac.compare_digest(expected, signature.lower()):
        return AuthResult(False, None, key_id, "bad_signature", "HMAC verification failed")

    return AuthResult(True, caller, key_id, "auth_ok", "authenticated", signed_message=msg)


# ---------- rate limit ----------

def count_prior_requests(audit_log_path: str, caller: str, window: Dict[str, Optional[str]]) -> int:
    if not os.path.exists(audit_log_path):
        return 0
    count = 0
    with open(audit_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            if rec.get("event") != "policy_release":
                continue
            if rec.get("caller") != caller:
                continue
            w = rec.get("window", {})
            if w.get("start") == window.get("start") and w.get("end") == window.get("end"):
                count += 1
    return count


def apply_rate_limit(audit_log_path: str, caller: str, window: Dict[str, Optional[str]], max_queries: int) -> Dict[str, Any]:
    used = count_prior_requests(audit_log_path, caller, window)
    allowed = used < max_queries
    return {
        "allowed": allowed,
        "used": used,
        "max": max_queries,
        "reason_code": "ok" if allowed else "rate_limit_exceeded",
        "reason": "ok" if allowed else f"rate limit exceeded ({used} >= {max_queries})",
    }


def seen_query_signature(audit_log_path: str, caller: str, query_sig: str) -> bool:
    if not os.path.exists(audit_log_path):
        return False
    with open(audit_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "policy_release":
                continue
            if rec.get("caller") != caller:
                continue
            if rec.get("canonical_query_signature") == query_sig:
                return True
    return False


# ---------- release policy ----------

def apply_threshold_policy(metrics: Dict[str, Optional[int]], threshold_k: int, round_sum_to: Optional[int]) -> Dict[str, Any]:
    size = metrics.get("intersection_size")
    total = metrics.get("intersection_sum")

    if size is None or total is None:
        return {
            "decision": "deny",
            "reason_code": "missing_metrics",
            "reason": "missing required metrics",
            "released": None,
        }

    if size < threshold_k:
        return {
            "decision": "deny",
            "reason_code": "below_k",
            "reason": f"intersection_size below threshold ({size} < {threshold_k})",
            "released": None,
        }

    released_sum = total
    if round_sum_to is not None and round_sum_to > 1:
        released_sum = int(round(total / round_sum_to) * round_sum_to)

    return {
        "decision": "allow",
        "reason_code": "threshold_passed",
        "reason": "threshold passed",
        "released": {
            "intersection_size": size,
            "intersection_sum": released_sum,
            "intersection_sum_raw": total,
        },
    }


# ---------- report builders ----------

def decorate_released_value(released: Optional[Dict[str, Any]], value_mode: Optional[str]) -> Optional[Dict[str, Any]]:
    if released is None:
        return None
    out = dict(released)
    if value_mode == "amount" and "intersection_sum" in out and out.get("intersection_sum") is not None:
        cents = int(out["intersection_sum"])
        out["intersection_sum_cents"] = cents
        out["intersection_sum_eur"] = cents_to_eur_str(cents)
        out["intersection_sum"] = out["intersection_sum_eur"]
    return out


def build_public_report(
    *,
    policy_version: str,
    job_id: Optional[str],
    caller: str,
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    bridge_meta: Dict[str, Any],
    input_sizes: Dict[str, Optional[int]],
    threshold_k: int,
    rate_limit_out: Dict[str, Any],
    policy_out: Dict[str, Any],
) -> Dict[str, Any]:
    released = decorate_released_value(policy_out.get("released"), value_mode)

    conversions = None
    value_sum = None
    aov = None
    if released is not None:
        conversions = released.get("intersection_size")
        if value_mode == "amount":
            value_sum = released.get("intersection_sum_eur") or released.get("intersection_sum")
            raw = released.get("intersection_sum_cents")
            if conversions and raw is not None and conversions > 0:
                average_cents = (
                    Decimal(int(raw)) / Decimal(int(conversions))
                ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                aov = cents_to_eur_str(int(average_cents))
        else:
            value_sum = released.get("intersection_sum")
            if conversions and value_sum is not None and conversions > 0:
                aov = value_sum / conversions

    full_report = {
        "schema": "public_report/v2",
        "generated_at_utc": utc_now_iso(),
        "policy_version": policy_version,
        "job_id": job_id,
        "correlation_id": job_id,
        "caller": caller,
        "window": window,
        "bucket": bucket,
        "value_mode": value_mode,
        "bridge": bridge_meta if bridge_meta.get("enabled") else None,
        "input_sizes": input_sizes,
        "released": policy_out["decision"] == "allow",
        "reason": policy_out["reason"],
        "reason_code": policy_out["reason_code"],
        "k_threshold": threshold_k,
        "rate_limit_used": rate_limit_out["used"],
        "rate_limit_max": rate_limit_out["max"],
        "conversions": conversions,
        "value_sum": value_sum,
        "aov": aov,
        "details": released,
    }

    # allow: return full report
    if full_report["released"]:
        return full_report

    # deny: return slim public report
    return {
        "schema": full_report["schema"],
        "generated_at_utc": full_report["generated_at_utc"],
        "policy_version": full_report["policy_version"],
        "job_id": full_report["job_id"],
        "correlation_id": full_report["correlation_id"],
        "caller": full_report["caller"],
        "released": False,
        "reason": full_report["reason"],
        "reason_code": full_report["reason_code"],
        "window": full_report["window"],   # 可选；如果你想更保守，可以删掉这一行
        "k_threshold": full_report["k_threshold"],
    }


def build_audit_record(
    *,
    policy_version: str,
    job_id: Optional[str],
    caller: str,
    key_id: Optional[str],
    timestamp: Optional[str],
    nonce: Optional[str],
    query_sig: str,
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    bridge_meta: Dict[str, Any],
    input_sizes: Dict[str, Optional[int]],
    input_path: str,
    out_path: str,
    threshold_k: int,
    round_sum_to: Optional[int],
    rate_limit_out: Dict[str, Any],
    metrics: Dict[str, Optional[int]],
    policy_out: Dict[str, Any],
    auth_result: AuthResult,
) -> Dict[str, Any]:
    input_sha256 = sha256_file(input_path)
    return {
        "ts_utc": utc_now_iso(),
        "event": "policy_release",
        "policy_version": policy_version,
        "job_id": job_id,
        "correlation_id": job_id,
        "caller": caller,
        "window": window,
        "bucket": bucket,
        "value_mode": value_mode,
        "bridge": bridge_meta if bridge_meta.get("enabled") else None,
        "input_sizes": input_sizes,
        "input_file": os.path.abspath(input_path),
        "input_sha256": input_sha256,
        "pjc_result_file": os.path.abspath(input_path),
        "pjc_result_sha256": input_sha256,
        "release_file": os.path.abspath(out_path),
        "release_sha256": sha256_file(out_path) if os.path.exists(out_path) else None,
        "threshold_k": threshold_k,
        "round_sum_to": round_sum_to,
        "rate_limit_used": rate_limit_out["used"],
        "rate_limit_max": rate_limit_out["max"],
        "canonical_query_signature": query_sig,
        "parsed_metrics": metrics,
        "decision": policy_out["decision"],
        "reason": policy_out["reason"],
        "reason_code": policy_out["reason_code"],
        "released": policy_out.get("released"),
        "auth": {
            "mode": "hmac" if key_id else "disabled_or_caller_only",
            "key_id": key_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "auth_ok": auth_result.ok,
            "auth_reason_code": auth_result.reason_code,
        },
    }


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="W2 policy release with threshold/rate-limit/audit and optional HMAC anti-replay")
    ap.add_argument("--job-dir", default=None, help="Job dir containing attribution_result.json and job_meta.json")
    ap.add_argument("--input", default=None, help="Path to attribution_result.json")
    ap.add_argument("--job-meta", default=None, help="Path to job_meta.json")
    ap.add_argument("--out", default=None, help="Output public_report.json path")
    ap.add_argument("--audit-log", default=None, help="Audit log jsonl path")

    ap.add_argument("--caller", default=None, help="Caller identity; in HMAC mode this must match auth config")
    ap.add_argument("--job-id", default=None, help="Optional job id for audit/report")
    ap.add_argument("--policy-version", default="w2-hmac-v1", help="Policy version label")

    ap.add_argument("--threshold-k", "--k", dest="threshold_k", type=int, default=20)
    ap.add_argument("--max-queries", "--n", dest="max_queries", type=int, default=5)
    ap.add_argument("--round-sum-to", type=int, default=None)
    ap.add_argument("--deny-duplicate-query", action="store_true", help="Deny an exact repeated canonical query signature for the caller")

    # optional HMAC authn/authz
    ap.add_argument("--auth-config", default=None, help="JSON file: {key_id: {caller, secret, enabled}}")
    ap.add_argument("--auth-required", action="store_true", help="Require HMAC auth")
    ap.add_argument("--key-id", default=None, help="HMAC key id")
    ap.add_argument("--timestamp", default=None, help="ISO8601 UTC timestamp, e.g. 2026-02-28T10:00:00Z")
    ap.add_argument("--nonce", default=None, help="Unique nonce for anti-replay")
    ap.add_argument("--signature", default=None, help="hex HMAC-SHA256 signature")
    ap.add_argument("--max-clock-skew-sec", type=int, default=300, help="Allowed clock skew for timestamp")
    ap.add_argument("--print-signing-template", action="store_true", help="Print the canonical HMAC message and exit")

    args = ap.parse_args()

    paths = resolve_paths(args)
    input_path = paths["input"]
    out_path = paths["out"]
    job_meta_path = paths["job_meta"]
    audit_log_path = paths["audit_log"]

    if not os.path.exists(input_path):
        raise SystemExit(f"missing input file: {input_path}")

    result = load_json(input_path)
    metrics = parse_pjc_result(result)
    job_meta = load_json_if_exists(job_meta_path)

    window = normalize_window(job_meta)
    input_sizes = extract_input_sizes(job_meta)
    bucket = try_get(job_meta, "bucket", "bucket_value", "campaign_id", default=None)
    value_mode = extract_value_mode(job_meta)
    bridge_meta = extract_bridge_meta(job_meta)
    job_id = args.job_id or try_get(job_meta, "job_id", default=os.path.basename(paths["job_dir"]))

    query_payload = canonical_query_payload(
        caller=args.caller or "",
        job_id=job_id,
        window=window,
        bucket=bucket,
        threshold_k=args.threshold_k,
        max_queries=args.max_queries,
    )
    query_sig = canonical_query_signature(query_payload)

    # helper for client-side signing/debugging
    if args.print_signing_template:
        effective_caller = args.caller or (load_auth_config(args.auth_config).get(args.key_id, {}).get("caller") if args.auth_config and args.key_id else "")
        msg = build_signed_message(
            key_id=args.key_id or "<key-id>",
            caller=effective_caller or "<caller>",
            timestamp=args.timestamp or "<timestamp>",
            nonce=args.nonce or "<nonce>",
            job_id=job_id,
            query_sig=query_sig,
        )
        print(msg)
        return

    auth_config = load_auth_config(args.auth_config)
    auth_result = authenticate_request(
        caller_arg=args.caller,
        auth_required=args.auth_required,
        auth_config=auth_config,
        key_id=args.key_id,
        timestamp=args.timestamp,
        nonce=args.nonce,
        signature=args.signature,
        audit_log_path=audit_log_path,
        max_clock_skew_sec=args.max_clock_skew_sec,
        job_id=job_id,
        query_sig=query_sig,
    )

    # auth failure: write audit record, but do not proceed to release
    if not auth_result.ok:
        caller_for_audit = args.caller or "unknown"
        deny_out = {
            "decision": "deny",
            "reason_code": auth_result.reason_code,
            "reason": auth_result.reason,
            "released": None,
        }
        rate_limit_out = {"used": 0, "max": args.max_queries}
        report = build_public_report(
            policy_version=args.policy_version,
            job_id=job_id,
            caller=caller_for_audit,
            window=window,
            bucket=bucket,
            value_mode=value_mode,
            bridge_meta=bridge_meta,
            input_sizes=input_sizes,
            threshold_k=args.threshold_k,
            rate_limit_out={"used": 0, "max": args.max_queries},
            policy_out=deny_out,
        )
        ensure_dir(os.path.dirname(out_path) or ".")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        audit_record = build_audit_record(
            policy_version=args.policy_version,
            job_id=job_id,
            caller=caller_for_audit,
            key_id=args.key_id,
            timestamp=args.timestamp,
            nonce=args.nonce,
            query_sig=query_sig,
            window=window,
            bucket=bucket,
            value_mode=value_mode,
            bridge_meta=bridge_meta,
            input_sizes=input_sizes,
            input_path=input_path,
            out_path=out_path,
            threshold_k=args.threshold_k,
            round_sum_to=args.round_sum_to,
            rate_limit_out={"used": 0, "max": args.max_queries, "allowed": False, "reason": "auth_failed", "reason_code": "auth_failed"},
            metrics=metrics,
            policy_out=deny_out,
            auth_result=auth_result,
        )
        append_jsonl(audit_log_path, audit_record)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    caller = auth_result.caller or args.caller or "local_demo"
    rate_limit_out = apply_rate_limit(audit_log_path, caller, window, args.max_queries)

    if args.deny_duplicate_query and seen_query_signature(audit_log_path, caller, query_sig):
        policy_out = {
            "decision": "deny",
            "reason_code": "duplicate_query",
            "reason": "duplicate canonical query signature for caller",
            "released": None,
        }
    elif not rate_limit_out["allowed"]:
        policy_out = {
            "decision": "deny",
            "reason_code": "rate_limit_exceeded",
            "reason": rate_limit_out["reason"],
            "released": None,
        }
    else:
        policy_out = apply_threshold_policy(metrics, args.threshold_k, args.round_sum_to)

    report = build_public_report(
        policy_version=args.policy_version,
        job_id=job_id,
        caller=caller,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        bridge_meta=bridge_meta,
        input_sizes=input_sizes,
        threshold_k=args.threshold_k,
        rate_limit_out=rate_limit_out,
        policy_out=policy_out,
    )

    ensure_dir(os.path.dirname(out_path) or ".")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    audit_record = build_audit_record(
        policy_version=args.policy_version,
        job_id=job_id,
        caller=caller,
        key_id=args.key_id,
        timestamp=args.timestamp,
        nonce=args.nonce,
        query_sig=query_sig,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        bridge_meta=bridge_meta,
        input_sizes=input_sizes,
        input_path=input_path,
        out_path=out_path,
        threshold_k=args.threshold_k,
        round_sum_to=args.round_sum_to,
        rate_limit_out=rate_limit_out,
        metrics=metrics,
        policy_out=policy_out,
        auth_result=auth_result,
    )
    append_jsonl(audit_log_path, audit_record)

    print(f"[ok] public report: {os.path.abspath(out_path)}")
    print(f"[ok] audit log:     {os.path.abspath(audit_log_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
