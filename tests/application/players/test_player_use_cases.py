from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import unittest

from src.application.players.errors import PlayerError
from src.application.players.use_cases import CreatePlayerCommand, CreatePlayerUseCase, GetPlayerStatsUseCase
from src.domain.players.entities import EMPTY_PLAYER_STATS, Player


class _Repo:
    def __init__(self) -> None:
        self.by_id: dict[str, Player] = {}

    def create(self, player: Player) -> Player:
        self.by_id[player.id] = player
        return player

    def get_by_id(self, *, player_id: str, owner_user_id: str) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return None
        return player


class _Ids:
    def new_id(self) -> str:
        return "player-1"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestPlayerUseCases(unittest.TestCase):
    def test_create_player_initializes_fixed_stats_payload(self) -> None:
        repo = _Repo()
        use_case = CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow())

        player = use_case.execute(
            CreatePlayerCommand(
                user_id="user-1",
                first_name="A",
                last_name="B",
                birth_date=date(2000, 1, 1),
                height_cm=180,
                weight_kg=75,
                primary_position="PG",
            )
        )

        self.assertEqual(player.stats, EMPTY_PLAYER_STATS)

    def test_get_player_stats_returns_persisted_stats_only(self) -> None:
        repo = _Repo()
        repo.by_id["player-1"] = Player(
            id="player-1",
            first_name="A",
            last_name="B",
            birth_date=date(2000, 1, 1),
            height_cm=180,
            weight_kg=75,
            primary_position="PG",
            owner_user_id="user-1",
            stats={**EMPTY_PLAYER_STATS, "points": 99},
        )

        player = GetPlayerStatsUseCase(players=repo).execute(user_id="user-1", player_id="player-1")
        self.assertEqual(player.stats["points"], 99)

    def test_get_player_stats_raises_not_found_for_other_owner(self) -> None:
        repo = _Repo()
        repo.by_id["player-1"] = Player(
            id="player-1",
            first_name="A",
            last_name="B",
            birth_date=date(2000, 1, 1),
            height_cm=180,
            weight_kg=75,
            primary_position="PG",
            owner_user_id="user-1",
        )

        with self.assertRaises(PlayerError):
            GetPlayerStatsUseCase(players=repo).execute(user_id="user-2", player_id="player-1")
