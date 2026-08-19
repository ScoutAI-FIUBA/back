CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    requested_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
    -- Identifier returned by the processing service when the job is accepted.
    -- Null until the service has acknowledged it.
    external_job_id TEXT NULL,
    -- Object-storage prefix holding results.json / tracks.jsonl once finished.
    results_key TEXT NULL,
    error_message TEXT NULL,
    -- 0-100, best effort. Null when the service reports no progress.
    progress_percent SMALLINT NULL CHECK (progress_percent BETWEEN 0 AND 100),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

-- A video may only have one job in flight at a time. GPU minutes are the most
-- expensive thing this system spends, so a double-submit (impatient user, retry
-- loop, double-clicked button) must be rejected by the database rather than
-- relied upon to be caught in application code.
CREATE UNIQUE INDEX IF NOT EXISTS idx_processing_jobs_one_active_per_video
    ON processing_jobs (video_id)
    WHERE status IN ('QUEUED', 'RUNNING');

-- Listing a team's jobs, newest first.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_team_created_at
    ON processing_jobs (team_id, created_at DESC);

-- Looking up every job for one video.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_video_created_at
    ON processing_jobs (video_id, created_at DESC);
