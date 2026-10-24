SET LOCAL lock_timeout = '5s';
ALTER TABLE videos ADD COLUMN IF NOT EXISTS match_id UUID NULL REFERENCES matches(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_videos_match_id ON videos (match_id) WHERE match_id IS NOT NULL;
