#!/usr/bin/env python3
"""Smoke for typed TLS readiness probe."""
from __future__ import annotations

import json
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "pjc_tls_readiness.schema.json"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_json_contract import load_json, validate_value  # noqa: E402


SCHEMA = load_json(str(SCHEMA_PATH))


def _validate(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_value(payload, SCHEMA)
    return payload


def _spawn_tcp_eof_server() -> tuple[int, threading.Event]:
    stop = threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.4)
    port = listener.getsockname()[1]

    def _serve() -> None:
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

    threading.Thread(target=_serve, daemon=True).start()
    return port, stop


def _spawn_tls_server(cert_dir: Path) -> tuple[int, threading.Event]:
    stop = threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.4)
    port = listener.getsockname()[1]

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=str(cert_dir / "server.crt"), keyfile=str(cert_dir / "server.key"))
    ctx.load_verify_locations(cafile=str(cert_dir / "ca.crt"))

    def _serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                tls = ctx.wrap_socket(conn, server_side=True)
                tls.close()
            except OSError:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            listener.close()
        except OSError:
            pass

    threading.Thread(target=_serve, daemon=True).start()
    return port, stop


def _run_probe(*, job_id: str, cert_dir: Path, port: int, output: Path) -> dict:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_pjc_tls_readiness.py"),
        "--job-id", job_id,
        "--role", "client",
        "--peer-host", "127.0.0.1",
        "--peer-port", str(port),
        "--server-hostname", "pjc-server",
        "--cert-dir", str(cert_dir),
        "--output", str(output),
    ]
    subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return _validate(output)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pjc_tls_ready_") as tmp:
        tmp_path = Path(tmp)
        subprocess.run([
            sys.executable,
            str(REPO_ROOT / "scripts" / "create_pjc_mtls_session.py"),
            "--job-id", "tls-ready-smoke",
            "--out-dir", str(tmp_path / "session"),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cert_dir = tmp_path / "session"
        bundle = tmp_path / "session" / "party_b_bundle"

        closed_port = 6553
        report = _run_probe(job_id="closed", cert_dir=bundle, port=closed_port, output=tmp_path / "closed.json")
        assert report["status"] == "fail", report
        assert report["diagnostic"]["category"] in {"tcp_refused", "tcp_timeout", "tcp_unreachable", "other"}, report

        eof_port, eof_stop = _spawn_tcp_eof_server()
        try:
            time.sleep(0.05)
            report = _run_probe(job_id="eof", cert_dir=bundle, port=eof_port, output=tmp_path / "eof.json")
            assert report["status"] == "fail", report
            assert report["diagnostic"]["category"] in {"tls_eof", "tls_handshake_failed", "other"}, report
        finally:
            eof_stop.set()

        ok_port, ok_stop = _spawn_tls_server(cert_dir)
        try:
            time.sleep(0.05)
            report = _run_probe(job_id="ok", cert_dir=bundle, port=ok_port, output=tmp_path / "ok.json")
            assert report["status"] == "ok", report
            assert report["ready"] is True, report
            assert report["diagnostic"]["decision"] == "allow", report
        finally:
            ok_stop.set()

    print("[ok] PJC TLS readiness smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
