"""Turn processing-pipeline output into game statistics.

The pipeline detects events and positions; it does not keep score. This module
is where tracked shots become a box score: assigning point values from court
geometry, attaching numbers and teams to tracks, and totalling per player and
per side.

Pure functions over already-parsed documents — no storage, no HTTP — so every
rule here is testable against a fixture.
"""

from __future__ import annotations

from src.domain.stats.court import court_reference, describe_shot, is_on_court
from src.domain.stats.entities import GameStats, PlayerStats, TeamStats

# Outcomes the pipeline reports for a shot. Anything else (notably "unknown")
# still counts as an attempt but never as a make.
MADE = "made"
MISSED = "missed"


def _coerce_track_id(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def team_by_track(teams_document: dict | None) -> dict[int, int]:
    """`track_id -> team_id` from the pipeline's team assignments.

    Accepts both pipeline shapes: the v1 `assignments` list of
    `{track_id, team_id}`, and the v2 `assignments_by_track_id` map of
    `{"<track_id>": team_id}`.
    """

    if not teams_document:
        return {}
    mapping: dict[int, int] = {}
    for assignment in teams_document.get("assignments") or []:
        track_id = _coerce_track_id(assignment.get("track_id"))
        team_id = assignment.get("team_id")
        if track_id is not None and team_id is not None:
            mapping[track_id] = int(team_id)
    for raw_track_id, team_id in (teams_document.get("assignments_by_track_id") or {}).items():
        track_id = _coerce_track_id(raw_track_id)
        if track_id is not None and team_id is not None:
            mapping[track_id] = int(team_id)
    return mapping


def number_by_track(
    numbers_document: dict | None,
    *,
    stable_to_track: dict[str, int] | None = None,
) -> dict[int, str]:
    """`track_id -> jersey number`, confirmed readings only.

    Unconfirmed guesses are dropped rather than surfaced: a wrong number on a
    stat line is worse than no number, because it silently attributes a shot to
    the wrong player.

    Two pipeline shapes are accepted. v1 lists `tracks` keyed by `track_id`. v2
    lists `players` keyed by `stable_player_id`; those are mapped back to a
    `track_id` via `stable_to_track` (built from the projected tracks, which
    carry both ids). Without that map, v2 numbers cannot be attached and are
    skipped rather than guessed at.

    TODO(jersey-numbers): sparse today. Fills out as CV number sampling improves
    (notably once the SAM window spans the whole clip); no change needed here.
    """

    if not numbers_document:
        return {}
    mapping: dict[int, str] = {}
    for track in numbers_document.get("tracks") or []:
        if track.get("status") != "confirmed":
            continue
        number = track.get("number")
        track_id = _coerce_track_id(track.get("track_id"))
        if track_id is not None and number not in (None, "", "unknown"):
            mapping[track_id] = str(number)
    for player in numbers_document.get("players") or []:
        if player.get("status") != "confirmed":
            continue
        number = player.get("number")
        track_id = (stable_to_track or {}).get(player.get("stable_player_id"))
        if track_id is not None and number not in (None, "", "unknown"):
            mapping[int(track_id)] = str(number)
    return mapping


def _link_roster(
    player: PlayerStats, *, roster: dict[str, dict] | None, our_team_side: int | None
) -> None:
    """Tie a track to a roster player, when it is one of the scout's own.

    Only the side the scout marked as their team is linked, and only by a
    confirmed jersey number: the opponent has no roster here, so their tracks
    stay anonymous.
    """

    if roster is None or our_team_side is None:
        return
    if player.team_id != our_team_side or player.jersey_number is None:
        return
    match = roster.get(player.jersey_number)
    if match is not None:
        player.roster_player_id = match["player_id"]
        player.roster_name = match["name"]


def build_game_stats(
    *,
    shots_document: dict | None,
    teams_document: dict | None,
    numbers_document: dict | None,
    roster: dict[str, dict] | None = None,
    our_team_side: int | None = None,
    stable_to_track: dict[str, int] | None = None,
) -> GameStats:
    """Assemble the box score for one processed video.

    When `roster` (jersey number -> roster player) and `our_team_side` are given,
    tracks on that side are tied to the scout's real players by number; without
    them every track stays anonymous, which is the behaviour before a side is
    picked.
    """

    teams_of = team_by_track(teams_document)
    numbers_of = number_by_track(numbers_document, stable_to_track=stable_to_track)

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
                # The raw outcome is kept so a shot chart can tell a miss (draw
                # red) from an undetermined result (draw neither), which the
                # made boolean alone collapses together.
                "outcome": shot.get("outcome"),
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

    for player in players.values():
        _link_roster(player, roster=roster, our_team_side=our_team_side)

    # Now that tracks carry a roster identity, stamp it onto their shot rows too,
    # so a shot chart can label a marker without a second lookup.
    roster_of = {
        track_id: (player.roster_player_id, player.roster_name)
        for track_id, player in players.items()
    }
    for row in shot_rows:
        linked = roster_of.get(row["track_id"], (None, None))
        row["roster_player_id"], row["roster_name"] = linked

    identified = sum(1 for player in players.values() if player.jersey_number)
    linked_count = sum(1 for player in players.values() if player.roster_player_id)
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
            # How many tracks were tied to a real roster player (own team only).
            "players_linked_to_roster": linked_count,
            # Stated plainly so the interface never implies a complete stat line.
            "measures": ["shooting"],
            "not_measured": ["rebounds", "assists", "turnovers", "steals", "fouls", "minutes"],
        },
    )


def _shot_result(outcome: str | None) -> str:
    """made / missed / unknown, from the raw pipeline outcome.

    A chart draws made green and missed red; a shot the pipeline could not
    resolve is neither, so it stays distinct rather than being drawn as a miss.
    """

    if outcome == MADE:
        return "made"
    if outcome == MISSED:
        return "missed"
    return "unknown"


def build_shot_chart(
    *,
    shots_document: dict | None,
    teams_document: dict | None,
    numbers_document: dict | None,
    track_id: int | None = None,
    roster: dict[str, dict] | None = None,
    our_team_side: int | None = None,
    stable_to_track: dict[str, int] | None = None,
) -> dict:
    """Every located shot as a court marker, grouped by the player who took it.

    Built on top of the box score so a marker is scored by exactly the same
    rules as the totals it must agree with. Each marker carries `made` and
    `result` for colouring (made green, missed red) and its court position in
    metres; `court` ships the geometry needed to draw the floor and arc under
    them. `track_id` narrows the chart to one player without changing any total.
    """

    game = build_game_stats(
        shots_document=shots_document,
        teams_document=teams_document,
        numbers_document=numbers_document,
        roster=roster,
        our_team_side=our_team_side,
        stable_to_track=stable_to_track,
    ).to_dict()

    display_of = {player["track_id"]: player["display_name"] for player in game["players"]}
    markers: list[dict] = []
    per_player: dict[int, dict] = {}

    for row in game["shots"]:
        if track_id is not None and row["track_id"] != track_id:
            continue
        marker = {
            "shot_id": row["shot_id"],
            "track_id": row["track_id"],
            "team_id": row["team_id"],
            "jersey_number": row["jersey_number"],
            "roster_player_id": row.get("roster_player_id"),
            "roster_name": row.get("roster_name"),
            "x_m": row["court_x_m"],
            "y_m": row["court_y_m"],
            "made": row["made"],
            "result": _shot_result(row.get("outcome")),
            "points": row["points"],
            "zone": row["zone"],
            "distance_m": row["distance_m"],
            "shot_type": row["shot_type"],
            "timestamp_seconds": row["timestamp_seconds"],
            "attribution": row["attribution"],
        }
        markers.append(marker)
        if row["track_id"] is not None:
            bucket = per_player.setdefault(
                row["track_id"],
                {
                    "track_id": row["track_id"],
                    "team_id": row["team_id"],
                    "jersey_number": row["jersey_number"],
                    "display_name": display_of.get(row["track_id"], f"Player {row['track_id']}"),
                    "shots": [],
                },
            )
            bucket["shots"].append(marker)

    return {
        "court": court_reference(),
        "shots": markers,
        "players": [per_player[key] for key in sorted(per_player)],
        "coverage": {
            **game["coverage"],
            "shots_charted": len(markers),
            "filtered_to_track_id": track_id,
        },
    }
