CREATE TABLE IF NOT EXISTS control_plane_mutations (
  id INTEGER PRIMARY KEY,
  mutation_id TEXT NOT NULL UNIQUE,
  operation TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  actor TEXT,
  source TEXT,
  old_state_json TEXT,
  new_state_json TEXT,
  status TEXT NOT NULL DEFAULT 'applied',
  applied_at_utc TEXT NOT NULL,
  notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_entity ON control_plane_mutations(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_actor ON control_plane_mutations(actor);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_applied_at ON control_plane_mutations(applied_at_utc);
