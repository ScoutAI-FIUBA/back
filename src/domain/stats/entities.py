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

    def add(self, *, made: bool, points: int, zone: str) -> None:
        self.attempted += 1
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

    @property
    def points(self) -> int:
        return self.two_point_made * 2 + self.three_point_made * 3

    def zone_breakdown(self) -> dict[str, dict]:
        """Per-zone shooting, with a percentage where one is meaningful."""

        return {
            zone: {
                "made": tally["made"],
                "attempted": tally["attempted"],
                "pct": _pct(tally["made"], tally["attempted"]),
            }
            for zone, tally in sorted(self.by_zone.items())
        }

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
            "by_zone": self.zone_breakdown(),
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
    shooting: ShotTally = field(default_factory=ShotTally)

    @property
    def display_name(self) -> str:
        if self.jersey_number:
            return f"#{self.jersey_number}"
        return f"Player {self.track_id}"

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "team_id": self.team_id,
            "jersey_number": self.jersey_number,
            "roster_player_id": self.roster_player_id,
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
