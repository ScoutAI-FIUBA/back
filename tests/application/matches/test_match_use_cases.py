from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
import unittest

from src.application.matches.errors import INVALID_MATCH_TEAMS, INVALID_WINNER_TEAM, PLAYER_NOT_FOUND, MatchError
from src.application.matches.use_cases import (
    CreateMatchCommand,
    CreateMatchUseCase,
    ReplaceMatchParticipantInput,
    ReplaceMatchStatsCommand,
    ReplaceMatchStatsUseCase,
)
from src.domain.matches.entities import Match, MatchParticipant, MatchStatsView
from src.domain.players.entities import EMPTY_PLAYER_STATS, Player


def _match() -> Match:
    now = datetime.now(timezone.utc)
    return Match(
        id="match-1",
        owner_user_id="user-1",
        home_team_id="team-home",
        away_team_id="team-away",
        match_date=date(2024, 1, 1),
        description="Game",
        created_at=now,
        updated_at=now,
    )


class _MatchRepo:
    def __init__(self) -> None:
        self.match = _match()
        self.last_replace: MatchStatsView | None = None

    def create(self, match: Match) -> Match:
        self.match = replace(match, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        return self.match

    def get_by_id(self, *, match_id: str, owner_user_id: str) -> Match | None:
        if self.match.id != match_id or self.match.owner_user_id != owner_user_id:
            return None
        return self.match

    def replace_stats(self, *, match_id: str, owner_user_id: str, stats, winner_team_id, participants):
        found = self.get_by_id(match_id=match_id, owner_user_id=owner_user_id)
        if found is None:
            return None
        self.match = replace(found, stats=stats, winner_team_id=winner_team_id)
        self.last_replace = MatchStatsView(match=self.match, participants=participants)
        return self.last_replace


class _TeamRepo:
    def __init__(self) -> None:
        self.owned = {("team-home", "user-1"), ("team-away", "user-1")}

    def is_owned_by(self, *, team_id: str, owner_user_id: str) -> bool:
        return (team_id, owner_user_id) in self.owned


class _Ids:
    def __init__(self) -> None:
        self.count = 0

    def new_id(self) -> str:
        self.count += 1
        return f"id-{self.count}"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class _PlayerRepo:
    def __init__(self) -> None:
        self.players: dict[tuple[str, str], Player] = {}

    def get_by_id(self, *, player_id: str, owner_user_id: str) -> Player | None:
        return self.players.get((player_id, owner_user_id))


class TestMatchUseCases(unittest.TestCase):
    def test_create_match_rejects_inaccessible_team(self) -> None:
        teams = _TeamRepo()
        teams.owned.remove(("team-away", "user-1"))
        use_case = CreateMatchUseCase(matches=_MatchRepo(), teams=teams, ids=_Ids(), uow=_Uow())

        with self.assertRaises(MatchError):
            use_case.execute(
                CreateMatchCommand(
                    user_id="user-1",
                    home_team_id="team-home",
                    away_team_id="team-away",
                    match_date=date(2024, 1, 1),
                )
            )

    def test_create_match_rejects_same_home_and_away_team(self) -> None:
        use_case = CreateMatchUseCase(matches=_MatchRepo(), teams=_TeamRepo(), ids=_Ids(), uow=_Uow())

        with self.assertRaises(MatchError) as ctx:
            use_case.execute(
                CreateMatchCommand(
                    user_id="user-1",
                    home_team_id="team-home",
                    away_team_id="team-home",
                    match_date=date(2024, 1, 1),
                )
            )

        self.assertEqual(ctx.exception.code, INVALID_MATCH_TEAMS)

    def test_replace_stats_rejects_invalid_winner_team(self) -> None:
        repo = _MatchRepo()
        use_case = ReplaceMatchStatsUseCase(matches=repo, players=_PlayerRepo(), ids=_Ids(), uow=_Uow())

        with self.assertRaises(MatchError) as ctx:
            use_case.execute(
                ReplaceMatchStatsCommand(
                    user_id="user-1",
                    match_id="match-1",
                    stats={"opaque": True},
                    winner_team_id="wrong-team",
                    participants=[],
                )
            )

        self.assertEqual(ctx.exception.code, INVALID_WINNER_TEAM)

    def test_replace_stats_keeps_payload_opaque_without_player_recompute(self) -> None:
        repo = _MatchRepo()
        players = _PlayerRepo()
        use_case = ReplaceMatchStatsUseCase(matches=repo, players=players, ids=_Ids(), uow=_Uow())
        player = Player(
            id="player-1",
            first_name="A",
            last_name="B",
            birth_date=date(2000, 1, 1),
            height_cm=180,
            weight_kg=75,
            primary_position="PG",
            owner_user_id="user-1",
            stats={**EMPTY_PLAYER_STATS, "points": 4},
        )
        players.players[(player.id, player.owner_user_id)] = player

        view = use_case.execute(
            ReplaceMatchStatsCommand(
                user_id="user-1",
                match_id="match-1",
                stats={"players": [{"name": "Ghost", "points": 999}]},
                winner_team_id="team-home",
                participants=[
                    ReplaceMatchParticipantInput(
                        team_side="HOME",
                        display_name="Known Player",
                        player_id=player.id,
                        jersey_number="9",
                    )
                ],
            )
        )

        self.assertEqual(view.match.stats, {"players": [{"name": "Ghost", "points": 999}]})
        self.assertEqual(player.stats["points"], 4)
        self.assertEqual(view.participants[0].player_id, "player-1")

    def test_replace_stats_rejects_unknown_participant_player(self) -> None:
        repo = _MatchRepo()
        use_case = ReplaceMatchStatsUseCase(matches=repo, players=_PlayerRepo(), ids=_Ids(), uow=_Uow())

        with self.assertRaises(MatchError) as ctx:
            use_case.execute(
                ReplaceMatchStatsCommand(
                    user_id="user-1",
                    match_id="match-1",
                    stats={"opaque": True},
                    winner_team_id="team-home",
                    participants=[
                        ReplaceMatchParticipantInput(
                            team_side="HOME",
                            display_name="Ghost",
                            player_id="missing-player",
                        )
                    ],
                )
            )

        self.assertEqual(ctx.exception.code, PLAYER_NOT_FOUND)

    def test_replace_stats_rejects_cross_owner_participant_player(self) -> None:
        repo = _MatchRepo()
        players = _PlayerRepo()
        players.players[("player-1", "user-2")] = Player(
            id="player-1",
            first_name="Other",
            last_name="Owner",
            birth_date=date(2000, 1, 1),
            height_cm=180,
            weight_kg=75,
            primary_position="PG",
            owner_user_id="user-2",
        )
        use_case = ReplaceMatchStatsUseCase(matches=repo, players=players, ids=_Ids(), uow=_Uow())

        with self.assertRaises(MatchError) as ctx:
            use_case.execute(
                ReplaceMatchStatsCommand(
                    user_id="user-1",
                    match_id="match-1",
                    stats={"opaque": True},
                    winner_team_id="team-home",
                    participants=[
                        ReplaceMatchParticipantInput(
                            team_side="HOME",
                            display_name="Other Owner",
                            player_id="player-1",
                        )
                    ],
                )
            )

        self.assertEqual(ctx.exception.code, PLAYER_NOT_FOUND)
