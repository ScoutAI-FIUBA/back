-- Adds the optional jersey number to players. Text so "00" stays distinct from
-- "0" and the value matches the CV pipeline, which reads numbers as strings.
-- Idempotent.

ALTER TABLE players
    ADD COLUMN IF NOT EXISTS jersey_number VARCHAR(2) NULL;

ALTER TABLE players
    DROP CONSTRAINT IF EXISTS players_jersey_number_check;

ALTER TABLE players
    ADD CONSTRAINT players_jersey_number_check
    CHECK (jersey_number IS NULL OR jersey_number ~ '^[0-9]{1,2}$');
