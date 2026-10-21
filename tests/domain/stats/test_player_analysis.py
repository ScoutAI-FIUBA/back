from src.domain.stats.player_analysis import CALC_VERSION, percentage, shot_outcome, stats_patch, without_nul


def test_outcome_buckets_follow_the_pipeline_outcome_not_a_guess():
    assert shot_outcome({"made": True, "outcome": "made"}) == "made"
    assert shot_outcome({"made": False, "outcome": "missed"}) == "missed"
    assert shot_outcome({"made": False, "outcome": "unknown"}) == "unresolved"
    assert shot_outcome({"made": False, "outcome": None}) == "unresolved"


def test_stats_patch_fills_only_what_the_analysis_measures():
    patch = stats_patch({"games": 2, "points": 5, "field_goals_made": 2, "field_goals_attempted": 3,
                         "two_point_made": 1, "two_point_attempted": 1, "three_point_made": 1, "three_point_attempted": 2})
    assert patch["games_played"] == 2
    assert patch["points"] == {"total": 5, "per_game": 3}  # 2.5 per game rounds up, not down to 2
    assert patch["field_goals"] == {"made_total": 2, "attempted_total": 3, "per_game": {"made": 1, "attempted": 2}, "percentage": 67}
    assert patch["three_point"]["percentage"] == 50
    # Half a shot per game reads as 1, never 0.
    assert patch["two_point"]["per_game"] == {"made": 1, "attempted": 1}
    for unmeasured in ("rebounds", "assists", "steals", "blocks", "turnovers", "free_throws", "record"):
        assert unmeasured not in patch


def test_nobody_who_never_shot_gets_a_percentage():
    patch = stats_patch({"games": 1, "points": 0, "field_goals_made": 0, "field_goals_attempted": 0,
                         "two_point_made": 0, "two_point_attempted": 0, "three_point_made": 0, "three_point_attempted": 0})
    assert patch["field_goals"]["percentage"] == 0 and percentage(0, 0) == 0
    assert stats_patch({"games": 0, "points": 0, "field_goals_made": 0, "field_goals_attempted": 0,
                        "two_point_made": 0, "two_point_attempted": 0, "three_point_made": 0,
                        "three_point_attempted": 0})["points"] == {"total": 0, "per_game": 0}


def test_without_nul_cleans_every_text_value_but_nothing_else():
    assert without_nul("co\x00rner") == "corner"
    assert without_nul(None) is None and without_nul(3) == 3
    assert without_nul([{"a\x00": "b\x00", "n": 1.5}]) == [{"a": "b", "n": 1.5}]


def test_the_calc_version_is_the_court_rules_generation():
    assert CALC_VERSION == 2
