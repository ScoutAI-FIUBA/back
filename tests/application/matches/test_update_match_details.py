from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date
import unittest

from src.application.matches.errors import MATCH_NOT_FOUND, MatchError
from src.application.matches.use_cases import UpdateMatchDetailsCommand, UpdateMatchDetailsUseCase
from src.domain.matches.entities import Match


class _Repo:
    def __init__(self) -> None:
        self.match = Match(
            id="m1", owner_user_id="user-1", home_team_id="h", away_team_id="a",
            match_date=date(2024, 1, 1), description="old", winner_team_id="h", stats={"x": 1},
        )

    def get_by_id(self, *, match_id, owner_user_id):
        return self.match if (match_id, owner_user_id) == ("m1", "user-1") else None

    def update_details(self, *, match_id, owner_user_id, match_date, update_description, description):
        found = self.get_by_id(match_id=match_id, owner_user_id=owner_user_id)
        if found is None:
            return None
        self.match = replace(
            found,
            match_date=match_date or found.match_date,
            description=description if update_description else found.description,
        )
        return self.match


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestUpdateMatchDetails(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _Repo()
        self.uc = UpdateMatchDetailsUseCase(matches=self.repo, uow=_Uow())

    def test_updates_date_and_description_only(self) -> None:
        out = self.uc.execute(
            UpdateMatchDetailsCommand(user_id="user-1", match_id="m1", match_date=date(2025, 5, 5),
                                      update_description=True, description="new")
        )
        self.assertEqual((out.match_date, out.description), (date(2025, 5, 5), "new"))
        self.assertEqual((out.home_team_id, out.away_team_id, out.winner_team_id, out.stats), ("h", "a", "h", {"x": 1}))

    def test_null_description_clears_and_omitted_keeps(self) -> None:
        out = self.uc.execute(UpdateMatchDetailsCommand(user_id="user-1", match_id="m1", update_description=True))
        self.assertIsNone(out.description)
        self.repo.match = replace(self.repo.match, description="keep")
        out = self.uc.execute(UpdateMatchDetailsCommand(user_id="user-1", match_id="m1", match_date=date(2025, 1, 1)))
        self.assertEqual(out.description, "keep")

    def test_empty_command_returns_match_unchanged(self) -> None:
        self.assertEqual(self.uc.execute(UpdateMatchDetailsCommand(user_id="user-1", match_id="m1")), self.repo.match)

    def test_other_owner_is_not_found(self) -> None:
        for cmd in (
            UpdateMatchDetailsCommand(user_id="user-2", match_id="m1", match_date=date(2025, 1, 1)),
            UpdateMatchDetailsCommand(user_id="user-2", match_id="m1"),
        ):
            with self.assertRaises(MatchError) as ctx:
                self.uc.execute(cmd)
            self.assertEqual(ctx.exception.code, MATCH_NOT_FOUND)
