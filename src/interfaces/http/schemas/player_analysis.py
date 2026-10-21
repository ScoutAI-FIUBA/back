"""Response models of the two player analysis endpoints, so their JSON shape is a stable contract.

Conventions, the same as every other stats endpoint:
- Shooting `pct` is a FRACTION between 0 and 1 (0.667), or null when the player never shot.
  `players.stats.*.percentage` (the player profile) is a different, older contract: an
  integer percent between 0 and 100.
- `seconds_on_screen` is time visible in the video, in seconds. It is not minutes played.
- `timestamp_seconds` counts from the start of the analysed video.
- `shot_value` is what the shot is worth by where it was taken (2 or 3), even when it missed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ShotChartPlayer(BaseModel):
    id: str
    first_name: str
    last_name: str
    jersey_number: str | None
    team_id: str | None


class ShotChartShot(BaseModel):
    shot_key: str = Field(description="Unique among all of the player's shots: '<job_id>:<shot_id>', or '<job_id>:row<id>' without a shot id.")
    shot_id: int | None
    job_id: str
    video_id: str
    video_title: str | None
    x_m: float
    y_m: float
    made: bool
    result: Literal["made", "missed", "unknown"] = Field(description="'unknown' is a shot whose outcome could not be resolved.")
    shot_value: Literal[2, 3] = Field(description="Worth of the shot by location, even when missed.")
    zone: str | None
    shot_type: str | None
    distance_m: float | None
    timestamp_seconds: float | None = Field(description="Seconds from the start of the analysed video, rounded to 2 decimals.")
    outcome_confidence: Literal["detected", "inferred", "timeout", "unresolved"] | None
    outcome_source: str | None
    release_timestamp_seconds: float | None
    resolved_timestamp_seconds: float | None
    attribution: str | None
    needs_review: bool | None


class ShotChartCoverage(BaseModel):
    shots_charted: int
    made: int
    missed: int
    unresolved: int
    videos: int


class ShotChartResponse(BaseModel):
    player_id: str
    player: ShotChartPlayer
    calc_version: int = Field(description="Version of the court/zone rules the shots were computed with.")
    court: dict[str, Any]
    shots: list[ShotChartShot]
    coverage: ShotChartCoverage


class ShootingSection(BaseModel):
    made: int
    attempted: int
    pct: float | None = Field(description="Fraction 0..1, null when there were no attempts.")


class BreakdownEntry(BaseModel):
    made: int
    attempted: int
    unresolved_attempts: int
    pct: float | None = Field(description="Fraction 0..1, null when there were no attempts.")


class AnalysisVideo(BaseModel):
    job_id: str
    video_id: str
    video_title: str | None
    jersey_number: str | None
    seconds_on_screen: float | None = Field(description="Seconds visible in this video, not minutes played.")
    distance_m: float | None
    points: int
    field_goals_made: int
    field_goals_attempted: int
    two_point_made: int
    two_point_attempted: int
    three_point_made: int
    three_point_attempted: int
    unresolved_attempts: int


class AnalysisStatsResponse(BaseModel):
    player_id: str
    calc_version: int = Field(description="Version of the court/zone rules the rows were computed with.")
    games: int = Field(description="Analysed videos where the player is linked, not official games.")
    points: int
    field_goals: ShootingSection
    two_point: ShootingSection
    three_point: ShootingSection
    unresolved_attempts: int
    seconds_on_screen: float | None
    distance_m: float | None
    by_zone: dict[str, BreakdownEntry]
    by_shot_type: dict[str, BreakdownEntry]
    videos: list[AnalysisVideo]
    not_measured: list[str]
