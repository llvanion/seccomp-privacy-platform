# Member C Gateway

Member C gateway provides a unified REST access layer for:

- Module A (PSI / attribution pipeline)
- Module B (SSE / searchable encryption)

It also provides:

- Unified response and error shape
- Rate limiting (Redis or in-memory fallback)
- Audit logging (SQLite or JSONL fallback)
- Local demo and verification scripts

## 1) API Overview

### Endpoints

- `GET /health`
- `POST /attribution/run`
- `POST /se/index/build`
- `POST /se/search`
- `GET /audit/query`

### Unified success response

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "timestamp": "2026-03-03T00:00:00+00:00"
}
```

### Unified error response

```json
{
  "code": 429,
  "message": "rate limit exceeded",
  "data": {
    "reason_code": "rate_limit_exceeded",
    "details": {}
  },
  "timestamp": "2026-03-03T00:00:00+00:00"
}
```

## 2) Module Integration

### Module A integration

If both env vars are set, `/attribution/run` executes A pipeline and reads `public_report.json`:

- `A_PIPELINE_SCRIPT`
- `A_CRITEO_TSV`

If missing, gateway uses local mock report for demo.

### Module B integration

`B_BACKEND`:

- `auto` (default): try `python_api`, fallback to `local`
- `python_api`: strict B Python API integration
- `local`: in-process fallback index (demo mode)

For `python_api` mode:

- `B_SSE_ROOT`: path to B repo/worktree
- `B_SERVER_URI`: B WebSocket server URI (default `ws://127.0.0.1:8001`)
- `B_SCHEME`: SSE scheme (default `CJJ14.PiBas`)

## 3) Security and Observability

### Rate limit

- Backend: `RATE_LIMIT_BACKEND=auto|redis|memory`
- Redis URL: `REDIS_URL`
- Limit/window:
  - `RATE_LIMIT_MAX_PER_ACTOR_ACTION`
  - `RATE_LIMIT_WINDOW_SECONDS`

### Audit

- Backend: `AUDIT_BACKEND=sqlite|jsonl`
- SQLite path: `AUDIT_DB_PATH`
- JSONL path: `AUDIT_JSONL_PATH`
- Query endpoint: `GET /audit/query?action=&actor=&start_ts=&end_ts=&limit=`

## 4) Configuration

Copy and edit env file:

```bash
cp .env.example .env
```

See `.env.example` for all options.

## 5) Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Run demo:

```bash
python scripts/run_local_demo.py
```

Run checks:

```bash
python scripts/verify_local_stack.py
```

## 6) Local Validation Scope

`scripts/verify_local_stack.py` validates:

- health endpoint
- SSE index build/search flow
- attribution run flow
- audit query availability

## 7) Notes

- This branch does not modify A/B source code.
- B integration is implemented on C side only.

---

Chinese README will be added in a follow-up update.
