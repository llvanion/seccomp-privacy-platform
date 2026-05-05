#!/usr/bin/env python3
"""OIDC / JWT claim mapper for the metadata sidecar.

Parses a JWT (header.payload.signature), extracts standard and custom claims,
and maps them to the local caller_identities format using a configurable
claim_mapping. Optionally verifies the HMAC-SHA256 signature (HS256) using
a secret from an env var — RS256 / JWKS verification is out of scope for this
prototype and would require an HTTP call to the issuer's JWKS URI.

Also performs issuer_registry lookup: if the resolved issuer is not registered
(or is disabled) in the metadata DB, the mapping is rejected.

Outputs oidc_claim_map/v1.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, utc_now  # noqa: E402
from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

SCHEMA_ID = "oidc_claim_map/v1"
CLAIM_MAPPING_SCHEMA = "oidc_claim_mapping_config/v1"

DEFAULT_CLAIM_MAP = {
    "caller": "sub",
    "issuer": "iss",
    "subject": "sub",
    "subject_type": "_const:service_account",
    "display_name": "name",
    "tenant_id": "tenant_id",
    "service_id": "client_id",
    "platform_roles": "roles",
}


def _b64url_decode(segment: str) -> bytes:
    padding = 4 - len(segment) % 4
    if padding != 4:
        segment += "=" * padding
    return base64.urlsafe_b64decode(segment)


def parse_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Return (header, payload_claims, raw_signature_bytes)."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"JWT must have 3 dot-separated parts, got {len(parts)}")
    header = json.loads(_b64url_decode(parts[0]))
    payload = json.loads(_b64url_decode(parts[1]))
    signature = _b64url_decode(parts[2])
    return header, payload, signature


def verify_hs256(token: str, secret: str) -> bool:
    """Verify HS256 signature. Returns True if valid."""
    parts = token.strip().split(".")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    provided = _b64url_decode(parts[2])
    return hmac.compare_digest(expected, provided)


def _b64url_uint(value: str) -> int:
    return int.from_bytes(_b64url_decode(value), "big")


def fetch_jwks(jwks_uri: str) -> dict[str, Any]:
    with urllib.request.urlopen(jwks_uri, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JWKS payload must be a JSON object: {jwks_uri}")
    return payload


def _rsa_public_key_from_jwk(jwk: dict[str, Any]) -> rsa.RSAPublicKey:
    if str(jwk.get("kty") or "") != "RSA":
        raise ValueError("JWKS key is not RSA")
    n = str(jwk.get("n") or "")
    e = str(jwk.get("e") or "")
    if not n or not e:
        raise ValueError("JWKS RSA key is missing n/e")
    public_numbers = rsa.RSAPublicNumbers(_b64url_uint(e), _b64url_uint(n))
    return public_numbers.public_key()


def verify_rs256(token: str, jwks: dict[str, Any]) -> bool:
    parts = token.strip().split(".")
    header, _, signature = parse_jwt(token)
    kid = str(header.get("kid") or "")
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("JWKS keys array is missing or empty")

    jwk: dict[str, Any] | None = None
    if kid:
        for item in keys:
            if isinstance(item, dict) and str(item.get("kid") or "") == kid:
                jwk = item
                break
        if jwk is None:
            raise ValueError(f"JWKS does not contain kid={kid!r}")
    else:
        rsa_keys = [item for item in keys if isinstance(item, dict) and str(item.get("kty") or "") == "RSA"]
        if len(rsa_keys) != 1:
            raise ValueError("JWT header has no kid and JWKS does not resolve to a single RSA key")
        jwk = rsa_keys[0]

    public_key = _rsa_public_key_from_jwk(jwk)
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    try:
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False
    return True


def resolve_claim_value(claims: dict[str, Any], mapping_value: str) -> Any:
    """Resolve a single mapping value: either a claim key or _const:<value>."""
    if mapping_value.startswith("_const:"):
        return mapping_value[len("_const:"):]
    # Support dotted paths: e.g. "realm_access.roles"
    parts = mapping_value.split(".")
    val: Any = claims
    for part in parts:
        if not isinstance(val, dict):
            return None
        val = val.get(part)
    return val


def apply_claim_mapping(
    claims: dict[str, Any],
    mapping: dict[str, str],
) -> dict[str, Any]:
    """Apply a claim_mapping dict to extracted JWT claims."""
    result: dict[str, Any] = {}
    for field, claim_key in mapping.items():
        result[field] = resolve_claim_value(claims, claim_key)
    return result


def load_claim_mapping_config(config_path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"claim mapping config must be a JSON object: {config_path}")
    if payload.get("schema") != CLAIM_MAPPING_SCHEMA:
        raise ValueError(f"claim mapping config must use {CLAIM_MAPPING_SCHEMA}: {config_path}")
    return payload


def lookup_issuer_registry(conn, issuer: str) -> dict[str, Any] | None:
    """Return issuer_registry row or None if not found."""
    row = conn.execute(
        "SELECT * FROM issuer_registry WHERE issuer = ?", (issuer,)
    ).fetchone()
    if row is None:
        return None
    rec = dict(row)
    for json_field in ("claim_mapping_json", "trusted_audiences_json"):
        if rec.get(json_field):
            try:
                rec[json_field] = json.loads(rec[json_field])
            except (ValueError, TypeError):
                pass
    return rec


def validate_token_expiry(claims: dict[str, Any]) -> dict[str, Any]:
    """Check exp/iat claims. Returns {expired, not_yet_valid, exp, iat}."""
    import time
    now = time.time()
    exp = claims.get("exp")
    iat = claims.get("iat")
    nbf = claims.get("nbf")
    return {
        "expired": bool(exp is not None and now > float(exp)),
        "not_yet_valid": bool(nbf is not None and now < float(nbf)),
        "exp": exp,
        "iat": iat,
        "nbf": nbf,
    }


def map_token(
    token: str,
    *,
    claim_mapping: dict[str, str],
    verify_secret: str | None,
    jwks_uri: str | None,
    db_path: str | None,
    require_registered_issuer: bool,
    trusted_audiences: list[str] | None,
) -> dict[str, Any]:
    header, claims, _ = parse_jwt(token)
    alg = str(header.get("alg") or "none")

    # Signature verification
    sig_verified = False
    sig_skipped = False
    sig_error: str | None = None
    resolved_jwks_uri = str(jwks_uri or "").strip() or None
    if verify_secret:
        if alg == "HS256":
            sig_verified = verify_hs256(token, verify_secret)
            if not sig_verified:
                sig_error = "HS256 signature mismatch"
        else:
            sig_error = f"algorithm {alg} not supported for local verification (only HS256)"
            sig_skipped = True
    elif resolved_jwks_uri:
        if alg == "RS256":
            try:
                sig_verified = verify_rs256(token, fetch_jwks(resolved_jwks_uri))
                if not sig_verified:
                    sig_error = "RS256 signature mismatch"
            except Exception as exc:
                sig_error = f"RS256 verification failed: {exc}"
        else:
            sig_error = f"algorithm {alg} not supported for JWKS verification (only RS256)"
    else:
        sig_skipped = True

    # Extract issuer early for registry lookup
    raw_issuer = str(claims.get("iss") or "")
    raw_audience = claims.get("aud")

    # Issuer registry check
    issuer_record: dict[str, Any] | None = None
    issuer_registered = False
    issuer_enabled = False
    issuer_error: str | None = None
    if db_path:
        conn = connect_db(db_path)
        apply_migrations(conn)
        issuer_record = lookup_issuer_registry(conn, raw_issuer)
        conn.close()
        if issuer_record:
            issuer_registered = True
            issuer_enabled = bool(int(issuer_record.get("enabled") or 0))
            if not issuer_enabled:
                issuer_error = f"issuer '{raw_issuer}' is registered but disabled"
            # Prefer claim_mapping from registry if present
            reg_mapping = issuer_record.get("claim_mapping_json")
            if isinstance(reg_mapping, dict):
                claim_mapping = {**claim_mapping, **reg_mapping}
            # Merge trusted_audiences from registry
            reg_audiences = issuer_record.get("trusted_audiences_json")
            if isinstance(reg_audiences, list) and reg_audiences:
                trusted_audiences = list({*(trusted_audiences or []), *reg_audiences})
            if not resolved_jwks_uri:
                issuer_jwks_uri = str(issuer_record.get("jwks_uri") or "").strip()
                if issuer_jwks_uri:
                    resolved_jwks_uri = issuer_jwks_uri
        elif require_registered_issuer:
            issuer_error = f"issuer '{raw_issuer}' is not in issuer_registry"

    if not verify_secret and resolved_jwks_uri and sig_skipped:
        sig_skipped = False
        if alg == "RS256":
            try:
                sig_verified = verify_rs256(token, fetch_jwks(resolved_jwks_uri))
                if not sig_verified:
                    sig_error = "RS256 signature mismatch"
            except Exception as exc:
                sig_error = f"RS256 verification failed: {exc}"
        else:
            sig_error = f"algorithm {alg} not supported for JWKS verification (only RS256)"

    # Audience check
    aud_ok = True
    aud_error: str | None = None
    if trusted_audiences:
        token_auds = raw_audience if isinstance(raw_audience, list) else ([raw_audience] if raw_audience else [])
        if not any(str(a) in trusted_audiences for a in token_auds):
            aud_ok = False
            aud_error = f"token audience {token_auds!r} not in trusted_audiences {trusted_audiences!r}"

    # Expiry
    expiry = validate_token_expiry(claims)

    # Apply claim mapping
    mapped = apply_claim_mapping(claims, claim_mapping)

    # Normalise platform_roles to list
    roles_raw = mapped.get("platform_roles")
    if isinstance(roles_raw, str):
        mapped["platform_roles"] = [r.strip() for r in roles_raw.split(",") if r.strip()]
    elif not isinstance(roles_raw, list):
        mapped["platform_roles"] = []

    # Build overall validity
    errors: list[str] = []
    if sig_error and not sig_skipped:
        errors.append(sig_error)
    if issuer_error:
        errors.append(issuer_error)
    if aud_error:
        errors.append(aud_error)
    if expiry["expired"]:
        errors.append("token has expired")
    if expiry["not_yet_valid"]:
        errors.append("token is not yet valid (nbf)")

    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "algorithm": alg,
        "jwks_uri": resolved_jwks_uri,
        "issuer": raw_issuer,
        "subject": str(claims.get("sub") or ""),
        "signature_verified": sig_verified,
        "signature_skipped": sig_skipped,
        "issuer_registered": issuer_registered,
        "issuer_enabled": issuer_enabled,
        "audience_ok": aud_ok,
        "expiry": expiry,
        "raw_claims": claims,
        "mapped_fields": mapped,
        "issuer_record": {
            k: v for k, v in (issuer_record or {}).items()
            if k not in ("claim_mapping_json",)
        } if issuer_record else None,
        "errors": errors,
        "valid": len(errors) == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Map OIDC/JWT claims to caller_identities fields")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--token", help="JWT string to parse and map")
    group.add_argument("--token-env", help="Env var containing the JWT")
    parser.add_argument("--claim-mapping-config", help="Path to oidc_claim_mapping_config/v1 JSON")
    parser.add_argument("--verify-secret-env", help="Env var with HMAC secret for HS256 verification")
    parser.add_argument("--jwks-uri", help="JWKS URI for RS256 verification")
    parser.add_argument("--db-path", help="Metadata SQLite DB for issuer_registry lookup")
    parser.add_argument("--require-registered-issuer", action="store_true",
                        help="Reject tokens from issuers not in issuer_registry")
    parser.add_argument("--trusted-audience", action="append", dest="trusted_audiences",
                        help="Trusted audience value (repeatable)")
    parser.add_argument("--output", help="Write report JSON to file")
    parser.add_argument("--fail-on-invalid", action="store_true",
                        help="Exit non-zero if token is not valid")
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "") if args.token_env else (args.token or "")
    if not token:
        print(json.dumps({"error": "no token provided or env var is empty"}))
        sys.exit(1)

    claim_mapping = dict(DEFAULT_CLAIM_MAP)
    if args.claim_mapping_config:
        cfg = load_claim_mapping_config(args.claim_mapping_config)
        override = cfg.get("claim_mapping")
        if isinstance(override, dict):
            claim_mapping.update(override)
        if not args.jwks_uri:
            config_jwks_uri = str(cfg.get("jwks_uri") or "").strip()
            if config_jwks_uri:
                args.jwks_uri = config_jwks_uri

    verify_secret: str | None = None
    if args.verify_secret_env:
        verify_secret = os.environ.get(args.verify_secret_env)

    result = map_token(
        token,
        claim_mapping=claim_mapping,
        verify_secret=verify_secret,
        jwks_uri=args.jwks_uri,
        db_path=args.db_path,
        require_registered_issuer=args.require_registered_issuer,
        trusted_audiences=args.trusted_audiences,
    )

    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.fail_on_invalid and not result["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
