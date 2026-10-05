-- Remediator round-robin: stamp when a row's remediation attempt last started
-- so budget-limited runs rotate through the backlog instead of repeating the head.
ALTER TABLE conferences ADD COLUMN IF NOT EXISTS remediation_attempted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_conferences_source_remediation_attempted
  ON conferences (source_id, remediation_attempted_at);
