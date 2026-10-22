-- What the video analyses measured for each roster player, kept per analysed video.
--
-- The analysis results live in object storage and are recomputed on every request. These
-- tables keep the part that belongs to a roster player so a player can be shown across all
-- of their videos: aggregated totals and every shot with its court position.
--
-- Only the latest finished analysis of a video is kept (rows are replaced per video), so
-- analysing the same video twice never counts its shots twice. Rows disappear with the
-- player, the job or the video.
--
-- `calc_version` is the version of the court/zone rules the zone and shot value were
-- computed with (CALC_VERSION in the domain module). `seconds_on_screen` is the time the
-- player was visible in the video, not minutes played.

CREATE TABLE IF NOT EXISTS player_analysis_games (
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jersey_number TEXT NULL,
    seconds_on_screen DOUBLE PRECISION NULL,
    distance_m DOUBLE PRECISION NULL,
    points INTEGER NOT NULL DEFAULT 0,
    field_goals_made INTEGER NOT NULL DEFAULT 0,
    field_goals_attempted INTEGER NOT NULL DEFAULT 0,
    two_point_made INTEGER NOT NULL DEFAULT 0,
    two_point_attempted INTEGER NOT NULL DEFAULT 0,
    three_point_made INTEGER NOT NULL DEFAULT 0,
    three_point_attempted INTEGER NOT NULL DEFAULT 0,
    unresolved_attempts INTEGER NOT NULL DEFAULT 0,
    calc_version SMALLINT NOT NULL DEFAULT 2,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One analysis per video (the latest finished job), so one row per player and video.
    PRIMARY KEY (video_id, player_id),
    CHECK (field_goals_made <= field_goals_attempted),
    CHECK (two_point_made <= two_point_attempted),
    CHECK (three_point_made <= three_point_attempted)
);

CREATE INDEX IF NOT EXISTS idx_player_analysis_games_player
    ON player_analysis_games (player_id, owner_user_id);

CREATE TABLE IF NOT EXISTS player_analysis_shots (
    id BIGSERIAL PRIMARY KEY,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- The shot's event id inside its job; null only if the pipeline gave none (or repeated one).
    shot_id INTEGER NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('made', 'missed', 'unresolved')),
    -- What the shot is worth by where it was taken (2 or 3), even when it missed.
    shot_value SMALLINT NOT NULL CHECK (shot_value IN (2, 3)),
    zone TEXT NULL,
    shot_type TEXT NULL,
    distance_m DOUBLE PRECISION NULL,
    court_x_m DOUBLE PRECISION NOT NULL,
    court_y_m DOUBLE PRECISION NOT NULL,
    timestamp_seconds DOUBLE PRECISION NULL,
    attribution TEXT NULL,
    needs_review BOOLEAN NULL,
    outcome_source TEXT NULL,
    outcome_confidence TEXT NULL
        CHECK (outcome_confidence IS NULL OR outcome_confidence IN ('detected', 'inferred', 'timeout', 'unresolved')),
    release_timestamp_seconds DOUBLE PRECISION NULL,
    resolved_timestamp_seconds DOUBLE PRECISION NULL,
    shooter_candidates JSONB NULL,
    calc_version SMALLINT NOT NULL DEFAULT 2,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, shot_id)
);

CREATE INDEX IF NOT EXISTS idx_player_analysis_shots_player
    ON player_analysis_shots (player_id, owner_user_id);
CREATE INDEX IF NOT EXISTS idx_player_analysis_shots_job ON player_analysis_shots (job_id);
CREATE INDEX IF NOT EXISTS idx_player_analysis_shots_video ON player_analysis_shots (video_id);
