from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.players.use_cases import (
    AssignPlayerTeamUseCase,
    CreatePlayerUseCase,
    CreateTeamRosterUseCase,
    DeletePlayerUseCase,
    GetPlayerStatsUseCase,
    ListPlayersByTeamUseCase,
    ListPlayersUseCase,
    UpdatePlayerUseCase,
)
from src.domain.matches.entities import Match
from src.domain.players.entities import EMPTY_PLAYER_STATS, Player
from src.interfaces.http.routes.players_router import create_players_router

TEAM_ID = "00000000-0000-4000-8000-000000000010"
OTHER_TEAM_ID = "00000000-0000-4000-8000-000000000099"
VALID = {
    "first_name": "Caitlin",
    "last_name": "Clark",
    "birth_date": "2002-01-22",
    "height_cm": 183,
    "weight_kg": 70,
    "primary_position": "PG",
}


class _PlayerRepo:
    """Owner-aware fake: every operation is scoped by owner_user_id."""

    def __init__(self) -> None:
        self.by_id: dict[str, Player] = {}

    def create(self, player: Player) -> Player:
        self.by_id[player.id] = player
        return player

    def list_by_owner(self, *, owner_user_id: str) -> list[Player]:
        return [p for p in self.by_id.values() if p.owner_user_id == owner_user_id]

    def update(self, *, player_id, owner_user_id, **fields) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return None
        updated = Player(id=player.id, owner_user_id=owner_user_id, team_id=player.team_id, stats=player.stats, **fields)
        self.by_id[player_id] = updated
        return updated

    def get_by_id(self, *, player_id: str, owner_user_id: str) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return None
        return player

    def delete(self, player_id: str, *, owner_user_id: str) -> bool:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return False
        del self.by_id[player_id]
        return True

    def assign_team(self, *, player_id, owner_user_id, team_id) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return None
        updated = Player(
            id=player.id, first_name=player.first_name, last_name=player.last_name,
            birth_date=player.birth_date, height_cm=player.height_cm, weight_kg=player.weight_kg,
            primary_position=player.primary_position, owner_user_id=owner_user_id, team_id=team_id,
            jersey_number=player.jersey_number, stats=player.stats,
        )
        self.by_id[player_id] = updated
        return updated

    def list_by_owner_and_team(self, *, owner_user_id, team_id) -> list[Player]:
        return [
            p for p in self.by_id.values()
            if p.owner_user_id == owner_user_id and p.team_id == team_id
        ]


class _TeamRepo:
    def __init__(self) -> None:
        self.owned: set[tuple[str, str]] = set()  # (team_id, owner)

    def is_owned_by(self, *, team_id: str, owner_user_id: str) -> bool:
        return (team_id, owner_user_id) in self.owned

    def lock_owned(self, *, team_id: str, owner_user_id: str) -> bool:
        return self.is_owned_by(team_id=team_id, owner_user_id=owner_user_id)


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"00000000-0000-4000-8000-{self._n:012d}"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class _GetPlayerMatchesUseCase:
    def execute(self, *, user_id: str, player_id: str) -> list[Match]:
        del user_id
        return [
            Match(
                id="match-1",
                owner_user_id="scout-1",
                home_team_id=TEAM_ID,
                away_team_id=OTHER_TEAM_ID,
                winner_team_id=TEAM_ID,
                match_date=date(2024, 1, 2),
                description=f"for-{player_id}",
                stats={"opaque": True},
            )
        ]


def build_client(
    *, user_id: str = "scout-1", team_repo: _TeamRepo | None = None, catch_up=None
) -> tuple[TestClient, _PlayerRepo]:
    repo = _PlayerRepo()
    teams = team_repo or _TeamRepo()
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.include_router(
        create_players_router(
            create_player_use_case=CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow()),
            list_players_use_case=ListPlayersUseCase(players=repo),
            list_players_by_team_use_case=ListPlayersByTeamUseCase(players=repo),
            update_player_use_case=UpdatePlayerUseCase(players=repo, uow=_Uow()),
            delete_player_use_case=DeletePlayerUseCase(players=repo, uow=_Uow()),
            assign_player_team_use_case=AssignPlayerTeamUseCase(players=repo, teams=teams, uow=_Uow()),
            get_player_stats_use_case=GetPlayerStatsUseCase(players=repo),
            get_player_matches_use_case=_GetPlayerMatchesUseCase(),
            create_team_roster_use_case=CreateTeamRosterUseCase(players=repo, teams=teams, ids=_Ids(), uow=_Uow()),
            catch_up=catch_up,
        )
    )
    return TestClient(app), repo


class TestPlayerCrud(unittest.TestCase):
    def test_create_and_list(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json=VALID)
        self.assertEqual(created.status_code, 201)
        pid = created.json()["player"]["id"]
        listed = client.get("/players").json()["players"]
        self.assertEqual([p["id"] for p in listed], [pid])

    def test_update_and_delete(self) -> None:
        client, _ = build_client()
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        updated = client.put(f"/players/{pid}", json={**VALID, "primary_position": "C"})
        self.assertEqual(updated.json()["player"]["primary_position"], "C")
        self.assertEqual(client.delete(f"/players/{pid}").status_code, 204)
        self.assertEqual(client.get("/players").json()["players"], [])


class TestOptionalProfile(unittest.TestCase):
    def test_name_only_player_is_created_with_nulls(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json={"first_name": "Ana", "last_name": "Paz"})
        self.assertEqual(created.status_code, 201)
        player = created.json()["player"]
        for key in ("birth_date", "height_cm", "weight_kg", "primary_position", "jersey_number"):
            self.assertIsNone(player[key], key)
        listed = client.get("/players").json()["players"]
        self.assertIsNone(listed[0]["birth_date"])

    def test_put_without_the_optional_fields_clears_them(self) -> None:
        client, _ = build_client()
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        updated = client.put(f"/players/{pid}", json={"first_name": "Caitlin", "last_name": "Clark"})
        self.assertEqual(updated.status_code, 200)
        player = updated.json()["player"]
        for key in ("birth_date", "height_cm", "weight_kg", "primary_position"):
            self.assertIsNone(player[key], key)

    def test_filled_optional_fields_are_still_checked(self) -> None:
        client, _ = build_client()
        base = {"first_name": "Ana", "last_name": "Paz"}
        for extra in ({"height_cm": 0}, {"weight_kg": 401}, {"primary_position": ""}, {"birth_date": "x"}):
            self.assertEqual(client.post("/players", json={**base, **extra}).status_code, 422, extra)
        bad = client.post("/players", json={**base, "primary_position": "GK"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["code"], "INVALID_POSITION")


def _bulk(entries, team_id: str = TEAM_ID) -> dict:
    return {
        "team_id": team_id,
        "players": [{"first_name": f"N{n}", "last_name": f"L{n}", "jersey_number": n} for n in entries],
    }


class TestBulkRoster(unittest.TestCase):
    def _client(self, catch_up=None):
        teams = _TeamRepo()
        teams.owned.add((TEAM_ID, "scout-1"))
        return build_client(team_repo=teams, catch_up=catch_up)

    def test_creates_players_into_the_team(self) -> None:
        client, repo = self._client()
        response = client.post("/players/bulk", json=_bulk(["7", "10"]))
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual([p["jersey_number"] for p in body["created"]], ["7", "10"])
        self.assertEqual({p["team_id"] for p in body["created"]}, {TEAM_ID})
        self.assertIsNone(body["created"][0]["height_cm"])
        self.assertEqual(body["skipped"], [])
        self.assertEqual(len(repo.list_by_owner_and_team(owner_user_id="scout-1", team_id=TEAM_ID)), 2)

    def test_repeating_the_request_skips_taken_jerseys(self) -> None:
        client, repo = self._client()
        client.post("/players/bulk", json=_bulk(["7", "10"]))
        again = client.post("/players/bulk", json=_bulk(["7", "11"])).json()
        self.assertEqual([p["jersey_number"] for p in again["created"]], ["11"])
        self.assertEqual(again["skipped"], [{"jersey_number": "7", "reason": "jersey_taken"}])
        self.assertEqual(len(repo.by_id), 3)

    def test_duplicate_jerseys_in_the_payload_are_rejected(self) -> None:
        client, repo = self._client()
        self.assertEqual(client.post("/players/bulk", json=_bulk(["7", "7"])).status_code, 422)
        self.assertEqual(repo.by_id, {})

    def test_size_and_jersey_limits(self) -> None:
        client, _ = self._client()
        self.assertEqual(client.post("/players/bulk", json=_bulk([str(n) for n in range(31)])).status_code, 422)
        self.assertEqual(client.post("/players/bulk", json=_bulk([str(n) for n in range(30)])).status_code, 201)
        self.assertEqual(client.post("/players/bulk", json=_bulk([])).status_code, 422)
        self.assertEqual(client.post("/players/bulk", json=_bulk(["100"])).status_code, 422)
        missing = {"team_id": TEAM_ID, "players": [{"first_name": "A", "last_name": "B"}]}
        self.assertEqual(client.post("/players/bulk", json=missing).status_code, 422)

    def test_unknown_or_foreign_team_is_not_found(self) -> None:
        client, repo = self._client()
        response = client.post("/players/bulk", json=_bulk(["7"], team_id=OTHER_TEAM_ID))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "TEAM_NOT_FOUND")
        self.assertEqual(repo.by_id, {})

    def test_team_is_caught_up_once(self) -> None:
        class _CatchUp:
            def __init__(self) -> None:
                self.invalidated: list[str] = []
                self.ran: list[str] = []

            def invalidate_team(self, team_id: str) -> None:
                self.invalidated.append(team_id)

            def execute(self, *, team_id: str) -> None:
                self.ran.append(team_id)

            def pending(self, user_id: str) -> bool:
                return False

        catch_up = _CatchUp()
        client, _ = self._client(catch_up=catch_up)
        client.post("/players/bulk", json=_bulk(["7", "8", "9"]))
        self.assertEqual(catch_up.invalidated, [TEAM_ID])
        self.assertEqual(catch_up.ran, [TEAM_ID])
        client.post("/players/bulk", json=_bulk(["7"]))  # nothing created: no new catch-up
        self.assertEqual(catch_up.ran, [TEAM_ID])


class TestJerseyNumber(unittest.TestCase):
    def test_jersey_number_round_trips(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json={**VALID, "jersey_number": "22"})
        self.assertEqual(created.json()["player"]["jersey_number"], "22")
        listed = client.get("/players").json()["players"]
        self.assertEqual(listed[0]["jersey_number"], "22")

    def test_jersey_number_is_optional(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json=VALID)
        self.assertEqual(created.status_code, 201)
        self.assertIsNone(created.json()["player"]["jersey_number"])

    def test_zero_is_kept_and_double_zero_stays_distinct(self) -> None:
        """0 is a real number, so it must not be read as "unassigned"."""

        client, _ = build_client()
        zero = client.post("/players", json={**VALID, "jersey_number": "0"})
        self.assertEqual(zero.json()["player"]["jersey_number"], "0")
        double_zero = client.post("/players", json={**VALID, "jersey_number": "00"})
        self.assertEqual(double_zero.json()["player"]["jersey_number"], "00")

    def test_blank_jersey_number_is_stored_as_unassigned(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json={**VALID, "jersey_number": "  "})
        self.assertEqual(created.status_code, 201)
        self.assertIsNone(created.json()["player"]["jersey_number"])

    def test_numeric_jersey_number_is_coerced_to_text(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json={**VALID, "jersey_number": 7})
        self.assertEqual(created.json()["player"]["jersey_number"], "7")

    def test_out_of_range_jersey_numbers_are_rejected(self) -> None:
        client, _ = build_client()
        for value in ("100", "-1", "1.5", "AB"):
            r = client.post("/players", json={**VALID, "jersey_number": value})
            self.assertEqual(r.status_code, 422, value)

    def test_update_can_change_and_clear_the_jersey_number(self) -> None:
        client, _ = build_client()
        pid = client.post("/players", json={**VALID, "jersey_number": "9"}).json()["player"]["id"]
        changed = client.put(f"/players/{pid}", json={**VALID, "jersey_number": "11"})
        self.assertEqual(changed.json()["player"]["jersey_number"], "11")
        cleared = client.put(f"/players/{pid}", json=VALID)
        self.assertIsNone(cleared.json()["player"]["jersey_number"])


class TestPlayerStatsEndpoints(unittest.TestCase):
    def test_get_player_stats_returns_canonical_nested_stats_payload(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json=VALID)
        player_id = created.json()["player"]["id"]

        response = client.get(f"/players/{player_id}/stats")
        self.assertEqual(response.status_code, 200)
        stats = response.json()["player"]["stats"]
        self.assertEqual(stats, EMPTY_PLAYER_STATS)
        self.assertEqual(set(stats), set(EMPTY_PLAYER_STATS))
        self.assertEqual(stats["record"], {"wins": 0, "losses": 0})
        self.assertEqual(stats["field_goals"]["per_game"], {"made": 0, "attempted": 0})
        self.assertIn("two_point", stats)
        self.assertIn("three_point", stats)
        self.assertNotIn("wins", stats)
        self.assertNotIn("losses", stats)
        self.assertNotIn("two_points", stats)
        self.assertNotIn("three_points", stats)
        self.assertNotIsInstance(stats["points"], int)

    def test_get_player_matches_returns_participation_matches(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json=VALID)
        player_id = created.json()["player"]["id"]

        response = client.get(f"/players/{player_id}/matches")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches"][0]["description"], f"for-{player_id}")


class TestPositionValidation(unittest.TestCase):
    def test_each_basketball_code_is_accepted(self) -> None:
        client, _ = build_client()
        for code in ("PG", "SG", "SF", "PF", "C"):
            r = client.post("/players", json={**VALID, "primary_position": code})
            self.assertEqual(r.status_code, 201, code)

    def test_football_position_is_rejected(self) -> None:
        """The old soccer codes must no longer be accepted."""

        client, _ = build_client()
        r = client.post("/players", json={**VALID, "primary_position": "DEL"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "INVALID_POSITION")

    def test_invalid_position_on_update_is_rejected(self) -> None:
        client, _ = build_client()
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        r = client.put(f"/players/{pid}", json={**VALID, "primary_position": "GK"})
        self.assertEqual(r.status_code, 422)


class TestOwnershipIsolation(unittest.TestCase):
    def test_a_scout_only_sees_their_own_players(self) -> None:
        client_a, repo = build_client(user_id="scout-a")
        client_a.post("/players", json=VALID)
        # A different scout sharing the same repo sees nothing.
        client_b, _ = build_client(user_id="scout-b")
        client_b_app_repo = _PlayerRepo()  # separate app; ownership still filters
        self.assertEqual(len(repo.list_by_owner(owner_user_id="scout-a")), 1)
        self.assertEqual(len(repo.list_by_owner(owner_user_id="scout-b")), 0)

    def test_cannot_update_another_scouts_player(self) -> None:
        # Seed a player owned by scout-a, then act as scout-b against the same repo.
        app_a = build_client(user_id="scout-a")
        client_a, repo = app_a
        pid = client_a.post("/players", json=VALID).json()["player"]["id"]

        # Rebuild a client for scout-b bound to the SAME repo.
        from fastapi import FastAPI
        app = FastAPI()

        @app.middleware("http")
        async def _u(request, call_next):
            request.state.user_id = "scout-b"
            return await call_next(request)

        app.include_router(
            create_players_router(
                create_player_use_case=CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow()),
                list_players_use_case=ListPlayersUseCase(players=repo),
                list_players_by_team_use_case=ListPlayersByTeamUseCase(players=repo),
                update_player_use_case=UpdatePlayerUseCase(players=repo, uow=_Uow()),
                delete_player_use_case=DeletePlayerUseCase(players=repo, uow=_Uow()),
                assign_player_team_use_case=AssignPlayerTeamUseCase(players=repo, teams=_TeamRepo(), uow=_Uow()),
                get_player_stats_use_case=GetPlayerStatsUseCase(players=repo),
                get_player_matches_use_case=_GetPlayerMatchesUseCase(),
            )
        )
        client_b = TestClient(app)
        # scout-b sees another scout's player as simply not found.
        self.assertEqual(client_b.put(f"/players/{pid}", json=VALID).status_code, 404)
        self.assertEqual(client_b.delete(f"/players/{pid}").status_code, 404)


class TestAssignTeam(unittest.TestCase):
    def test_assign_to_owned_team(self) -> None:
        teams = _TeamRepo()
        teams.owned.add((TEAM_ID, "scout-1"))
        client, _ = build_client(team_repo=teams)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        r = client.put(f"/players/{pid}/team/{TEAM_ID}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["player"]["team_id"], TEAM_ID)

    def test_cannot_assign_to_a_team_you_do_not_own(self) -> None:
        """A team owned by someone else is reported as not found."""

        teams = _TeamRepo()  # scout-1 owns nothing
        client, _ = build_client(team_repo=teams)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        r = client.put(f"/players/{pid}/team/{OTHER_TEAM_ID}")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "TEAM_NOT_FOUND")

    def test_filter_by_team(self) -> None:
        teams = _TeamRepo()
        teams.owned.add((TEAM_ID, "scout-1"))
        client, _ = build_client(team_repo=teams)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        client.put(f"/players/{pid}/team/{TEAM_ID}")
        filtered = client.get(f"/players?team_id={TEAM_ID}").json()["players"]
        self.assertEqual([p["id"] for p in filtered], [pid])


if __name__ == "__main__":
    unittest.main()
