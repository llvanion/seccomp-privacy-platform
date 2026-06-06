#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from metadata_db import apply_migrations, connect_db, table_exists


WORKFLOW_NAME = "sse_bridge_pipeline"
DEFAULT_LEASE_SECONDS = 300


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def lease_owner(label: str = "") -> str:
    prefix = str(label or "query-workflow").strip()
    return f"{prefix}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def execution_id_for(*, job_id: str, request_digest: str) -> str:
    return f"qwe_{uuid.uuid5(uuid.NAMESPACE_URL, f'{WORKFLOW_NAME}:{job_id}:{request_digest}').hex}"


def _iso_after(now: str, lease_seconds: int) -> str:
    return (parse_utc(now) + timedelta(seconds=max(1, int(lease_seconds)))).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()} if hasattr(row, "keys") else None


def metadata_json(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    raw = row.get("metadata_json")
    if not raw:
        return {}
    try:
        decoded = json.loads(str(raw))
    except json.JSONDecodeError:
        return {"unparseable_metadata_json": str(raw)}
    return decoded if isinstance(decoded, dict) else {"metadata_json": decoded}


def connect_execution_db(db_path: str = "", db_dsn: str = "") -> Any:
    if not db_path and not db_dsn:
        raise ValueError("query workflow execution store requires metadata db path or dsn")
    conn = connect_db(db_path, dsn=db_dsn)
    apply_migrations(conn)
    if not table_exists(conn, "query_workflow_executions"):
        raise RuntimeError("metadata DB is missing query_workflow_executions table")
    return conn


def load_execution(conn: Any, *, job_id: str = "", out_base: str = "") -> dict[str, Any] | None:
    if job_id:
        row = conn.execute(
            "SELECT * FROM query_workflow_executions WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    elif out_base:
        row = conn.execute(
            "SELECT * FROM query_workflow_executions WHERE out_base = ?",
            (out_base,),
        ).fetchone()
    else:
        raise ValueError("load_execution requires job_id or out_base")
    return _row_to_dict(row)


def _same_request(row: dict[str, Any], *, request_digest: str, out_base: str) -> bool:
    return str(row.get("request_digest") or "") == request_digest and str(row.get("out_base") or "") == out_base


def _is_expired(row: dict[str, Any], *, now: str) -> bool:
    try:
        return parse_utc(str(row.get("lease_expires_at_utc") or "")) <= parse_utc(now)
    except ValueError:
        return True


def claim_execution(
    conn: Any,
    *,
    job_id: str,
    out_base: str,
    request_digest: str,
    request_source: str,
    caller: str = "",
    tenant_id: str = "",
    dataset_id: str = "",
    mode: str = "execute",
    owner: str = "",
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    steal_expired: bool = False,
    artifact_paths: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    owner = owner or lease_owner()
    existing = load_execution(conn, job_id=job_id)
    if existing is None:
        existing = load_execution(conn, out_base=out_base)
    if existing is not None:
        state = str(existing.get("state") or "")
        terminal = bool(existing.get("terminal"))
        if terminal:
            raise RuntimeError(f"query workflow execution is terminal: job_id={existing.get('job_id')} state={state}")
        if not _same_request(existing, request_digest=request_digest, out_base=out_base):
            raise RuntimeError(
                "query workflow execution already exists for different request or out_base: "
                f"job_id={existing.get('job_id')} state={state}"
            )
        if not steal_expired or not _is_expired(existing, now=now):
            raise RuntimeError(
                "query workflow execution lease is active: "
                f"job_id={existing.get('job_id')} owner={existing.get('lease_owner')} "
                f"expires={existing.get('lease_expires_at_utc')}"
            )
        conn.execute(
            """
            UPDATE query_workflow_executions
            SET state = ?, terminal = 0, lease_owner = ?, lease_expires_at_utc = ?,
                heartbeat_at_utc = ?, updated_at_utc = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                "running",
                owner,
                _iso_after(now, lease_seconds),
                now,
                now,
                _json(metadata or {"stolen_from_owner": existing.get("lease_owner")}),
                existing["id"],
            ),
        )
        conn.commit()
        claimed = load_execution(conn, job_id=job_id)
        assert claimed is not None
        return claimed

    paths = artifact_paths or {}
    conn.execute(
        """
        INSERT INTO query_workflow_executions(
          execution_id, workflow, job_id, out_base, request_digest, request_source,
          caller, tenant_id, dataset_id, mode, state, terminal, lease_owner,
          lease_expires_at_utc, heartbeat_at_utc, started_at_utc, updated_at_utc,
          status_path, receipts_path, submission_manifest_path, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution_id_for(job_id=job_id, request_digest=request_digest),
            WORKFLOW_NAME,
            job_id,
            out_base,
            request_digest,
            request_source,
            caller or None,
            tenant_id or None,
            dataset_id or None,
            mode,
            "running",
            owner,
            _iso_after(now, lease_seconds),
            now,
            now,
            now,
            paths.get("status_path"),
            paths.get("receipts_path"),
            paths.get("submission_manifest_path"),
            _json(metadata or {}),
        ),
    )
    conn.commit()
    claimed = load_execution(conn, job_id=job_id)
    assert claimed is not None
    return claimed


def enqueue_execution(
    conn: Any,
    *,
    job_id: str,
    out_base: str,
    request_digest: str,
    request_source: str,
    caller: str = "",
    tenant_id: str = "",
    dataset_id: str = "",
    mode: str = "execute",
    owner: str = "",
    artifact_paths: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    owner = owner or lease_owner("query-workflow-queue")
    existing = load_execution(conn, job_id=job_id)
    if existing is None:
        existing = load_execution(conn, out_base=out_base)
    if existing is not None:
        state = str(existing.get("state") or "")
        if bool(existing.get("terminal")):
            raise RuntimeError(f"query workflow execution is terminal: job_id={existing.get('job_id')} state={state}")
        if not _same_request(existing, request_digest=request_digest, out_base=out_base):
            raise RuntimeError(
                "query workflow execution already exists for different request or out_base: "
                f"job_id={existing.get('job_id')} state={state}"
            )
        raise RuntimeError(
            "query workflow execution already exists and is non-terminal: "
            f"job_id={existing.get('job_id')} state={state}"
        )

    paths = artifact_paths or {}
    conn.execute(
        """
        INSERT INTO query_workflow_executions(
          execution_id, workflow, job_id, out_base, request_digest, request_source,
          caller, tenant_id, dataset_id, mode, state, terminal, lease_owner,
          lease_expires_at_utc, heartbeat_at_utc, started_at_utc, updated_at_utc,
          status_path, receipts_path, submission_manifest_path, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution_id_for(job_id=job_id, request_digest=request_digest),
            WORKFLOW_NAME,
            job_id,
            out_base,
            request_digest,
            request_source,
            caller or None,
            tenant_id or None,
            dataset_id or None,
            mode,
            "queued",
            owner,
            now,
            now,
            now,
            now,
            paths.get("status_path"),
            paths.get("receipts_path"),
            paths.get("submission_manifest_path"),
            _json(metadata or {}),
        ),
    )
    conn.commit()
    queued = load_execution(conn, job_id=job_id)
    assert queued is not None
    return queued


def claim_next_execution(
    conn: Any,
    *,
    owner: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    steal_expired: bool = False,
) -> dict[str, Any] | None:
    now = utc_now()
    row = conn.execute(
        """
        SELECT * FROM query_workflow_executions
        WHERE terminal = 0 AND state = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        ("queued",),
    ).fetchone()
    existing = _row_to_dict(row)
    if existing is None and steal_expired:
        row = conn.execute(
            """
            SELECT * FROM query_workflow_executions
            WHERE terminal = 0 AND state IN (?, ?) AND lease_expires_at_utc <= ?
            ORDER BY lease_expires_at_utc ASC, id ASC
            LIMIT 1
            """,
            ("running", "cancel_requested", now),
        ).fetchone()
        existing = _row_to_dict(row)
    if existing is None:
        return None
    metadata = metadata_json(existing)
    if str(existing.get("state") or "") == "running":
        metadata.setdefault("stolen_from_owner", existing.get("lease_owner"))
    next_state = "cancel_requested" if str(existing.get("state") or "") == "cancel_requested" else "running"
    conn.execute(
        """
        UPDATE query_workflow_executions
        SET state = ?, terminal = 0, lease_owner = ?, lease_expires_at_utc = ?,
            heartbeat_at_utc = ?, updated_at_utc = ?, metadata_json = ?
        WHERE id = ? AND terminal = 0
        """,
        (
            next_state,
            owner,
            _iso_after(now, lease_seconds),
            now,
            now,
            _json(metadata),
            existing["id"],
        ),
    )
    conn.commit()
    return load_execution(conn, job_id=str(existing.get("job_id") or ""))


def request_cancel_execution(
    conn: Any,
    *,
    job_id: str,
    actor: str = "",
    reason: str = "",
) -> dict[str, Any]:
    now = utc_now()
    row = load_execution(conn, job_id=job_id)
    if row is None:
        raise RuntimeError(f"query workflow execution not found: {job_id}")
    if bool(row.get("terminal")):
        raise RuntimeError(f"query workflow execution is terminal: {job_id}")
    metadata = metadata_json(row)
    metadata["cancel_requested_by"] = actor or None
    metadata["cancel_reason"] = reason or None
    metadata["cancel_requested_at_utc"] = now
    state = str(row.get("state") or "")
    if state == "queued":
        conn.execute(
            """
            UPDATE query_workflow_executions
            SET state = ?, terminal = 1, finished_at_utc = ?, updated_at_utc = ?,
                heartbeat_at_utc = ?, last_exit_code = ?, metadata_json = ?
            WHERE id = ?
            """,
            ("cancelled", now, now, now, 130, _json(metadata), row["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE query_workflow_executions
            SET state = ?, updated_at_utc = ?, metadata_json = ?
            WHERE id = ?
            """,
            ("cancel_requested", now, _json(metadata), row["id"]),
        )
    conn.commit()
    updated = load_execution(conn, job_id=job_id)
    assert updated is not None
    return updated


def heartbeat_execution(
    conn: Any,
    *,
    job_id: str,
    owner: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any]:
    now = utc_now()
    row = load_execution(conn, job_id=job_id)
    if row is None:
        raise RuntimeError(f"query workflow execution not found: {job_id}")
    if bool(row.get("terminal")):
        raise RuntimeError(f"query workflow execution is terminal: {job_id}")
    if str(row.get("lease_owner") or "") != owner:
        raise RuntimeError("query workflow execution lease owner mismatch")
    conn.execute(
        """
        UPDATE query_workflow_executions
        SET heartbeat_at_utc = ?, lease_expires_at_utc = ?, updated_at_utc = ?
        WHERE id = ?
        """,
        (now, _iso_after(now, lease_seconds), now, row["id"]),
    )
    conn.commit()
    updated = load_execution(conn, job_id=job_id)
    assert updated is not None
    return updated


def finish_execution(
    conn: Any,
    *,
    job_id: str,
    owner: str,
    exit_code: int | None,
    state: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    row = load_execution(conn, job_id=job_id)
    if row is None:
        raise RuntimeError(f"query workflow execution not found: {job_id}")
    if bool(row.get("terminal")):
        raise RuntimeError(f"query workflow execution is already terminal: {job_id}")
    if str(row.get("lease_owner") or "") != owner:
        raise RuntimeError("query workflow execution lease owner mismatch")
    final_state = state or ("completed" if exit_code in (None, 0) else "failed")
    if final_state not in {"completed", "failed", "cancelled", "timed_out"}:
        raise ValueError(f"unsupported terminal execution state: {final_state}")
    conn.execute(
        """
        UPDATE query_workflow_executions
        SET state = ?, terminal = 1, finished_at_utc = ?, updated_at_utc = ?,
            heartbeat_at_utc = ?, last_exit_code = ?, metadata_json = ?
        WHERE id = ?
        """,
        (final_state, now, now, now, exit_code, _json(metadata or {}), row["id"]),
    )
    conn.commit()
    updated = load_execution(conn, job_id=job_id)
    assert updated is not None
    return updated
