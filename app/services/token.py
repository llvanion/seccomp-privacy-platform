from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from app.errors import GatewayError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


@dataclass
class TokenClaims:
    jti: str
    sub: str
    scope: list[str]
    resource_id: str | None
    iat: int
    exp: int
    iss: str

    @property
    def expires_at(self) -> str:
        return datetime.fromtimestamp(self.exp, tz=timezone.utc).isoformat()

    def as_payload(self) -> dict[str, Any]:
        return {
            "jti": self.jti,
            "sub": self.sub,
            "scope": self.scope,
            "resource_id": self.resource_id,
            "iat": self.iat,
            "exp": self.exp,
            "iss": self.iss,
        }


class TokenService:
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        default_expire_seconds: int,
        backend: str,
        sqlite_path: Path,
        jsonl_path: Path,
    ) -> None:
        self.secret = secret.encode("utf-8")
        self.issuer = issuer
        self.default_expire_seconds = default_expire_seconds
        self.backend = backend
        self.sqlite_path = sqlite_path
        self.jsonl_path = jsonl_path

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        if self.backend == "sqlite":
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS revoked_tokens (
                    jti TEXT PRIMARY KEY,
                    revoked_at TEXT NOT NULL,
                    revoked_by TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revoked_tokens_revoked_at ON revoked_tokens(revoked_at)")
            conn.commit()

    def _sign(self, signing_input: str) -> str:
        digest = hmac.new(self.secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        return _b64url_encode(digest)

    def _encode(self, payload: dict[str, Any]) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}"
        return f"{signing_input}.{self._sign(signing_input)}"

    def _decode_unverified(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise GatewayError("bad_token_format", "invalid token format", status_code=401)
        try:
            return json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        except Exception as exc:
            raise GatewayError("bad_token_payload", "invalid token payload", status_code=401) from exc

    def issue_token(
        self,
        *,
        actor: str,
        scopes: list[str],
        resource_id: str | None = None,
        expire_seconds: int | None = None,
    ) -> tuple[str, TokenClaims]:
        ttl = expire_seconds or self.default_expire_seconds
        now = utc_now()
        claims = TokenClaims(
            jti=str(uuid4()),
            sub=actor,
            scope=sorted(set(scopes)),
            resource_id=resource_id,
            iat=int(now.timestamp()),
            exp=int((now + timedelta(seconds=ttl)).timestamp()),
            iss=self.issuer,
        )
        return self._encode(claims.as_payload()), claims

    def revoke_token(
        self,
        *,
        jti: str,
        revoked_by: str,
        reason: str,
    ) -> None:
        record = {
            "jti": jti,
            "revoked_at": utc_now_iso(),
            "revoked_by": revoked_by,
            "reason": reason,
        }
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    """
                    INSERT INTO revoked_tokens(jti, revoked_at, revoked_by, reason)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(jti) DO UPDATE SET
                        revoked_at=excluded.revoked_at,
                        revoked_by=excluded.revoked_by,
                        reason=excluded.reason
                    """,
                    (record["jti"], record["revoked_at"], record["revoked_by"], record["reason"]),
                )
                conn.commit()
            return

        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def is_revoked(self, jti: str) -> bool:
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as conn:
                row = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ? LIMIT 1", (jti,)).fetchone()
            return row is not None

        if not self.jsonl_path.exists():
            return False
        for line in self.jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("jti") == jti:
                return True
        return False

    def parse_and_validate(self, token: str) -> TokenClaims:
        parts = token.split(".")
        if len(parts) != 3:
            raise GatewayError("bad_token_format", "invalid token format", status_code=401)

        signing_input = ".".join(parts[:2])
        expected_sig = self._sign(signing_input)
        if not hmac.compare_digest(expected_sig, parts[2]):
            raise GatewayError("bad_token_signature", "invalid token signature", status_code=401)

        payload = self._decode_unverified(token)
        if payload.get("iss") != self.issuer:
            raise GatewayError("bad_token_issuer", "invalid token issuer", status_code=401)

        try:
            claims = TokenClaims(
                jti=str(payload["jti"]),
                sub=str(payload["sub"]),
                scope=[str(item) for item in payload.get("scope", [])],
                resource_id=str(payload["resource_id"]) if payload.get("resource_id") is not None else None,
                iat=int(payload["iat"]),
                exp=int(payload["exp"]),
                iss=str(payload["iss"]),
            )
        except Exception as exc:
            raise GatewayError("bad_token_claims", "invalid token claims", status_code=401) from exc

        if int(utc_now().timestamp()) >= claims.exp:
            raise GatewayError("token_expired", "token expired", status_code=401)
        if self.is_revoked(claims.jti):
            raise GatewayError("token_revoked", "token revoked", status_code=401)
        return claims

    def extract_jti(self, token: str) -> str:
        payload = self._decode_unverified(token)
        jti = payload.get("jti")
        if not jti:
            raise GatewayError("missing_jti", "token missing jti", status_code=400)
        return str(jti)

    def require_scope(self, claims: TokenClaims, required_scope: str, resource_id: str | None = None) -> None:
        if required_scope not in claims.scope:
            raise GatewayError("scope_denied", "required scope missing", status_code=403)
        if claims.resource_id is not None and resource_id is not None and claims.resource_id != resource_id:
            raise GatewayError("resource_denied", "token resource mismatch", status_code=403)
