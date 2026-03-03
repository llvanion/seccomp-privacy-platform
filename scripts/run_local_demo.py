from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"


def run_demo() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        print("[1] health")
        print(c.get("/health").json())

        print("[2] se index build")
        build_payload = {
            "index_name": "demo_index",
            "records": [
                {"keys": ["China", "中国", "CN"], "values": ["enc_a1", "enc_a2"]},
                {"keys": ["Github", "代码托管"], "values": ["enc_g1"]},
            ],
        }
        print(c.post("/se/index/build", json=build_payload).json())

        print("[3] se search")
        print(c.post("/se/search", json={"index_name": "demo_index", "keyword": "中国"}).json())

        print("[4] attribution run (mock fallback when A env is not configured)")
        payload = {
            "job_id": "demo_job_001",
            "start_ts": 1596439471,
            "end_ts": 1596445871,
            "k": 20,
            "caller": "member_c_demo",
            "n": 5,
            "value_mode": "count",
        }
        resp = c.post("/attribution/run", json=payload).json()
        print(resp)

        print("[5] audit query")
        print(c.get("/audit/query", params={"limit": 10}).json())

        report_path = Path("runs/demo_job_001/public_report.json")
        if report_path.exists():
            print("public_report.json:")
            print(json.loads(report_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    run_demo()
