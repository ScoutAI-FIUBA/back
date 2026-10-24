from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import unittest

from src.application.players.errors import PlayerError
from src.application.players.use_cases import (
    CreatePlayerCommand,
    CreatePlayerUseCase,
    CreateTeamRosterCommand,
    CreateTeamRosterUseCase,
    GetPlayerStatsUseCase,
    RosterPlayerInput,
)
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


class _CountingIds:
    def __init__(self) -> None:
        self.count = 0

    def new_id(self) -> str:
        self.count += 1
        return f"player-{self.count}"


class _RosterRepo(_Repo):
    def list_by_owner_and_team(self, *, owner_user_id: str, team_id: str) -> list[Player]:
        return [p for p in self.by_id.values() if p.owner_user_id == owner_user_id and p.team_id == team_id]


class _Teams:
    def __init__(self, owned: set[tuple[str, str]]) -> None:
        self.owned = owned
        self.locked: list[str] = []

    def lock_owned(self, *, team_id: str, owner_user_id: str) -> bool:
        self.locked.append(team_id)
        return (team_id, owner_user_id) in self.owned


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestPlayerUseCases(unittest.TestCase):
    def test_create_player_without_profile_fields(self) -> None:
        use_case = CreatePlayerUseCase(players=_Repo(), ids=_Ids(), uow=_Uow())
        player = use_case.execute(CreatePlayerCommand(user_id="user-1", first_name="A", last_name="B"))
        self.assertIsNone(player.primary_position)
        self.assertIsNone(player.birth_date)

    def test_invalid_position_is_still_rejected(self) -> None:
        use_case = CreatePlayerUseCase(players=_Repo(), ids=_Ids(), uow=_Uow())
        with self.assertRaises(PlayerError) as raised:
            use_case.execute(
                CreatePlayerCommand(user_id="user-1", first_name="A", last_name="B", primary_position="GK")
            )
        self.assertEqual(raised.exception.code, "INVALID_POSITION")

    def test_roster_skips_taken_jersey_and_sets_team(self) -> None:
        repo = _RosterRepo()
        repo.by_id["old"] = Player(
            id="old", first_name="O", last_name="P", jersey_number="7", owner_user_id="user-1", team_id="team-1"
        )
        teams = _Teams({("team-1", "user-1")})
        use_case = CreateTeamRosterUseCase(players=repo, teams=teams, ids=_CountingIds(), uow=_Uow())
        result = use_case.execute(
            CreateTeamRosterCommand(
                user_id="user-1",
                team_id="team-1",
                players=[RosterPlayerInput("A", "B", "7"), RosterPlayerInput("C", "D", "8")],
            )
        )
        self.assertEqual(result.skipped_jersey_numbers, ["7"])
        self.assertEqual([p.jersey_number for p in result.created], ["8"])
        self.assertEqual(result.created[0].team_id, "team-1")
        self.assertEqual(result.created[0].owner_user_id, "user-1")
        self.assertEqual(teams.locked, ["team-1"])

    def test_roster_treats_07_and_7_as_the_same_jersey(self) -> None:
        repo = _RosterRepo()
        repo.by_id["old"] = Player(
            id="old", first_name="O", last_name="P", jersey_number="7", owner_user_id="user-1", team_id="team-1"
        )
        use_case = CreateTeamRosterUseCase(
            players=repo, teams=_Teams({("team-1", "user-1")}), ids=_CountingIds(), uow=_Uow()
        )
        result = use_case.execute(
            CreateTeamRosterCommand(
                user_id="user-1",
                team_id="team-1",
                players=[RosterPlayerInput("A", "B", "07"), RosterPlayerInput("C", "D", "08"), RosterPlayerInput("E", "F", "8")],
            )
        )
        self.assertEqual(result.skipped_jersey_numbers, ["07", "8"])
        self.assertEqual([p.jersey_number for p in result.created], ["08"])

    def test_zero_and_double_zero_stay_distinct(self) -> None:
        from src.domain.players.jersey import normalize_jersey_number

        self.assertNotEqual(normalize_jersey_number("0"), normalize_jersey_number("00"))
        self.assertEqual(normalize_jersey_number("07"), normalize_jersey_number("7"))

    def test_roster_for_unknown_team_is_not_found(self) -> None:
        repo = _RosterRepo()
        use_case = CreateTeamRosterUseCase(players=repo, teams=_Teams(set()), ids=_CountingIds(), uow=_Uow())
        with self.assertRaises(PlayerError) as raised:
            use_case.execute(
                CreateTeamRosterCommand(
                    user_id="user-1", team_id="team-9", players=[RosterPlayerInput("A", "B", "7")]
                )
            )
        self.assertEqual(raised.exception.code, "TEAM_NOT_FOUND")
        self.assertEqual(repo.by_id, {})

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
        self.assertEqual(set(player.stats), set(EMPTY_PLAYER_STATS))
        self.assertEqual(set(player.stats["record"]), {"wins", "losses"})
        self.assertEqual(set(player.stats["two_point"]), {"made_total", "attempted_total", "per_game", "percentage"})
        self.assertIsNot(player.stats, EMPTY_PLAYER_STATS)
        self.assertIsNot(player.stats["record"], EMPTY_PLAYER_STATS["record"])

    def test_get_player_stats_returns_persisted_stats_only(self) -> None:
        repo = _Repo()
        persisted_stats = {
            **EMPTY_PLAYER_STATS,
            "points": {"total": 99, "per_game": 21},
            "record": {"wins": 7, "losses": 2},
        }
        repo.by_id["player-1"] = Player(
            id="player-1",
            first_name="A",
            last_name="B",
            birth_date=date(2000, 1, 1),
            height_cm=180,
            weight_kg=75,
            primary_position="PG",
            owner_user_id="user-1",
            stats=persisted_stats,
        )

        player = GetPlayerStatsUseCase(players=repo).execute(user_id="user-1", player_id="player-1")
        self.assertEqual(player.stats, persisted_stats)

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
