from pathlib import Path
import sys


def ensure_repo_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[2]
    sse_root = repo_root / "sse"
    scripts_root = repo_root / "scripts"
    for path in (repo_root, sse_root, scripts_root):
        raw = str(path)
        if raw not in sys.path:
            sys.path.insert(0, raw)
    return repo_root, sse_root
