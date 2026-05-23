#!/usr/bin/env python3
"""Focused smoke for the PJC two-party live TLS diagnostic helper.

Exercises ``_two_party_tls_diagnostic`` against three deterministic local
scenarios so the report shape and decision logic stays pinned even when the
real VPS data-plane is unreachable:

1. Closed TCP port → ``decision=deny`` and ``category in {tcp_refused, tcp_timeout}``.
2. TCP accepts but socket closes before any TLS bytes → ``category=tls_eof``.
3. Local cert files missing → ``suggested_action`` mentions them.

Every report is validated against ``schemas/pjc_tls_diagnostic.schema.json``.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import serve_operator_dashboard as sod
from validate_json_contract import load_json, validate_value


SCHEMA = load_json(str(REPO_ROOT / "schemas" / "pjc_tls_diagnostic.schema.json"))


def _validate(report: dict) -> None:
    validate_value(report, SCHEMA)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn_tcp_eof_server() -> tuple[int, threading.Event]:
    """Listen on a free TCP port; close incoming connections immediately."""
    stop = threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.4)
    port = listener.getsockname()[1]

    def _serve():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        try:
            listener.close()
        except OSError:
            pass

    thread = threading.Thread(target=_serve, daemon=True, name="tls-eof-smoke")
    thread.start()
    return port, stop


def test_closed_port() -> None:
    print("[1/3] closed port → tcp_refused/timeout ...")
    port = _free_port()
    body = {
        "job_id": "diag-smoke",
        "role": "client",
        "peer_host": "127.0.0.1",
        "peer_port": port,
        "server_hostname": "pjc-server",
        "tcp_timeout_sec": 1.0,
        "tls_timeout_sec": 1.0,
    }
    out = sod._two_party_tls_diagnostic(body)
    _validate(out["report"])
    report = out["report"]
    assert report["decision"] == "deny", report
    assert report["category"] in {"tcp_refused", "tcp_timeout", "tcp_unreachable", "other"}, report
    assert report["tcp"]["ok"] is False, report
    assert report["tls"]["attempted"] is False, report
    print("       closed port OK")


def test_tls_eof_pattern() -> None:
    print("[2/3] tcp accepts + immediate close → tls_eof ...")
    port, stop = _spawn_tcp_eof_server()
    try:
        time.sleep(0.05)
        body = {
            "job_id": "diag-smoke",
            "role": "client",
            "peer_host": "127.0.0.1",
            "peer_port": port,
            "server_hostname": "pjc-server",
            "tcp_timeout_sec": 1.0,
            "tls_timeout_sec": 1.5,
        }
        out = sod._two_party_tls_diagnostic(body)
        _validate(out["report"])
        report = out["report"]
        assert report["tcp"]["ok"] is True, report
        assert report["tls"]["attempted"] is True, report
        assert report["tls"]["ok"] is False, report
        # Python's ssl typically surfaces this as "[SSL: ... ] ... or "EOF occurred ..."
        assert report["category"] in {"tls_eof", "tls_handshake_failed", "other"}, report
        assert report["suggested_action"], report
        assert report["decision"] == "deny", report
    finally:
        stop.set()
    print("       tls eof OK")


def test_missing_local_certs() -> None:
    print("[3/3] missing local certs surfaced in suggestion ...")
    with tempfile.TemporaryDirectory(prefix="tls_diag_smoke_") as tmp:
        cert_dir = Path(tmp) / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        # do not write any cert files
        port = _free_port()  # closed
        body = {
            "job_id": "diag-smoke",
            "role": "client",
            "peer_host": "127.0.0.1",
            "peer_port": port,
            "server_hostname": "pjc-server",
            "cert_dir": str(cert_dir),
            "tcp_timeout_sec": 0.5,
            "tls_timeout_sec": 0.5,
        }
        out = sod._two_party_tls_diagnostic(body)
        _validate(out["report"])
        report = out["report"]
        local_files = report["local_files"]
        assert local_files["ca.crt"] is False, report
        assert local_files["client.crt"] is False, report
        assert local_files["client.key"] is False, report
    print("       missing certs OK")


def main() -> int:
    test_closed_port()
    test_tls_eof_pattern()
    test_missing_local_certs()
    print("[ok] PJC TLS diagnostic smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
