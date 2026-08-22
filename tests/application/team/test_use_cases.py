from __future__ import annotations

import unittest

from src.application.team.errors import TEAM_DELETE_CONFLICT, TEAM_HAS_MATCHES, TeamError
from src.application.team.ports import (
    TEAM_DELETE_CONFLICT_KIND_GENERIC,
    TEAM_DELETE_CONFLICT_KIND_MATCH,
    TeamDeleteConflictError,
)
from src.application.team.use_cases import DeleteTeamCommand, DeleteTeamUseCase


class _TeamsRepo:
    def __init__(self) -> None:
        self.raise_conflict_kind: str | None = None

    def delete(self, team_id: str, *, owner_user_id: str) -> bool:
        del team_id, owner_user_id
        if self.raise_conflict_kind is not None:
            raise TeamDeleteConflictError("team delete conflict", kind=self.raise_conflict_kind)
        return True


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
