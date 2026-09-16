CREATE OR REPLACE FUNCTION pg_temp.jsonb_to_int_or_null(value jsonb)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE jsonb_typeof(value)
        WHEN 'number' THEN trunc((value #>> '{}')::numeric)::int
        WHEN 'boolean' THEN CASE WHEN (value #>> '{}')::boolean THEN 1 ELSE 0 END
        WHEN 'string' THEN CASE
            WHEN btrim(value #>> '{}') ~ '^[+-]?\d+$' THEN btrim(value #>> '{}')::int
            ELSE NULL
        END
        ELSE NULL
    END
$$;

ALTER TABLE players
ALTER COLUMN stats SET DEFAULT jsonb_build_object(
    'games_played', 0,
    'record', jsonb_build_object('wins', 0, 'losses', 0),
    'points', jsonb_build_object('total', 0, 'per_game', 0),
    'rebounds', jsonb_build_object('total', 0, 'per_game', 0),
    'assists', jsonb_build_object('total', 0, 'per_game', 0),
    'steals', jsonb_build_object('total', 0, 'per_game', 0),
    'blocks', jsonb_build_object('total', 0, 'per_game', 0),
    'turnovers', jsonb_build_object('total', 0, 'per_game', 0),
    'field_goals', jsonb_build_object('made_total', 0, 'attempted_total', 0, 'per_game', jsonb_build_object('made', 0, 'attempted', 0), 'percentage', 0),
    'two_point', jsonb_build_object('made_total', 0, 'attempted_total', 0, 'per_game', jsonb_build_object('made', 0, 'attempted', 0), 'percentage', 0),
    'three_point', jsonb_build_object('made_total', 0, 'attempted_total', 0, 'per_game', jsonb_build_object('made', 0, 'attempted', 0), 'percentage', 0),
    'free_throws', jsonb_build_object('made_total', 0, 'attempted_total', 0, 'per_game', jsonb_build_object('made', 0, 'attempted', 0), 'percentage', 0)
);

WITH source_rows AS (
    SELECT
        id,
        CASE
            WHEN jsonb_typeof(stats) = 'object' THEN stats
            ELSE '{}'::jsonb
        END AS stats_source,
        COALESCE(stats->'field_goals', '{}'::jsonb) AS field_goals_source,
        COALESCE(stats->'two_point', stats->'two_points', '{}'::jsonb) AS two_point_source,
        COALESCE(stats->'three_point', stats->'three_points', '{}'::jsonb) AS three_point_source,
        COALESCE(stats->'free_throws', '{}'::jsonb) AS free_throws_source
    FROM players
)
UPDATE players AS players_target
SET stats = jsonb_build_object(
    'games_played',
    COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'games_played'), 0),
    'record', jsonb_build_object(
        'wins',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'record'->'wins'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'wins'),
            0
        ),
        'losses',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'record'->'losses'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'losses'),
            0
        )
    ),
    'points', jsonb_build_object(
        'total',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'points'->'total'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'points'),
            0
        ),
        'per_game',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'points'->'per_game'),
            0
        )
    ),
    'rebounds', jsonb_build_object(
        'total',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'rebounds'->'total'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'rebounds'),
            0
        ),
        'per_game',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'rebounds'->'per_game'),
            0
        )
    ),
    'assists', jsonb_build_object(
        'total',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'assists'->'total'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'assists'),
            0
        ),
        'per_game',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'assists'->'per_game'),
            0
        )
    ),
    'steals', jsonb_build_object(
        'total',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'steals'->'total'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'steals'),
            0
        ),
        'per_game',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'steals'->'per_game'),
            0
        )
    ),
    'blocks', jsonb_build_object(
        'total',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'blocks'->'total'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'blocks'),
            0
        ),
        'per_game',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'blocks'->'per_game'),
            0
        )
    ),
    'turnovers', jsonb_build_object(
        'total',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'turnovers'->'total'),
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'turnovers'),
            0
        ),
        'per_game',
        COALESCE(
            pg_temp.jsonb_to_int_or_null(source_rows.stats_source->'turnovers'->'per_game'),
            0
        )
    ),
    'field_goals', jsonb_build_object(
        'made_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.field_goals_source->'made_total'), 0),
        'attempted_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.field_goals_source->'attempted_total'), 0),
        'per_game', jsonb_build_object(
            'made', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.field_goals_source->'per_game'->'made'), 0),
            'attempted', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.field_goals_source->'per_game'->'attempted'), 0)
        ),
        'percentage', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.field_goals_source->'percentage'), 0)
    ),
    'two_point', jsonb_build_object(
        'made_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.two_point_source->'made_total'), 0),
        'attempted_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.two_point_source->'attempted_total'), 0),
        'per_game', jsonb_build_object(
            'made', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.two_point_source->'per_game'->'made'), 0),
            'attempted', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.two_point_source->'per_game'->'attempted'), 0)
        ),
        'percentage', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.two_point_source->'percentage'), 0)
    ),
    'three_point', jsonb_build_object(
        'made_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.three_point_source->'made_total'), 0),
        'attempted_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.three_point_source->'attempted_total'), 0),
        'per_game', jsonb_build_object(
            'made', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.three_point_source->'per_game'->'made'), 0),
            'attempted', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.three_point_source->'per_game'->'attempted'), 0)
        ),
        'percentage', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.three_point_source->'percentage'), 0)
    ),
    'free_throws', jsonb_build_object(
        'made_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.free_throws_source->'made_total'), 0),
        'attempted_total', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.free_throws_source->'attempted_total'), 0),
        'per_game', jsonb_build_object(
            'made', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.free_throws_source->'per_game'->'made'), 0),
            'attempted', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.free_throws_source->'per_game'->'attempted'), 0)
        ),
        'percentage', COALESCE(pg_temp.jsonb_to_int_or_null(source_rows.free_throws_source->'percentage'), 0)
    )
)
FROM source_rows
WHERE players_target.id = source_rows.id;

ALTER TABLE players
ALTER COLUMN stats SET NOT NULL;
