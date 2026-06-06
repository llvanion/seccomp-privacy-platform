#!/usr/bin/env python3
"""Shared helper for resolving the effective PJC binary directory."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_pjc_bin_dir(
    *,
    workspace: Path,
    requested_bin_dir: Path | None = None,
    require_streaming: bool = False,
) -> dict[str, Any]:
    """Run the binary capability gate and return its JSON report."""
    out_dir = Path(tempfile.mkdtemp(prefix="pjc_bin_gate_"))
    out_path = out_dir / "pjc_binary_capability_gate.json"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_pjc_binary_capability_gate.py"),
        "--workspace", str(Path(workspace).resolve()),
        "--out", str(out_path),
    ]
    if requested_bin_dir is not None:
        cmd.extend(["--requested-bin-dir", str(Path(requested_bin_dir).resolve())])
    if require_streaming:
        cmd.append("--require-streaming")
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if not out_path.is_file():
        raise RuntimeError(
            "pjc binary capability gate did not produce a report\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    report = json.loads(out_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise RuntimeError(f"unexpected non-object report: {out_path}")
    return report
