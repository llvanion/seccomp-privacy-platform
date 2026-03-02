from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class AAdapter:
    def run_psi(
        self,
        *,
        job_id: str,
        start: int,
        end: int,
        k: int,
        caller: str,
        n: int,
        value_mode: str,
        out_dir: str | None = None,
    ) -> dict:
        job_dir = Path(out_dir) if out_dir else settings.runs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        if settings.a_pipeline_script and Path(settings.a_pipeline_script).exists() and settings.a_criteo_tsv:
            cmd = [
                "bash",
                settings.a_pipeline_script,
                "--criteo-tsv",
                settings.a_criteo_tsv,
                "--start-ts",
                str(start),
                "--end-ts",
                str(end),
                "--value-mode",
                value_mode,
                "--out",
                str(job_dir),
                "--job-id",
                job_id,
                "--k",
                str(k),
                "--caller",
                caller,
                "--n",
                str(n),
            ]
            logger.info("Executing A pipeline: %s", " ".join(cmd))
            subprocess.run(cmd, check=True)

            report_path = job_dir / "public_report.json"
            if report_path.exists():
                return json.loads(report_path.read_text(encoding="utf-8"))

        # Fallback mock report for local C demo before A/B merge.
        mock_report = {
            "job_id": job_id,
            "released": True,
            "reason": "ok",
            "reason_code": "allow",
            "conversions": 12,
            "value_sum": 12,
            "aov": 1,
            "window": {"start_ts": start, "end_ts": end},
            "k_threshold": k,
            "rate_limit_used": 1,
            "rate_limit_max": n,
        }
        (job_dir / "public_report.json").write_text(
            json.dumps(mock_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return mock_report
