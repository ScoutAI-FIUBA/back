"""Turning pipeline output into a box score.

Fixtures mirror the real documents the pipeline writes, including their awkward
parts: shots with no identified shooter, tracks whose jersey number was never
confirmed, and two players legitimately wearing the same number on opposite
teams.
"""

from __future__ import annotations

import unittest

from src.application.stats.aggregation import build_game_stats, number_by_track, team_by_track

# 6.21m from the near hoop — inside the arc, matching the real measured shot.
TWO_POINT_XY = [3.867, 13.267]
# Straight out from the hoop, comfortably beyond the arc.
THREE_POINT_XY = [9.5, 7.5]


def shots(*entries) -> dict:
    return {"shots": list(entries)}


def shot(**overrides) -> dict:
    base = {
        "event_id": 1,
        "outcome": "made",
        "shot_origin_court_xy_m": TWO_POINT_XY,
        "shooter_track_id": 9,
        "shooter_team_id": 1,
        "start_timestamp_seconds": 4.0,
        "shot_type": "jump_shot",
        "shooter_attribution_method": "nearest_player_bbox_to_shot_anchor",
    }
    base.update(overrides)
    return base


TEAMS = {"assignments": [
    {"track_id": 9, "team_id": 1},
    {"track_id": 5, "team_id": 0},
    {"track_id": 3, "team_id": 1},
]}

NUMBERS = {"tracks": [
    {"track_id": 9, "status": "confirmed", "number": "22"},
    {"track_id": 5, "status": "confirmed", "number": "22"},   # other team, also 22
    {"track_id": 3, "status": "unknown", "number": "unknown"},
]}


class TestLookups(unittest.TestCase):
    def test_team_lookup(self) -> None:
        self.assertEqual(team_by_track(TEAMS), {9: 1, 5: 0, 3: 1})

    def test_unconfirmed_numbers_are_dropped(self) -> None:
        """A wrong number misattributes a shot; absence is the safer answer."""

        self.assertEqual(number_by_track(NUMBERS), {9: "22", 5: "22"})

    def test_missing_documents_are_tolerated(self) -> None:
        self.assertEqual(team_by_track(None), {})
        self.assertEqual(number_by_track({}), {})


class TestGameStats(unittest.TestCase):
    def build(self, shots_document):
        return build_game_stats(
            shots_document=shots_document, teams_document=TEAMS, numbers_document=NUMBERS
        ).to_dict()

    def test_a_made_two_scores_two_points(self) -> None:
        stats = self.build(shots(shot()))
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["points"], 2)
        self.assertEqual(team["field_goals_made"], 1)
        self.assertEqual(team["field_goals_attempted"], 1)

    def test_a_made_three_scores_three_points(self) -> None:
        stats = self.build(shots(shot(shot_origin_court_xy_m=THREE_POINT_XY)))
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["points"], 3)
        self.assertEqual(team["three_point_made"], 1)

    def test_a_miss_counts_as_an_attempt_but_not_a_score(self) -> None:
        stats = self.build(shots(shot(outcome="missed")))
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["points"], 0)
        self.assertEqual(team["field_goals_attempted"], 1)
        self.assertEqual(team["field_goals_made"], 0)

    def test_an_unknown_outcome_is_never_counted_as_made(self) -> None:
        stats = self.build(shots(shot(outcome="unknown")))
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["field_goals_made"], 0)
        self.assertEqual(team["field_goals_attempted"], 1)

    def test_percentages_are_computed(self) -> None:
        stats = self.build(shots(shot(event_id=1), shot(event_id=2, outcome="missed")))
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["field_goal_pct"], 0.5)

    def test_a_player_who_never_shot_has_no_percentage(self) -> None:
        """None, not zero — 0% would read as having missed everything."""

        stats = self.build(shots())
        idle = next(p for p in stats["players"] if p["track_id"] == 3)
        self.assertIsNone(idle["field_goal_pct"])
        self.assertEqual(idle["field_goals_attempted"], 0)

    def test_every_tracked_player_is_listed_not_only_scorers(self) -> None:
        stats = self.build(shots(shot()))
        self.assertEqual({p["track_id"] for p in stats["players"]}, {3, 5, 9})

    def test_same_number_on_opposite_teams_is_kept_apart(self) -> None:
        """Both teams can field a 22; they must not merge into one player."""

        stats = self.build(shots(shot()))
        twenty_twos = [p for p in stats["players"] if p["jersey_number"] == "22"]
        self.assertEqual(len(twenty_twos), 2)
        self.assertEqual({p["team_id"] for p in twenty_twos}, {0, 1})

    def test_player_without_a_number_gets_a_readable_label(self) -> None:
        stats = self.build(shots())
        unnamed = next(p for p in stats["players"] if p["track_id"] == 3)
        self.assertEqual(unnamed["display_name"], "Player 3")

    def test_player_with_a_number_is_labelled_by_it(self) -> None:
        stats = self.build(shots())
        named = next(p for p in stats["players"] if p["track_id"] == 9)
        self.assertEqual(named["display_name"], "#22")

    def test_shot_without_a_court_position_is_not_scored(self) -> None:
        """Point value depends on where it was taken from."""

        stats = self.build(shots(shot(shot_origin_court_xy_m=None)))
        self.assertEqual(stats["coverage"]["shots_without_court_position"], 1)
        self.assertEqual(stats["shots"], [])

    def test_wildly_off_court_projection_is_discarded(self) -> None:
        stats = self.build(shots(shot(shot_origin_court_xy_m=[400.0, 7.5])))
        self.assertEqual(stats["coverage"]["shots_without_court_position"], 1)

    def test_shot_without_a_shooter_still_counts_for_the_team(self) -> None:
        """Team totals should not lose a shot just because attribution failed."""

        stats = self.build(shots(shot(shooter_track_id=None)))
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["field_goals_attempted"], 1)
        self.assertEqual(stats["coverage"]["shots_without_shooter"], 1)

    def test_shot_rows_carry_what_a_chart_needs(self) -> None:
        stats = self.build(shots(shot()))
        row = stats["shots"][0]
        self.assertEqual(row["court_x_m"], 3.87)
        self.assertEqual(row["court_y_m"], 13.27)
        self.assertTrue(row["made"])
        self.assertEqual(row["points"], 2)
        self.assertEqual(row["timestamp_seconds"], 4.0)

    def test_attribution_method_is_exposed(self) -> None:
        """Proximity guesses should be distinguishable from confident ones."""

        row = self.build(shots(shot()))["shots"][0]
        self.assertEqual(row["attribution"], "nearest_player_bbox_to_shot_anchor")

    def test_coverage_states_what_is_not_measured(self) -> None:
        """The interface must be able to avoid implying a full stat line."""

        coverage = self.build(shots(shot()))["coverage"]
        self.assertEqual(coverage["measures"], ["shooting"])
        for absent in ("rebounds", "assists", "turnovers", "fouls"):
            self.assertIn(absent, coverage["not_measured"])

    def test_coverage_counts_identified_players(self) -> None:
        coverage = self.build(shots())["coverage"]
        self.assertEqual(coverage["players_tracked"], 3)
        self.assertEqual(coverage["players_with_jersey_number"], 2)

    def test_no_shots_produces_an_empty_but_valid_box_score(self) -> None:
        stats = self.build(shots())
        self.assertEqual(stats["shots"], [])
        self.assertTrue(all(t["points"] == 0 for t in stats["teams"]))

    def test_no_documents_at_all_does_not_crash(self) -> None:
        stats = build_game_stats(
            shots_document=None, teams_document=None, numbers_document=None
        ).to_dict()
        self.assertEqual(stats["teams"], [])
        self.assertEqual(stats["players"], [])


if __name__ == "__main__":
    unittest.main()


class TestZoneEfficiency(unittest.TestCase):
    """Where a player scores, not merely where they shoot."""

    # Distances chosen to land in distinct zones from the near hoop at (1.575, 7.5).
    AT_RIM = [2.5, 7.5]
    MID = [7.0, 7.5]
    ARC = [9.5, 7.5]

    def build(self, *entries):
        return build_game_stats(
            shots_document=shots(*entries), teams_document=TEAMS, numbers_document=NUMBERS
        ).to_dict()

    def test_zone_records_made_and_attempted(self) -> None:
        stats = self.build(
            shot(event_id=1, shot_origin_court_xy_m=self.MID, outcome="made"),
            shot(event_id=2, shot_origin_court_xy_m=self.MID, outcome="missed"),
        )
        player = next(p for p in stats["players"] if p["track_id"] == 9)
        self.assertEqual(player["by_zone"]["mid_range"], {"made": 1, "attempted": 2, "pct": 0.5})

    def test_a_cold_zone_is_distinguishable_from_a_hot_one(self) -> None:
        """Counting attempts alone would make these two zones look identical."""

        stats = self.build(
            shot(event_id=1, shot_origin_court_xy_m=self.AT_RIM, outcome="made"),
            shot(event_id=2, shot_origin_court_xy_m=self.AT_RIM, outcome="made"),
            shot(event_id=3, shot_origin_court_xy_m=self.ARC, outcome="missed"),
            shot(event_id=4, shot_origin_court_xy_m=self.ARC, outcome="missed"),
        )
        zones = next(p for p in stats["players"] if p["track_id"] == 9)["by_zone"]
        self.assertEqual(zones["at_the_rim"]["pct"], 1.0)
        self.assertEqual(zones["above_the_break_three"]["pct"], 0.0)
        self.assertEqual(zones["at_the_rim"]["attempted"], zones["above_the_break_three"]["attempted"])

    def test_zero_percent_is_reported_when_a_zone_was_attempted(self) -> None:
        """Distinct from None, which means the player never shot from there."""

        stats = self.build(shot(shot_origin_court_xy_m=self.MID, outcome="missed"))
        zones = next(p for p in stats["players"] if p["track_id"] == 9)["by_zone"]
        self.assertEqual(zones["mid_range"]["pct"], 0.0)

    def test_unattempted_zones_are_absent_not_zeroed(self) -> None:
        stats = self.build(shot(shot_origin_court_xy_m=self.MID))
        zones = next(p for p in stats["players"] if p["track_id"] == 9)["by_zone"]
        self.assertEqual(list(zones), ["mid_range"])

    def test_team_zones_aggregate_across_players(self) -> None:
        stats = self.build(
            shot(event_id=1, shooter_track_id=9, shot_origin_court_xy_m=self.MID, outcome="made"),
            shot(event_id=2, shooter_track_id=3, shot_origin_court_xy_m=self.MID, outcome="missed"),
        )
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["by_zone"]["mid_range"], {"made": 1, "attempted": 2, "pct": 0.5})
