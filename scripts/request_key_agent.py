#!/usr/bin/env python3
import argparse
import json
import os
import socket


def main() -> int:
    ap = argparse.ArgumentParser(description="Request a secret from the local Unix-socket key agent.")
    ap.add_argument("--socket-path", required=True)
    ap.add_argument("--key-name", required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--job-id", default="")
    ap.add_argument("--auth-token-env", default="")
    ap.add_argument("--identity-token-env", default="")
    args = ap.parse_args()

    payload = {
        "caller": args.caller,
        "job_id": args.job_id,
        "key_name": args.key_name,
        "purpose": args.purpose,
    }
    if args.auth_token_env:
        auth_token = os.environ.get(args.auth_token_env)
        if not auth_token:
            raise SystemExit(f"[ERROR] environment variable {args.auth_token_env} is not set")
        payload["auth_token"] = auth_token
    if args.identity_token_env:
        identity_token = os.environ.get(args.identity_token_env)
        if not identity_token:
            raise SystemExit(f"[ERROR] environment variable {args.identity_token_env} is not set")
        payload["identity_bearer_token"] = identity_token

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(args.socket_path)
        client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = client.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as e:
        raise SystemExit(f"[ERROR] key agent request failed: {e}") from e
    finally:
        client.close()

    raw = b"".join(chunks)
    if not raw:
        raise SystemExit("[ERROR] key agent returned an empty response")
    try:
        result = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"[ERROR] key agent returned invalid JSON: {e}") from e
    if not isinstance(result, dict):
        raise SystemExit("[ERROR] key agent returned a non-object result")
    if result.get("schema") == "key_agent_error/v1":
        raise SystemExit(f"[ERROR] {result.get('error', 'key agent failed')}")
    if result.get("schema") != "key_agent_result/v1":
        raise SystemExit(f"[ERROR] unexpected key agent schema: {result.get('schema')}")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
