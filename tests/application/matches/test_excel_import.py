from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace as NS

from src.application.matches.errors import (
    INVALID_MATCH_TEAMS,
    INVALID_STATS_FILE,
    STATS_FILE_TOO_LARGE,
    TEAM_MISMATCH,
    TEAM_NOT_FOUND,
    MatchError,
)
from src.application.matches.excel_import import (
    BoxScoreFileError,
    PreviewMatchStatsImportUseCase,
    PreviewStatsImportCommand,
)
from src.infrastructure.matches.cabb_box_score_parser import MAX_FILE_BYTES, CabbBoxScoreParser
from tests.box_score_fixtures import AWAY_PLAYERS, HOME_PLAYERS, as_csv, as_xlsx, grid

HOME, AWAY = "team-home", "team-away"


class _Teams:
    def __init__(self, home="Club Alfa", away="Club Beta"):
        self._names = (home, away)

    def list_by_owner(self, *, owner_user_id):
        return [NS(id=HOME, name=self._names[0]), NS(id=AWAY, name=self._names[1])]


class _NoRoster:
    def list_by_owner_and_team(self, *, owner_user_id, team_id):
        return []


class _Players:
    def list_by_owner_and_team(self, *, owner_user_id, team_id):
        if team_id == HOME:
            return [NS(id="p4", first_name="Uno", last_name="Alfa", jersey_number="4")]
        return [
            NS(id="pa", first_name="A", last_name="A", jersey_number="7"),
            NS(id="pb", first_name="B", last_name="B", jersey_number="7"),
        ]


def _use_case() -> PreviewMatchStatsImportUseCase:
    return PreviewMatchStatsImportUseCase(parser=CabbBoxScoreParser(), teams=_Teams(), players=_Players())


class TestParser(unittest.TestCase):
    def test_xlsx_and_csv_give_the_same_result(self) -> None:
        rows = grid()
        parser = CabbBoxScoreParser()
        from_xlsx = parser.parse(as_xlsx(rows))
        for delimiter in (";", ",", "\t"):
            for encoding in ("utf-8", "utf-8-sig", "cp1252"):
                with self.subTest(delimiter=delimiter, encoding=encoding):
                    self.assertEqual(from_xlsx.teams, parser.parse(as_csv(rows, delimiter=delimiter, encoding=encoding)).teams)

    def test_reads_title_teams_players_and_totals(self) -> None:
        score = CabbBoxScoreParser().parse(as_xlsx(grid()))
        self.assertEqual((score.home_name_hint, score.away_name_hint), ("Club Alfa", "Club Beta"))
        self.assertEqual(score.competition, "LIGA TEST - 2026")
        home, away = score.teams
        self.assertEqual((home.name, len(home.players), home.totals.points), ("Club Alfa", 3, 13))
        self.assertEqual(away.name, "Club Beta")
        alfa = home.players[0]
        self.assertEqual((alfa.jersey_number, alfa.line.minutes_seconds, alfa.line.points), ("4", 1800, 8))
        self.assertEqual((alfa.line.two_point.made, alfa.line.two_point.attempted), (2, 4))
        self.assertTrue(alfa.played)
        self.assertFalse(home.players[2].played)

    def test_rejects_garbage_and_foreign_layouts(self) -> None:
        parser = CabbBoxScoreParser()
        for data in (b"", b"PK not really a zip", b"plain text without separators", b"\x00\x01\x02binary"):
            with self.subTest(data=data[:12]), self.assertRaises(BoxScoreFileError):
                parser.parse(data)
        rows = grid()
        rows[[i for i, r in enumerate(rows) if r and r[0] == "Num."][0]][3] = "XXX"
        with self.assertRaises(BoxScoreFileError):
            parser.parse(as_xlsx(rows))

    def test_rejects_oversized_input(self) -> None:
        with self.assertRaises(BoxScoreFileError) as caught:
            CabbBoxScoreParser().parse(b"x" * (MAX_FILE_BYTES + 1))
        self.assertTrue(caught.exception.too_large)

    def test_rejects_an_impossible_shooting_split(self) -> None:
        rows = grid()
        rows[[i for i, r in enumerate(rows) if r and r[0] == "4"][0]][4] = "5/2"
        with self.assertRaises(BoxScoreFileError):
            CabbBoxScoreParser().parse(as_xlsx(rows))


class TestPreviewUseCase(unittest.TestCase):
    def test_without_teams_uses_file_order_and_links_nothing(self) -> None:
        preview = _use_case().execute(PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid())))
        self.assertIsNone(preview.winner_team_id)
        self.assertEqual(preview.report["linked_players"], [])
        self.assertEqual({p["reason"] for p in preview.report["unlinked_players"]}, {"no_team_selected"})
        self.assertEqual(preview.stats["teams"]["HOME"]["name"], "Club Alfa")

    def test_links_by_jersey_and_flags_ambiguous_numbers(self) -> None:
        preview = _use_case().execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id=HOME, away_team_id=AWAY)
        )
        self.assertEqual([p["player_id"] for p in preview.report["linked_players"]], ["p4"])
        reasons = {(p["team_side"], p["jersey_number"]): p["reason"] for p in preview.report["unlinked_players"]}
        self.assertEqual(reasons[("AWAY", "7")], "ambiguous_jersey_number")
        self.assertEqual(reasons[("HOME", "5")], "no_roster_player")
        self.assertTrue(any("appears twice" in w for w in preview.report["warnings"]))

    def test_participants_are_only_players_who_played(self) -> None:
        preview = _use_case().execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id=HOME, away_team_id=AWAY)
        )
        self.assertEqual(len(preview.participants), 4)
        self.assertNotIn("GAMMA, TRES", [p["display_name"] for p in preview.participants])
        all_rows = preview.stats["players"]
        self.assertEqual(len(all_rows), 5)
        self.assertFalse(next(r for r in all_rows if r["name"] == "GAMMA, TRES")["played"])
        self.assertEqual(next(r for r in all_rows if r["name"] == "ALFA, UNO")["free_throws"]["pct"], 80.0)

    def test_winner_follows_points_and_ties_have_none(self) -> None:
        command = lambda rows: PreviewStatsImportCommand(user_id="u", data=as_xlsx(rows), home_team_id=HOME, away_team_id=AWAY)  # noqa: E731
        self.assertEqual(_use_case().execute(command(grid())).winner_team_id, HOME)
        self.assertEqual(_use_case().execute(command(grid(home_points=9, away_points=15))).winner_team_id, AWAY)
        self.assertIsNone(_use_case().execute(command(grid(home_points=9, away_points=9))).winner_team_id)

    def test_swapped_team_order_in_the_file_is_corrected(self) -> None:
        rows = grid(
            title="Estadísticas - Club Beta vs Club Alfa - X",
            home_name="Club Beta",
            away_name="Club Alfa",
            home_players=AWAY_PLAYERS,
            away_players=HOME_PLAYERS,
        )
        preview = _use_case().execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(rows), home_team_id=HOME, away_team_id=AWAY)
        )
        self.assertEqual(preview.stats["teams"]["HOME"]["name"], "Club Alfa")
        self.assertEqual(preview.stats["teams"]["AWAY"]["name"], "Club Beta")

    def test_abbreviated_team_names_are_accepted(self) -> None:
        rows = grid(title="Estadísticas - Bos. Celtics vs Brk Nets - X", home_name="Bos. Celtics", away_name="Brk. Nets")
        use_case = PreviewMatchStatsImportUseCase(
            parser=CabbBoxScoreParser(), teams=_Teams("Boston Celtics", "Brooklyn Nets"), players=_NoRoster()
        )
        preview = use_case.execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(rows), home_team_id=HOME, away_team_id=AWAY)
        )
        checks = {t["side"]: t for t in preview.report["teams"]}
        self.assertTrue(checks["HOME"]["matches_selected_team"])
        self.assertEqual(checks["HOME"]["name_score"], 1.0)
        self.assertIsNone(checks["HOME"]["roster_score"])
        self.assertFalse(any("does not look like" in w for w in preview.report["warnings"]))

    def test_a_different_team_name_is_accepted_when_the_roster_is_the_same(self) -> None:
        rows = grid(home_name="Otro Club", away_name="Tercer Club")
        preview = _use_case().execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(rows), home_team_id=HOME, away_team_id=AWAY)
        )
        home = next(t for t in preview.report["teams"] if t["side"] == "HOME")
        self.assertEqual(home["name_score"], 0.0)
        self.assertEqual(home["roster_score"], 1.0)
        self.assertTrue(home["matches_selected_team"])

    def test_a_clearly_different_team_is_refused_with_details(self) -> None:
        use_case = PreviewMatchStatsImportUseCase(
            parser=CabbBoxScoreParser(), teams=_Teams("Zeta Squad", "Omega Five"), players=_NoRoster()
        )
        with self.assertRaises(MatchError) as caught:
            use_case.execute(
                PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id=HOME, away_team_id=AWAY)
            )
        error = caught.exception
        self.assertEqual(error.code, TEAM_MISMATCH)
        self.assertEqual({t["side"] for t in error.details["teams"]}, {"HOME", "AWAY"})
        self.assertEqual(error.details["teams"][0]["name_in_file"], "Club Alfa")

    def test_the_mismatch_can_be_allowed_explicitly(self) -> None:
        use_case = PreviewMatchStatsImportUseCase(
            parser=CabbBoxScoreParser(), teams=_Teams("Zeta Squad", "Omega Five"), players=_NoRoster()
        )
        preview = use_case.execute(
            PreviewStatsImportCommand(
                user_id="u",
                data=as_xlsx(grid()),
                home_team_id=HOME,
                away_team_id=AWAY,
                allow_team_mismatch=True,
            )
        )
        self.assertEqual(len(preview.participants), 4)
        self.assertEqual(sum("does not look like" in w for w in preview.report["warnings"]), 2)

    def test_only_one_selected_team_is_checked_and_the_other_side_is_inferred(self) -> None:
        rows = grid(
            title="Estadísticas - Club Beta vs Club Alfa - X",
            home_name="Club Beta",
            away_name="Club Alfa",
            home_players=AWAY_PLAYERS,
            away_players=HOME_PLAYERS,
        )
        preview = _use_case().execute(PreviewStatsImportCommand(user_id="u", data=as_xlsx(rows), home_team_id=HOME))
        self.assertEqual(preview.stats["teams"]["HOME"]["name"], "Club Alfa")
        self.assertEqual(preview.stats["teams"]["AWAY"]["name"], "Club Beta")

    def test_teams_listed_with_uuid_ids_are_found_by_their_string_id(self) -> None:
        # psycopg returns UUID columns as uuid.UUID while the HTTP layer passes the ids as strings.
        home, away = uuid.uuid4(), uuid.uuid4()

        class UuidTeams:
            def list_by_owner(self, *, owner_user_id):
                return [NS(id=home, name="Club Alfa"), NS(id=away, name="Club Beta")]

        use_case = PreviewMatchStatsImportUseCase(parser=CabbBoxScoreParser(), teams=UuidTeams(), players=_NoRoster())
        preview = use_case.execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id=str(home), away_team_id=str(away))
        )
        self.assertEqual(preview.stats["teams"]["HOME"]["name"], "Club Alfa")
        with self.assertRaises(MatchError) as caught:
            use_case.execute(
                PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id=str(uuid.uuid4()))
            )
        self.assertEqual(caught.exception.code, TEAM_NOT_FOUND)

    def test_inconsistent_points_are_reported(self) -> None:
        preview = _use_case().execute(
            PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid(home_points=99)), home_team_id=HOME, away_team_id=AWAY)
        )
        self.assertTrue(any("file totals say 99" in w for w in preview.report["warnings"]))

    def test_errors_use_the_match_error_codes(self) -> None:
        def code(command):
            with self.assertRaises(MatchError) as caught:
                _use_case().execute(command)
            return caught.exception.code

        self.assertEqual(code(PreviewStatsImportCommand(user_id="u", data=b"nope")), INVALID_STATS_FILE)
        self.assertEqual(code(PreviewStatsImportCommand(user_id="u", data=b"x" * (MAX_FILE_BYTES + 1))), STATS_FILE_TOO_LARGE)
        self.assertEqual(
            code(PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id="other", away_team_id=AWAY)),
            TEAM_NOT_FOUND,
        )
        self.assertEqual(
            code(PreviewStatsImportCommand(user_id="u", data=as_xlsx(grid()), home_team_id=HOME, away_team_id=HOME)),
            INVALID_MATCH_TEAMS,
        )


if __name__ == "__main__":
    unittest.main()
