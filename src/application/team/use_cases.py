from __future__ import annotations

"""Team application use cases.

These use cases define team-facing contracts and delegate persistence to
application ports.
"""

from dataclasses import dataclass

from src.application.team.ports import TeamClockPort, TeamIdGeneratorPort, TeamRepositoryPort
from src.domain.team.entities import Team


@dataclass(frozen=True)
class CreateTeamCommand:
    """Input contract for creating a team."""

    name: str
    short_name: str
    city: str
    country: str


@dataclass(frozen=True)
class UpdateTeamCommand:
    """Input contract for updating mutable team profile fields."""

    team_id: str
    name: str
    short_name: str
    city: str
    country: str


@dataclass(frozen=True)
class DeleteTeamCommand:
    """Input contract for deleting a team by identifier."""

    team_id: str


class CreateTeamUseCase:
    """Creates a team with generated identifier and creation timestamp."""

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
                created_at=self._clock.now(),
            )
        )


class ListTeamsUseCase:
    """Read-only listing of all teams."""

    def __init__(self, *, teams: TeamRepositoryPort) -> None:
        self._teams = teams

    def execute(self) -> list[Team]:
        return self._teams.list_all()


class UpdateTeamUseCase:
    """Applies a full team update and returns `None` when not found.

    Not-found mapping is intentionally delegated to the caller boundary so this
    use case remains transport-agnostic.
    """

    def __init__(self, *, teams: TeamRepositoryPort) -> None:
        self._teams = teams

    def execute(self, command: UpdateTeamCommand) -> Team | None:
        return self._teams.update(
            command.team_id,
            name=command.name,
            short_name=command.short_name,
            city=command.city,
            country=command.country,
        )


class DeleteTeamUseCase:
    """Deletes a team and returns repository success flag."""

    def __init__(self, *, teams: TeamRepositoryPort) -> None:
        self._teams = teams

    def execute(self, command: DeleteTeamCommand) -> bool:
        return self._teams.delete(command.team_id)
