from __future__ import annotations

import unittest

from src.application.team.errors import TEAM_DELETE_CONFLICT, TEAM_HAS_MATCHES, TeamError
from src.application.team.ports import (
    TEAM_DELETE_CONFLICT_KIND_GENERIC,
    TEAM_DELETE_CONFLICT_KIND_MATCH,
    TeamDeleteConflictError,
)
from datetime import datetime, timezone

from src.application.team.use_cases import (
    CreateTeamCommand,
    CreateTeamUseCase,
    DeleteTeamCommand,
    DeleteTeamUseCase,
    UpdateTeamCommand,
    UpdateTeamUseCase,
)


class _TeamsRepo:
    def __init__(self) -> None:
        self.raise_conflict_kind: str | None = None

    def delete(self, team_id: str, *, owner_user_id: str) -> bool:
        del team_id, owner_user_id
        if self.raise_conflict_kind is not None:
            raise TeamDeleteConflictError("team delete conflict", kind=self.raise_conflict_kind)
        return True


class _Clock:
    def now(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Ids:
    def new_id(self) -> str:
        return "team-1"


class _RecordingRepo:
    def __init__(self) -> None:
        self.created = None
        self.update_kwargs = None

    def create(self, team):
        self.created = team
        return team

    def update(self, team_id, **kwargs):
        self.update_kwargs = kwargs
        return None


class TestTeamIsOwnUseCases(unittest.TestCase):
    def _create(self, **extra) -> _RecordingRepo:
        repo = _RecordingRepo()
        CreateTeamUseCase(teams=repo, clock=_Clock(), ids=_Ids()).execute(
            CreateTeamCommand(user_id="u", name="n", short_name="s", city="c", country="x", **extra)
        )
        return repo

    def test_create_defaults_to_rival(self) -> None:
        self.assertFalse(self._create().created.is_own)

    def test_create_passes_is_own(self) -> None:
        self.assertTrue(self._create(is_own=True).created.is_own)

    def _update(self, **extra) -> dict:
        repo = _RecordingRepo()
        UpdateTeamUseCase(teams=repo).execute(
            UpdateTeamCommand(user_id="u", team_id="t", name="n", short_name="s", city="c", country="x", **extra)
        )
        return repo.update_kwargs

    def test_update_defaults_to_keep(self) -> None:
        self.assertIsNone(self._update()["is_own"])

    def test_update_passes_is_own(self) -> None:
        self.assertIs(self._update(is_own=False)["is_own"], False)
        self.assertIs(self._update(is_own=True)["is_own"], True)


class TestDeleteTeamUseCase(unittest.TestCase):
    def test_delete_maps_match_conflict_to_team_has_matches(self) -> None:
        repo = _TeamsRepo()
        repo.raise_conflict_kind = TEAM_DELETE_CONFLICT_KIND_MATCH
        use_case = DeleteTeamUseCase(teams=repo)

        with self.assertRaises(TeamError) as ctx:
            use_case.execute(DeleteTeamCommand(user_id="user-1", team_id="team-1"))

        self.assertEqual(ctx.exception.code, TEAM_HAS_MATCHES)

    def test_delete_maps_non_match_conflict_to_generic_team_delete_conflict(self) -> None:
        repo = _TeamsRepo()
        repo.raise_conflict_kind = TEAM_DELETE_CONFLICT_KIND_GENERIC
        use_case = DeleteTeamUseCase(teams=repo)

        with self.assertRaises(TeamError) as ctx:
            use_case.execute(DeleteTeamCommand(user_id="user-1", team_id="team-1"))

        self.assertEqual(ctx.exception.code, TEAM_DELETE_CONFLICT)


if __name__ == "__main__":
    unittest.main()
