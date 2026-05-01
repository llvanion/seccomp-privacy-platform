#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from metadata_db import apply_migrations, connect_db


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize the sidecar metadata database and apply SQL migrations.")
    ap.add_argument("--db-path", required=True)
    args = ap.parse_args()

    conn = connect_db(args.db_path)
    try:
        applied = apply_migrations(conn)
    finally:
        conn.close()

    print(json.dumps({
        "db_path": str(Path(args.db_path).resolve()),
        "applied_migrations": applied,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
