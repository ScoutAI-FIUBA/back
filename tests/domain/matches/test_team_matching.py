from __future__ import annotations

import unittest

from src.domain.matches.team_matching import (
    NAME_MATCH_THRESHOLD,
    name_similarity,
    roster_similarity,
    same_team,
    surname_matches,
)


class TestNameSimilarity(unittest.TestCase):
    def test_same_team_written_differently(self) -> None:
        for left, right in (
            ("Boston Celtics", "Bos. Celtics"),
            ("Boston Celtics", "BOSTON  CELTICS"),
            ("Boston Celtics", "Celtics Boston"),
            ("Boston Celtics", "Boston Celtcs"),
            ("Brooklyn Nets", "Brk. Nets"),
            ("Club Moreno", "C.S.D.y C. Moreno"),
            ("Peñarol", "Penarol MdP"),
        ):
            with self.subTest(left=left, right=right):
                self.assertGreaterEqual(name_similarity(left, right), NAME_MATCH_THRESHOLD)

    def test_different_teams_that_share_a_word(self) -> None:
        for left, right in (
            ("Los Angeles Lakers", "Los Angeles Clippers"),
            ("Boston Celtics", "Boston Bruins"),
            ("Boston Celtics", "Brooklyn Nets"),
            ("Gimnasia y Esgrima", "Gimnasia de La Plata"),
        ):
            with self.subTest(left=left, right=right):
                self.assertLess(name_similarity(left, right), NAME_MATCH_THRESHOLD)

    def test_empty_names_never_match(self) -> None:
        self.assertEqual(name_similarity("", "Boston Celtics"), 0.0)
        self.assertEqual(name_similarity("...", "Boston Celtics"), 0.0)


class TestRosterSimilarity(unittest.TestCase):
    def test_surname_in_file_format(self) -> None:
        self.assertTrue(surname_matches("BELIZAN, LAUTARO MARTÍN", "Belizan"))
        self.assertTrue(surname_matches("TAROCCO MAGGI, SEBASTIAN", "Tarocco Maggi"))
        self.assertFalse(surname_matches("LUQUE, FRANCISCO", "Zinna"))

    def test_counts_players_present_in_both(self) -> None:
        file_players = [("4", "ALFA, UNO"), ("5", "BETA, DOS"), ("6", "GAMMA, TRES"), ("7", "DELTA, X")]
        roster = [("4", "Alfa"), ("5", "Beta"), ("9", "Zeta")]
        self.assertEqual(roster_similarity(file_players, roster), 2 / 3)

    def test_same_number_different_person_does_not_count(self) -> None:
        self.assertEqual(roster_similarity([("4", "ALFA, UNO")], [("4", "Omega")]), 0.0)

    def test_no_evidence_is_none_not_zero(self) -> None:
        self.assertIsNone(roster_similarity([("4", "ALFA, UNO")], []))
        self.assertIsNone(roster_similarity([(None, "ALFA, UNO")], [("4", "Alfa")]))

    def test_either_signal_is_enough(self) -> None:
        self.assertTrue(same_team(1.0, None))
        self.assertTrue(same_team(0.0, 0.8))
        self.assertFalse(same_team(0.2, 0.2))
        self.assertFalse(same_team(0.2, None))


if __name__ == "__main__":
    unittest.main()
