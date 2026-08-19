-- Results reported by the processing service when a job finishes.
--
-- Stored here rather than fetched from object storage on demand: the service
-- already knows what it wrote, so it sends the list in its completion callback.
-- That keeps this app from ever reading job outputs — it only mints presigned
-- URLs, which is a local signing operation.

ALTER TABLE processing_jobs
    -- Filenames written under `results_key`, e.g. ["results.json", "tracks.jsonl"].
    -- A list rather than a fixed set of columns so the processing service can add
    -- artifacts without a migration here.
    ADD COLUMN IF NOT EXISTS artifacts JSONB NULL,
    -- Small run summary (frames processed, tracks found, timings) surfaced
    -- directly on the job so the UI can show outcome numbers while polling,
    -- without a second request for the results payload.
    ADD COLUMN IF NOT EXISTS summary JSONB NULL;
