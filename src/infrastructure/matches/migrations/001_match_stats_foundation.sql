CREATE TABLE IF NOT EXISTS matches (
    id UUID PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    home_team_id UUID NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    away_team_id UUID NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    winner_team_id UUID NULL REFERENCES teams(id) ON DELETE RESTRICT,
    match_date DATE NOT NULL,
    description TEXT NULL,
    stats JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_matches_distinct_teams CHECK (home_team_id <> away_team_id),
    CONSTRAINT chk_matches_winner_team CHECK (
        winner_team_id IS NULL OR winner_team_id = home_team_id OR winner_team_id = away_team_id
    ),
    CONSTRAINT uq_matches_id_owner UNIQUE (id, owner_user_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_owner_match_date_created_at
    ON matches (owner_user_id, match_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_matches_home_team_id ON matches (home_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_away_team_id ON matches (away_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_winner_team_id ON matches (winner_team_id);

CREATE TABLE IF NOT EXISTS match_participants (
    id UUID PRIMARY KEY,
    match_id UUID NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    player_id UUID NULL REFERENCES players(id) ON DELETE SET NULL,
    team_side TEXT NOT NULL,
    display_name TEXT NOT NULL,
    jersey_number TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_match_participants_team_side CHECK (team_side IN ('HOME', 'AWAY')),
    CONSTRAINT fk_match_participants_match_owner
        FOREIGN KEY (match_id, owner_user_id)
        REFERENCES matches(id, owner_user_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_match_participants_match_id ON match_participants (match_id);
CREATE INDEX IF NOT EXISTS idx_match_participants_owner_player_match
    ON match_participants (owner_user_id, player_id, match_id);
