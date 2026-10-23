-- Which version of the player stats rules each finished analysis was last kept with; NULL = not yet.
ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS player_stats_synced_version SMALLINT NULL;
ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS player_stats_synced_at TIMESTAMPTZ NULL;
