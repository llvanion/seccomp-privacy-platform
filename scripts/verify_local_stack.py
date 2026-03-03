from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8080"


def assert_ok(resp: httpx.Response, step: str) -> dict:
    if resp.status_code != 200:
        raise RuntimeError(f"{step} failed: status={resp.status_code}, body={resp.text}")
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"{step} failed: code={body.get('code')}, body={body}")
    return body


def run() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        health = assert_ok(c.get("/health"), "health")
        print("[ok] health:", health["data"])

        build = assert_ok(
            c.post(
                "/se/index/build",
                json={
                    "index_name": "verify_index",
                    "records": [
                        {"keys": ["k1", "k2"], "values": ["v1", "v2"]},
                        {"keys": ["k2"], "values": ["v3"]},
                    ],
                },
            ),
            "se/index/build",
        )
        print("[ok] build:", build["data"])

        search = assert_ok(
            c.post("/se/search", json={"index_name": "verify_index", "keyword": "k2"}),
            "se/search",
        )
        print("[ok] search:", search["data"])

        attr = assert_ok(
            c.post(
                "/attribution/run",
                json={
                    "job_id": "verify_job",
                    "start_ts": 1596439471,
                    "end_ts": 1596445871,
                    "k": 20,
                    "caller": "verify_client",
                    "n": 5,
                    "value_mode": "count",
                },
            ),
            "attribution/run",
        )
        print("[ok] attribution:", attr["data"]["reason_code"])

        audit = assert_ok(c.get("/audit/query", params={"limit": 20}), "audit/query")
        if audit["data"]["total"] <= 0:
            raise RuntimeError("audit/query failed: expected non-empty rows")
        print("[ok] audit total:", audit["data"]["total"])

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"VERIFY FAILED: {exc}")
        sys.exit(1)
