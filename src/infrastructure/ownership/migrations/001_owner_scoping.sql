-- Scopes teams and players to their owner. Idempotent.
--
-- The owner-less rows this originally had to clear are long gone, so the
-- DELETE statements that did it have been removed: they only ever had data to
-- destroy, and the migration runner used to replay this file on every deploy.
-- A database still holding owner-less rows will now fail loudly on the
-- SET NOT NULL below, which is the better outcome.

ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE players
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE teams ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE players ALTER COLUMN owner_user_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_teams_owner_user_id ON teams (owner_user_id);
CREATE INDEX IF NOT EXISTS idx_players_owner_user_id ON players (owner_user_id);
