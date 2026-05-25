ALTER TABLE players
ADD COLUMN IF NOT EXISTS team_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_players_team_id'
    ) THEN
        ALTER TABLE players
        ADD CONSTRAINT fk_players_team_id
        FOREIGN KEY (team_id) REFERENCES teams(id)
        ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_players_team_id ON players (team_id);
