from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.application.matches.errors import (
    INVALID_MATCH_TEAMS,
    INVALID_STATS_FILE,
    STATS_FILE_TOO_LARGE,
    TEAM_MISMATCH,
    TEAM_NOT_FOUND,
    MatchError,
)
from src.application.players.ports import PlayerRepositoryPort
from src.application.team.ports import TeamRepositoryPort
from src.domain.matches.box_score import BoxScoreLine, BoxScorePlayer, BoxScoreTeam, ParsedBoxScore
from src.domain.matches.team_matching import name_similarity, roster_similarity, same_team


class BoxScoreFileError(Exception):
    def __init__(self, message: str, *, too_large: bool = False) -> None:
        self.too_large = too_large
        super().__init__(message)


class BoxScoreParserPort(ABC):
    @abstractmethod
    def parse(self, data: bytes) -> ParsedBoxScore:
        raise NotImplementedError


@dataclass(frozen=True)
class PreviewStatsImportCommand:
    user_id: str
    data: bytes
    home_team_id: str | None = None
    away_team_id: str | None = None
    allow_team_mismatch: bool = False


@dataclass(frozen=True)
class StatsImportPreview:
    """Draft that the client can review and then save with ``PUT /matches/{id}/stats``."""

    winner_team_id: str | None
    participants: list[dict[str, Any]]
    stats: dict[str, Any]
    report: dict[str, Any] = field(default_factory=dict)


def _shooting(made: int, attempted: int) -> dict[str, Any]:
    return {
        "made": made,
        "attempted": attempted,
        "pct": round(made * 100 / attempted, 1) if attempted else None,
    }


def _line_payload(line: BoxScoreLine) -> dict[str, Any]:
    minutes, seconds = divmod(line.minutes_seconds, 60)
    return {
        "minutes": f"{minutes:02d}:{seconds:02d}",
        "seconds_played": line.minutes_seconds,
        "points": line.points,
        "two_point": _shooting(line.two_point.made, line.two_point.attempted),
        "three_point": _shooting(line.three_point.made, line.three_point.attempted),
        "free_throws": _shooting(line.free_throw.made, line.free_throw.attempted),
        "rebounds": {
            "defensive": line.rebounds_defensive,
            "offensive": line.rebounds_offensive,
            "total": line.rebounds_total,
        },
        "assists": line.assists,
        "steals": line.steals,
        "turnovers": line.turnovers,
        "blocks": line.blocks,
        "blocks_received": line.blocks_received,
        "fouls": line.fouls,
        "fouls_drawn": line.fouls_drawn,
        "valuation": line.valuation,
        "plus_minus": line.plus_minus,
    }


def _computed_points(line: BoxScoreLine) -> int:
    return 2 * line.two_point.made + 3 * line.three_point.made + line.free_throw.made


class PreviewMatchStatsImportUseCase:
    """Turns an uploaded federation box score into a match-stats draft.

    Read-only: nothing is persisted. Linking to roster players is by jersey number
    and only when the number identifies exactly one player of that team.
    """

    def __init__(
        self,
        *,
        parser: BoxScoreParserPort,
        teams: TeamRepositoryPort,
        players: PlayerRepositoryPort,
    ) -> None:
        self._parser = parser
        self._teams = teams
        self._players = players

    def execute(self, command: PreviewStatsImportCommand) -> StatsImportPreview:
        if command.home_team_id is not None and command.home_team_id == command.away_team_id:
            raise MatchError(code=INVALID_MATCH_TEAMS, message="Home and away teams must be different")
        try:
            score = self._parser.parse(command.data)
        except BoxScoreFileError as exc:
            code = STATS_FILE_TOO_LARGE if exc.too_large else INVALID_STATS_FILE
            raise MatchError(code=code, message=str(exc)) from None

        warnings: list[str] = []
        owned = {team.id: team for team in self._teams.list_by_owner(owner_user_id=command.user_id)}
        selected = {"HOME": command.home_team_id, "AWAY": command.away_team_id}
        for team_id in selected.values():
            if team_id is not None and team_id not in owned:
                raise MatchError(code=TEAM_NOT_FOUND, message="Team not found")

        rosters = {
            side: (
                self._players.list_by_owner_and_team(owner_user_id=command.user_id, team_id=team_id)
                if team_id is not None
                else []
            )
            for side, team_id in selected.items()
        }
        blocks, checks = self._assign_sides(
            score, selected, owned, rosters, allow_mismatch=command.allow_team_mismatch, warnings=warnings
        )

        participants: list[dict[str, Any]] = []
        player_rows: list[dict[str, Any]] = []
        team_reports: list[dict[str, Any]] = []
        linked: list[dict[str, Any]] = []
        unlinked: list[dict[str, Any]] = []
        team_stats: dict[str, Any] = {}

        for side in ("HOME", "AWAY"):
            block = blocks[side]
            team_id = selected[side]
            roster = self._roster_by_jersey(rosters[side])
            seen_numbers: set[str] = set()
            played_points = 0
            for player in block.players:
                played_points += player.line.points
                if player.line.points != _computed_points(player.line):
                    warnings.append(
                        f"{block.name} #{player.jersey_number or '?'} {player.name}: points do not equal "
                        "2P/3P/FT made"
                    )
                if player.jersey_number is not None:
                    if player.jersey_number in seen_numbers:
                        warnings.append(f"{block.name}: jersey number {player.jersey_number} appears twice")
                    seen_numbers.add(player.jersey_number)
                player_id = self._link(player, roster, side, linked, unlinked, selected[side] is not None)
                player_rows.append(
                    {
                        "team_side": side,
                        "jersey_number": player.jersey_number,
                        "name": player.name,
                        "played": player.played,
                        "player_id": player_id,
                        **_line_payload(player.line),
                    }
                )
                if player.played:
                    participants.append(
                        {
                            "team_side": side,
                            "display_name": player.name,
                            "jersey_number": player.jersey_number,
                            "player_id": player_id,
                        }
                    )
            totals = block.totals
            if totals is not None and totals.points != played_points:
                warnings.append(
                    f"{block.name}: player points add up to {played_points} but the file totals say {totals.points}"
                )
            team_stats[side] = {
                "name": block.name,
                "points": totals.points if totals is not None else played_points,
                "totals": _line_payload(totals) if totals is not None else None,
            }
            team_reports.append(
                {
                    "side": side,
                    "excel_name": block.name,
                    "team_id": team_id,
                    "team_name": owned[team_id].name if team_id is not None else None,
                    "name_score": checks[side]["name_score"],
                    "roster_score": checks[side]["roster_score"],
                    "matches_selected_team": checks[side]["matches"],
                    "players_in_file": len(block.players),
                    "players_who_played": sum(1 for p in block.players if p.played),
                }
            )

        winner_team_id = None
        home_points, away_points = team_stats["HOME"]["points"], team_stats["AWAY"]["points"]
        if home_points != away_points:
            winner_side = "HOME" if home_points > away_points else "AWAY"
            winner_team_id = selected[winner_side]

        return StatsImportPreview(
            winner_team_id=winner_team_id,
            participants=participants,
            stats={
                "source": "cabb_excel",
                "schema_version": 1,
                "title": score.title,
                "competition": score.competition,
                "teams": team_stats,
                "players": player_rows,
            },
            report={
                "teams": team_reports,
                "linked_players": linked,
                "unlinked_players": unlinked,
                "warnings": warnings,
            },
        )

    def _assign_sides(
        self,
        score: ParsedBoxScore,
        selected: dict[str, str | None],
        owned: dict[str, Any],
        rosters: dict[str, list[Any]],
        *,
        allow_mismatch: bool,
        warnings: list[str],
    ) -> tuple[dict[str, BoxScoreTeam], dict[str, dict[str, Any]]]:
        """Decides which table is HOME and which is AWAY and checks them against the selected teams.

        A table belongs to a team when the names are alike (abbreviations and punctuation
        tolerated) or the players are (same jersey number and surname). Either is enough.
        """

        first, second = score.teams

        def check(block: BoxScoreTeam, side: str) -> dict[str, Any]:
            team_id = selected[side]
            if team_id is None:
                return {"name_score": None, "roster_score": None, "matches": None, "combined": 0.0}
            name_score = round(name_similarity(block.name, owned[team_id].name), 2)
            roster_score = roster_similarity(
                [(p.jersey_number, p.name) for p in block.players],
                [(p.jersey_number, p.last_name) for p in rosters[side]],
            )
            roster_score = round(roster_score, 2) if roster_score is not None else None
            return {
                "name_score": name_score,
                "roster_score": roster_score,
                "matches": same_team(name_score, roster_score),
                "combined": max(name_score, roster_score or 0.0),
            }

        straight = {"HOME": check(first, "HOME"), "AWAY": check(second, "AWAY")}
        swapped = {"HOME": check(second, "HOME"), "AWAY": check(first, "AWAY")}
        use_swapped = sum(c["combined"] for c in swapped.values()) > sum(c["combined"] for c in straight.values())
        blocks = {"HOME": second, "AWAY": first} if use_swapped else {"HOME": first, "AWAY": second}
        checks = swapped if use_swapped else straight

        bad = [side for side in ("HOME", "AWAY") if checks[side]["matches"] is False]
        if bad:
            details = {
                "teams": [
                    {
                        "side": side,
                        "selected_team": owned[selected[side]].name,
                        "name_in_file": blocks[side].name,
                        "name_score": checks[side]["name_score"],
                        "roster_score": checks[side]["roster_score"],
                    }
                    for side in bad
                ]
            }
            if not allow_mismatch:
                raise MatchError(
                    code=TEAM_MISMATCH,
                    message="The team in the file does not look like the selected team.",
                    details=details,
                )
            for entry in details["teams"]:
                warnings.append(
                    f"The file's team {entry['name_in_file']!r} does not look like {entry['selected_team']!r} "
                    "(accepted because the mismatch was allowed)."
                )
        return blocks, checks

    @staticmethod
    def _roster_by_jersey(roster_players: list[Any]) -> dict[str, list[Any]]:
        roster: dict[str, list[Any]] = {}
        for player in roster_players:
            if player.jersey_number:
                roster.setdefault(player.jersey_number, []).append(player)
        return roster

    @staticmethod
    def _link(
        player: BoxScorePlayer,
        roster: dict[str, list[Any]],
        side: str,
        linked: list[dict[str, Any]],
        unlinked: list[dict[str, Any]],
        has_team: bool,
    ) -> str | None:
        entry = {"team_side": side, "jersey_number": player.jersey_number, "name": player.name}
        if not has_team or player.jersey_number is None:
            unlinked.append({**entry, "reason": "no_team_selected" if not has_team else "no_jersey_number"})
            return None
        candidates = roster.get(player.jersey_number, [])
        if len(candidates) == 1:
            found = candidates[0]
            linked.append({**entry, "player_id": found.id, "roster_name": f"{found.first_name} {found.last_name}"})
            return found.id
        unlinked.append({**entry, "reason": "ambiguous_jersey_number" if candidates else "no_roster_player"})
        return None
