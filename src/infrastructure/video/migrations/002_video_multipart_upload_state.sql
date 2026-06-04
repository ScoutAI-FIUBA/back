ALTER TABLE videos
ADD COLUMN IF NOT EXISTS multipart_upload_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_videos_team_pending_upload
    ON videos (team_id, multipart_upload_id)
    WHERE status = 'PENDING_UPLOAD' AND deleted_at IS NULL;
