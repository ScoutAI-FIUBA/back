from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.application.matches.errors import (
    INVALID_MATCH_TEAMS,
    INVALID_WINNER_TEAM,
    MATCH_NOT_FOUND,
    PLAYER_NOT_FOUND,
    TEAM_NOT_FOUND,
    MatchError,
)
from src.application.matches.ports import IdGeneratorPort, MatchRepositoryPort, UnitOfWorkPort
from src.application.players.ports import PlayerRepositoryPort
from src.application.team.ports import TeamRepositoryPort
from src.domain.matches.entities import Match, MatchParticipant, MatchStatsView, TeamStatsSummary


@dataclass(frozen=True)
class CreateMatchCommand:
    user_id: str
    home_team_id: str
    away_team_id: str
    match_date: date
    description: str | None = None


@dataclass(frozen=True)
class UpdateMatchDetailsCommand:
    user_id: str
    match_id: str
    match_date: date | None = None
    # description may legitimately be None (clear it), so "not provided" needs its own flag.
    update_description: bool = False
    description: str | None = None


@dataclass(frozen=True)
class ReplaceMatchParticipantInput:
    team_side: str
    display_name: str
    player_id: str | None = None
    jersey_number: str | None = None


@dataclass(frozen=True)
class ReplaceMatchStatsCommand:
    user_id: str
    match_id: str
    stats: Any | None
    participants: list[ReplaceMatchParticipantInput]
    winner_team_id: str | None = None


def _require_owned_team(*, teams: TeamRepositoryPort, user_id: str, team_id: str) -> None:
    if not teams.is_owned_by(team_id=team_id, owner_user_id=user_id):
        raise MatchError(code=TEAM_NOT_FOUND, message="Team not found")


def _require_owned_player(*, players: PlayerRepositoryPort, user_id: str, player_id: str) -> None:
    if players.get_by_id(player_id=player_id, owner_user_id=user_id) is None:
        raise MatchError(code=PLAYER_NOT_FOUND, message="Player not found")


class CreateMatchUseCase:
    def __init__(
        self,
        *,
        matches: MatchRepositoryPort,
        teams: TeamRepositoryPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._matches = matches
        self._teams = teams
        self._ids = ids
        self._uow = uow

    def execute(self, command: CreateMatchCommand) -> Match:
        with self._uow.transaction():
            if command.home_team_id == command.away_team_id:
                raise MatchError(
                    code=INVALID_MATCH_TEAMS,
                    message="Home and away teams must be different",
                )
            _require_owned_team(teams=self._teams, user_id=command.user_id, team_id=command.home_team_id)
            _require_owned_team(teams=self._teams, user_id=command.user_id, team_id=command.away_team_id)
            return self._matches.create(
                Match(
                    id=self._ids.new_id(),
                    owner_user_id=command.user_id,
                    home_team_id=command.home_team_id,
                    away_team_id=command.away_team_id,
                    match_date=command.match_date,
                    description=command.description,
                )
            )


class UpdateMatchDetailsUseCase:
    """Edits only the date and description. Teams stay immutable: changing them would
    invalidate the stored stats, winner, participants and linked videos."""

    def __init__(self, *, matches: MatchRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._matches = matches
        self._uow = uow

    def execute(self, command: UpdateMatchDetailsCommand) -> Match:
        with self._uow.transaction():
            if command.match_date is None and not command.update_description:
                match = self._matches.get_by_id(match_id=command.match_id, owner_user_id=command.user_id)
            else:
                match = self._matches.update_details(
                    match_id=command.match_id,
                    owner_user_id=command.user_id,
                    match_date=command.match_date,
                    update_description=command.update_description,
                    description=command.description,
                )
        if match is None:
            raise MatchError(code=MATCH_NOT_FOUND, message="Match not found")
        return match


class ListMatchesUseCase:
    def __init__(self, *, matches: MatchRepositoryPort, teams: TeamRepositoryPort) -> None:
        self._matches = matches
        self._teams = teams

    def execute(self, *, user_id: str, team_id: str | None = None) -> list[Match]:
        if team_id is not None:
            _require_owned_team(teams=self._teams, user_id=user_id, team_id=team_id)
        return self._matches.list_by_owner(owner_user_id=user_id, team_id=team_id)


class GetMatchUseCase:
    def __init__(self, *, matches: MatchRepositoryPort) -> None:
        self._matches = matches

    def execute(self, *, user_id: str, match_id: str) -> Match:
        match = self._matches.get_by_id(match_id=match_id, owner_user_id=user_id)
        if match is None:
            raise MatchError(code=MATCH_NOT_FOUND, message="Match not found")
        return match


class ReplaceMatchStatsUseCase:
    def __init__(
        self,
        *,
        matches: MatchRepositoryPort,
        players: PlayerRepositoryPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._matches = matches
        self._players = players
        self._ids = ids
        self._uow = uow

    def execute(self, command: ReplaceMatchStatsCommand) -> MatchStatsView:
        with self._uow.transaction():
            match = self._matches.get_by_id(match_id=command.match_id, owner_user_id=command.user_id)
            if match is None:
                raise MatchError(code=MATCH_NOT_FOUND, message="Match not found")
            if command.winner_team_id is not None and command.winner_team_id not in {
                match.home_team_id,
                match.away_team_id,
            }:
                raise MatchError(
                    code=INVALID_WINNER_TEAM,
                    message="Winner team must match the home or away team",
                )
            for item in command.participants:
                if item.player_id is not None:
                    _require_owned_player(players=self._players, user_id=command.user_id, player_id=item.player_id)
            participants = [
                MatchParticipant(
                    id=self._ids.new_id(),
                    match_id=command.match_id,
                    owner_user_id=command.user_id,
                    player_id=item.player_id,
                    team_side=item.team_side,
                    display_name=item.display_name,
                    jersey_number=item.jersey_number,
                )
                for item in command.participants
            ]
            updated = self._matches.replace_stats(
                match_id=command.match_id,
                owner_user_id=command.user_id,
                stats=command.stats,
                winner_team_id=command.winner_team_id,
                participants=participants,
            )
        if updated is None:
            raise MatchError(code=MATCH_NOT_FOUND, message="Match not found")
        return updated


class GetMatchStatsUseCase:
    def __init__(self, *, matches: MatchRepositoryPort) -> None:
        self._matches = matches

    def execute(self, *, user_id: str, match_id: str) -> MatchStatsView:
        view = self._matches.get_stats(match_id=match_id, owner_user_id=user_id)
        if view is None:
            raise MatchError(code=MATCH_NOT_FOUND, message="Match not found")
        return view


class GetPlayerMatchesUseCase:
    def __init__(self, *, matches: MatchRepositoryPort, players: PlayerRepositoryPort) -> None:
        self._matches = matches
        self._players = players

    def execute(self, *, user_id: str, player_id: str) -> list[Match]:
        player = self._players.get_by_id(player_id=player_id, owner_user_id=user_id)
        if player is None:
            raise MatchError(code=PLAYER_NOT_FOUND, message="Player not found")
        return self._matches.list_player_matches(owner_user_id=user_id, player_id=player.id)


class GetTeamStatsUseCase:
    def __init__(self, *, matches: MatchRepositoryPort, teams: TeamRepositoryPort) -> None:
        self._matches = matches
        self._teams = teams

    def execute(self, *, user_id: str, team_id: str) -> TeamStatsSummary:
        _require_owned_team(teams=self._teams, user_id=user_id, team_id=team_id)
        return self._matches.get_team_stats(owner_user_id=user_id, team_id=team_id)
