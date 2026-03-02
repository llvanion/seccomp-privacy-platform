# Member C Gateway (W1-W3 demo)

This folder contains the first deliverable for member C:

- W1: FastAPI gateway skeleton + unified response
- W2: Adapter for module A pipeline (`run_pipeline.sh`) with local mock fallback
- W3: Adapter for module B (Python-side local index demo)

## Endpoints

- `GET /health`
- `POST /attribution/run`
- `POST /se/index/build`
- `POST /se/search`

All endpoints return unified structure:

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "timestamp": "2026-03-02T00:00:00+00:00"
}
```

## Quick start

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
python scripts/run_local_demo.py
```

## A adapter behavior

If env vars are set and script exists:

- `A_PIPELINE_SCRIPT`
- `A_CRITEO_TSV`

then `/attribution/run` executes A pipeline script and reads `public_report.json` from `RUNS_ROOT/<job_id>`.

Otherwise it generates a local mock `public_report.json` for demo.

## B adapter behavior

Current W3 demo uses an in-process Python index (same multi-key semantics as B README examples) so member C can demo before merge.
When branch merge happens, we will replace this adapter implementation with direct B Python API calls.
