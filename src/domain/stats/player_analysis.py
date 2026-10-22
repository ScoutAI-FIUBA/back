"""What the analyses measured for one roster player, across all of their videos.

Pure functions over plain rows so the rules (what counts as an attempt, how the player
totals are shaped) live in one place and are testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

# Version of the court/zone rules the stored zones and shot values were computed with.
# Bump it together with COURT_RULES_VERSION of the court module whenever those rules change,
# so rows kept under older rules can be told apart (and rebuilt).
CALC_VERSION = 2

MADE = "made"
MISSED = "missed"
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class PlayerGameRow:
    """One roster player's result in one analysed video."""

    player_id: str
    job_id: str
    video_id: str
    owner_user_id: str
    jersey_number: str | None
    # Time the player was visible in the video, in seconds. Not minutes played.
    seconds_on_screen: float | None
    distance_m: float | None
    points: int
    field_goals_made: int
    field_goals_attempted: int
    two_point_made: int
    two_point_attempted: int
    three_point_made: int
    three_point_attempted: int
    unresolved_attempts: int


@dataclass(frozen=True)
class PlayerShotRow:
    """One located shot taken by a roster player."""

    player_id: str
    job_id: str
    video_id: str
    owner_user_id: str
    shot_id: int | None
    outcome: str
    # What the shot is worth by where it was taken (2 or 3), even when it missed.
    shot_value: int
    zone: str | None
    shot_type: str | None
    distance_m: float | None
    court_x_m: float
    court_y_m: float
    timestamp_seconds: float | None
    attribution: str | None
    needs_review: bool | None
    outcome_source: str | None = None
    outcome_confidence: str | None = None
    release_timestamp_seconds: float | None = None
    resolved_timestamp_seconds: float | None = None
    shooter_candidates: list | None = None


def without_nul(value):
    """The value with every NUL character removed from its text.

    Postgres refuses `\\x00` in text and JSONB, and the text here comes from model output and
    user-entered titles, so it is stripped on the way in instead of failing the whole video.
    """

    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [without_nul(item) for item in value]
    if isinstance(value, dict):
        return {without_nul(key): without_nul(item) for key, item in value.items()}
    return value


def shot_outcome(row: dict) -> str:
    """made / missed / unresolved for a shot row of the game stats."""

    if row.get("made") is True or row.get("outcome") == MADE:
        return MADE
    if row.get("outcome") == MISSED:
        return MISSED
    return UNRESOLVED


def _round_half_up(value: float) -> int:
    # Python's round() sends 0.5 to 0 and 2.5 to 2; an average of "half a shot" should read 1.
    return int(value + 0.5)


def percentage(made: int, attempted: int) -> int:
    return _round_half_up(100 * made / attempted) if attempted else 0


def _per_game(total: int, games: int) -> int:
    """Whole-number average: the player stats contract stores integers. Exact totals are in the totals endpoint."""

    return _round_half_up(total / games) if games else 0


def _shooting(made: int, attempted: int, games: int) -> dict:
    return {
        "made_total": made,
        "attempted_total": attempted,
        "per_game": {"made": _per_game(made, games), "attempted": _per_game(attempted, games)},
        "percentage": percentage(made, attempted),
    }


def stats_patch(totals: dict) -> dict:
    """The part of a player's `stats` document the analyses can fill, from their totals.

    Only measured fields: rebounds, assists, steals, blocks, turnovers and free throws are
    not measured by the analysis, so they are left out and keep whatever the player has.
    """

    games = int(totals.get("games") or 0)
    points = int(totals.get("points") or 0)
    return {
        "games_played": games,
        "points": {"total": points, "per_game": _per_game(points, games)},
        "field_goals": _shooting(totals["field_goals_made"], totals["field_goals_attempted"], games),
        "two_point": _shooting(totals["two_point_made"], totals["two_point_attempted"], games),
        "three_point": _shooting(totals["three_point_made"], totals["three_point_attempted"], games),
    }
