import argparse
import hashlib
import hmac
import json
import math
import os
import random as _random
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

_DP_RNG = _random.SystemRandom()


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
    u = _DP_RNG.uniform(-0.5 + 1e-10, 0.5 - 1e-10)
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


def first_nonempty(*values):
    for value in values:
        if value not in (None, "", {}, []):
            return value
    return None


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def json_pretty_bytes(record: Dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json_atomic(path: str, record: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "wb") as f:
        f.write(json_pretty_bytes(record))
    os.replace(tmp_path, path)


def json_payload_sha256(record: Dict[str, Any]) -> str:
    return sha256_hex_bytes(json_pretty_bytes(record))


def random_hex(nbytes: int = 12) -> str:
    return os.urandom(nbytes).hex()


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


def extract_privacy_scope(
    job_meta: Dict[str, Any],
    *,
    caller: str,
    tenant_id_arg: Optional[str],
    dataset_id_arg: Optional[str],
    purpose_arg: Optional[str],
) -> Dict[str, Optional[str]]:
    return {
        "caller": caller,
        "tenant_id": tenant_id_arg or try_get(job_meta, "tenant_id", "tenant", default=None),
        "dataset_id": dataset_id_arg or try_get(job_meta, "dataset_id", "dataset", default=None),
        "purpose": purpose_arg or try_get(job_meta, "purpose", "release_purpose", default=None),
    }


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
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    bridge_meta: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "purpose": purpose,
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
        "approval_required": False,
        "approval_queue_path": None,
        "approval_request_id": None,
    }


def _scope_value_matches(record_value: Any, expected: Optional[str]) -> bool:
    if expected is None:
        return record_value is None
    return record_value == expected


def _load_privacy_budget_records(
    ledger_path: str,
    *,
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
) -> List[Dict[str, Any]]:
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
            if (
                rec.get("schema") == "privacy_budget_ledger/v1"
                and rec.get("caller") == caller
                and _scope_value_matches(rec.get("tenant_id"), tenant_id)
                and _scope_value_matches(rec.get("dataset_id"), dataset_id)
                and _scope_value_matches(rec.get("purpose"), purpose)
            ):
                records.append(rec)
    return records


def default_privacy_budget_store_path(ledger_path: Optional[str]) -> Optional[str]:
    if not ledger_path:
        return None
    return os.path.abspath(ledger_path) + ".sqlite"


def resolve_privacy_budget_store_path(args: argparse.Namespace) -> Optional[str]:
    if args.privacy_budget_disable_transactional_store:
        return None
    if args.privacy_budget_store:
        return os.path.abspath(args.privacy_budget_store)
    return default_privacy_budget_store_path(args.privacy_budget_ledger)


def privacy_scope_key(
    *,
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
) -> str:
    payload = {
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "purpose": purpose,
    }
    return canonical_query_signature(payload)


def privacy_budget_ledger_record(
    *,
    policy_version: str,
    job_id: Optional[str],
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    privacy_budget: Dict[str, Any],
    policy_out: Dict[str, Any],
    metrics: Dict[str, Optional[int]],
    public_report_path: str,
    public_report_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    consumed = policy_out.get("decision") == "allow" and privacy_budget.get("decision") == "allow"
    return {
        "schema": "privacy_budget_ledger/v1",
        "ts_utc": utc_now_iso(),
        "policy_version": policy_version,
        "job_id": job_id,
        "correlation_id": job_id,
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "purpose": purpose,
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
        "public_report_sha256": public_report_sha256 if public_report_sha256 is not None else (sha256_file(public_report_path) if os.path.exists(public_report_path) else None),
    }


def privacy_budget_record_sha256(record: Dict[str, Any]) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_hex_str(payload)


def approval_is_expired(expires_at_utc: Optional[str]) -> bool:
    if not expires_at_utc:
        return False
    try:
        return parse_iso8601_utc(expires_at_utc) <= utc_now()
    except Exception:
        return True


class PrivacyBudgetStore:
    def __init__(self, store_path: Optional[str]) -> None:
        self.store_path = os.path.abspath(store_path) if store_path else None
        self.conn: Optional[sqlite3.Connection] = None
        self._transaction_open = False

    @property
    def enabled(self) -> bool:
        return bool(self.store_path)

    def __enter__(self) -> "PrivacyBudgetStore":
        if not self.store_path:
            return self
        ensure_dir(os.path.dirname(self.store_path) or ".")
        self.conn = sqlite3.connect(self.store_path, timeout=30.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
        self._with_lock_retry(self._init_schema)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.conn is not None:
            if self._transaction_open:
                self.conn.execute("ROLLBACK")
                self._transaction_open = False
            self.conn.close()
        return False

    def _init_schema(self) -> None:
        assert self.conn is not None
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS privacy_budget_consumption_events (
              id INTEGER PRIMARY KEY,
              created_at_utc TEXT NOT NULL,
              updated_at_utc TEXT NOT NULL,
              scope_key TEXT NOT NULL,
              caller TEXT NOT NULL,
              tenant_id TEXT,
              dataset_id TEXT,
              purpose TEXT,
              job_id TEXT,
              correlation_id TEXT,
              policy_version TEXT,
              query_fingerprint TEXT NOT NULL,
              query_payload_sha256 TEXT NOT NULL,
              window_start TEXT,
              window_end TEXT,
              window_json TEXT NOT NULL,
              bucket_json TEXT,
              bucket_key TEXT,
              value_mode TEXT,
              threshold_k INTEGER NOT NULL,
              decision TEXT NOT NULL,
              reason_code TEXT NOT NULL,
              reason TEXT NOT NULL,
              abuse_signal TEXT,
              matched_prior_fingerprint TEXT,
              matched_prior_job_id TEXT,
              matched_prior_relation TEXT,
              budget_limit REAL,
              budget_cost REAL,
              budget_used_before REAL,
              budget_used_after REAL,
              budget_consumed INTEGER NOT NULL DEFAULT 0,
              approval_request_id TEXT,
              public_report_sha256 TEXT,
              ledger_path TEXT,
              status TEXT NOT NULL DEFAULT 'committed',
              failure_reason TEXT,
              source_record_sha256 TEXT,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS privacy_budget_approval_events (
              id INTEGER PRIMARY KEY,
              created_at_utc TEXT NOT NULL,
              updated_at_utc TEXT NOT NULL,
              request_id TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL,
              caller TEXT NOT NULL,
              tenant_id TEXT,
              dataset_id TEXT,
              purpose TEXT,
              job_id TEXT,
              correlation_id TEXT,
              policy_version TEXT,
              query_fingerprint TEXT NOT NULL,
              query_payload_sha256 TEXT NOT NULL,
              matched_prior_fingerprint TEXT,
              matched_prior_job_id TEXT,
              matched_prior_relation TEXT,
              requested_at_utc TEXT NOT NULL,
              decided_at_utc TEXT,
              decided_by TEXT,
              decision_reason TEXT,
              expires_at_utc TEXT,
              consumed_at_utc TEXT,
              consumed_by_job_id TEXT,
              consuming_event_id INTEGER,
              request_payload_json TEXT NOT NULL,
              latest_decision_json TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_privacy_budget_scope_query_consumed
              ON privacy_budget_consumption_events(scope_key, query_fingerprint)
              WHERE budget_consumed = 1 AND decision = 'allow' AND status IN ('reserved', 'committed');
            CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_scope
              ON privacy_budget_consumption_events(scope_key, created_at_utc);
            CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_job
              ON privacy_budget_consumption_events(job_id);
            CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_decision
              ON privacy_budget_consumption_events(decision, reason_code);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_privacy_budget_consumption_source_record
              ON privacy_budget_consumption_events(source_record_sha256)
              WHERE source_record_sha256 IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_status
              ON privacy_budget_approval_events(status, updated_at_utc);
            CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_scope
              ON privacy_budget_approval_events(caller, tenant_id, dataset_id, purpose);
            CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_query
              ON privacy_budget_approval_events(query_fingerprint);
            """
        )

    @staticmethod
    def _with_lock_retry(func):
        last_exc: Optional[Exception] = None
        for attempt in range(10):
            try:
                return func()
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                last_exc = exc
                time.sleep(0.05 * (2 ** min(attempt, 5)))
        if last_exc is not None:
            raise last_exc
        return None

    def begin_immediate(self) -> None:
        if not self.enabled:
            return
        assert self.conn is not None
        self.conn.execute("BEGIN IMMEDIATE")
        self._transaction_open = True

    def commit(self) -> None:
        if not self.enabled:
            return
        assert self.conn is not None
        self.conn.execute("COMMIT")
        self._transaction_open = False

    def rollback(self) -> None:
        if not self.enabled or not self._transaction_open:
            return
        assert self.conn is not None
        self.conn.execute("ROLLBACK")
        self._transaction_open = False

    @staticmethod
    def _bucket_key(bucket: Optional[str]) -> str:
        return json.dumps(bucket, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def load_scope_records(
        self,
        *,
        caller: str,
        tenant_id: Optional[str],
        dataset_id: Optional[str],
        purpose: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        assert self.conn is not None
        scope_key = privacy_scope_key(caller=caller, tenant_id=tenant_id, dataset_id=dataset_id, purpose=purpose)
        rows = self.conn.execute(
            """
            SELECT payload_json
            FROM privacy_budget_consumption_events
            WHERE scope_key = ?
              AND status IN ('reserved', 'committed')
            ORDER BY id
            """,
            (scope_key,),
        ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    def insert_approval_request(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        assert self.conn is not None
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO privacy_budget_approval_events(
              created_at_utc, updated_at_utc, request_id, status, caller,
              tenant_id, dataset_id, purpose, job_id, correlation_id,
              policy_version, query_fingerprint, query_payload_sha256,
              matched_prior_fingerprint, matched_prior_job_id,
              matched_prior_relation, requested_at_utc, request_payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("created_at_utc") or now,
                now,
                record["request_id"],
                record["status"],
                record["caller"],
                record.get("tenant_id"),
                record.get("dataset_id"),
                record.get("purpose"),
                record.get("job_id"),
                record.get("correlation_id"),
                record.get("policy_version"),
                record.get("query_fingerprint"),
                record.get("query_payload_sha256"),
                record.get("matched_prior_fingerprint"),
                record.get("matched_prior_job_id"),
                record.get("matched_prior_relation"),
                record.get("created_at_utc") or now,
                json.dumps(record, ensure_ascii=False, sort_keys=True),
            ),
        )

    def load_approval_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        assert self.conn is not None
        row = self.conn.execute(
            """
            SELECT *
            FROM privacy_budget_approval_events
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["request_payload_json"]))
        latest_decision = None
        if row["latest_decision_json"]:
            latest_decision = json.loads(str(row["latest_decision_json"]))
        return {
            **payload,
            "status": row["status"],
            "decided_at_utc": row["decided_at_utc"],
            "decided_by": row["decided_by"],
            "decision_reason": row["decision_reason"],
            "expires_at_utc": row["expires_at_utc"],
            "consumed_at_utc": row["consumed_at_utc"],
            "consumed_by_job_id": row["consumed_by_job_id"],
            "consuming_event_id": row["consuming_event_id"],
            "latest_decision": latest_decision,
        }

    def list_approval_requests(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        assert self.conn is not None
        if status:
            rows = self.conn.execute(
                "SELECT request_id FROM privacy_budget_approval_events WHERE status = ? ORDER BY updated_at_utc DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT request_id FROM privacy_budget_approval_events ORDER BY updated_at_utc DESC"
            ).fetchall()
        return [
            item for item in (self.load_approval_request(str(row["request_id"])) for row in rows)
            if item is not None
        ]

    def transition_approval_request(
        self,
        *,
        request_id: str,
        action: str,
        actor: str,
        reason: Optional[str] = None,
        expires_at_utc: Optional[str] = None,
        consuming_job_id: Optional[str] = None,
        consuming_event_id: Optional[int] = None,
        decision_record: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("privacy budget approval transition requires transactional store")
        current = self.load_approval_request(request_id)
        if current is None:
            raise RuntimeError(f"privacy budget approval request not found: {request_id}")
        status = str(current.get("status") or "")
        now = utc_now_iso()
        decision_json = json.dumps(decision_record, ensure_ascii=False, sort_keys=True) if decision_record else None

        if action == "approve":
            if status != "pending_approval":
                raise RuntimeError(f"approval request is not pending_approval: {status}")
            if actor and actor == str(current.get("caller") or ""):
                raise PermissionError("same_identity_self_approval")
            new_status = "approved"
            self.conn.execute(
                """
                UPDATE privacy_budget_approval_events
                SET status = ?, updated_at_utc = ?, decided_at_utc = ?,
                    decided_by = ?, decision_reason = ?, expires_at_utc = ?,
                    latest_decision_json = ?
                WHERE request_id = ?
                """,
                (new_status, now, now, actor, reason, expires_at_utc, decision_json, request_id),
            )
        elif action == "reject":
            if status != "pending_approval":
                raise RuntimeError(f"approval request is not pending_approval: {status}")
            new_status = "rejected"
            self.conn.execute(
                """
                UPDATE privacy_budget_approval_events
                SET status = ?, updated_at_utc = ?, decided_at_utc = ?,
                    decided_by = ?, decision_reason = ?, latest_decision_json = ?
                WHERE request_id = ?
                """,
                (new_status, now, now, actor, reason, decision_json, request_id),
            )
        elif action == "expire":
            if status not in {"pending_approval", "approved"}:
                raise RuntimeError(f"approval request cannot expire from status: {status}")
            new_status = "expired"
            self.conn.execute(
                """
                UPDATE privacy_budget_approval_events
                SET status = ?, updated_at_utc = ?, decided_at_utc = ?,
                    decided_by = ?, decision_reason = ?, expires_at_utc = ?,
                    latest_decision_json = ?
                WHERE request_id = ?
                """,
                (new_status, now, now, actor, reason, expires_at_utc or now, decision_json, request_id),
            )
        elif action == "consume":
            if status != "approved":
                raise RuntimeError(f"approval request is not approved: {status}")
            if approval_is_expired(current.get("expires_at_utc")):
                raise RuntimeError("privacy budget approval is expired")
            new_status = "consumed"
            self.conn.execute(
                """
                UPDATE privacy_budget_approval_events
                SET status = ?, updated_at_utc = ?, consumed_at_utc = ?,
                    consumed_by_job_id = ?, consuming_event_id = ?,
                    latest_decision_json = ?
                WHERE request_id = ?
                """,
                (new_status, now, now, consuming_job_id, consuming_event_id, decision_json, request_id),
            )
        else:
            raise ValueError(f"unsupported privacy budget approval action: {action}")

        updated = self.load_approval_request(request_id)
        assert updated is not None
        return updated

    def bootstrap_approval_requests(self, queue_path: Optional[str]) -> None:
        if not self.enabled or not queue_path or not os.path.exists(queue_path):
            return
        with open(queue_path, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except Exception:
                    continue
                if record.get("schema") == "privacy_budget_approval_request/v1":
                    self.insert_approval_request(record)

    def bootstrap_approval_decisions(self, decisions_path: Optional[str]) -> None:
        if not self.enabled or not decisions_path or not os.path.exists(decisions_path):
            return
        with open(decisions_path, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except Exception:
                    continue
                if record.get("schema") != "privacy_budget_approval_decision/v1":
                    continue
                action = str(record.get("action") or "")
                request_id = str(record.get("request_id") or "")
                if not request_id:
                    continue
                current = self.load_approval_request(request_id)
                if current is None:
                    continue
                if current.get("status") == record.get("status"):
                    continue
                try:
                    self.transition_approval_request(
                        request_id=request_id,
                        action=action,
                        actor=str(record.get("actor") or ""),
                        reason=record.get("reason"),
                        expires_at_utc=record.get("expires_at_utc"),
                        consuming_job_id=record.get("consuming_job_id"),
                        consuming_event_id=record.get("consuming_event_id"),
                        decision_record=record,
                    )
                except Exception:
                    continue

    def insert_event(
        self,
        *,
        record: Dict[str, Any],
        ledger_path: Optional[str],
        privacy_budget: Dict[str, Any],
        status: str,
        public_report_sha256: Optional[str] = None,
        failure_reason: Optional[str] = None,
        source_record_sha256: Optional[str] = None,
        or_ignore: bool = False,
    ) -> int:
        if not self.enabled:
            return 0
        assert self.conn is not None
        scope_key = privacy_scope_key(
            caller=str(record["caller"]),
            tenant_id=record.get("tenant_id"),
            dataset_id=record.get("dataset_id"),
            purpose=record.get("purpose"),
        )
        now = utc_now_iso()
        window = record.get("window") if isinstance(record.get("window"), dict) else {}
        bucket = record.get("bucket")
        budget = record.get("budget") if isinstance(record.get("budget"), dict) else {}
        insert_verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
        cursor = self.conn.execute(
            f"""
            {insert_verb} INTO privacy_budget_consumption_events(
              created_at_utc, updated_at_utc, scope_key, caller, tenant_id,
              dataset_id, purpose, job_id, correlation_id, policy_version,
              query_fingerprint, query_payload_sha256, window_start, window_end,
              window_json, bucket_json, bucket_key, value_mode, threshold_k,
              decision, reason_code, reason, abuse_signal,
              matched_prior_fingerprint, matched_prior_job_id,
              matched_prior_relation, budget_limit, budget_cost,
              budget_used_before, budget_used_after, budget_consumed,
              approval_request_id, public_report_sha256, ledger_path, status,
              failure_reason, source_record_sha256, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                scope_key,
                record["caller"],
                record.get("tenant_id"),
                record.get("dataset_id"),
                record.get("purpose"),
                record.get("job_id"),
                record.get("correlation_id"),
                record.get("policy_version"),
                record.get("query_fingerprint"),
                record.get("query_payload_sha256"),
                window.get("start"),
                window.get("end"),
                json.dumps(window, ensure_ascii=False, sort_keys=True),
                json.dumps(bucket, ensure_ascii=False, sort_keys=True),
                self._bucket_key(bucket),
                record.get("value_mode"),
                int(record.get("threshold_k") or 0),
                record.get("decision"),
                record.get("reason_code"),
                record.get("reason"),
                record.get("abuse_signal"),
                record.get("matched_prior_fingerprint"),
                record.get("matched_prior_job_id"),
                record.get("matched_prior_relation"),
                budget.get("limit"),
                budget.get("cost"),
                budget.get("used_before"),
                budget.get("used_after"),
                1 if budget.get("consumed") is True else 0,
                privacy_budget.get("approval_request_id"),
                public_report_sha256,
                os.path.abspath(ledger_path) if ledger_path else None,
                status,
                failure_reason,
                source_record_sha256,
                json.dumps(record, ensure_ascii=False, sort_keys=True),
            ),
        )
        return int(cursor.lastrowid)

    def update_event_status(
        self,
        event_id: int,
        *,
        status: str,
        record: Optional[Dict[str, Any]] = None,
        public_report_sha256: Optional[str] = None,
        failure_reason: Optional[str] = None,
        source_record_sha256: Optional[str] = None,
    ) -> None:
        if not self.enabled or event_id <= 0:
            return
        assert self.conn is not None
        updates = [
            "updated_at_utc = ?",
            "status = ?",
            "public_report_sha256 = ?",
            "failure_reason = ?",
        ]
        params: list[Any] = [utc_now_iso(), status, public_report_sha256, failure_reason]
        if record is not None:
            updates.append("payload_json = ?")
            params.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        if source_record_sha256 is not None:
            updates.append("source_record_sha256 = ?")
            params.append(source_record_sha256)
        params.append(event_id)
        self.conn.execute(
            f"UPDATE privacy_budget_consumption_events SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )

    def bootstrap_from_jsonl_ledger(self, ledger_path: Optional[str]) -> None:
        if not self.enabled or not ledger_path or not os.path.exists(ledger_path):
            return
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except Exception:
                    continue
                if record.get("schema") != "privacy_budget_ledger/v1":
                    continue
                record_hash = privacy_budget_record_sha256(record)
                self.insert_event(
                    record=record,
                    ledger_path=ledger_path,
                    privacy_budget={"approval_request_id": None},
                    status="committed",
                    public_report_sha256=record.get("public_report_sha256"),
                    source_record_sha256=record_hash,
                    or_ignore=True,
                )

    def write_report_and_commit(
        self,
        *,
        report: Dict[str, Any],
        out_path: str,
        operator_report: Optional[Dict[str, Any]],
        operator_report_path: Optional[str],
        audit_record: Dict[str, Any],
        audit_log_path: str,
        ledger_record: Optional[Dict[str, Any]],
        ledger_path: Optional[str],
        event_id: int,
        approval_request_record: Optional[Dict[str, Any]] = None,
        approval_queue_path: Optional[str] = None,
        approval_decision_record: Optional[Dict[str, Any]] = None,
        approval_decisions_path: Optional[str] = None,
        approval_consume_request_id: Optional[str] = None,
    ) -> None:
        public_report_sha = json_payload_sha256(report)
        ledger_hash = privacy_budget_record_sha256(ledger_record) if ledger_record else None
        try:
            write_json_atomic(out_path, report)
            if operator_report is not None and operator_report_path:
                write_json_atomic(operator_report_path, operator_report)
            if ledger_record is not None and ledger_path:
                append_jsonl(ledger_path, ledger_record)
            if approval_request_record is not None and approval_queue_path:
                append_jsonl(approval_queue_path, approval_request_record)
            append_jsonl(audit_log_path, audit_record)
            if approval_decision_record is not None and approval_decisions_path:
                append_jsonl(approval_decisions_path, approval_decision_record)
            if approval_consume_request_id and approval_decision_record is not None:
                self.transition_approval_request(
                    request_id=approval_consume_request_id,
                    action="consume",
                    actor=str(approval_decision_record.get("actor") or "policy_release"),
                    consuming_job_id=approval_decision_record.get("consuming_job_id"),
                    consuming_event_id=approval_decision_record.get("consuming_event_id"),
                    decision_record=approval_decision_record,
                )
        except Exception as exc:
            if event_id:
                self.update_event_status(
                    event_id,
                    status="failed_after_reserve",
                    record=ledger_record,
                    public_report_sha256=public_report_sha,
                    failure_reason=str(exc),
                )
                self.commit()
            raise

        if event_id:
            self.update_event_status(
                event_id,
                status="committed",
                record=ledger_record,
                public_report_sha256=public_report_sha,
                source_record_sha256=ledger_hash,
            )
        self.commit()


def _load_privacy_budget_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    config = load_json(path)
    if config.get("schema") != "privacy_budget_config/v1":
        raise ValueError(f"privacy budget config must use schema privacy_budget_config/v1: {path}")
    return config


def _budget_scope_match(rule: Dict[str, Any], scope: Dict[str, Optional[str]]) -> bool:
    match = rule.get("match")
    if not isinstance(match, dict):
        return False
    if str(match.get("caller") or "") != scope["caller"]:
        return False
    for field in ("tenant_id", "dataset_id", "purpose"):
        configured = match.get(field)
        if configured is None or configured == "*":
            continue
        if configured != scope.get(field):
            return False
    return True


def resolve_privacy_budget_scope(
    *,
    config: Dict[str, Any],
    scope: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    if not config:
        return {
            "matched_scope_index": None,
            "max_queries": None,
            "near_duplicate_window_seconds": None,
            "reason_code": "privacy_budget_config_missing",
            "reason": "privacy budget config was not provided",
        }
    default = config.get("default") if isinstance(config.get("default"), dict) else {}
    resolved = {
        "matched_scope_index": None,
        "max_queries": int(default.get("max_queries", 0)),
        "near_duplicate_window_seconds": int(default.get("near_duplicate_window_seconds", 0)),
        "near_duplicate_window_round_seconds": int(default.get("near_duplicate_window_round_seconds", 3600)),
        "near_duplicate_threshold_round_step": int(default.get("near_duplicate_threshold_round_step", 1)),
        "reason_code": "ok",
        "reason": None,
    }
    scopes = config.get("scopes") if isinstance(config.get("scopes"), list) else []
    for idx, rule in enumerate(scopes):
        if not isinstance(rule, dict):
            continue
        if _budget_scope_match(rule, scope):
            resolved.update({
                "matched_scope_index": idx,
                "max_queries": int(rule.get("max_queries", resolved["max_queries"])),
                "near_duplicate_window_seconds": int(rule.get("near_duplicate_window_seconds", resolved["near_duplicate_window_seconds"])),
                "near_duplicate_window_round_seconds": int(rule.get("near_duplicate_window_round_seconds", resolved["near_duplicate_window_round_seconds"])),
                "near_duplicate_threshold_round_step": int(rule.get("near_duplicate_threshold_round_step", resolved["near_duplicate_threshold_round_step"])),
            })
            return resolved
    if resolved["max_queries"] == 0:
        resolved["reason_code"] = "privacy_budget_missing_scope"
        resolved["reason"] = "no privacy budget scope matched and default max_queries=0"
    return resolved


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


def _window_gap_seconds(a: Dict[str, Optional[str]], b: Dict[str, Optional[str]]) -> Optional[float]:
    a_start, a_end = _parse_window_dt(a)
    b_start, b_end = _parse_window_dt(b)
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return None
    if a_end <= b_start:
        return max(0.0, (b_start - a_end).total_seconds())
    if b_end <= a_start:
        return max(0.0, (a_start - b_end).total_seconds())
    return 0.0


def _round_window_value(value: Optional[str], *, round_seconds: int) -> Optional[str]:
    if not value:
        return value
    if round_seconds <= 0:
        return value
    dt = parse_iso8601_utc(value)
    rounded_epoch = int(dt.timestamp()) // round_seconds * round_seconds
    return datetime.fromtimestamp(rounded_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _threshold_bucket(threshold_k: int, *, round_step: int) -> int:
    if round_step <= 1:
        return int(threshold_k)
    return max(0, int(threshold_k) // round_step)


def _near_duplicate_signature(
    *,
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    round_seconds: int,
    round_step: int,
    ignore_bucket: bool = False,
) -> str:
    payload = {
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "purpose": purpose,
        "window_start": _round_window_value(window.get("start"), round_seconds=round_seconds),
        "window_end": _round_window_value(window.get("end"), round_seconds=round_seconds),
        "bucket": None if ignore_bucket else bucket,
        "value_mode": value_mode,
        "threshold_bucket": _threshold_bucket(threshold_k, round_step=round_step),
    }
    return canonical_query_signature(payload)


def evaluate_privacy_budget(
    *,
    ledger_path: Optional[str],
    prior_records_override: Optional[List[Dict[str, Any]]] = None,
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
    job_id: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    bridge_meta: Dict[str, Any],
    budget_limit: Optional[float],
    budget_cost: float,
    scope_resolution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not ledger_path:
        return privacy_budget_default()
    if budget_cost <= 0:
        raise ValueError("--privacy-budget-cost must be positive")
    if scope_resolution and budget_limit is None and scope_resolution.get("max_queries") is not None:
        budget_limit = float(scope_resolution["max_queries"])
    if budget_limit is not None and budget_limit < 0:
        raise ValueError("--privacy-budget-limit must be non-negative")
    near_duplicate_window_seconds = int(scope_resolution.get("near_duplicate_window_seconds") or 0) if scope_resolution else 0
    near_duplicate_window_round_seconds = int(scope_resolution.get("near_duplicate_window_round_seconds") or 3600) if scope_resolution else 3600
    near_duplicate_threshold_round_step = int(scope_resolution.get("near_duplicate_threshold_round_step") or 1) if scope_resolution else 1

    payload = canonical_privacy_budget_payload(
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        purpose=purpose,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=threshold_k,
        bridge_meta=bridge_meta,
    )
    query_fingerprint = canonical_query_signature(payload)
    near_duplicate_fingerprint = _near_duplicate_signature(
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        purpose=purpose,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=threshold_k,
        round_seconds=near_duplicate_window_round_seconds,
        round_step=near_duplicate_threshold_round_step,
        ignore_bucket=False,
    )
    bucketless_near_duplicate_fingerprint = _near_duplicate_signature(
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        purpose=purpose,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=threshold_k,
        round_seconds=near_duplicate_window_round_seconds,
        round_step=near_duplicate_threshold_round_step,
        ignore_bucket=True,
    )
    if prior_records_override is None:
        prior_records = _load_privacy_budget_records(
            ledger_path,
            caller=caller,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            purpose=purpose,
        )
    else:
        prior_records = prior_records_override
    consumed_records = [
        rec for rec in prior_records
        if rec.get("budget", {}).get("consumed") is True and rec.get("decision") == "allow"
    ]
    used_before = sum(float(rec.get("budget", {}).get("cost") or 0.0) for rec in consumed_records)

    base = {
        "enabled": True,
        "ledger_path": os.path.abspath(ledger_path),
        "scope": {
            "caller": caller,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "purpose": purpose,
            "matched_scope_index": scope_resolution.get("matched_scope_index") if scope_resolution else None,
        },
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

    if scope_resolution and scope_resolution.get("reason_code") != "ok":
        return {
            **base,
            "decision": "deny",
            "reason_code": scope_resolution["reason_code"],
            "reason": scope_resolution["reason"] or "privacy budget scope resolution failed",
        }

    for prior in consumed_records:
        prior_fingerprint = prior.get("query_fingerprint")
        prior_window = prior.get("window") if isinstance(prior.get("window"), dict) else {}
        relation = _window_relation(window, prior_window)
        relation_for_report = relation
        gap_seconds = _window_gap_seconds(window, prior_window)
        same_bucket = prior.get("bucket") == bucket
        prior_near_duplicate_fingerprint = _near_duplicate_signature(
            caller=str(prior.get("caller") or caller),
            tenant_id=prior.get("tenant_id"),
            dataset_id=prior.get("dataset_id"),
            purpose=prior.get("purpose"),
            window=prior_window,
            bucket=prior.get("bucket"),
            value_mode=prior.get("value_mode"),
            threshold_k=int(prior.get("threshold_k") or 0),
            round_seconds=near_duplicate_window_round_seconds,
            round_step=near_duplicate_threshold_round_step,
            ignore_bucket=False,
        )
        prior_bucketless_near_duplicate_fingerprint = _near_duplicate_signature(
            caller=str(prior.get("caller") or caller),
            tenant_id=prior.get("tenant_id"),
            dataset_id=prior.get("dataset_id"),
            purpose=prior.get("purpose"),
            window=prior_window,
            bucket=prior.get("bucket"),
            value_mode=prior.get("value_mode"),
            threshold_k=int(prior.get("threshold_k") or 0),
            round_seconds=near_duplicate_window_round_seconds,
            round_step=near_duplicate_threshold_round_step,
            ignore_bucket=True,
        )
        rounded_window_or_threshold_match = near_duplicate_fingerprint == prior_near_duplicate_fingerprint
        rounded_bucketless_match = bucketless_near_duplicate_fingerprint == prior_bucketless_near_duplicate_fingerprint
        close_disjoint_window = (
            relation == "disjoint"
            and near_duplicate_window_seconds > 0
            and gap_seconds is not None
            and gap_seconds <= near_duplicate_window_seconds
        )
        if close_disjoint_window:
            relation_for_report = "unknown"
        if prior_fingerprint == query_fingerprint:
            return {
                **base,
                "decision": "deny",
                "reason_code": "privacy_budget_duplicate_query",
                "reason": "privacy budget denied exact repeated query fingerprint",
                "abuse_signal": "exact_duplicate",
                "matched_prior_fingerprint": prior_fingerprint,
                "matched_prior_job_id": prior.get("job_id"),
                "matched_prior_relation": relation_for_report,
            }
        if same_bucket and (
            relation in {"same", "contains", "contained_by", "overlaps", "unknown"}
            or rounded_window_or_threshold_match
            or close_disjoint_window
        ):
            detail = relation
            if rounded_window_or_threshold_match and relation == "disjoint":
                detail = "rounded_window_or_threshold_match"
            elif close_disjoint_window:
                detail = f"close_window_gap<={near_duplicate_window_seconds}s"
            return {
                **base,
                "decision": "deny",
                "reason_code": "privacy_budget_near_duplicate",
                "reason": f"privacy budget denied suspicious same-bucket query pattern ({detail})",
                "abuse_signal": "near_duplicate_or_differencing",
                "matched_prior_fingerprint": prior_fingerprint,
                "matched_prior_job_id": prior.get("job_id"),
                "matched_prior_relation": relation_for_report,
            }
        if (
            not same_bucket
            and rounded_bucketless_match
            and (
                relation in {"same", "contains", "contained_by", "overlaps", "unknown"}
                or close_disjoint_window
            )
        ):
            return {
                **base,
                "decision": "deny",
                "reason_code": "privacy_budget_bucket_probe",
                "reason": "privacy budget denied suspicious cross-bucket differencing pattern",
                "abuse_signal": "near_duplicate_or_differencing",
                "matched_prior_fingerprint": prior_fingerprint,
                "matched_prior_job_id": prior.get("job_id"),
                "matched_prior_relation": relation_for_report,
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
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
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
    record = privacy_budget_ledger_record(
        policy_version=policy_version,
        job_id=job_id,
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        purpose=purpose,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=threshold_k,
        privacy_budget=privacy_budget,
        policy_out=policy_out,
        metrics=metrics,
        public_report_path=public_report_path,
    )
    append_jsonl(ledger_path, record)


def build_privacy_budget_approval_request(
    *,
    queue_path: Optional[str],
    policy_version: str,
    job_id: Optional[str],
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    privacy_budget: Dict[str, Any],
    policy_out: Dict[str, Any],
    metrics: Dict[str, Optional[int]],
    public_report_path: str,
    public_report_sha256: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not queue_path or not privacy_budget.get("enabled"):
        return None
    if privacy_budget.get("reason_code") not in {"privacy_budget_near_duplicate", "privacy_budget_bucket_probe"}:
        return None
    request_basis = {
        "policy_version": policy_version,
        "job_id": job_id,
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "purpose": purpose,
        "query_fingerprint": privacy_budget.get("query_fingerprint"),
        "matched_prior_fingerprint": privacy_budget.get("matched_prior_fingerprint"),
        "matched_prior_job_id": privacy_budget.get("matched_prior_job_id"),
        "matched_prior_relation": privacy_budget.get("matched_prior_relation"),
    }
    request_id = "pba_" + canonical_query_signature(request_basis)[:24]
    record = {
        "schema": "privacy_budget_approval_request/v1",
        "created_at_utc": utc_now_iso(),
        "status": "pending_approval",
        "request_id": request_id,
        "policy_version": policy_version,
        "job_id": job_id,
        "correlation_id": job_id,
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "purpose": purpose,
        "decision": policy_out.get("decision"),
        "reason_code": policy_out.get("reason_code"),
        "reason": policy_out.get("reason"),
        "abuse_signal": privacy_budget.get("abuse_signal"),
        "matched_prior_fingerprint": privacy_budget.get("matched_prior_fingerprint"),
        "matched_prior_job_id": privacy_budget.get("matched_prior_job_id"),
        "matched_prior_relation": privacy_budget.get("matched_prior_relation"),
        "query_fingerprint": privacy_budget.get("query_fingerprint"),
        "query_payload_sha256": canonical_query_signature(privacy_budget.get("query_payload") or {}),
        "window": window,
        "bucket": bucket,
        "value_mode": value_mode,
        "threshold_k": threshold_k,
        "budget": {
            "limit": privacy_budget.get("budget_limit"),
            "cost": privacy_budget.get("budget_cost"),
            "used_before": privacy_budget.get("budget_used_before"),
            "used_after": privacy_budget.get("budget_used_before"),
            "consumed": False,
        },
        "parsed_metrics": metrics,
        "public_report_sha256": public_report_sha256 if public_report_sha256 is not None else (sha256_file(public_report_path) if os.path.exists(public_report_path) else None),
        "approval_recommendation": "manual_review_required",
    }
    return record


def append_privacy_budget_approval_request(
    *,
    queue_path: Optional[str],
    policy_version: str,
    job_id: Optional[str],
    caller: str,
    tenant_id: Optional[str],
    dataset_id: Optional[str],
    purpose: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    threshold_k: int,
    privacy_budget: Dict[str, Any],
    policy_out: Dict[str, Any],
    metrics: Dict[str, Optional[int]],
    public_report_path: str,
) -> Optional[Dict[str, Any]]:
    record = build_privacy_budget_approval_request(
        queue_path=queue_path,
        policy_version=policy_version,
        job_id=job_id,
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        purpose=purpose,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=threshold_k,
        privacy_budget=privacy_budget,
        policy_out=policy_out,
        metrics=metrics,
        public_report_path=public_report_path,
    )
    if not record or not queue_path:
        return None
    queue_abs = os.path.abspath(queue_path)
    append_jsonl(queue_abs, record)
    return {
        "request_id": record["request_id"],
        "queue_path": queue_abs,
        "status": record["status"],
    }


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


# Operator-only fields (S5). When --public-report-redact-operator-fields is on,
# these keys are stripped from public_report.json and routed to the operator
# report instead. Listed here once so the redaction layer + a future contract
# smoke can stay in sync without re-stating the set.
PUBLIC_REPORT_OPERATOR_ONLY_FIELDS = (
    "input_sizes",      # raw row counts per role — direct frame-count leak
    "rate_limit_used",  # internal accounting
    "rate_limit_max",   # internal accounting
    "bridge",           # bridge metadata: normalizer version, token scope, etc.
    "details",          # full released decoration including raw cents
)


def compact_object(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    compact = {key: value for key, value in payload.items() if value not in (None, "", {}, [])}
    return compact or None


def load_source_governance(
    *,
    source_attestation_path: Optional[str],
    source_truthfulness_report_path: Optional[str],
    job_meta: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    source_attestation = load_json_if_exists(source_attestation_path)
    source_truthfulness_report = load_json_if_exists(source_truthfulness_report_path)
    if not source_attestation and not source_truthfulness_report:
        return None, None, None
    inputs = try_get(job_meta, "inputs", default={})
    if not isinstance(inputs, dict):
        inputs = {}
    source_attestation_sha256 = sha256_file(source_attestation_path) if source_attestation_path and os.path.exists(source_attestation_path) else None
    source_truthfulness_report_sha256 = (
        sha256_file(source_truthfulness_report_path)
        if source_truthfulness_report_path and os.path.exists(source_truthfulness_report_path)
        else None
    )
    input_commitment_sha256 = first_nonempty(
        source_attestation.get("input_commitment_sha256") if source_attestation else None,
        inputs.get("input_commitment_sha256"),
    )
    governance_public = compact_object(
        {
            "source_attestation_sha256": source_attestation_sha256,
            "source_attestation_mode": source_attestation.get("attestation_mode") if source_attestation else None,
            "source_attestation_signoff_status": source_attestation.get("signoff_status") if source_attestation else None,
            "source_truthfulness_report_sha256": source_truthfulness_report_sha256,
            "input_commitment_sha256": input_commitment_sha256,
        }
    )
    governance_operator = compact_object(
        {
            "approval_id": source_attestation.get("approval_id") if source_attestation else None,
            "operator_identity": source_attestation.get("operator_identity") if source_attestation else None,
            "reviewer_identity": source_attestation.get("reviewer_identity") if source_attestation else None,
            "source_truthfulness_decision": source_truthfulness_report.get("decision") if source_truthfulness_report else None,
            "source_truthfulness_reason_code": source_truthfulness_report.get("reason_code") if source_truthfulness_report else None,
        }
    )
    governance_audit = compact_object(
        {
            **(governance_public or {}),
            **(governance_operator or {}),
            "source_attestation_path": os.path.abspath(source_attestation_path) if source_attestation_path else None,
            "source_truthfulness_report_path": os.path.abspath(source_truthfulness_report_path) if source_truthfulness_report_path else None,
        }
    )
    return governance_public, governance_operator, governance_audit


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
    governance_public: Optional[Dict[str, Any]] = None,
    bucket_size: bool = False,
    redact_operator_fields: bool = False,
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
        "governance": governance_public,
    }

    # allow: return full report (with optional operator-only redaction).
    if full_report["released"]:
        if redact_operator_fields:
            redacted = {k: v for k, v in full_report.items() if k not in PUBLIC_REPORT_OPERATOR_ONLY_FIELDS}
            redacted["operator_fields_redacted"] = True
            return redacted
        return full_report

    # deny: return slim public report (already excludes operator-only fields by construction)
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
        "governance": full_report["governance"],
    }


def _maybe_write_operator_report(
    *,
    args,
    out_path: str,
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
    governance_public: Optional[Dict[str, Any]] = None,
    governance_operator: Optional[Dict[str, Any]] = None,
    bucket_size: bool = False,
) -> None:
    """Write the operator-grade copy of the release report (S5).

    Always emitted when ``--public-report-redact-operator-fields`` is on
    (so the operator can still see what the caller cannot). Also emitted
    when ``--operator-report-path`` is explicitly set, even if the public
    report is unredacted. Otherwise no-ops to keep the legacy behavior.
    """
    redacted = bool(args.public_report_redact_operator_fields)
    explicit = bool(args.operator_report_path)
    if not redacted and not explicit:
        return
    if args.operator_report_path:
        op_path = args.operator_report_path
    else:
        base, _ = os.path.splitext(out_path)
        op_path = base + ".operator.json"
    full_report = build_public_report(
        policy_version=policy_version,
        job_id=job_id,
        caller=caller,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        bridge_meta=bridge_meta,
        input_sizes=input_sizes,
        threshold_k=threshold_k,
        rate_limit_out=rate_limit_out,
        policy_out=policy_out,
        governance_public=governance_public,
        bucket_size=bucket_size,
        redact_operator_fields=False,  # operator copy always carries the full set
    )
    full_report["schema"] = "operator_release_report/v1"
    full_report["public_report_was_redacted"] = redacted
    if governance_operator:
        full_report["governance_operator"] = governance_operator
    ensure_dir(os.path.dirname(op_path) or ".")
    with open(op_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)


def build_operator_report_if_needed(
    *,
    args,
    out_path: str,
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
    governance_public: Optional[Dict[str, Any]] = None,
    governance_operator: Optional[Dict[str, Any]] = None,
    bucket_size: bool = False,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    redacted = bool(args.public_report_redact_operator_fields)
    explicit = bool(args.operator_report_path)
    if not redacted and not explicit:
        return None, None
    if args.operator_report_path:
        op_path = args.operator_report_path
    else:
        base, _ = os.path.splitext(out_path)
        op_path = base + ".operator.json"
    full_report = build_public_report(
        policy_version=policy_version,
        job_id=job_id,
        caller=caller,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        bridge_meta=bridge_meta,
        input_sizes=input_sizes,
        threshold_k=threshold_k,
        rate_limit_out=rate_limit_out,
        policy_out=policy_out,
        governance_public=governance_public,
        bucket_size=bucket_size,
        redact_operator_fields=False,
    )
    full_report["schema"] = "operator_release_report/v1"
    full_report["public_report_was_redacted"] = redacted
    if governance_operator:
        full_report["governance_operator"] = governance_operator
    return op_path, full_report


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
    governance: Optional[Dict[str, Any]] = None,
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
    if governance is not None:
        record["governance"] = governance
    if privacy_budget is not None:
        record["privacy_budget"] = privacy_budget
    return record


def evaluate_policy_and_budget(
    *,
    args: argparse.Namespace,
    caller: str,
    privacy_scope: Dict[str, Optional[str]],
    privacy_budget_scope_resolution: Optional[Dict[str, Any]],
    effective_privacy_budget_limit: Optional[float],
    rate_limit_out: Dict[str, Any],
    query_sig: str,
    audit_log_path: str,
    job_id: Optional[str],
    window: Dict[str, Optional[str]],
    bucket: Optional[str],
    value_mode: Optional[str],
    bridge_meta: Dict[str, Any],
    metrics: Dict[str, Optional[int]],
    prior_records_override: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    privacy_budget_out = privacy_budget_default()

    if args.deny_duplicate_query and seen_query_signature(audit_log_path, caller, query_sig):
        return {
            "decision": "deny",
            "reason_code": "duplicate_query",
            "reason": "duplicate canonical query signature for caller",
            "released": None,
        }, privacy_budget_out

    if not rate_limit_out["allowed"]:
        return {
            "decision": "deny",
            "reason_code": "rate_limit_exceeded",
            "reason": rate_limit_out["reason"],
            "released": None,
        }, privacy_budget_out

    privacy_budget_out = evaluate_privacy_budget(
        ledger_path=args.privacy_budget_ledger,
        prior_records_override=prior_records_override,
        caller=caller,
        tenant_id=privacy_scope["tenant_id"],
        dataset_id=privacy_scope["dataset_id"],
        purpose=privacy_scope["purpose"],
        job_id=job_id,
        window=window,
        bucket=bucket,
        value_mode=value_mode,
        threshold_k=args.threshold_k,
        bridge_meta=bridge_meta,
        budget_limit=effective_privacy_budget_limit,
        budget_cost=args.privacy_budget_cost,
        scope_resolution=privacy_budget_scope_resolution,
    )
    if privacy_budget_out.get("decision") == "deny":
        if (
            args.privacy_budget_approval_queue
            and privacy_budget_out.get("reason_code") in {"privacy_budget_near_duplicate", "privacy_budget_bucket_probe"}
        ):
            privacy_budget_out = {
                **privacy_budget_out,
                "approval_required": True,
                "approval_queue_path": os.path.abspath(args.privacy_budget_approval_queue),
            }
        return {
            "decision": "deny",
            "reason_code": privacy_budget_out["reason_code"],
            "reason": privacy_budget_out["reason"],
            "released": None,
        }, privacy_budget_out

    return apply_threshold_policy(
        metrics, args.threshold_k, args.round_sum_to,
        dp_epsilon=args.dp_epsilon,
        dp_sensitivity=args.dp_sensitivity,
    ), privacy_budget_out


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
    ap.add_argument("--tenant-id", default=None, help="Privacy-budget tenant scope override")
    ap.add_argument("--dataset-id", default=None, help="Privacy-budget dataset scope override")
    ap.add_argument("--purpose", default=None, help="Privacy-budget release purpose override")

    ap.add_argument("--threshold-k", "--k", dest="threshold_k", type=int, default=20)
    ap.add_argument("--max-queries", "--n", dest="max_queries", type=int, default=5)
    ap.add_argument("--round-sum-to", type=int, default=None)
    ap.add_argument("--deny-duplicate-query", action="store_true", help="Deny an exact repeated canonical query signature for the caller")
    ap.add_argument("--privacy-budget-ledger", default=None,
                    help="Optional JSONL privacy_budget_ledger/v1 path. Enables budget, duplicate, and overlapping-window checks before release.")
    ap.add_argument("--privacy-budget-store", default=None,
                    help=(
                        "Optional SQLite transactional privacy-budget store. "
                        "Defaults to <privacy-budget-ledger>.sqlite when "
                        "--privacy-budget-ledger is set. Use --privacy-budget-disable-transactional-store "
                        "only for legacy JSONL-only compatibility tests."
                    ))
    ap.add_argument("--privacy-budget-disable-transactional-store", action="store_true",
                    help="Disable the SQLite transactional privacy-budget source of truth and use legacy JSONL evaluation only.")
    ap.add_argument("--privacy-budget-config", default=None,
                    help="Optional privacy_budget_config/v1 JSON path. In production mode it selects caller/tenant/dataset/purpose budget scopes.")
    ap.add_argument("--privacy-budget-required", action="store_true",
                    help="Fail closed unless a privacy-budget ledger is configured; deny releases when no configured budget scope matches.")
    ap.add_argument("--privacy-budget-limit", type=float, default=None,
                    help="Maximum cumulative privacy budget units for this caller in --privacy-budget-ledger.")
    ap.add_argument("--privacy-budget-cost", type=float, default=1.0,
                    help="Budget units consumed by an allowed release when --privacy-budget-ledger is enabled.")
    ap.add_argument("--privacy-budget-approval-queue", default=None,
                    help=(
                        "Optional JSONL privacy_budget_approval_request/v1 path. "
                        "When set, near-duplicate privacy-budget denials are also "
                        "queued for manual review; release still fails closed."
                    ))
    ap.add_argument("--privacy-budget-approval-decisions", default=None,
                    help=(
                        "Optional JSONL privacy_budget_approval_decision/v1 path. "
                        "Approved near-duplicate releases consume the approval and "
                        "append a consumed decision record after the release commits."
                    ))
    ap.add_argument("--privacy-budget-approval-id", default=None,
                    help="Approved privacy-budget approval request id to consume for a near-duplicate release.")
    ap.add_argument("--privacy-budget-approval-actor", default=None,
                    help="Actor consuming --privacy-budget-approval-id. Defaults to caller when omitted.")

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
    ap.add_argument("--require-dp", action="store_true",
                    help=(
                        "Fail-closed if --dp-epsilon and --dp-sensitivity are not both set "
                        "with positive values. Recommended for any public release path, and "
                        "required when bucket-level reports are generated (compare "
                        "policy_postprocess_buckets.py --require-dp)."
                    ))
    ap.add_argument("--public-report-redact-operator-fields", action="store_true",
                    help=(
                        "S5: drop operator-only metadata (input_sizes, rate_limit_used/max, "
                        "bridge, details) from public_report.json. The fields are still "
                        "available to operators via --operator-report-path."
                    ))
    ap.add_argument("--operator-report-path", default=None,
                    help=(
                        "Path to write an operator-grade copy of the release report (always "
                        "includes input_sizes / bridge / details / rate_limit_*). When "
                        "--public-report-redact-operator-fields is set, this is where the "
                        "redacted fields land. Defaults to <out>.operator.json sibling."
                    ))
    ap.add_argument("--source-attestation", default=None,
                    help="Optional source_attestation/v1 artifact bound to this release.")
    ap.add_argument("--source-truthfulness-report", default=None,
                    help="Optional source_truthfulness_report/v1 verifier output bound to this release.")

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

    if args.privacy_budget_approval_id and not args.privacy_budget_approval_queue:
        raise SystemExit("policy_release: --privacy-budget-approval-id requires --privacy-budget-approval-queue")
    if args.privacy_budget_approval_id and not args.privacy_budget_ledger:
        raise SystemExit("policy_release: --privacy-budget-approval-id requires --privacy-budget-ledger")
    if args.privacy_budget_approval_id and args.privacy_budget_disable_transactional_store:
        raise SystemExit("policy_release: --privacy-budget-approval-id requires the transactional privacy-budget store")
    if args.privacy_budget_approval_id and not args.privacy_budget_approval_decisions:
        raise SystemExit("policy_release: --privacy-budget-approval-id requires --privacy-budget-approval-decisions")

    # Fail-closed DP enforcement (A.11). If the operator asked for DP-enforced
    # mode, refuse to run unless both knobs are present and positive. We do
    # this before any IO so a misconfigured release never touches the audit
    # log or the public_report path.
    if args.require_dp:
        missing = []
        if args.dp_epsilon is None or float(args.dp_epsilon) <= 0:
            missing.append("--dp-epsilon")
        if args.dp_sensitivity is None or int(args.dp_sensitivity) <= 0:
            missing.append("--dp-sensitivity")
        if missing:
            raise SystemExit(
                "policy_release: --require-dp set but missing/non-positive: "
                + ", ".join(missing)
            )
    if args.privacy_budget_required and not args.privacy_budget_ledger:
        raise SystemExit("policy_release: --privacy-budget-required set but --privacy-budget-ledger is missing")

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
    governance_public, governance_operator, governance_audit = load_source_governance(
        source_attestation_path=args.source_attestation,
        source_truthfulness_report_path=args.source_truthfulness_report,
        job_meta=job_meta,
    )

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
            governance_public=governance_public,
            redact_operator_fields=bool(args.public_report_redact_operator_fields),
        )
        ensure_dir(os.path.dirname(out_path) or ".")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        _maybe_write_operator_report(
            args=args,
            out_path=out_path,
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
            governance_public=governance_public,
            governance_operator=governance_operator,
        )

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
            governance=governance_audit,
            privacy_budget=privacy_budget_default(),
        )
        append_jsonl(audit_log_path, audit_record)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    caller = auth_result.caller or args.caller or "local_demo"
    privacy_scope = extract_privacy_scope(
        job_meta,
        caller=caller,
        tenant_id_arg=args.tenant_id,
        dataset_id_arg=args.dataset_id,
        purpose_arg=args.purpose,
    )
    privacy_budget_config = _load_privacy_budget_config(args.privacy_budget_config)
    privacy_budget_scope_resolution = None
    if privacy_budget_config or args.privacy_budget_required:
        privacy_budget_scope_resolution = resolve_privacy_budget_scope(
            config=privacy_budget_config,
            scope=privacy_scope,
        )
    effective_privacy_budget_limit = args.privacy_budget_limit
    if (
        effective_privacy_budget_limit is None
        and privacy_budget_scope_resolution
        and privacy_budget_scope_resolution.get("max_queries") is not None
    ):
        effective_privacy_budget_limit = float(privacy_budget_scope_resolution["max_queries"])

    rate_limit_out = apply_rate_limit(audit_log_path, caller, window, args.max_queries)
    store_path = resolve_privacy_budget_store_path(args)

    with PrivacyBudgetStore(store_path) as budget_store:
        event_id = 0
        ledger_record = None
        approval_request_record = None
        approval_request = None
        approval_decision_record = None
        approval_consume_request_id = None
        if budget_store.enabled:
            budget_store.begin_immediate()
            budget_store.bootstrap_from_jsonl_ledger(args.privacy_budget_ledger)
            budget_store.bootstrap_approval_requests(args.privacy_budget_approval_queue)
            budget_store.bootstrap_approval_decisions(args.privacy_budget_approval_decisions)
            prior_records = budget_store.load_scope_records(
                caller=caller,
                tenant_id=privacy_scope["tenant_id"],
                dataset_id=privacy_scope["dataset_id"],
                purpose=privacy_scope["purpose"],
            )
        else:
            prior_records = None

        policy_out, privacy_budget_out = evaluate_policy_and_budget(
            args=args,
            caller=caller,
            privacy_scope=privacy_scope,
            privacy_budget_scope_resolution=privacy_budget_scope_resolution,
            effective_privacy_budget_limit=effective_privacy_budget_limit,
            rate_limit_out=rate_limit_out,
            query_sig=query_sig,
            audit_log_path=audit_log_path,
            job_id=job_id,
            window=window,
            bucket=bucket,
            value_mode=value_mode,
            bridge_meta=bridge_meta,
            metrics=metrics,
            prior_records_override=prior_records,
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
            governance_public=governance_public,
            bucket_size=args.bucket_intersection_size,
            redact_operator_fields=bool(args.public_report_redact_operator_fields),
        )
        report_sha = json_payload_sha256(report)

        if (
            args.privacy_budget_approval_id
            and privacy_budget_out.get("decision") == "deny"
            and privacy_budget_out.get("reason_code") == "privacy_budget_near_duplicate"
        ):
            if not budget_store.enabled:
                raise RuntimeError("approved privacy-budget release requires transactional store")
            approval = budget_store.load_approval_request(args.privacy_budget_approval_id)
            if approval is None:
                raise RuntimeError(f"privacy budget approval request not found: {args.privacy_budget_approval_id}")
            approval_status = str(approval.get("status") or "")
            if approval_status != "approved":
                raise RuntimeError(f"privacy budget approval request is not approved: {approval_status}")
            if approval_is_expired(approval.get("expires_at_utc")):
                raise RuntimeError("privacy budget approval request is expired")
            approval_actor = args.privacy_budget_approval_actor or caller
            if approval_actor == str(approval.get("caller") or ""):
                raise PermissionError("same_identity_self_approval")
            approval_scope = {
                "caller": approval.get("caller"),
                "tenant_id": approval.get("tenant_id"),
                "dataset_id": approval.get("dataset_id"),
                "purpose": approval.get("purpose"),
            }
            if approval_scope != {
                "caller": caller,
                "tenant_id": privacy_scope["tenant_id"],
                "dataset_id": privacy_scope["dataset_id"],
                "purpose": privacy_scope["purpose"],
            }:
                raise RuntimeError("privacy budget approval scope does not match release scope")
            if approval.get("query_fingerprint") != privacy_budget_out.get("query_fingerprint"):
                raise RuntimeError("privacy budget approval fingerprint does not match release query")
            approved_used_after = (privacy_budget_out.get("budget_used_before") or 0) + args.privacy_budget_cost
            approved_limit = privacy_budget_out.get("budget_limit")
            if approved_limit is not None and approved_used_after > float(approved_limit):
                raise RuntimeError("approved privacy-budget release exceeds budget limit")
            policy_out = apply_threshold_policy(
                metrics, args.threshold_k, args.round_sum_to,
                dp_epsilon=args.dp_epsilon,
                dp_sensitivity=args.dp_sensitivity,
            )
            privacy_budget_out = {
                **privacy_budget_out,
                "decision": "allow",
                "reason_code": "privacy_budget_approved",
                "reason": "near-duplicate release approved and budget consume reserved",
                "budget_used_after": approved_used_after,
                "approval_required": False,
                "approval_request_id": approval["request_id"],
                "approval": {
                    "request_id": approval["request_id"],
                    "status": "approved",
                    "decided_by": approval.get("decided_by"),
                    "decided_at_utc": approval.get("decided_at_utc"),
                    "expires_at_utc": approval.get("expires_at_utc"),
                },
            }
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
                governance_public=governance_public,
                bucket_size=args.bucket_intersection_size,
                redact_operator_fields=bool(args.public_report_redact_operator_fields),
            )
            report_sha = json_payload_sha256(report)
            approval_decision_record = {
                "schema": "privacy_budget_approval_decision/v1",
                "created_at_utc": utc_now_iso(),
                "action": "consume",
                "status": "consumed",
                "request_id": approval["request_id"],
                "actor": approval_actor,
                "caller": caller,
                "tenant_id": privacy_scope["tenant_id"],
                "dataset_id": privacy_scope["dataset_id"],
                "purpose": privacy_scope["purpose"],
                "job_id": approval.get("job_id"),
                "consuming_job_id": job_id,
                "query_fingerprint": privacy_budget_out.get("query_fingerprint"),
                "query_payload_sha256": canonical_query_signature(privacy_budget_out.get("query_payload") or {}),
                "reason": "approved near-duplicate privacy-budget release consumed",
                "expires_at_utc": approval.get("expires_at_utc"),
                "public_report_sha256": report_sha,
                "budget_consumed": True,
                "consuming_event_id": None,
            }
            approval_consume_request_id = approval["request_id"]
        elif args.privacy_budget_approval_id:
            raise RuntimeError("privacy budget approval id can only be consumed for an approval-eligible privacy-budget denial")

        approval_request_record = build_privacy_budget_approval_request(
            queue_path=args.privacy_budget_approval_queue,
            policy_version=args.policy_version,
            job_id=job_id,
            caller=caller,
            tenant_id=privacy_scope["tenant_id"],
            dataset_id=privacy_scope["dataset_id"],
            purpose=privacy_scope["purpose"],
            window=window,
            bucket=bucket,
            value_mode=value_mode,
            threshold_k=args.threshold_k,
            privacy_budget=privacy_budget_out,
            policy_out=policy_out,
            metrics=metrics,
            public_report_path=out_path,
            public_report_sha256=report_sha,
        )
        if approval_request_record and budget_store.enabled:
            budget_store.insert_approval_request(approval_request_record)
        if approval_request_record and args.privacy_budget_approval_queue:
            queue_abs = os.path.abspath(args.privacy_budget_approval_queue)
            approval_request = {
                "request_id": approval_request_record["request_id"],
                "queue_path": queue_abs,
                "status": approval_request_record["status"],
            }
            privacy_budget_out = {
                **privacy_budget_out,
                "approval_request_id": approval_request["request_id"],
                "approval_request": approval_request,
            }

        if args.privacy_budget_ledger and privacy_budget_out.get("enabled"):
            ledger_record = privacy_budget_ledger_record(
                policy_version=args.policy_version,
                job_id=job_id,
                caller=caller,
                tenant_id=privacy_scope["tenant_id"],
                dataset_id=privacy_scope["dataset_id"],
                purpose=privacy_scope["purpose"],
                window=window,
                bucket=bucket,
                value_mode=value_mode,
                threshold_k=args.threshold_k,
                privacy_budget=privacy_budget_out,
                policy_out=policy_out,
                metrics=metrics,
                public_report_path=out_path,
                public_report_sha256=report_sha,
            )
            event_status = "reserved" if ledger_record["budget"]["consumed"] is True else "committed"
            event_id = budget_store.insert_event(
                record=ledger_record,
                ledger_path=args.privacy_budget_ledger,
                privacy_budget=privacy_budget_out,
                status=event_status,
                public_report_sha256=report_sha,
            )
            if approval_decision_record is not None:
                approval_decision_record["consuming_event_id"] = event_id

        operator_report_path, operator_report = build_operator_report_if_needed(
            args=args,
            out_path=out_path,
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
            governance_public=governance_public,
            governance_operator=governance_operator,
            bucket_size=args.bucket_intersection_size,
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
            governance=governance_audit,
            privacy_budget=privacy_budget_out,
        )

        budget_store.write_report_and_commit(
            report=report,
            out_path=out_path,
            operator_report=operator_report,
            operator_report_path=operator_report_path,
            audit_record=audit_record,
            audit_log_path=audit_log_path,
            ledger_record=ledger_record,
            ledger_path=args.privacy_budget_ledger,
            event_id=event_id,
            approval_request_record=approval_request_record,
            approval_queue_path=args.privacy_budget_approval_queue,
            approval_decision_record=approval_decision_record,
            approval_decisions_path=args.privacy_budget_approval_decisions,
            approval_consume_request_id=approval_consume_request_id,
        )

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
