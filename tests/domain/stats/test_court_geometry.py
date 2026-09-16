"""Court geometry and shot scoring.

These encode the basketball rules the box score depends on. Getting the
three-point line wrong silently misreports every score in the app, so the
boundary cases are tested explicitly rather than assumed.
"""

from __future__ import annotations

import unittest

from src.domain.stats.court import (
    AWAY_HOOP,
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    HOME_HOOP,
    describe_shot,
    is_on_court,
    nearest_hoop,
)


class TestNearestHoop(unittest.TestCase):
    def test_shot_near_one_baseline_picks_that_hoop(self) -> None:
        self.assertEqual(nearest_hoop((3.0, 7.5)), HOME_HOOP)
        self.assertEqual(nearest_hoop((25.0, 7.5)), AWAY_HOOP)

    def test_halfway_line_resolves_without_error(self) -> None:
        """Exactly mid-court is arbitrary but must not crash or return None."""

        self.assertIn(nearest_hoop((COURT_LENGTH_M / 2, 7.5)), (HOME_HOOP, AWAY_HOOP))

    def test_hoop_is_inset_from_the_baseline(self) -> None:
        """A hoop stands inside the court, not on the line."""

        self.assertGreater(HOME_HOOP[0], 0)
        self.assertEqual(HOME_HOOP[1], COURT_WIDTH_M / 2)


class TestShotValue(unittest.TestCase):
    def test_layup_is_two_points_at_the_rim(self) -> None:
        shot = describe_shot((2.0, 7.5))
        self.assertEqual(shot.points, 2)
        self.assertEqual(shot.zone, "at_the_rim")
        self.assertFalse(shot.is_three)

    def test_paint_is_two_points(self) -> None:
        # 4.4m from the hoop — around the free-throw line.
        shot = describe_shot((6.0, 7.5))
        self.assertEqual(shot.points, 2)
        self.assertEqual(shot.zone, "paint")

    def test_mid_range_is_two_points(self) -> None:
        # 5.4m out: past the paint, still inside the arc.
        shot = describe_shot((7.0, 7.5))
        self.assertEqual(shot.points, 2)
        self.assertEqual(shot.zone, "mid_range")

    def test_beyond_the_arc_is_three_points(self) -> None:
        shot = describe_shot((9.0, 7.5))
        self.assertEqual(shot.points, 3)
        self.assertEqual(shot.zone, "above_the_break_three")

    def test_corner_three_counts_despite_being_closer_than_the_arc(self) -> None:
        """The corner line is 6.60m, nearer than the 6.75m arc.

        Scoring on distance alone would wrongly call this a two — the exact bug
        this rule exists to prevent.
        """

        corner = describe_shot((HOME_HOOP[0], COURT_WIDTH_M - 0.9))
        self.assertLess(corner.distance_m, 6.75)
        self.assertEqual(corner.points, 3)
        self.assertEqual(corner.zone, "corner_three")

    def test_both_corners_score_the_same(self) -> None:
        near = describe_shot((HOME_HOOP[0], 0.9))
        far = describe_shot((HOME_HOOP[0], COURT_WIDTH_M - 0.9))
        self.assertEqual(near.points, far.points)
        self.assertEqual(near.points, 3)

    def test_just_inside_the_corner_lane_is_two(self) -> None:
        """A step in from the corner line is worth two."""

        inside = describe_shot((HOME_HOOP[0], COURT_WIDTH_M - 1.6))
        self.assertEqual(inside.points, 2)

    def test_a_shot_at_the_far_end_uses_the_far_hoop(self) -> None:
        """Teams change ends; scoring must not assume a fixed direction."""

        near_far_hoop = describe_shot((AWAY_HOOP[0] - 1.0, 7.5))
        self.assertEqual(near_far_hoop.points, 2)
        self.assertEqual(near_far_hoop.zone, "at_the_rim")

    def test_distance_is_reported_in_metres(self) -> None:
        shot = describe_shot((HOME_HOOP[0] + 5.0, 7.5))
        self.assertAlmostEqual(shot.distance_m, 5.0, places=2)

    def test_the_measured_test_clip_shot_is_a_two(self) -> None:
        """The real shot from the pipeline: 6.21m out, inside the arc."""

        shot = describe_shot((3.867, 13.267))
        self.assertEqual(shot.points, 2)
        self.assertAlmostEqual(shot.distance_m, 6.21, places=1)


class TestOnCourt(unittest.TestCase):
    def test_centre_court_is_on_court(self) -> None:
        self.assertTrue(is_on_court((14.0, 7.5)))

    def test_corners_are_on_court(self) -> None:
        self.assertTrue(is_on_court((0.0, 0.0)))
        self.assertTrue(is_on_court((COURT_LENGTH_M, COURT_WIDTH_M)))

    def test_slightly_out_of_bounds_is_accepted(self) -> None:
        """Players do step out; only nonsense projections should be dropped."""

        self.assertTrue(is_on_court((-0.5, 7.5)))

    def test_broken_projection_is_rejected(self) -> None:
        """Bad homography can place a player hundreds of metres away."""

        self.assertFalse(is_on_court((250.0, 7.5)))
        self.assertFalse(is_on_court((14.0, -80.0)))


if __name__ == "__main__":
    unittest.main()
