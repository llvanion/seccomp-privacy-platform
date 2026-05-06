#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from metadata_db import apply_migrations, connect_db


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize the sidecar metadata database and apply SQL migrations.")
    ap.add_argument("--db-path", default="")
    ap.add_argument("--db-dsn", default="")
    args = ap.parse_args()
    if not args.db_path and not args.db_dsn:
        raise SystemExit("[ERROR] one of --db-path or --db-dsn is required")

    conn = connect_db(args.db_path, dsn=args.db_dsn)
    try:
        applied = apply_migrations(conn)
    finally:
        conn.close()

    print(json.dumps({
        "db_path": str(Path(args.db_path).resolve()) if args.db_path else None,
        "db_dsn": args.db_dsn or None,
        "applied_migrations": applied,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
