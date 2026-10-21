"""Table-driven checks of the three-point rules and zones, for both baskets.

The right basket is tested by mirroring the left one along the court length, so
a rule that only works on one side fails here.
"""

from __future__ import annotations

import math
import unittest

from src.domain.stats.court import (
    AWAY_HOOP,
    COURT_LENGTH_M,
    COURT_RULES_VERSION,
    CORNER_SEGMENT_END_M,
    CORNER_THREE_LATERAL_M,
    HOME_HOOP,
    THREE_POINT_RADIUS_M,
    describe_shot,
)

HX, HY = HOME_HOOP
EPS = 0.01
ARC_X = HX + CORNER_SEGMENT_END_M  # where the straight segment meets the arc

# (name, (x, y) around the LEFT hoop, expected points, expected zone)
LEFT_CASES = [
    # behind the baseline: only the straight segment counts
    ("behind baseline, inside corner line", (-0.5, 1.0), 2, "mid_range"),
    ("behind baseline, on the axis", (-0.5, HY), 2, "paint"),
    ("behind baseline, past corner line", (-0.5, HY - CORNER_THREE_LATERAL_M - EPS), 3, "corner_three"),
    ("behind hoop, just inside corner line", (0.2, HY + CORNER_THREE_LATERAL_M - EPS), 2, "mid_range"),
    ("level with hoop, just outside corner line", (HX, HY + CORNER_THREE_LATERAL_M + EPS), 3, "corner_three"),
    ("level with hoop, just inside corner line", (HX, HY + CORNER_THREE_LATERAL_M - EPS), 2, "mid_range"),
    ("on the corner line exactly", (HX, HY - CORNER_THREE_LATERAL_M), 3, "corner_three"),
    # corner segment ends where the arc starts
    ("corner, just before the arc starts", (ARC_X - EPS, 0.5), 3, "corner_three"),
    ("corner, just after the arc starts", (ARC_X + EPS, 0.5), 3, "above_the_break_three"),
    ("corner, far from the baseline", (8.0, 0.5), 3, "above_the_break_three"),
    # the arc itself
    ("top of the arc, just inside", (HX + THREE_POINT_RADIUS_M - EPS, HY), 2, "mid_range"),
    ("top of the arc, on the line", (HX + THREE_POINT_RADIUS_M, HY), 3, "above_the_break_three"),
    ("top of the arc, just outside", (HX + THREE_POINT_RADIUS_M + EPS, HY), 3, "above_the_break_three"),
    ("45 degrees, just inside", (HX + (THREE_POINT_RADIUS_M - EPS) * math.cos(math.pi / 4),
                                 HY + (THREE_POINT_RADIUS_M - EPS) * math.sin(math.pi / 4)), 2, "mid_range"),
    ("45 degrees, just outside", (HX + (THREE_POINT_RADIUS_M + EPS) * math.cos(math.pi / 4),
                                  HY + (THREE_POINT_RADIUS_M + EPS) * math.sin(math.pi / 4)), 3, "above_the_break_three"),
    # inside the arc
    ("at the rim", (HX + 0.5, HY), 2, "at_the_rim"),
    ("paint", (HX + 3.0, HY), 2, "paint"),
    ("mid range", (HX + 5.0, HY), 2, "mid_range"),
]


def _mirror(point: tuple[float, float]) -> tuple[float, float]:
    return (COURT_LENGTH_M - point[0], point[1])


class TestCourtRules(unittest.TestCase):
    def test_left_basket(self) -> None:
        for name, xy, points, zone in LEFT_CASES:
            with self.subTest(name):
                shot = describe_shot(xy)
                self.assertEqual((shot.points, shot.zone), (points, zone))

    def test_right_basket_mirrors_the_left(self) -> None:
        for name, xy, points, zone in LEFT_CASES:
            with self.subTest(name):
                shot = describe_shot(_mirror(xy))
                self.assertEqual((shot.points, shot.zone), (points, zone))
                self.assertAlmostEqual(shot.distance_m, describe_shot(xy).distance_m, delta=0.011)

    def test_flipping_the_sideline_does_not_change_the_result(self) -> None:
        for name, (x, y), points, zone in LEFT_CASES:
            with self.subTest(name):
                shot = describe_shot((x, 2 * HY - y))
                self.assertEqual((shot.points, shot.zone), (points, zone))

    def test_corner_zone_ends_where_the_arc_starts(self) -> None:
        self.assertAlmostEqual(CORNER_SEGMENT_END_M, 1.415, places=3)
        self.assertAlmostEqual(math.hypot(CORNER_SEGMENT_END_M, CORNER_THREE_LATERAL_M), THREE_POINT_RADIUS_M)

    def test_hoops_are_symmetric(self) -> None:
        self.assertAlmostEqual(HOME_HOOP[0] + AWAY_HOOP[0], COURT_LENGTH_M)

    def test_rules_version_is_declared(self) -> None:
        self.assertEqual(COURT_RULES_VERSION, 2)


# Shot origins (court metres) of the real analysed clips, with the points and zone
# the pre-fix rules gave. Points never change. The only intentional zone change is
# 86f87c1b: it is 2.6 m from the hoop towards midcourt, past the 1.415 m where the
# corner segment meets the arc, so it was corner_three and is now above_the_break.
REAL_SHOTS = [
    ("4b889bbd", (18.62412452697754, 6.119649887084961), 3, "above_the_break_three"),
    ("804f1784", (22.781435012817383, 3.300750494003296), 2, "mid_range"),
    ("86f87c1b", (23.81763458251953, 14.438721656799316), 3, "above_the_break_three"),
    ("9d60cf76", (19.761953353881836, 10.424656867980957), 3, "above_the_break_three"),
    ("3931fd9f", (25.54408836364746, 7.717466354370117), 2, "at_the_rim"),
    ("6dee2866 a", (2.4268734455108643, 12.695664405822754), 2, "mid_range"),
    ("6dee2866 b", (2.82010555267334, 9.007742881774902), 2, "paint"),
    ("6dee2866 c", (6.4117512702941895, 10.4653902053833), 2, "mid_range"),
    ("87f5d08c", (11.078987121582031, 6.694714069366455), 3, "above_the_break_three"),
    ("cd5ce862 a", (25.763450622558594, 9.268373489379883), 2, "paint"),
    ("cd5ce862 b", (18.67365837097168, 4.011099338531494), 3, "above_the_break_three"),
    ("cd5ce862 c", (2.5771491527557373, 8.942025184631348), 2, "at_the_rim"),
]


class TestRealShotsUnchanged(unittest.TestCase):
    def test_real_shots_keep_points_and_zone(self) -> None:
        for name, xy, points, zone in REAL_SHOTS:
            with self.subTest(name):
                shot = describe_shot(xy)
                self.assertEqual((shot.points, shot.zone), (points, zone))


if __name__ == "__main__":
    unittest.main()
