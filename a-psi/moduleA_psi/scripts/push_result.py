#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser(description="Push a PJC result JSON to a callback endpoint.")
    ap.add_argument("--url", required=True, help="HTTP endpoint that accepts POSTed JSON.")
    ap.add_argument("--result", required=True, help="Path to attribution_result.json.")
    ap.add_argument("--token", default="", help="Optional bearer token for Authorization header.")
    args = ap.parse_args()

    result_path = os.path.abspath(args.result)
    if not os.path.isfile(result_path):
        raise SystemExit(f"missing result file: {result_path}")

    with open(result_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(args.url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if args.token:
      req.add_header("Authorization", f"Bearer {args.token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"[ok] pushed result to {args.url} status={resp.status}")
            if body.strip():
                print(body.strip())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(body, file=sys.stderr)
        raise SystemExit(f"HTTP {e.code} when pushing result to {args.url}")
    except urllib.error.URLError as e:
        raise SystemExit(f"network error when pushing result to {args.url}: {e.reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

