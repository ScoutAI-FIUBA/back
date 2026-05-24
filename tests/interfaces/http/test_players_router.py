from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import unittest

from src.application.players.use_cases import (
    CreatePlayerUseCase,
    DeletePlayerUseCase,
    ListPlayersUseCase,
    UpdatePlayerUseCase,
)
from src.domain.players.entities import Player
from src.interfaces.http.players_router import create_players_router


class _PlayerRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, Player] = {}

    def create(self, player: Player) -> Player:
        self.by_id[player.id] = player
        return player

    def list_all(self) -> list[Player]:
        return list(self.by_id.values())

    def update(self, player: Player) -> Player | None:
        if player.id not in self.by_id:
            return None
        self.by_id[player.id] = player
        return player

    def delete(self, player_id: str) -> bool:
        return self.by_id.pop(player_id, None) is not None


class _Ids:
    def __init__(self) -> None:
        self._value = 0

    def new_id(self) -> str:
        self._value += 1
        return f"00000000-0000-4000-8000-{self._value:012d}"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestPlayersRouter(unittest.TestCase):
    def _endpoints(self):
        repo = _PlayerRepo()
        router = create_players_router(
            create_player_use_case=CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow()),
            list_players_use_case=ListPlayersUseCase(players=repo),
            update_player_use_case=UpdatePlayerUseCase(players=repo, uow=_Uow()),
            delete_player_use_case=DeletePlayerUseCase(players=repo, uow=_Uow()),
        )
        create_endpoint = next(route.endpoint for route in router.routes if route.path == "/players")
        list_endpoint = next(
            route.endpoint for route in router.routes if route.path == "/players" and "GET" in route.methods
        )
        update_endpoint = next(route.endpoint for route in router.routes if route.path == "/players/{player_id}")
        delete_endpoint = next(
            route.endpoint
            for route in router.routes
            if route.path == "/players/{player_id}" and "DELETE" in route.methods
        )
        return create_endpoint, list_endpoint, update_endpoint, delete_endpoint

    def test_players_crud_contract(self) -> None:
        create_endpoint, list_endpoint, update_endpoint, delete_endpoint = self._endpoints()
        payload = type(
            "PlayerPayload",
            (),
            {
                "first_name": "Lio",
                "last_name": "Messi",
                "birth_date": date(1987, 6, 24),
                "height_cm": 170,
                "weight_kg": 72,
                "primary_position": "RW",
            },
        )()
        created = create_endpoint(payload)
        player_id = created["player"]["id"]

        listed = list_endpoint()
        self.assertEqual(len(listed["players"]), 1)
        self.assertEqual(listed["players"][0]["id"], player_id)

        updated = update_endpoint(
            player_id,
            type(
                "PlayerPayload",
                (),
                {
                    "first_name": "Leo",
                    "last_name": "Messi",
                    "birth_date": date(1987, 6, 24),
                    "height_cm": 171,
                    "weight_kg": 73,
                    "primary_position": "AM",
                },
            )(),
        )
        self.assertEqual(updated["player"]["first_name"], "Leo")

        deleted = delete_endpoint(player_id)
        self.assertEqual(deleted.status_code, 204)

    def test_update_and_delete_missing_player(self) -> None:
        _, _, update_endpoint, delete_endpoint = self._endpoints()
        payload = type(
            "PlayerPayload",
            (),
            {
                "first_name": "Leo",
                "last_name": "Messi",
                "birth_date": date(1987, 6, 24),
                "height_cm": 171,
                "weight_kg": 73,
                "primary_position": "AM",
            },
        )()
        missing_id = "00000000-0000-4000-8000-000000000999"
        updated = update_endpoint(missing_id, payload)
        self.assertEqual(updated.status_code, 404)

        deleted = delete_endpoint(missing_id)
        self.assertEqual(deleted.status_code, 404)


if __name__ == "__main__":
    unittest.main()
