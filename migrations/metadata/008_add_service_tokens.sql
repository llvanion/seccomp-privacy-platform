-- 008: Service identity token registry for A4 service-to-service auth.
--
-- Stores metadata about issued service tokens (never the raw secret).
-- token_hash = SHA-256 of the raw token; used to check revocation without
-- exposing the token itself. The signing secret lives in the keyring or env.

CREATE TABLE IF NOT EXISTS service_tokens (
    id INTEGER PRIMARY KEY,
    jti TEXT NOT NULL UNIQUE,
    service_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'service',
    issued_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    token_hash TEXT NOT NULL,
    issuer TEXT,
    notes TEXT,
    revoked_at_utc TEXT,
    revocation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_service_tokens_service_id ON service_tokens (service_id);
CREATE INDEX IF NOT EXISTS idx_service_tokens_status ON service_tokens (status);
CREATE INDEX IF NOT EXISTS idx_service_tokens_expires ON service_tokens (expires_at_utc);
CREATE INDEX IF NOT EXISTS idx_service_tokens_jti ON service_tokens (jti);
