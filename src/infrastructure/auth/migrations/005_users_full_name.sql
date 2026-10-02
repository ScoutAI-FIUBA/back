-- The display name previously lived only in the browser's localStorage, so it
-- was lost on any other device. Nullable because accounts created before this
-- never sent one. Idempotent.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS full_name VARCHAR(120) NULL;
