from __future__ import annotations

from dataclasses import dataclass

from src.application.team.ports import TeamClockPort, TeamIdGeneratorPort, TeamRepositoryPort
from src.domain.team.entities import Team


@dataclass(frozen=True)
class CreateTeamCommand:
    user_id: str
    name: str
    short_name: str
    city: str
    country: str


@dataclass(frozen=True)
class UpdateTeamCommand:
    user_id: str
    team_id: str
    name: str
    short_name: str
    city: str
    country: str


@dataclass(frozen=True)
class DeleteTeamCommand:
    user_id: str
    team_id: str


class CreateTeamUseCase:
    def __init__(self, *, teams: TeamRepositoryPort, clock: TeamClockPort, ids: TeamIdGeneratorPort) -> None:
        self._teams = teams
        self._clock = clock
        self._ids = ids

    def execute(self, command: CreateTeamCommand) -> Team:
        return self._teams.create(
            Team(
                id=self._ids.new_id(),
                name=command.name,
                short_name=command.short_name,
                city=command.city,
                country=command.country,
                owner_user_id=command.user_id,
                created_at=self._clock.now(),
            )
        )


class ListTeamsUseCase:
    def __init__(self, *, teams: TeamRepositoryPort) -> None:
        self._teams = teams

    def execute(self, *, user_id: str) -> list[Team]:
        return self._teams.list_by_owner(owner_user_id=user_id)


class UpdateTeamUseCase:
    def __init__(self, *, teams: TeamRepositoryPort) -> None:
        self._teams = teams

    def execute(self, command: UpdateTeamCommand) -> Team | None:
        return self._teams.update(
            command.team_id,
            owner_user_id=command.user_id,
            name=command.name,
            short_name=command.short_name,
            city=command.city,
            country=command.country,
        )


class DeleteTeamUseCase:
    def __init__(self, *, teams: TeamRepositoryPort) -> None:
        self._teams = teams

    def execute(self, command: DeleteTeamCommand) -> bool:
        return self._teams.delete(command.team_id, owner_user_id=command.user_id)
