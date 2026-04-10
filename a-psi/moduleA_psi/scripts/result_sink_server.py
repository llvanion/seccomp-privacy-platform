#!/usr/bin/env python3
import argparse
import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_handler(out_dir: str, token: str):
    class ResultHandler(BaseHTTPRequestHandler):
        def _write(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/results":
                self._write(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
                return

            if token:
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {token}":
                    self._write(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._write(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return

            job_id = str(payload.get("job_id") or "unknown")
            payload["_received_at_utc"] = utc_now_iso()
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{job_id}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            self._write(HTTPStatus.OK, {"ok": True, "path": out_path})

        def log_message(self, fmt: str, *args) -> None:
            return

    return ResultHandler


def main() -> int:
    ap = argparse.ArgumentParser(description="Receive PJC result JSON via HTTP POST and save it to disk.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--out-dir", required=True, help="Directory for received result JSON files.")
    ap.add_argument("--token", default="", help="Optional bearer token required for uploads.")
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(os.path.abspath(args.out_dir), args.token))
    print(f"[info] result sink listening on {args.host}:{args.port}")
    print(f"[info] writing results to {os.path.abspath(args.out_dir)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
