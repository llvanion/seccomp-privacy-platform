import argparse
import hashlib
import hmac
import json
import math
import os
import random as _random
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple


# ---------- basic utils ----------

def ensure_dir(path: str) -> None:
    if path:
        os.makedirs(path, exist_ok=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def elapsed_ms(started_at: float) -> int:
    return int(round((perf_counter() - started_at) * 1000))


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


# ---------- signed result delivery ----------

def deliver_signed_result(
    *,
    report_path: str,
    callback_url: str,
    delivery_key_env: str,
) -> Dict[str, Any]:
    delivery_key = os.environ.get(delivery_key_env, "")
    if not delivery_key:
        raise ValueError(f"result delivery key env {delivery_key_env!r} is not set")
    with open(report_path, "rb") as f:
        report_bytes = f.read()
    report_sha256 = sha256_hex_bytes(report_bytes)
    signature = hmac_sha256_hex(delivery_key, report_sha256)
    req = urllib.request.Request(
        callback_url,
        data=report_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Report-SHA256": report_sha256,
            "X-Report-Signature": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode("utf-8", errors="replace")
    return {
        "callback_url": callback_url,
        "report_sha256": report_sha256,
        "signature_algorithm": "hmac-sha256",
        "http_status": status,
        "delivered": 200 <= status < 300,
    }


# ---------- differential privacy ----------

def _laplace_noise(scale: float) -> float:
    # Inverse-CDF method: no numpy dependency required.
    # scale = sensitivity / epsilon
    u = _random.uniform(-0.5 + 1e-10, 0.5 - 1e-10)
    return -scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))


def bucket_intersection_size(n: int) -> str:
    if n < 10:   return "<10"
    if n < 50:   return "10-49"
    if n < 200:  return "50-199"
    return "200+"


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


def canonical_privacy_budget_payload(
    *,
    caller: str,
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    bridge_meta: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "caller": caller,
        "window_start": window.get("start"),
        "window_end": window.get("end"),
        "bucket": bucket,
        "value_mode": value_mode,
        "threshold_k": threshold_k,
        "token_scope": bridge_meta.get("token_scope"),
        "server_join_key_column": bridge_meta.get("server_join_key_column"),
        "client_join_key_column": bridge_meta.get("client_join_key_column"),
        "client_value_column": bridge_meta.get("client_value_column"),
    }


def privacy_budget_default() -> Dict[str, Any]:
    return {
        "enabled": False,
        "decision": "not_applicable",
        "reason_code": "disabled",
        "reason": "privacy budget ledger disabled",
        "ledger_path": None,
        "budget_limit": None,
        "budget_cost": None,
        "budget_used_before": None,
        "budget_used_after": None,
        "query_fingerprint": None,
        "abuse_signal": None,
        "matched_prior_fingerprint": None,
        "matched_prior_job_id": None,
        "matched_prior_relation": None,
    }


def _load_privacy_budget_records(ledger_path: str, caller: str) -> List[Dict[str, Any]]:
    if not os.path.exists(ledger_path):
        return []
    records = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("schema") == "privacy_budget_ledger/v1" and rec.get("caller") == caller:
                records.append(rec)
    return records


def _parse_window_dt(window: Dict[str, Optional[str]]) -> Tuple[Optional[datetime], Optional[datetime]]:
    try:
        start = parse_iso8601_utc(window["start"]) if window.get("start") else None
        end = parse_iso8601_utc(window["end"]) if window.get("end") else None
        return start, end
    except Exception:
        return None, None


def _window_relation(a: Dict[str, Optional[str]], b: Dict[str, Optional[str]]) -> str:
    if a.get("start") == b.get("start") and a.get("end") == b.get("end"):
        return "same"
    a_start, a_end = _parse_window_dt(a)
    b_start, b_end = _parse_window_dt(b)
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return "unknown"
    if a_end <= b_start or b_end <= a_start:
        return "disjoint"
    if a_start <= b_start and a_end >= b_end:
        return "contains"
    if b_start <= a_start and b_end >= a_end:
        return "contained_by"
    return "overlaps"


def evaluate_privacy_budget(
    *,
    ledger_path: Optional[str],
    caller: str,
    job_id: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    bridge_meta: Dict[str, Any],
    budget_limit: Optional[float],
    budget_cost: float,
) -> Dict[str, Any]:
    if not ledger_path:
        return privacy_budget_default()
    if budget_cost <= 0:
        raise ValueError("--privacy-budget-cost must be positive")
    if budget_limit is not None and budget_limit < 0:
        raise ValueError("--privacy-budget-limit must be non-negative")

    payload = canonical_privacy_budget_payload(
        caller=caller,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=threshold_k,
        bridge_meta=bridge_meta,
    )
    query_fingerprint = canonical_query_signature(payload)
    prior_records = _load_privacy_budget_records(ledger_path, caller)
    consumed_records = [
        rec for rec in prior_records
        if rec.get("budget", {}).get("consumed") is True and rec.get("decision") == "allow"
    ]
    used_before = sum(float(rec.get("budget", {}).get("cost") or 0.0) for rec in consumed_records)

    base = {
        "enabled": True,
        "ledger_path": os.path.abspath(ledger_path),
        "budget_limit": budget_limit,
        "budget_cost": budget_cost,
        "budget_used_before": used_before,
        "budget_used_after": used_before,
        "query_fingerprint": query_fingerprint,
        "query_payload": payload,
        "abuse_signal": None,
        "matched_prior_fingerprint": None,
        "matched_prior_job_id": None,
        "matched_prior_relation": None,
    }

    for prior in consumed_records:
        prior_fingerprint = prior.get("query_fingerprint")
        prior_window = prior.get("window") if isinstance(prior.get("window"), dict) else {}
        relation = _window_relation(window, prior_window)
        same_bucket = prior.get("bucket") == bucket
        if prior_fingerprint == query_fingerprint:
            return {
                **base,
                "decision": "deny",
                "reason_code": "privacy_budget_duplicate_query",
                "reason": "privacy budget denied exact repeated query fingerprint",
                "abuse_signal": "exact_duplicate",
                "matched_prior_fingerprint": prior_fingerprint,
                "matched_prior_job_id": prior.get("job_id"),
                "matched_prior_relation": relation,
            }
        if same_bucket and relation in {"same", "contains", "contained_by", "overlaps", "unknown"}:
            return {
                **base,
                "decision": "deny",
                "reason_code": "privacy_budget_near_duplicate",
                "reason": f"privacy budget denied {relation} query window for caller/bucket",
                "abuse_signal": "near_duplicate_or_differencing",
                "matched_prior_fingerprint": prior_fingerprint,
                "matched_prior_job_id": prior.get("job_id"),
                "matched_prior_relation": relation,
            }

    used_after = used_before + budget_cost
    if budget_limit is not None and used_after > budget_limit:
        return {
            **base,
            "decision": "deny",
            "reason_code": "privacy_budget_exhausted",
            "reason": f"privacy budget exhausted ({used_before:g} + {budget_cost:g} > {budget_limit:g})",
            "abuse_signal": "budget_exhausted",
        }

    return {
        **base,
        "decision": "allow",
        "reason_code": "privacy_budget_ok",
        "reason": "privacy budget check passed",
        "budget_used_after": used_after,
    }


def append_privacy_budget_ledger_record(
    *,
    ledger_path: Optional[str],
    policy_version: str,
    job_id: Optional[str],
    caller: str,
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    privacy_budget: Dict[str, Any],
    policy_out: Dict[str, Any],
    metrics: Dict[str, Optional[int]],
    public_report_path: str,
) -> None:
    if not ledger_path or not privacy_budget.get("enabled"):
        return
    consumed = policy_out.get("decision") == "allow" and privacy_budget.get("decision") == "allow"
    record = {
        "schema": "privacy_budget_ledger/v1",
        "ts_utc": utc_now_iso(),
        "policy_version": policy_version,
        "job_id": job_id,
        "correlation_id": job_id,
        "caller": caller,
        "window": window,
        "bucket": bucket,
        "value_mode": value_mode,
        "threshold_k": threshold_k,
        "query_fingerprint": privacy_budget.get("query_fingerprint"),
        "query_payload_sha256": canonical_query_signature(privacy_budget.get("query_payload") or {}),
        "decision": policy_out.get("decision"),
        "reason_code": policy_out.get("reason_code"),
        "reason": policy_out.get("reason"),
        "abuse_signal": privacy_budget.get("abuse_signal"),
        "matched_prior_fingerprint": privacy_budget.get("matched_prior_fingerprint"),
        "matched_prior_job_id": privacy_budget.get("matched_prior_job_id"),
        "matched_prior_relation": privacy_budget.get("matched_prior_relation"),
        "budget": {
            "limit": privacy_budget.get("budget_limit"),
            "cost": privacy_budget.get("budget_cost"),
            "used_before": privacy_budget.get("budget_used_before"),
            "used_after": privacy_budget.get("budget_used_after") if consumed else privacy_budget.get("budget_used_before"),
            "consumed": consumed,
        },
        "parsed_metrics": metrics,
        "public_report_sha256": sha256_file(public_report_path) if os.path.exists(public_report_path) else None,
    }
    append_jsonl(ledger_path, record)


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

def apply_threshold_policy(
    metrics: Dict[str, Optional[int]],
    threshold_k: int,
    round_sum_to: Optional[int],
    *,
    dp_epsilon: Optional[float] = None,
    dp_sensitivity: Optional[int] = None,
) -> Dict[str, Any]:
    size = metrics.get("intersection_size")
    total = metrics.get("intersection_sum")

    if size is None or total is None:
        return {
            "decision": "deny",
            "reason_code": "missing_metrics",
            "reason": "missing required metrics",
            "dp_noise_applied": False,
            "dp_epsilon": None,
            "released": None,
        }

    if size < threshold_k:
        return {
            "decision": "deny",
            "reason_code": "below_k",
            "reason": f"intersection_size below threshold ({size} < {threshold_k})",
            "dp_noise_applied": False,
            "dp_epsilon": None,
            "released": None,
        }

    released_sum = total
    if round_sum_to is not None and round_sum_to > 1:
        released_sum = int(round(total / round_sum_to) * round_sum_to)

    dp_noise_applied = False
    if dp_epsilon is not None and dp_sensitivity is not None and dp_epsilon > 0 and dp_sensitivity > 0:
        noise = _laplace_noise(dp_sensitivity / dp_epsilon)
        released_sum = int(round(released_sum + noise))
        dp_noise_applied = True

    return {
        "decision": "allow",
        "reason_code": "threshold_passed",
        "reason": "threshold passed",
        "dp_noise_applied": dp_noise_applied,
        "dp_epsilon": dp_epsilon if dp_noise_applied else None,
        "released": {
            "intersection_size": size,
            "intersection_size_bucket": bucket_intersection_size(size),
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
    bucket_size: bool = False,
) -> Dict[str, Any]:
    released = decorate_released_value(policy_out.get("released"), value_mode)

    conversions = None
    conversions_bucket = None
    value_sum = None
    aov = None
    if released is not None:
        conversions = released.get("intersection_size")
        conversions_bucket = released.get("intersection_size_bucket")
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
        "conversions": conversions_bucket if bucket_size else conversions,
        "conversions_exact_suppressed": bucket_size,
        "dp_noise_applied": policy_out.get("dp_noise_applied", False),
        "dp_epsilon": policy_out.get("dp_epsilon"),
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
    duration_ms: Optional[int],
    privacy_budget: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    input_sha256 = sha256_file(input_path)
    record = {
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
        "duration_ms": duration_ms,
        "decision": policy_out["decision"],
        "reason": policy_out["reason"],
        "reason_code": policy_out["reason_code"],
        "dp_noise_applied": policy_out.get("dp_noise_applied", False),
        "dp_epsilon": policy_out.get("dp_epsilon"),
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
    if privacy_budget is not None:
        record["privacy_budget"] = privacy_budget
    return record


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
    ap.add_argument("--privacy-budget-ledger", default=None,
                    help="Optional JSONL privacy_budget_ledger/v1 path. Enables budget, duplicate, and overlapping-window checks before release.")
    ap.add_argument("--privacy-budget-limit", type=float, default=None,
                    help="Maximum cumulative privacy budget units for this caller in --privacy-budget-ledger.")
    ap.add_argument("--privacy-budget-cost", type=float, default=1.0,
                    help="Budget units consumed by an allowed release when --privacy-budget-ledger is enabled.")

    # signed result delivery
    ap.add_argument("--result-callback-url", default=None,
                    help="URL to POST the public report to after a successful release")
    ap.add_argument("--result-delivery-key-env", default=None,
                    help="Env var holding the HMAC-SHA256 delivery signing key for --result-callback-url")

    # differential privacy
    ap.add_argument("--dp-epsilon", type=float, default=None,
                    help="Laplace mechanism epsilon for DP noise on intersection_sum. "
                         "Requires --dp-sensitivity. Noise scale = sensitivity/epsilon.")
    ap.add_argument("--dp-sensitivity", type=int, default=None,
                    help="L1 sensitivity of intersection_sum (maximum individual value). "
                         "Required when --dp-epsilon is set.")
    ap.add_argument("--bucket-intersection-size", action="store_true",
                    help="Replace exact intersection_size in public_report with a bucket label (<10, 10-49, 50-199, 200+).")

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
    started_at = perf_counter()

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
            duration_ms=elapsed_ms(started_at),
            privacy_budget=privacy_budget_default(),
        )
        append_jsonl(audit_log_path, audit_record)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    caller = auth_result.caller or args.caller or "local_demo"
    rate_limit_out = apply_rate_limit(audit_log_path, caller, window, args.max_queries)
    privacy_budget_out = privacy_budget_default()

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
        privacy_budget_out = evaluate_privacy_budget(
            ledger_path=args.privacy_budget_ledger,
            caller=caller,
            job_id=job_id,
            window=window,
            bucket=bucket,
            value_mode=value_mode,
            threshold_k=args.threshold_k,
            bridge_meta=bridge_meta,
            budget_limit=args.privacy_budget_limit,
            budget_cost=args.privacy_budget_cost,
        )
        if privacy_budget_out.get("decision") == "deny":
            policy_out = {
                "decision": "deny",
                "reason_code": privacy_budget_out["reason_code"],
                "reason": privacy_budget_out["reason"],
                "released": None,
            }
        else:
            policy_out = apply_threshold_policy(
                metrics, args.threshold_k, args.round_sum_to,
                dp_epsilon=args.dp_epsilon,
                dp_sensitivity=args.dp_sensitivity,
            )

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
        bucket_size=args.bucket_intersection_size,
    )

    ensure_dir(os.path.dirname(out_path) or ".")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    append_privacy_budget_ledger_record(
        ledger_path=args.privacy_budget_ledger,
        policy_version=args.policy_version,
        job_id=job_id,
        caller=caller,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=args.threshold_k,
        privacy_budget=privacy_budget_out,
        policy_out=policy_out,
        metrics=metrics,
        public_report_path=out_path,
    )

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
        duration_ms=elapsed_ms(started_at),
        privacy_budget=privacy_budget_out,
    )
    append_jsonl(audit_log_path, audit_record)

    print(f"[ok] public report: {os.path.abspath(out_path)}")
    print(f"[ok] audit log:     {os.path.abspath(audit_log_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.result_callback_url and args.result_delivery_key_env and policy_out["decision"] == "allow":
        try:
            delivery = deliver_signed_result(
                report_path=out_path,
                callback_url=args.result_callback_url,
                delivery_key_env=args.result_delivery_key_env,
            )
            status = "ok" if delivery["delivered"] else "failed"
            print(f"[{status}] result delivery: {delivery['callback_url']} http={delivery['http_status']}")
        except Exception as exc:
            print(f"[warn] result delivery failed: {exc}")


if __name__ == "__main__":
    main()
