#!/usr/bin/env python3
"""Pure-Python mTLS proxy for PJC gRPC traffic — fallback for systems without socat.

Server mode (Party A):
  Listens on TLS_PORT, wraps in mTLS, forwards to PJC binary on loopback.

  python3 pjc_tls_proxy.py server \
    --cert config/tls/server.crt \
    --key  config/tls/server.key \
    --ca   config/tls/ca.crt \
    --tls-port  10502 \
    --local-port 10501

Client mode (Party B):
  Listens on LOCAL_PROXY_PORT, connects upstream over mTLS to Party A.

  python3 pjc_tls_proxy.py client \
    --cert config/tls/client.crt \
    --key  config/tls/client.key \
    --ca   config/tls/ca.crt \
    --server-host PARTY_A_IP \
    --tls-port    10502 \
    --local-port  10503
"""
import argparse
import socket
import ssl
import sys
import threading
from pathlib import Path


BUFSIZE = 65536


def _relay(src: socket.socket, dst: socket.socket, label: str) -> None:
    try:
        while True:
            data = src.recv(BUFSIZE)
            if not data:
                break
            dst.sendall(data)
    except (OSError, ssl.SSLError):
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """Bidirectional relay between two sockets in two threads."""
    t = threading.Thread(target=_relay, args=(a, b, "→"), daemon=True)
    t.start()
    _relay(b, a, "←")
    t.join(timeout=5)


def build_ssl_ctx(mode: str, *, cert: str, key: str, ca: str) -> ssl.SSLContext:
    side = ssl.Purpose.CLIENT_AUTH if mode == "server" else ssl.Purpose.SERVER_AUTH
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if mode == "server" else ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    if mode == "client":
        ctx.check_hostname = False  # we verify CA signature, not hostname
    return ctx


def run_server(*, tls_port: int, local_port: int, cert: str, key: str, ca: str, bind: str) -> None:
    ctx = build_ssl_ctx("server", cert=cert, key=key, ca=ca)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((bind, tls_port))
    listener.listen(8)
    print(f"[ok] TLS server listening on {bind}:{tls_port} → 127.0.0.1:{local_port}", flush=True)
    while True:
        raw, addr = listener.accept()
        try:
            tls_conn = ctx.wrap_socket(raw, server_side=True)
        except ssl.SSLError as e:
            print(f"[warn] TLS handshake failed from {addr}: {e}", flush=True)
            raw.close()
            continue
        try:
            local = socket.create_connection(("127.0.0.1", local_port), timeout=10)
        except OSError as e:
            print(f"[error] cannot reach PJC server on port {local_port}: {e}", flush=True)
            tls_conn.close()
            continue
        print(f"[info] accepted TLS connection from {addr}", flush=True)
        threading.Thread(target=_pipe, args=(tls_conn, local), daemon=True).start()


def run_client(*, server_host: str, tls_port: int, local_port: int, cert: str, key: str, ca: str) -> None:
    ctx = build_ssl_ctx("client", cert=cert, key=key, ca=ca)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", local_port))
    listener.listen(8)
    print(f"[ok] local proxy listening on 127.0.0.1:{local_port} → TLS → {server_host}:{tls_port}", flush=True)
    while True:
        local, _ = listener.accept()
        try:
            raw = socket.create_connection((server_host, tls_port), timeout=15)
            tls_conn = ctx.wrap_socket(raw, server_hostname=server_host)
        except (OSError, ssl.SSLError) as e:
            print(f"[error] cannot reach TLS server {server_host}:{tls_port}: {e}", flush=True)
            local.close()
            continue
        print(f"[info] TLS tunnel established to {server_host}:{tls_port}", flush=True)
        threading.Thread(target=_pipe, args=(local, tls_conn), daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser(description="mTLS proxy for PJC gRPC traffic.")
    ap.add_argument("mode", choices=["server", "client"])
    ap.add_argument("--cert", required=True, help="TLS certificate file")
    ap.add_argument("--key", required=True, help="TLS private key file")
    ap.add_argument("--ca", required=True, help="CA certificate file for peer verification")
    ap.add_argument("--tls-port", type=int, default=10502, help="External TLS port (default 10502)")
    ap.add_argument("--local-port", type=int, default=10501,
                    help="Loopback port: PJC server port in server mode, proxy listen port in client mode (default 10501/10503)")
    ap.add_argument("--bind", default="0.0.0.0", help="Bind address for server mode (default 0.0.0.0)")
    ap.add_argument("--server-host", default="", help="Party A's IP/hostname (client mode only)")
    args = ap.parse_args()

    for path in (args.cert, args.key, args.ca):
        if not Path(path).is_file():
            raise SystemExit(f"[error] file not found: {path}")

    if args.mode == "server":
        run_server(
            tls_port=args.tls_port,
            local_port=args.local_port,
            cert=args.cert,
            key=args.key,
            ca=args.ca,
            bind=args.bind,
        )
    else:
        if not args.server_host:
            raise SystemExit("[error] --server-host is required in client mode")
        local_port = args.local_port if args.local_port != 10501 else 10503
        run_client(
            server_host=args.server_host,
            tls_port=args.tls_port,
            local_port=local_port,
            cert=args.cert,
            key=args.key,
            ca=args.ca,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
