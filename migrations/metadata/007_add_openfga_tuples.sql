-- 007: Local OpenFGA-style tuple store for A2 authz sync/check adapter.
--
-- Stores authorization tuples synced from authz_tuple_export/v1.
-- This is a sidecar table — it does not replace the release policy.
-- The UNIQUE constraint on (user, relation, object) makes upsert idempotent.

CREATE TABLE IF NOT EXISTS openfga_tuples (
    id INTEGER PRIMARY KEY,
    user TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    user_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_policy_id TEXT,
    synced_at_utc TEXT NOT NULL,
    UNIQUE (user, relation, object)
);

CREATE INDEX IF NOT EXISTS idx_openfga_tuples_user ON openfga_tuples (user);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_object ON openfga_tuples (object);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_relation ON openfga_tuples (relation);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_synced ON openfga_tuples (synced_at_utc);
