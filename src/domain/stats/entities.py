"""Game statistics assembled from processing output."""

from __future__ import annotations

from dataclasses import dataclass, field


def _pct(made: int, attempted: int) -> float | None:
    """Shooting percentage, or None when nobody shot.

    None rather than 0.0 on purpose: a player who took no shots has no
    percentage, and showing 0% would read as having missed everything.
    """

    return None if attempted <= 0 else round(made / attempted, 3)


@dataclass
class ShotTally:
    """Shooting totals for one player or one team."""

    attempted: int = 0
    made: int = 0
    two_point_attempted: int = 0
    two_point_made: int = 0
    three_point_attempted: int = 0
    three_point_made: int = 0
    # Made and attempted per court zone, so a client can show where a player
    # scores rather than only where they shoot. Counting attempts alone would
    # make a cold shooter and a hot one look identical.
    by_zone: dict[str, dict[str, int]] = field(default_factory=dict)
    # Shots whose outcome the pipeline could not determine. They are NOT attempts:
    # counting an unknown as a miss would drag the percentage down for shots that
    # may well have gone in, so they are reported beside the totals instead.
    unresolved_attempts: int = 0
    unresolved_by_zone: dict[str, int] = field(default_factory=dict)
    # Made and attempted per shot type (jump_shot, layup, ...), resolved shots only.
    by_shot_type: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, *, made: bool, points: int, zone: str, shot_type: str | None = None) -> None:
        self.attempted += 1
        type_tally = self.by_shot_type.setdefault(shot_type or "unknown", {"made": 0, "attempted": 0})
        type_tally["attempted"] += 1
        if made:
            type_tally["made"] += 1
        tally = self.by_zone.setdefault(zone, {"made": 0, "attempted": 0})
        tally["attempted"] += 1
        if made:
            tally["made"] += 1
        if points == 3:
            self.three_point_attempted += 1
        else:
            self.two_point_attempted += 1
        if made:
            self.made += 1
            if points == 3:
                self.three_point_made += 1
            else:
                self.two_point_made += 1

    def add_unresolved(self, *, zone: str) -> None:
        self.unresolved_attempts += 1
        self.unresolved_by_zone[zone] = self.unresolved_by_zone.get(zone, 0) + 1

    def merge(self, other: "ShotTally") -> None:
        """Fold another tally in, for players the pipeline split in two."""

        self.attempted += other.attempted
        self.made += other.made
        self.two_point_attempted += other.two_point_attempted
        self.two_point_made += other.two_point_made
        self.three_point_attempted += other.three_point_attempted
        self.three_point_made += other.three_point_made
        self.unresolved_attempts += other.unresolved_attempts
        for zone, tally in other.by_zone.items():
            bucket = self.by_zone.setdefault(zone, {"made": 0, "attempted": 0})
            bucket["made"] += tally["made"]
            bucket["attempted"] += tally["attempted"]
        for zone, count in other.unresolved_by_zone.items():
            self.unresolved_by_zone[zone] = self.unresolved_by_zone.get(zone, 0) + count
        for shot_type, tally in other.by_shot_type.items():
            bucket = self.by_shot_type.setdefault(shot_type, {"made": 0, "attempted": 0})
            bucket["made"] += tally["made"]
            bucket["attempted"] += tally["attempted"]

    @property
    def points(self) -> int:
        return self.two_point_made * 2 + self.three_point_made * 3

    def zone_breakdown(self) -> dict[str, dict]:
        """Per-zone shooting, with a percentage where one is meaningful."""

        zones = sorted(set(self.by_zone) | set(self.unresolved_by_zone))
        breakdown: dict[str, dict] = {}
        for zone in zones:
            tally = self.by_zone.get(zone, {"made": 0, "attempted": 0})
            entry = {
                "made": tally["made"],
                "attempted": tally["attempted"],
                "pct": _pct(tally["made"], tally["attempted"]),
            }
            # Only present where a shot went unresolved, so clean zones keep the
            # shape they always had.
            if self.unresolved_by_zone.get(zone):
                entry["unresolved_attempts"] = self.unresolved_by_zone[zone]
            breakdown[zone] = entry
        return breakdown

    def to_dict(self) -> dict:
        return {
            "points": self.points,
            "field_goals_made": self.made,
            "field_goals_attempted": self.attempted,
            "field_goal_pct": _pct(self.made, self.attempted),
            "two_point_made": self.two_point_made,
            "two_point_attempted": self.two_point_attempted,
            "two_point_pct": _pct(self.two_point_made, self.two_point_attempted),
            "three_point_made": self.three_point_made,
            "three_point_attempted": self.three_point_attempted,
            "three_point_pct": _pct(self.three_point_made, self.three_point_attempted),
            "unresolved_attempts": self.unresolved_attempts,
            "by_zone": self.zone_breakdown(),
            "by_shot_type": {kind: dict(tally) for kind, tally in sorted(self.by_shot_type.items())},
        }


@dataclass
class PlayerStats:
    """One tracked player.

    `track_id` is the pipeline's identifier and is always present. `jersey_number`
    is filled in only when the pipeline could read it confidently, and
    `roster_player_id` only once a track has been linked to a real player — so a
    client must be able to render a row with neither.

    TODO(jersey-numbers): today ~4/10 players get a confirmed number, so most
    rows fall back to "Player 7" and `roster_player_id` is always null. When CV
    number recognition improves, these fill in and stats become per named player.
    Do not build the UI assuming they stay empty.
    """

    track_id: int
    team_id: int | None = None
    jersey_number: str | None = None
    roster_player_id: str | None = None
    # The real player's name, filled in only once a track is linked to the
    # scout's roster (own team, matched by jersey number). Opponents stay
    # unlinked, so this is None for them and the label falls back to the number.
    roster_name: str | None = None
    # v2's real identity (one per player, versus many segmented `track_id`s).
    # Present only on v2 output; None on v1.
    stable_player_id: str | None = None
    # How many frames this player was tracked, used to rank who was actually on
    # court (10 players) versus refs/bench/fragments. 0 when unknown.
    observations: int = 0
    # True for the most-present five per team — the players on court.
    on_court: bool = False
    # Time on screen and ground covered, from the pipeline's player summary. None
    # when the job predates it (distance) or the frame rate is unknown (seconds).
    seconds_observed: float | None = None
    distance_m: float | None = None
    # How trustworthy the jersey read is: confirmed / ambiguous / unknown, and how
    # many sampled frames agreed. `team_agreement` is the share of the player's
    # rows that sit on their team (1.0 = never flipped sides).
    jersey_status: str = "unknown"
    jersey_support_count: int = 0
    team_agreement: float | None = None
    shooting: ShotTally = field(default_factory=ShotTally)

    @property
    def display_name(self) -> str:
        if self.roster_name:
            return self.roster_name
        if self.jersey_number:
            return f"#{self.jersey_number}"
        if self.stable_player_id:
            return self.stable_player_id
        return f"Player {self.track_id}"

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "stable_player_id": self.stable_player_id,
            "team_id": self.team_id,
            "jersey_number": self.jersey_number,
            "observations": self.observations,
            "on_court": self.on_court,
            "seconds_observed": self.seconds_observed,
            "distance_m": self.distance_m,
            "jersey_status": self.jersey_status,
            "jersey_support_count": self.jersey_support_count,
            "team_agreement": self.team_agreement,
            "roster_player_id": self.roster_player_id,
            "roster_name": self.roster_name,
            "display_name": self.display_name,
            **self.shooting.to_dict(),
        }


@dataclass
class TeamStats:
    team_id: int
    shooting: ShotTally = field(default_factory=ShotTally)
    player_count: int = 0

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "players_tracked": self.player_count,
            **self.shooting.to_dict(),
        }


@dataclass
class GameStats:
    """Everything the analysis screen needs for one processed video."""

    teams: list[TeamStats] = field(default_factory=list)
    players: list[PlayerStats] = field(default_factory=list)
    shots: list[dict] = field(default_factory=list)
    # Honest reporting of what could not be determined, so the interface can say
    # so rather than implying the numbers are complete.
    coverage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "teams": [team.to_dict() for team in self.teams],
            "players": [player.to_dict() for player in self.players],
            "shots": self.shots,
            "coverage": self.coverage,
        }
