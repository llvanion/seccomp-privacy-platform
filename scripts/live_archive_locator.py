from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def find_latest_live_archive(
    *,
    repo_root: Path,
    canonical_dirname: str,
    archive_filename: str,
    expected_schema: str,
) -> Path | None:
    candidates = sorted((repo_root / "tmp").glob(f"{canonical_dirname}*"))
    valid: list[tuple[float, Path]] = []
    for directory in candidates:
        if not directory.is_dir():
            continue
        archive_path = directory / archive_filename
        if not archive_path.is_file():
            continue
        payload = _load_json_object(archive_path)
        if payload is None:
            continue
        if str(payload.get("schema") or "") != expected_schema:
            continue
        valid.append((archive_path.stat().st_mtime, archive_path))
    if not valid:
        return None
    valid.sort(key=lambda item: (item[0], str(item[1])))
    return valid[-1][1]
