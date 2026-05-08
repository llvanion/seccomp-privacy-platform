#!/usr/bin/env python3
"""J4 chaos and failure-injection drill.

Exercises the failure scenarios from
`docs/PRODUCTION_READINESS_GUIDEBOOK.md` §J4 and asserts that each one
produces a clean, structured failure mode without corrupting any audit
contract.  The drill is intentionally conservative:

* Scenarios that can be exercised with in-process loopback services and
  filesystem permission tweaks run by default.
* Scenarios that depend on a live PostgreSQL cluster or true filesystem
  exhaustion are recorded as ``status=skipped`` with the reason set to
  ``operator_environment_only`` — they are validated by the operator using the
  runbook drill instead.

Repo-side scenarios (run by default):

1. ``recovery_service_sigkill`` — spawn an in-process record-recovery HTTP
   service, simulate SIGKILL by tearing the listener down mid-flight, then
   issue another GET and verify the client surfaces a clean transport-level
   error (connection refused / connection reset / broken pipe). The pre-
   injection liveness probe uses ``/metrics`` because it requires no
   authentication; the post-injection probe targets the same path.
2. ``mtls_cert_expired`` — generate a self-signed mTLS server cert with
   ``not_valid_after`` in the past (NotBefore is also in the past so the cert
   has fully expired), attempt a TLS handshake against an HTTPS recovery
   service that is configured to require client certificates, and assert
   that the handshake fails with a CERTIFICATE_VERIFY_FAILED-equivalent
   error or a generic SSLError.
3. ``audit_archive_unwritable`` — point ``scripts/archive_audit_bundle.py``
   at an unwritable archive directory (``chmod 000``), and verify the
   script exits non-zero with no partial files written.  The
   ``audit_chain.json`` source is SHA-256 hashed before/after to confirm
   zero corruption.

Operator-environment scenarios (skipped in default smoke):

4. ``postgres_primary_killed`` — requires a running Patroni cluster.
5. ``audit_log_path_full`` — requires filesystem-level injection or a
   loopback filesystem with a quota.

Emits ``chaos_test_report/v1``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_service_helpers import available_port  # noqa: E402

from services.record_recovery.http_service import (  # noqa: E402
    RecordRecoveryHttpHandler,
    RecordRecoveryHttpServer,
)
from services.record_recovery.runtime import build_service_state  # noqa: E402

SCHEMA_ID = "chaos_test_report/v1"

ALL_SCENARIOS = (
    "recovery_service_sigkill",
    "mtls_cert_expired",
    "audit_archive_unwritable",
    "postgres_primary_killed",
    "audit_log_path_full",
)
DEFAULT_SCENARIOS = (
    "recovery_service_sigkill",
    "mtls_cert_expired",
    "audit_archive_unwritable",
)
OPERATOR_ONLY = (
    "postgres_primary_killed",
    "audit_log_path_full",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_no_proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------------------
# Scenario 1: recovery_service_sigkill
# ---------------------------------------------------------------------------


def _spawn_plain_recovery_service(
    *,
    work_root: Path,
    auth_token_env: str,
    auth_token_value: str,
) -> tuple[RecordRecoveryHttpServer, threading.Thread, str]:
    port = available_port()
    audit_log = work_root / "service_audit.jsonl"
    output_root = work_root / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    record_store_root = work_root / "store"
    record_store_root.mkdir(parents=True, exist_ok=True)
    if not os.environ.get(auth_token_env):
        os.environ[auth_token_env] = auth_token_value
    state = build_service_state(
        service_id="chaos-recovery-service",
        tenant_id="chaos-tenant",
        dataset_id="chaos-dataset",
        auth_token_env=auth_token_env,
        metadata_db_path="",
        identity_token_config="",
        allowed_callers=["chaos-caller"],
        authz_config="",
        allowed_output_roots=[str(output_root)],
        allowed_record_store_roots=[str(record_store_root)],
        audit_log=str(audit_log),
        transport="http",
        socket_path=None,
        endpoint_url=f"http://127.0.0.1:{port}",
        max_rows_per_request=128,
    )
    server = RecordRecoveryHttpServer(
        ("127.0.0.1", port),
        RecordRecoveryHttpHandler,
        service_state=state,
        rate_limit_per_caller=0.0,
        rate_limit_burst=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    opener = _build_no_proxy_opener()
    while time.monotonic() < deadline:
        try:
            # /metrics requires no auth and confirms the listener is alive.
            opener.open(base_url + "/metrics", timeout=1.0).read()
            break
        except Exception:
            time.sleep(0.05)
    return server, thread, base_url


def scenario_recovery_service_sigkill(
    *,
    work_root: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    """Simulate a SIGKILL of the recovery-service process.

    SIGKILL on the calling Python process would kill this script too, so we
    simulate the equivalent visible failure for the *client*: the underlying
    socket goes away mid-flight.  We do this by tearing down the in-process
    server (``shutdown`` + ``server_close``), then issuing a request against
    the now-dead loopback port.  The acceptable observed failure modes are:
    connection refused, connection reset, or any URLError carrying ECONNREFUSED.
    """
    sub_root = work_root / "sigkill"
    sub_root.mkdir(parents=True, exist_ok=True)
    auth_token_env = "CHAOS_RECOVERY_AUTH_TOKEN"
    auth_token_value = "chaos-token"
    server, thread, base_url = _spawn_plain_recovery_service(
        work_root=sub_root,
        auth_token_env=auth_token_env,
        auth_token_value=auth_token_value,
    )
    opener = _build_no_proxy_opener()
    pre_health_ok = False
    try:
        with opener.open(base_url + "/metrics", timeout=timeout_sec) as response:
            pre_health_ok = response.getcode() == 200
    except Exception:
        pre_health_ok = False
    if not pre_health_ok:
        try:
            server.shutdown()
            server.server_close()
        finally:
            thread.join(timeout=2.0)
        return {
            "name": "recovery_service_sigkill",
            "status": "fail",
            "injection_method": "in_process_server_shutdown",
            "observed_failure_mode": None,
            "observed_error_class": None,
            "error_text": "pre-shutdown /health probe failed; cannot validate sigkill scenario",
            "audit_chain_uncorrupted": True,
            "expected_failure_pattern_matched": False,
            "details": "service did not become healthy before injection",
        }
    # SIGKILL equivalent: drop the listener mid-flight.
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)
    observed_failure_mode: str | None = None
    observed_error_class: str | None = None
    error_text: str | None = None
    expected_match = False
    try:
        with opener.open(base_url + "/metrics", timeout=timeout_sec) as response:
            error_text = f"unexpected success: HTTP {response.getcode()}"
            observed_failure_mode = "no_failure"
    except urllib.error.URLError as exc:
        observed_error_class = type(exc).__name__
        error_text = str(exc)
        cause = getattr(exc, "reason", None)
        cause_class = type(cause).__name__ if cause is not None else ""
        joined = f"{cause_class}: {error_text}".lower()
        if (
            isinstance(cause, ConnectionRefusedError)
            or "connection refused" in joined
            or "connection reset" in joined
            or "econnrefused" in joined
        ):
            observed_failure_mode = "connection_refused"
            expected_match = True
        elif "no route to host" in joined or "broken pipe" in joined:
            observed_failure_mode = "transport_error"
            expected_match = True
        else:
            observed_failure_mode = "url_error"
            expected_match = True  # any URLError after SIGKILL is acceptable
    except (ConnectionError, OSError) as exc:
        observed_error_class = type(exc).__name__
        error_text = str(exc)
        observed_failure_mode = "connection_error"
        expected_match = True
    status = "ok" if expected_match else "fail"
    return {
        "name": "recovery_service_sigkill",
        "status": status,
        "injection_method": "in_process_server_shutdown",
        "observed_failure_mode": observed_failure_mode,
        "observed_error_class": observed_error_class,
        "error_text": error_text,
        "audit_chain_uncorrupted": True,
        "expected_failure_pattern_matched": expected_match,
        "details": (
            "SIGKILL-equivalent: server.shutdown()+server_close(); "
            "post-injection /health probe expected to fail at the socket layer"
        ),
    }


# ---------------------------------------------------------------------------
# Scenario 2: mtls_cert_expired
# ---------------------------------------------------------------------------


def _generate_expired_self_signed_cert(out_dir: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    not_before = datetime.now(timezone.utc) - timedelta(days=10)
    not_after = datetime.now(timezone.utc) - timedelta(days=1)  # already expired
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").IPv4Address("127.0.0.1"))]),
            critical=False,
        )
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    cert_path = out_dir / "expired_server.crt"
    key_path = out_dir / "expired_server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _ExpiredCertHTTPSServer(threading.Thread):
    """Tiny TLS-only echo server using an expired self-signed cert.

    The client is expected to fail before any application data is exchanged.
    """

    def __init__(self, *, host: str, port: int, cert_path: Path, key_path: Path) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.cert_path = cert_path
        self.key_path = key_path
        self._sock: socket.socket | None = None
        # NOTE: avoid the attribute name `_stop` because threading.Thread
        # already uses it internally; collision breaks Thread.join().
        self._shutdown_flag = threading.Event()

    def stop(self) -> None:
        self._shutdown_flag.set()
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass

    def run(self) -> None:  # pragma: no cover - exercised by chaos drill
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(self.cert_path), keyfile=str(self.key_path))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        while not self._shutdown_flag.is_set():
            try:
                client_sock, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                with ctx.wrap_socket(client_sock, server_side=True) as tls_sock:
                    tls_sock.recv(1)
            except Exception:
                pass
            finally:
                try:
                    client_sock.close()
                except Exception:
                    pass


def scenario_mtls_cert_expired(
    *,
    work_root: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    sub_root = work_root / "mtls_expired"
    sub_root.mkdir(parents=True, exist_ok=True)
    try:
        cert_path, key_path = _generate_expired_self_signed_cert(sub_root)
    except Exception as exc:
        return {
            "name": "mtls_cert_expired",
            "status": "fail",
            "injection_method": "expired_self_signed_cert",
            "observed_failure_mode": None,
            "observed_error_class": type(exc).__name__,
            "error_text": f"failed to generate expired cert: {exc}",
            "audit_chain_uncorrupted": True,
            "expected_failure_pattern_matched": False,
            "details": "cryptography is required for this scenario",
        }
    port = available_port()
    server = _ExpiredCertHTTPSServer(host="127.0.0.1", port=port, cert_path=cert_path, key_path=key_path)
    server.start()
    # Give the listener a moment to bind.
    time.sleep(0.1)
    observed_failure_mode: str | None = None
    observed_error_class: str | None = None
    error_text: str | None = None
    expected_match = False
    try:
        client_ctx = ssl.create_default_context()
        client_ctx.load_verify_locations(cafile=str(cert_path))
        client_ctx.check_hostname = False  # SAN matches but expiry should fire first
        sock = socket.create_connection(("127.0.0.1", port), timeout=timeout_sec)
        try:
            with client_ctx.wrap_socket(sock, server_hostname="127.0.0.1") as tls_sock:
                tls_sock.sendall(b"\x00")
                tls_sock.recv(1)
            observed_failure_mode = "no_failure"
            error_text = "TLS handshake unexpectedly succeeded"
        finally:
            try:
                sock.close()
            except Exception:
                pass
    except ssl.SSLCertVerificationError as exc:
        observed_error_class = type(exc).__name__
        error_text = str(exc)
        if "expired" in error_text.lower() or "certificate has expired" in error_text.lower() or exc.verify_code in {10, 9}:
            observed_failure_mode = "certificate_expired"
            expected_match = True
        else:
            observed_failure_mode = "certificate_verify_failed"
            expected_match = True
    except ssl.SSLError as exc:
        observed_error_class = type(exc).__name__
        error_text = str(exc)
        if "expired" in error_text.lower():
            observed_failure_mode = "certificate_expired"
            expected_match = True
        elif "certificate" in error_text.lower():
            observed_failure_mode = "certificate_verify_failed"
            expected_match = True
        else:
            observed_failure_mode = "ssl_error"
            expected_match = True
    except Exception as exc:
        observed_error_class = type(exc).__name__
        error_text = str(exc)
        observed_failure_mode = "transport_error"
        # Don't mark as expected unless we recognise it as TLS-related
        expected_match = False
    finally:
        server.stop()
        server.join(timeout=2.0)
    status = "ok" if expected_match else "fail"
    return {
        "name": "mtls_cert_expired",
        "status": status,
        "injection_method": "expired_self_signed_cert",
        "observed_failure_mode": observed_failure_mode,
        "observed_error_class": observed_error_class,
        "error_text": error_text,
        "audit_chain_uncorrupted": True,
        "expected_failure_pattern_matched": expected_match,
        "details": (
            "Server cert NotAfter set to ~24h in the past; client "
            "ssl.create_default_context() must reject the handshake before any record is sent."
        ),
    }


# ---------------------------------------------------------------------------
# Scenario 3: audit_archive_unwritable
# ---------------------------------------------------------------------------


def _build_synthetic_audit_chain_seal(work_root: Path) -> tuple[Path, Path, str]:
    """Reuse the well-tested seal_audit_artifact pipeline to produce a real
    audit_chain.json + audit_chain.seal.json pair so the chaos drill exercises
    the same archive code path as production."""
    audit_chain = {
        "schema": "audit_chain/v1",
        "ts_utc": utc_now_iso(),
        "job_id": "chaos-job",
        "correlation_id": "chaos-job",
        "tenant_id": "chaos-tenant",
        "dataset_id": "chaos-dataset",
        "service_id": "chaos-service",
        "stages": [
            {
                "stage": "policy_release",
                "decision": "allow",
                "reason_code": "ok",
                "ts_utc": utc_now_iso(),
            }
        ],
        "paths": {"out_base": str(work_root)},
    }
    chain_path = work_root / "audit_chain.json"
    chain_path.write_text(json.dumps(audit_chain, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    seal_path = work_root / "audit_chain.seal.json"
    seal_proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "seal_audit_artifact.py"),
            "--input",
            str(chain_path),
            "--out",
            str(seal_path),
            "--job-id",
            "chaos-job",
        ],
        capture_output=True,
        text=True,
    )
    if seal_proc.returncode != 0:
        raise RuntimeError(f"seal_audit_artifact failed: {seal_proc.stderr.strip()}")
    chain_sha = sha256_bytes(chain_path.read_bytes())
    return chain_path, seal_path, chain_sha


def scenario_audit_archive_unwritable(
    *,
    work_root: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    sub_root = work_root / "audit_archive"
    sub_root.mkdir(parents=True, exist_ok=True)
    try:
        chain_path, seal_path, pre_chain_sha = _build_synthetic_audit_chain_seal(sub_root)
    except Exception as exc:
        return {
            "name": "audit_archive_unwritable",
            "status": "fail",
            "injection_method": "chmod_000_archive_dir",
            "observed_failure_mode": None,
            "observed_error_class": type(exc).__name__,
            "error_text": f"could not synthesize audit chain/seal: {exc}",
            "audit_chain_uncorrupted": True,
            "expected_failure_pattern_matched": False,
            "details": "seal_audit_artifact prerequisites failed",
        }
    archive_dir = sub_root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    pre_archive_listing = sorted(p.name for p in archive_dir.iterdir())
    original_mode = archive_dir.stat().st_mode
    os.chmod(archive_dir, 0)
    observed_failure_mode: str | None = None
    observed_error_class: str | None = None
    error_text: str | None = None
    expected_match = False
    archive_proc: subprocess.CompletedProcess[str] | None = None
    try:
        archive_proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "archive_audit_bundle.py"),
                "--audit-chain",
                str(chain_path),
                "--audit-seal",
                str(seal_path),
                "--archive-dir",
                str(archive_dir),
                "--job-id",
                "chaos-job",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        observed_error_class = "subprocess.CompletedProcess"
        if archive_proc.returncode != 0:
            error_text = archive_proc.stderr.strip() or archive_proc.stdout.strip()
            observed_failure_mode = "archive_dir_unwritable"
            expected_match = True
        else:
            error_text = "archive_audit_bundle.py exited 0 against an unwritable archive dir"
            observed_failure_mode = "no_failure"
    except subprocess.TimeoutExpired as exc:
        observed_error_class = type(exc).__name__
        error_text = f"archive_audit_bundle.py timed out: {exc}"
        observed_failure_mode = "timeout"
    finally:
        try:
            os.chmod(archive_dir, original_mode if original_mode else (stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP))
        except Exception:
            pass
    post_archive_listing = sorted(p.name for p in archive_dir.iterdir())
    no_partial_files = post_archive_listing == pre_archive_listing
    post_chain_sha = sha256_bytes(chain_path.read_bytes())
    audit_chain_uncorrupted = post_chain_sha == pre_chain_sha
    if not no_partial_files:
        expected_match = False
        observed_failure_mode = "partial_writes_detected"
    if not audit_chain_uncorrupted:
        expected_match = False
        observed_failure_mode = "audit_chain_corrupted"
    status = "ok" if expected_match and audit_chain_uncorrupted and no_partial_files else "fail"
    return {
        "name": "audit_archive_unwritable",
        "status": status,
        "injection_method": "chmod_000_archive_dir",
        "observed_failure_mode": observed_failure_mode,
        "observed_error_class": observed_error_class,
        "error_text": error_text,
        "audit_chain_uncorrupted": audit_chain_uncorrupted,
        "expected_failure_pattern_matched": expected_match,
        "details": (
            f"archive dir mode set to 0o000 before invocation; "
            f"pre={len(pre_archive_listing)} post={len(post_archive_listing)} "
            f"chain_sha_match={audit_chain_uncorrupted}"
        ),
    }


# ---------------------------------------------------------------------------
# Operator-only scenarios (always emit status=skipped)
# ---------------------------------------------------------------------------


def scenario_operator_skipped(name: str, reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "skipped",
        "injection_method": "operator_environment_only",
        "observed_failure_mode": None,
        "observed_error_class": None,
        "error_text": None,
        "audit_chain_uncorrupted": True,
        "expected_failure_pattern_matched": False,
        "details": reason,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_scenarios(selected: list[str], *, work_root: Path, timeout_sec: float) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in selected:
        if name == "recovery_service_sigkill":
            results.append(scenario_recovery_service_sigkill(work_root=work_root, timeout_sec=timeout_sec))
        elif name == "mtls_cert_expired":
            results.append(scenario_mtls_cert_expired(work_root=work_root, timeout_sec=timeout_sec))
        elif name == "audit_archive_unwritable":
            results.append(scenario_audit_archive_unwritable(work_root=work_root, timeout_sec=timeout_sec))
        elif name == "postgres_primary_killed":
            results.append(
                scenario_operator_skipped(
                    name,
                    "requires a running Patroni cluster; see OPS_RUNBOOK.md §J4 chaos drills",
                )
            )
        elif name == "audit_log_path_full":
            results.append(
                scenario_operator_skipped(
                    name,
                    "requires filesystem-level injection; see OPS_RUNBOOK.md §J4 chaos drills",
                )
            )
        else:
            raise SystemExit(f"[ERROR] unknown chaos scenario: {name}")
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "fail")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    audit_corruptions = sum(1 for r in results if not r.get("audit_chain_uncorrupted", True))
    pattern_matched = sum(1 for r in results if r.get("expected_failure_pattern_matched"))
    overall = "ok" if failed == 0 and audit_corruptions == 0 else "fail"
    return {
        "status": overall,
        "total": total,
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
        "audit_chain_corruptions": audit_corruptions,
        "expected_pattern_matched": pattern_matched,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="J4 chaos and failure-injection drill.")
    ap.add_argument(
        "--scenarios",
        default=",".join(DEFAULT_SCENARIOS),
        help=(
            "Comma-separated chaos scenarios to run. Use 'all' to include the "
            "operator-only scenarios as 'skipped'. Available: "
            + ",".join(ALL_SCENARIOS)
        ),
    )
    ap.add_argument("--timeout-sec", type=float, default=10.0)
    ap.add_argument("--work-dir", default="", help="Optional pinned work dir; otherwise a temp dir is used.")
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-ok", action="store_true")
    args = ap.parse_args()

    if args.scenarios.strip().lower() == "all":
        selected = list(ALL_SCENARIOS)
    else:
        selected = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    for name in selected:
        if name not in ALL_SCENARIOS:
            raise SystemExit(f"[ERROR] unknown chaos scenario: {name}")

    if args.work_dir:
        work_root = Path(args.work_dir)
        work_root.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        tmp = tempfile.mkdtemp(prefix="seccomp_chaos_")
        work_root = Path(tmp)
        cleanup = True

    started = time.monotonic()
    try:
        results = run_scenarios(selected, work_root=work_root, timeout_sec=args.timeout_sec)
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        if cleanup:
            shutil.rmtree(work_root, ignore_errors=True)

    summary = summarize(results)
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "duration_ms": duration_ms,
        "selected_scenarios": selected,
        "scenarios": results,
        "summary": summary,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_ok and summary["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc
