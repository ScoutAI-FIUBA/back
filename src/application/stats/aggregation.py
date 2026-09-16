"""Turn processing-pipeline output into game statistics.

The pipeline detects events and positions; it does not keep score. This module
is where tracked shots become a box score: assigning point values from court
geometry, attaching numbers and teams to tracks, and totalling per player and
per side.

Pure functions over already-parsed documents — no storage, no HTTP — so every
rule here is testable against a fixture.
"""

from __future__ import annotations

from src.domain.stats.court import describe_shot, is_on_court
from src.domain.stats.entities import GameStats, PlayerStats, TeamStats

# Outcomes the pipeline reports for a shot. Anything else (notably "unknown")
# still counts as an attempt but never as a make.
MADE = "made"


def team_by_track(teams_document: dict | None) -> dict[int, int]:
    """`track_id -> team_id` from the pipeline's team assignments."""

    if not teams_document:
        return {}
    mapping: dict[int, int] = {}
    for assignment in teams_document.get("assignments") or []:
        track_id = assignment.get("track_id")
        team_id = assignment.get("team_id")
        if track_id is not None and team_id is not None:
            mapping[int(track_id)] = int(team_id)
    return mapping


def number_by_track(numbers_document: dict | None) -> dict[int, str]:
    """`track_id -> jersey number`, confirmed readings only.

    Unconfirmed guesses are dropped rather than surfaced: a wrong number on a
    stat line is worse than no number, because it silently attributes a shot to
    the wrong player.

    TODO(jersey-numbers): sparse today (~22 crops/game read). Fills out as CV
    number sampling improves; no change needed here.
    """

    if not numbers_document:
        return {}
    mapping: dict[int, str] = {}
    for track in numbers_document.get("tracks") or []:
        if track.get("status") != "confirmed":
            continue
        number = track.get("number")
        track_id = track.get("track_id")
        if track_id is not None and number not in (None, "", "unknown"):
            mapping[int(track_id)] = str(number)
    return mapping


def build_game_stats(
    *,
    shots_document: dict | None,
    teams_document: dict | None,
    numbers_document: dict | None,
) -> GameStats:
    """Assemble the box score for one processed video."""

    teams_of = team_by_track(teams_document)
    numbers_of = number_by_track(numbers_document)

    players: dict[int, PlayerStats] = {}
    teams: dict[int, TeamStats] = {}
    shot_rows: list[dict] = []

    raw_shots = (shots_document or {}).get("shots") or []
    unattributed = 0
    unprojected = 0

    for shot in raw_shots:
        court_xy = shot.get("shot_origin_court_xy_m")
        made = shot.get("outcome") == MADE

        # A shot the homography could not place cannot be scored, because its
        # point value depends on where it was taken from.
        if not court_xy or len(court_xy) < 2 or not is_on_court((court_xy[0], court_xy[1])):
            unprojected += 1
            continue

        location = describe_shot((float(court_xy[0]), float(court_xy[1])))
        track_id = shot.get("shooter_track_id")
        team_id = shot.get("shooter_team_id")
        if team_id is None and track_id is not None:
            team_id = teams_of.get(int(track_id))

        if track_id is None:
            unattributed += 1
        else:
            track_id = int(track_id)
            player = players.setdefault(
                track_id,
                PlayerStats(
                    track_id=track_id,
                    team_id=team_id if team_id is None else int(team_id),
                    jersey_number=numbers_of.get(track_id),
                ),
            )
            player.shooting.add(made=made, points=location.points, zone=location.zone)

        if team_id is not None:
            team = teams.setdefault(int(team_id), TeamStats(team_id=int(team_id)))
            team.shooting.add(made=made, points=location.points, zone=location.zone)

        shot_rows.append(
            {
                "shot_id": shot.get("event_id"),
                "track_id": track_id,
                "team_id": None if team_id is None else int(team_id),
                "jersey_number": None if track_id is None else numbers_of.get(track_id),
                "made": made,
                "points": location.points,
                "zone": location.zone,
                "distance_m": location.distance_m,
                "court_x_m": round(float(court_xy[0]), 2),
                "court_y_m": round(float(court_xy[1]), 2),
                "timestamp_seconds": shot.get("start_timestamp_seconds"),
                "shot_type": shot.get("shot_type"),
                # How the shooter was chosen. "nearest_player_bbox_to_shot_anchor"
                # is a proximity guess, so a client may want to flag it.
                "attribution": shot.get("shooter_attribution_method"),
            }
        )

    # Every tracked player appears, not only those who shot, so the interface can
    # list a full squad rather than only scorers.
    for track_id, team_id in sorted(teams_of.items()):
        player = players.setdefault(
            track_id,
            PlayerStats(track_id=track_id, team_id=team_id, jersey_number=numbers_of.get(track_id)),
        )
        if player.team_id is None:
            player.team_id = team_id
        teams.setdefault(team_id, TeamStats(team_id=team_id))

    for player in players.values():
        if player.team_id is not None and player.team_id in teams:
            teams[player.team_id].player_count += 1

    identified = sum(1 for player in players.values() if player.jersey_number)
    return GameStats(
        teams=[teams[key] for key in sorted(teams)],
        players=sorted(players.values(), key=lambda p: (p.team_id or -1, p.track_id)),
        shots=shot_rows,
        coverage={
            "shots_detected": len(raw_shots),
            "shots_scored": len(shot_rows),
            "shots_without_court_position": unprojected,
            "shots_without_shooter": unattributed,
            "players_tracked": len(players),
            # TODO(jersey-numbers): low today; UI can watch this ratio to decide
            # whether to show numbers or fall back to "Player N".
            "players_with_jersey_number": identified,
            # Stated plainly so the interface never implies a complete stat line.
            "measures": ["shooting"],
            "not_measured": ["rebounds", "assists", "turnovers", "steals", "fouls", "minutes"],
        },
    )
