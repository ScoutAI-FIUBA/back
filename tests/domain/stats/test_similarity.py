"""Reducing a clip to a feature vector and comparing two clips.

Similarity is on shape of play — where shots came from, where players were, how
fast and how spread — never on player identity.
"""

from __future__ import annotations

import unittest

from src.domain.stats.similarity import build_clip_features, feature_similarity


def shots(*points_and_outcomes) -> dict:
    return {
        "shots": [
            {"shot_origin_court_xy_m": xy, "outcome": outcome}
            for xy, outcome in points_and_outcomes
        ]
    }


def positions(*rows) -> list[dict]:
    return [
        {"frame_index": frame, "track_id": track, "court_xy_m": [x, y]}
        for frame, track, x, y in rows
    ]


RIM = [2.5, 7.5]
MID = [7.0, 7.5]
ARC = [9.5, 7.5]


class TestBuildFeatures(unittest.TestCase):
    def test_shot_zone_histogram_is_normalized(self) -> None:
        features = build_clip_features(
            shots_document=shots((RIM, "made"), (RIM, "missed"), (ARC, "made")),
            position_rows=[],
        )
        self.assertAlmostEqual(sum(features["shot_zones"].values()), 1.0)
        self.assertAlmostEqual(features["shot_zones"]["at_the_rim"], 2 / 3)
        self.assertAlmostEqual(features["make_rate"], round(2 / 3, 3))

    def test_no_shots_gives_empty_histogram_and_no_make_rate(self) -> None:
        features = build_clip_features(shots_document={"shots": []}, position_rows=[])
        self.assertEqual(sum(features["shot_zones"].values()), 0.0)
        self.assertIsNone(features["make_rate"])
        self.assertEqual(features["shot_count"], 0)

    def test_occupancy_is_a_normalized_grid(self) -> None:
        features = build_clip_features(
            shots_document=None,
            position_rows=positions((0, 1, 2.0, 7.5), (1, 1, 3.0, 7.5)),
        )
        self.assertAlmostEqual(sum(features["occupancy"]), 1.0)

    def test_tempo_is_mean_step_distance(self) -> None:
        features = build_clip_features(
            shots_document=None,
            position_rows=positions((0, 1, 0.0, 0.0), (1, 1, 3.0, 4.0)),
        )
        self.assertEqual(features["tempo_m_per_sample"], 5.0)

    def test_v2_tempo_groups_segments_of_one_player_by_stable_id(self) -> None:
        # One player at x = 0, 1, 10, 11 — a big jump mid-path — split across two
        # segmented track_ids at the jump. As one path the steps are 1, 9, 1
        # (mean 3.6667); grouped by track the 9m jump vanishes and both segments
        # read a tempo of 1.0, so grouping by stable id is what keeps it honest.
        rows = [
            {"frame_index": 0, "track_id": 11, "stable_player_id": "p", "court_xy_m": [0.0, 7.5]},
            {"frame_index": 1, "track_id": 11, "stable_player_id": "p", "court_xy_m": [1.0, 7.5]},
            {"frame_index": 2, "track_id": 77, "stable_player_id": "p", "court_xy_m": [10.0, 7.5]},
            {"frame_index": 3, "track_id": 77, "stable_player_id": "p", "court_xy_m": [11.0, 7.5]},
        ]
        features = build_clip_features(shots_document=None, position_rows=rows)
        self.assertEqual(features["tempo_m_per_sample"], 3.6667)

    def test_spread_measures_distance_from_the_frame_centroid(self) -> None:
        features = build_clip_features(
            shots_document=None,
            position_rows=positions((0, 1, 0.0, 7.5), (0, 2, 4.0, 7.5)),
        )
        self.assertEqual(features["spread_m"], 2.0)

    def test_off_court_points_are_ignored(self) -> None:
        features = build_clip_features(
            shots_document=None,
            position_rows=positions((0, 1, 2.0, 7.5), (1, 1, 400.0, 7.5)),
        )
        self.assertAlmostEqual(sum(features["occupancy"]), 1.0)


class TestSimilarity(unittest.TestCase):
    def features(self, *, shot_points, rows):
        return build_clip_features(shots_document=shots(*shot_points), position_rows=positions(*rows))

    def test_identical_clips_score_one(self) -> None:
        a = self.features(shot_points=[(RIM, "made")], rows=[(0, 1, 2.0, 7.5), (1, 1, 3.0, 7.5)])
        self.assertEqual(feature_similarity(a, a)["score"], 1.0)

    def test_different_shot_locations_lower_the_shot_score(self) -> None:
        a = self.features(shot_points=[(RIM, "made")], rows=[])
        b = self.features(shot_points=[(ARC, "made")], rows=[])
        self.assertLess(feature_similarity(a, b)["shot_score"], 1.0)

    def test_movement_weight_zero_uses_only_shots(self) -> None:
        a = self.features(shot_points=[(RIM, "made")], rows=[(0, 1, 2.0, 7.5), (1, 1, 2.1, 7.5)])
        b = self.features(shot_points=[(RIM, "made")], rows=[(0, 1, 25.0, 1.0), (1, 1, 26.0, 14.0)])
        result = feature_similarity(a, b, movement_weight=0.0)
        self.assertEqual(result["score"], result["shot_score"])

    def test_movement_weight_one_uses_only_movement(self) -> None:
        a = self.features(shot_points=[(RIM, "made")], rows=[(0, 1, 2.0, 7.5)])
        b = self.features(shot_points=[(ARC, "missed")], rows=[(0, 1, 2.0, 7.5)])
        result = feature_similarity(a, b, movement_weight=1.0)
        self.assertEqual(result["score"], result["movement_score"])


if __name__ == "__main__":
    unittest.main()
