-- What the video analyses measured for each roster player, kept per analysed video.
--
-- The analysis results live in object storage and are recomputed on every request. These
-- tables keep the part that belongs to a roster player so a player can be shown across all
-- of their videos: aggregated totals and every shot with its court position.
--
-- Only the latest finished analysis of a video is kept (rows are replaced per video), so
-- analysing the same video twice never counts its shots twice. Rows disappear with the
-- player, the job or the video.

CREATE TABLE IF NOT EXISTS player_analysis_games (
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jersey_number TEXT NULL,
    seconds_observed DOUBLE PRECISION NULL,
    distance_m DOUBLE PRECISION NULL,
    points INTEGER NOT NULL DEFAULT 0,
    field_goals_made INTEGER NOT NULL DEFAULT 0,
    field_goals_attempted INTEGER NOT NULL DEFAULT 0,
    two_point_made INTEGER NOT NULL DEFAULT 0,
    two_point_attempted INTEGER NOT NULL DEFAULT 0,
    three_point_made INTEGER NOT NULL DEFAULT 0,
    three_point_attempted INTEGER NOT NULL DEFAULT 0,
    unresolved_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_player_analysis_games_video ON player_analysis_games (video_id);
CREATE INDEX IF NOT EXISTS idx_player_analysis_games_owner_player
    ON player_analysis_games (owner_user_id, player_id);

CREATE TABLE IF NOT EXISTS player_analysis_shots (
    id BIGSERIAL PRIMARY KEY,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- The shot's event id inside its job; null only if the pipeline gave none.
    shot_id INTEGER NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('made', 'missed', 'unresolved')),
    points INTEGER NOT NULL,
    zone TEXT NULL,
    shot_type TEXT NULL,
    distance_m DOUBLE PRECISION NULL,
    court_x_m DOUBLE PRECISION NOT NULL,
    court_y_m DOUBLE PRECISION NOT NULL,
    timestamp_seconds DOUBLE PRECISION NULL,
    attribution TEXT NULL,
    needs_review BOOLEAN NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, shot_id)
);

CREATE INDEX IF NOT EXISTS idx_player_analysis_shots_player
    ON player_analysis_shots (owner_user_id, player_id);
CREATE INDEX IF NOT EXISTS idx_player_analysis_shots_video ON player_analysis_shots (video_id);
