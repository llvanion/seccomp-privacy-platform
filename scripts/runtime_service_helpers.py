#!/usr/bin/env python3
import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, build_opener


def available_port(*, host: str = "127.0.0.1") -> int:
    """Return a likely-free TCP port on ``host``.

    Caveat — this helper is best-effort, not a reservation. The returned port
    is the one the kernel assigned to a temporary socket that is then closed;
    another process can win the race between this call and the caller's own
    ``bind()``. We set ``SO_REUSEADDR`` so the most common race outcome
    (TIME_WAIT collision after our socket closes) does not block the real
    service from re-binding. For a hard reservation, use
    :func:`reserve_available_port`, which keeps the socket open and lets the
    caller hand it to the real listener via ``socket.fromfd`` / ``adopt``.
    """
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def reserve_available_port(*, host: str = "127.0.0.1") -> tuple[int, socket.socket]:
    """Return ``(port, sock)`` for a port that is held open until ``sock`` closes.

    Callers running entirely in-process can keep ``sock`` open until the real
    listener binds; this eliminates the TOCTOU window from
    :func:`available_port`. ``SO_REUSEADDR`` is set on both sockets, so the
    real listener can ``bind()`` to ``port`` while ``sock`` is still
    technically holding it (the real listener owns the four-tuple once it
    accepts).
    """
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    return int(sock.getsockname()[1]), sock


def tcp_port_ready(*, host: str, port: int, connect_timeout_sec: float = 0.2) -> bool:
    with socket.socket() as sock:
        sock.settimeout(connect_timeout_sec)
        return sock.connect_ex((host, port)) == 0


def wait_for_tcp_port(
    *,
    host: str,
    port: int,
    timeout_sec: float,
    interval_sec: float = 0.1,
    connect_timeout_sec: float = 0.2,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if tcp_port_ready(host=host, port=port, connect_timeout_sec=connect_timeout_sec):
            return
        time.sleep(interval_sec)
    raise RuntimeError(f"TCP port did not become ready in time: {host}:{port}")


def fetch_json(url: str, *, timeout_sec: float = 0.5) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    with opener.open(url, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON object expected from {url}")
    return payload


def wait_for_json_health(
    *,
    url: str,
    timeout_sec: float,
    interval_sec: float = 0.1,
    request_timeout_sec: float = 0.5,
    ok_field: str = "ok",
    ok_value: Any = True,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload = fetch_json(url, timeout_sec=request_timeout_sec)
            if payload.get(ok_field) == ok_value:
                return payload
            last_error = f"unexpected {ok_field}={payload.get(ok_field)!r}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(interval_sec)
    message = f"JSON health endpoint did not become ready in time: {url}"
    if last_error:
        message = f"{message} ({last_error})"
    raise RuntimeError(message)


def _walk_json_field(payload: Any, field_path: str) -> Any:
    value = payload
    for part in field_path.split("."):
        if not isinstance(value, dict):
            raise KeyError(field_path)
        value = value[part]
    return value


def read_json_field(
    *,
    field_path: str,
    json_file: Path | None = None,
    default: str | None = None,
) -> Any:
    if json_file is None:
        payload = json.load(sys.stdin)
    else:
        with json_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    try:
        return _walk_json_field(payload, field_path)
    except KeyError:
        if default is not None:
            return default
        raise


def parse_ok_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    return raw


def render_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Shared runtime helpers for local service orchestration and contract smoke.")
    sub = ap.add_subparsers(dest="command", required=True)

    port = sub.add_parser("available-port", help="Print an available TCP port on the local host.")
    port.add_argument("--host", default="127.0.0.1")

    wait_health = sub.add_parser("wait-json-health", help="Wait for a JSON health endpoint to report ok=true.")
    wait_health.add_argument("--url", required=True)
    wait_health.add_argument("--timeout-sec", type=float, default=10.0)
    wait_health.add_argument("--interval-sec", type=float, default=0.1)
    wait_health.add_argument("--request-timeout-sec", type=float, default=0.5)
    wait_health.add_argument("--ok-field", default="ok")
    wait_health.add_argument("--ok-value", default="true")

    wait_port = sub.add_parser("wait-tcp-port", help="Wait for a TCP listener to accept connections.")
    wait_port.add_argument("--host", default="127.0.0.1")
    wait_port.add_argument("--port", required=True, type=int)
    wait_port.add_argument("--timeout-sec", type=float, default=10.0)
    wait_port.add_argument("--interval-sec", type=float, default=0.1)
    wait_port.add_argument("--connect-timeout-sec", type=float, default=0.2)

    check_port = sub.add_parser("check-tcp-port", help="Exit 0 when a TCP listener is accepting connections.")
    check_port.add_argument("--host", default="127.0.0.1")
    check_port.add_argument("--port", required=True, type=int)
    check_port.add_argument("--connect-timeout-sec", type=float, default=0.2)

    read_field = sub.add_parser("read-json-field", help="Read a dotted JSON field from a file or stdin.")
    read_field.add_argument("--field", required=True)
    read_field.add_argument("--json-file", default="")
    read_field.add_argument("--default", default=None)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "available-port":
        print(available_port(host=args.host))
        return 0
    if args.command == "wait-json-health":
        wait_for_json_health(
            url=args.url,
            timeout_sec=args.timeout_sec,
            interval_sec=args.interval_sec,
            request_timeout_sec=args.request_timeout_sec,
            ok_field=args.ok_field,
            ok_value=parse_ok_value(args.ok_value),
        )
        return 0
    if args.command == "wait-tcp-port":
        wait_for_tcp_port(
            host=args.host,
            port=args.port,
            timeout_sec=args.timeout_sec,
            interval_sec=args.interval_sec,
            connect_timeout_sec=args.connect_timeout_sec,
        )
        return 0
    if args.command == "check-tcp-port":
        return 0 if tcp_port_ready(host=args.host, port=args.port, connect_timeout_sec=args.connect_timeout_sec) else 1
    if args.command == "read-json-field":
        json_file = Path(args.json_file) if args.json_file else None
        print(render_value(read_json_field(field_path=args.field, json_file=json_file, default=args.default)))
        return 0
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
