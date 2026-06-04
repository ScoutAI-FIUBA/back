CREATE TABLE IF NOT EXISTS videos (
    id UUID PRIMARY KEY,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    storage_key TEXT NOT NULL UNIQUE,
    title VARCHAR(180) NOT NULL,
    description TEXT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING_UPLOAD', 'READY', 'FAILED', 'DELETED')),
    mime_type TEXT NULL,
    size_bytes BIGINT NULL CHECK (size_bytes > 0),
    duration_ms INTEGER NULL CHECK (duration_ms > 0),
    etag TEXT NULL,
    upload_expires_at TIMESTAMPTZ NULL,
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS video_players (
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(video_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_videos_team_status_created_at
    ON videos (team_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_videos_team_created_not_deleted
    ON videos (team_id, created_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_videos_owner_created_at
    ON videos (owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_video_players_player_id
    ON video_players (player_id);
