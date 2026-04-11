from __future__ import annotations

import json
import logging
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from app.config import settings
from app.errors import GatewayError

logger = logging.getLogger(__name__)


class AAdapter:
    def _write_advertiser_input(
        self,
        *,
        job_dir: Path,
        exposure_records: list[dict[str, Any]],
        bucket_by: str | None,
    ) -> None:
        payload = {
            "bucket_by": bucket_by,
            "record_count": len(exposure_records),
            "records": exposure_records,
        }
        (job_dir / "advertiser_input.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_mock_report(
        self,
        *,
        job_id: str,
        start: int,
        end: int,
        k: int,
        n: int,
        value_mode: str,
        exposure_records: list[dict[str, Any]],
        bucket_by: str | None,
    ) -> dict[str, Any]:
        unique_users = {str(record.get("user_id", "")).strip() for record in exposure_records if record.get("user_id")}
        unique_user_count = len(unique_users)
        simulated_intersection = min(unique_user_count, unique_user_count // 3)

        bucket_stats: list[dict[str, Any]] = []
        if bucket_by:
            counts = Counter()
            for record in exposure_records:
                bucket_value = record.get(bucket_by)
                if bucket_value is None and isinstance(record.get("labels"), dict):
                    bucket_value = record["labels"].get(bucket_by)
                if bucket_value is None:
                    bucket_value = "unknown"
                counts[str(bucket_value)] += 1
            for bucket, count in sorted(counts.items()):
                bucket_stats.append(
                    {
                        "bucket": bucket,
                        "exposure_count": count,
                        "intersection_size": min(count, max(0, count // 3)),
                    }
                )

        released = simulated_intersection >= k
        reason_code = "allow" if released else "below_threshold"
        return {
            "job_id": job_id,
            "released": released,
            "reason_code": reason_code,
            "summary": {
                "exposure_record_count": len(exposure_records),
                "exposure_unique_users": unique_user_count,
                "intersection_size": simulated_intersection,
                "value_mode": value_mode,
            },
            "window": {"start_ts": start, "end_ts": end},
            "policy": {
                "k_threshold": k,
                "frequency_cap": n,
                "bucket_by": bucket_by,
            },
            "bucket_stats": bucket_stats,
        }

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
        exposure_records: list[dict[str, Any]] | None = None,
        bucket_by: str | None = None,
    ) -> dict[str, Any]:
        job_dir = Path(out_dir) if out_dir else settings.runs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        exposure_records = exposure_records or []
        self._write_advertiser_input(job_dir=job_dir, exposure_records=exposure_records, bucket_by=bucket_by)

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
            raise GatewayError(
                "a_report_missing",
                f"A pipeline completed but report not found: {report_path}",
                status_code=502,
            )

        # Fallback mock report for local C demo before A/B merge.
        mock_report = self._build_mock_report(
            job_id=job_id,
            start=start,
            end=end,
            k=k,
            n=n,
            value_mode=value_mode,
            exposure_records=exposure_records,
            bucket_by=bucket_by,
        )
        (job_dir / "public_report.json").write_text(
            json.dumps(mock_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return mock_report

    def read_report(self, *, job_id: str, out_dir: str | None = None) -> dict[str, Any]:
        job_dir = Path(out_dir) if out_dir else settings.runs_root / job_id
        report_path = job_dir / "public_report.json"
        if not report_path.exists():
            raise GatewayError("a_report_missing", f"report not found for job_id={job_id}", status_code=404)
        return json.loads(report_path.read_text(encoding="utf-8"))
