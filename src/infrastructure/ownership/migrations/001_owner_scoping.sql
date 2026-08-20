-- Scopes teams and players to their owner. One-time reset: existing rows have no
-- owner, so this drops them and everything tied to them. Idempotent.

ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE players
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE;

DELETE FROM processing_jobs
    WHERE team_id IN (SELECT id FROM teams WHERE owner_user_id IS NULL);
DELETE FROM videos
    WHERE team_id IN (SELECT id FROM teams WHERE owner_user_id IS NULL);
DELETE FROM players WHERE owner_user_id IS NULL;
DELETE FROM teams WHERE owner_user_id IS NULL;

ALTER TABLE teams ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE players ALTER COLUMN owner_user_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_teams_owner_user_id ON teams (owner_user_id);
CREATE INDEX IF NOT EXISTS idx_players_owner_user_id ON players (owner_user_id);
