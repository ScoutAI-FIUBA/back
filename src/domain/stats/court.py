"""Court geometry and shot scoring.

Pure functions over FIBA court coordinates in metres, as produced by the
processing pipeline's homography. No I/O, no framework — this is the basketball
knowledge the rest of the system reasons with.

Coordinate frame, matching the pipeline's projection:

    x runs along the length of the court, 0 to 28 metres
    y runs across the width,              0 to 15 metres

    (0,0) ┌──────────────────────────────┐
          │  ●                        ●  │  ● = hoop centres
          └──────────────────────────────┘ (28,15)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# FIBA competition court.
COURT_LENGTH_M = 28.0
COURT_WIDTH_M = 15.0

# Hoop centre sits 1.575 m in from each baseline, on the centre line of the width.
HOOP_INSET_M = 1.575
HOME_HOOP = (HOOP_INSET_M, COURT_WIDTH_M / 2)
AWAY_HOOP = (COURT_LENGTH_M - HOOP_INSET_M, COURT_WIDTH_M / 2)

# The three-point line: an arc 6.75 m from the hoop, closed off by two straight
# lines 0.90 m in from each sideline. A shot from the corner is therefore a three
# at a shorter distance than one from the top of the arc.
THREE_POINT_RADIUS_M = 6.75
CORNER_LANE_FROM_SIDELINE_M = 0.90
CORNER_THREE_LATERAL_M = (COURT_WIDTH_M / 2) - CORNER_LANE_FROM_SIDELINE_M  # 6.60

# Where the straight corner segment meets the arc, measured from the hoop towards
# midcourt: sqrt(6.75^2 - 6.60^2) = 1.415 m. Past it the arc governs; at or behind
# it only the straight line counts.
CORNER_SEGMENT_END_M = math.sqrt(THREE_POINT_RADIUS_M**2 - CORNER_THREE_LATERAL_M**2)

# Bump whenever the zone or points rules in this module change, so persisted
# shot rows can be told apart from ones built under older rules.
COURT_RULES_VERSION = 2

# Float noise guard so a shot exactly on a line (which counts as a three) is not
# demoted by a 1e-15 rounding error.
_LINE_EPSILON_M = 1e-9

TWO_POINTS = 2
THREE_POINTS = 3


@dataclass(frozen=True)
class ShotLocation:
    """Where a shot was taken from, described in basketball terms."""

    distance_m: float
    points: int
    zone: str

    @property
    def is_three(self) -> bool:
        return self.points == THREE_POINTS


def nearest_hoop(court_xy: tuple[float, float]) -> tuple[float, float]:
    """Which basket a shot was aimed at.

    Inferred from proximity rather than from team assignment, because the
    pipeline does not know which side each team is attacking, and teams swap ends
    at half time anyway.
    """

    x, y = court_xy
    return HOME_HOOP if math.dist((x, y), HOME_HOOP) <= math.dist((x, y), AWAY_HOOP) else AWAY_HOOP


def describe_shot(court_xy: tuple[float, float]) -> ShotLocation:
    """Classify a shot by distance and value."""

    x, y = float(court_xy[0]), float(court_xy[1])
    hoop_x, hoop_y = nearest_hoop((x, y))
    distance = math.hypot(x - hoop_x, y - hoop_y)
    lateral = abs(y - hoop_y)

    # Depth of the shot from the hoop towards midcourt; negative means behind the hoop.
    forward = (x - hoop_x) if hoop_x == HOME_HOOP[0] else (hoop_x - x)

    # The arc only exists in front of the hoop. Along the straight corner segment
    # (up to where it meets the arc, and everywhere behind the hoop) the line is
    # 6.60 m from the hoop axis, closer than the arc, so a shot can be worth three
    # at less than the arc radius.
    in_corner_lane = lateral >= CORNER_THREE_LATERAL_M - _LINE_EPSILON_M
    beyond_arc = forward > 0 and distance >= THREE_POINT_RADIUS_M - _LINE_EPSILON_M

    if in_corner_lane and forward <= CORNER_SEGMENT_END_M:
        points, zone = THREE_POINTS, "corner_three"
    elif in_corner_lane or beyond_arc:
        points, zone = THREE_POINTS, "above_the_break_three"
    elif distance <= 1.8:
        points, zone = TWO_POINTS, "at_the_rim"
    elif distance <= 4.5:
        points, zone = TWO_POINTS, "paint"
    else:
        points, zone = TWO_POINTS, "mid_range"

    return ShotLocation(distance_m=round(distance, 2), points=points, zone=zone)


def court_reference() -> dict:
    """Everything a client needs to draw the floor and the three-point line.

    The stats endpoints return court positions in metres on this frame; without
    the hoop centres and arc radius a client cannot draw the line the points sit
    against, so it is shipped alongside them rather than duplicated in the UI.
    """

    return {
        "length_m": COURT_LENGTH_M,
        "width_m": COURT_WIDTH_M,
        "hoop_inset_m": HOOP_INSET_M,
        "hoops": {
            "home": {"x_m": HOME_HOOP[0], "y_m": HOME_HOOP[1]},
            "away": {"x_m": AWAY_HOOP[0], "y_m": AWAY_HOOP[1]},
        },
        "three_point_radius_m": THREE_POINT_RADIUS_M,
        "corner_three_lateral_m": CORNER_THREE_LATERAL_M,
    }


def step_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line court distance in metres between two projected points."""

    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def is_on_court(court_xy: tuple[float, float], *, tolerance_m: float = 1.0) -> bool:
    """Whether a projected position is plausibly inside the court.

    Homography can place a player well outside the lines when keypoints are poor.
    A small tolerance keeps genuine out-of-bounds positions while discarding
    obviously broken projections.
    """

    x, y = float(court_xy[0]), float(court_xy[1])
    return (
        -tolerance_m <= x <= COURT_LENGTH_M + tolerance_m
        and -tolerance_m <= y <= COURT_WIDTH_M + tolerance_m
    )
