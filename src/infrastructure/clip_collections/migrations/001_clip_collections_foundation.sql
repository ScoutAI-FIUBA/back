-- Converges the pre-virtual-clip schema: those tables stored one row per
-- exported file, so there is no in-place upgrade to the start_ms/end_ms shape.
-- Guarded on the old columns, so it is inert on a current database, and the
-- migration runner records this file once rather than replaying it per deploy.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = CURRENT_SCHEMA()
          AND table_name = 'clip_collection_items'
          AND column_name IN ('filename', 'storage_key', 'cloudflare_url')
    ) THEN
        DROP TABLE IF EXISTS clip_collection_items;
        DROP TABLE IF EXISTS clip_collections;
    END IF;
END $$;

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
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    CHECK (end_ms - start_ms <= 30000),
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
