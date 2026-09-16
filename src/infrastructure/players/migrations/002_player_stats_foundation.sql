ALTER TABLE players
ADD COLUMN IF NOT EXISTS stats JSONB;

UPDATE players
SET stats = jsonb_build_object(
    'games_played', 0,
    'wins', 0,
    'losses', 0,
    'points', 0,
    'rebounds', 0,
    'assists', 0,
    'steals', 0,
    'blocks', 0,
    'turnovers', 0
)
WHERE stats IS NULL;

ALTER TABLE players
ALTER COLUMN stats SET DEFAULT jsonb_build_object(
    'games_played', 0,
    'wins', 0,
    'losses', 0,
    'points', 0,
    'rebounds', 0,
    'assists', 0,
    'steals', 0,
    'blocks', 0,
    'turnovers', 0
);

ALTER TABLE players
ALTER COLUMN stats SET NOT NULL;
