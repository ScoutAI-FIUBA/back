CREATE TABLE IF NOT EXISTS clip_collections (
    id UUID PRIMARY KEY,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(180) NOT NULL,
    description TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_collection_items (
    id UUID PRIMARY KEY,
    collection_id UUID NOT NULL REFERENCES clip_collections(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    cloudflare_url TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position > 0),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (collection_id, position)
);

CREATE INDEX IF NOT EXISTS idx_clip_collections_video_created_at
    ON clip_collections (video_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clip_collections_owner_video_created_at
    ON clip_collections (owner_user_id, video_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clip_collection_items_collection_position
    ON clip_collection_items (collection_id, position ASC, created_at ASC);
