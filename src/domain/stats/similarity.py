"""Clip similarity from spatial features.

A clip is reduced to a small, fixed-length feature vector describing *where* and
*how* the play happened — shot locations, where players occupied the court, how
fast they moved, how spread out they were — and two clips are compared by
distance between their vectors. Identity is never used: two clips are similar
when their shape of movement and shot locations match, not when "player #7 did
something", because identity is unreliable across clips.

Pure functions over already-parsed documents, so every rule is testable.
"""

from __future__ import annotations

import math

from src.domain.stats.court import COURT_LENGTH_M, COURT_WIDTH_M, describe_shot, is_on_court

FEATURE_VERSION = 1

# Court-occupancy grid: length is split into more cells than width because play
# moves mostly end-to-end. 6 x 3 = 18 cells is coarse enough to be stable under
# homography noise while still separating "left wing" from "right corner".
GRID_LENGTH_CELLS = 6
GRID_WIDTH_CELLS = 3

ZONES = ("at_the_rim", "paint", "mid_range", "corner_three", "above_the_break_three")

# Scales that turn an absolute difference into a 0..1 dissimilarity. Heuristic,
# and deliberately generous: they set how quickly two clips stop looking alike as
# their tempo or spread diverge.
TEMPO_SCALE_M_PER_SAMPLE = 1.0
SPREAD_SCALE_M = COURT_WIDTH_M / 2

DEFAULT_MOVEMENT_WEIGHT = 0.5


def _normalize(counts: list[float]) -> list[float]:
    total = sum(counts)
    if total <= 0:
        return [0.0 for _ in counts]
    return [value / total for value in counts]


def _shot_zone_histogram(shots_document: dict | None) -> tuple[list[float], int, float | None]:
    counts = {zone: 0 for zone in ZONES}
    made = 0
    attempts = 0
    for shot in (shots_document or {}).get("shots") or []:
        court_xy = shot.get("shot_origin_court_xy_m")
        if not court_xy or len(court_xy) < 2 or not is_on_court((court_xy[0], court_xy[1])):
            continue
        location = describe_shot((float(court_xy[0]), float(court_xy[1])))
        if location.zone in counts:
            counts[location.zone] += 1
        attempts += 1
        if shot.get("outcome") == "made":
            made += 1
    histogram = _normalize([float(counts[zone]) for zone in ZONES])
    make_rate = None if attempts == 0 else round(made / attempts, 3)
    return histogram, attempts, make_rate


def _cell_index(x: float, y: float) -> int:
    col = min(int(x / COURT_LENGTH_M * GRID_LENGTH_CELLS), GRID_LENGTH_CELLS - 1)
    row = min(int(y / COURT_WIDTH_M * GRID_WIDTH_CELLS), GRID_WIDTH_CELLS - 1)
    col = max(col, 0)
    row = max(row, 0)
    return row * GRID_LENGTH_CELLS + col


def _movement_features(position_rows: list[dict]) -> tuple[list[float], float, float]:
    """Occupancy grid, mean tempo (m per sample), mean spread (m)."""

    cells = [0.0] * (GRID_LENGTH_CELLS * GRID_WIDTH_CELLS)
    by_track: dict[int, list[tuple[float, float]]] = {}
    by_frame: dict[int, list[tuple[float, float]]] = {}

    for row in position_rows:
        court_xy = row.get("court_xy_m")
        track_id = row.get("track_id", row.get("player_id"))
        if track_id is None or not court_xy or len(court_xy) < 2:
            continue
        point = (float(court_xy[0]), float(court_xy[1]))
        if not is_on_court(point):
            continue
        cells[_cell_index(point[0], point[1])] += 1
        by_track.setdefault(int(track_id), []).append(point)
        frame = row.get("frame_index")
        if frame is not None:
            by_frame.setdefault(int(frame), []).append(point)

    tempos: list[float] = []
    for path in by_track.values():
        if len(path) < 2:
            continue
        steps = [math.dist(path[i - 1], path[i]) for i in range(1, len(path))]
        tempos.append(sum(steps) / len(steps))
    tempo = round(sum(tempos) / len(tempos), 4) if tempos else 0.0

    spreads: list[float] = []
    for points in by_frame.values():
        if len(points) < 2:
            continue
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        spreads.append(sum(math.dist(p, (cx, cy)) for p in points) / len(points))
    spread = round(sum(spreads) / len(spreads), 4) if spreads else 0.0

    return _normalize(cells), tempo, spread


def build_clip_features(*, shots_document: dict | None, position_rows: list[dict]) -> dict:
    """Reduce one clip to its comparable feature vector."""

    shot_zones, shot_count, make_rate = _shot_zone_histogram(shots_document)
    occupancy, tempo, spread = _movement_features(position_rows)
    return {
        "version": FEATURE_VERSION,
        "shot_zones": {zone: shot_zones[index] for index, zone in enumerate(ZONES)},
        "shot_count": shot_count,
        "make_rate": make_rate,
        "occupancy": occupancy,
        "tempo_m_per_sample": tempo,
        "spread_m": spread,
    }


def _histogram_similarity(a: list[float], b: list[float]) -> float:
    """1 for identical distributions, 0 for disjoint ones (L1 based).

    Two empty distributions are treated as identical: a clip with no shots is
    like another clip with no shots.
    """

    if sum(a) == 0 and sum(b) == 0:
        return 1.0
    l1 = sum(abs(x - y) for x, y in zip(a, b))
    return max(0.0, 1.0 - l1 / 2.0)


def _scalar_similarity(a: float, b: float, *, scale: float) -> float:
    return max(0.0, 1.0 - abs(a - b) / scale)


def _shot_similarity(a: dict, b: dict) -> float:
    zones_a = [a["shot_zones"][zone] for zone in ZONES]
    zones_b = [b["shot_zones"][zone] for zone in ZONES]
    zone_sim = _histogram_similarity(zones_a, zones_b)
    if a["make_rate"] is None or b["make_rate"] is None:
        return zone_sim
    return 0.75 * zone_sim + 0.25 * _scalar_similarity(a["make_rate"], b["make_rate"], scale=1.0)


def _movement_similarity(a: dict, b: dict) -> float:
    occupancy = _histogram_similarity(a["occupancy"], b["occupancy"])
    tempo = _scalar_similarity(
        a["tempo_m_per_sample"], b["tempo_m_per_sample"], scale=TEMPO_SCALE_M_PER_SAMPLE
    )
    spread = _scalar_similarity(a["spread_m"], b["spread_m"], scale=SPREAD_SCALE_M)
    return 0.6 * occupancy + 0.2 * tempo + 0.2 * spread


def feature_similarity(a: dict, b: dict, *, movement_weight: float = DEFAULT_MOVEMENT_WEIGHT) -> dict:
    """Weighted similarity of two clips, plus the two component scores.

    `movement_weight` slides from 0 (shots only) to 1 (movement only); 0.5
    weighs the two evenly.
    """

    weight = min(1.0, max(0.0, movement_weight))
    shot_score = _shot_similarity(a, b)
    movement_score = _movement_similarity(a, b)
    score = (1.0 - weight) * shot_score + weight * movement_score
    return {
        "score": round(score, 4),
        "shot_score": round(shot_score, 4),
        "movement_score": round(movement_score, 4),
    }
