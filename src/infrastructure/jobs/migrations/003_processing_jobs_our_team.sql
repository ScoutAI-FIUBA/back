ALTER TABLE processing_jobs
ADD COLUMN IF NOT EXISTS our_team_side SMALLINT NULL
CHECK (our_team_side IS NULL OR our_team_side IN (0, 1));
