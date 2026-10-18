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
from src.domain.stats.entities import GameStats, PlayerStats, ShotTally, TeamStats

# Outcomes the pipeline reports for a shot. Anything else (notably "unknown",
# which also covers a ball that went toward the basket but was never confirmed
# and a clip that ended mid-shot) is UNRESOLVED: it is neither a make nor a miss,
# so it is kept out of attempts and percentages and reported on its own.
MADE = "made"
MISSED = "missed"
UNRESOLVED = "unresolved"

# Box-score lines this service cannot produce from shot and tracking data alone.
NOT_MEASURED = [
    "rebounds", "assists", "turnovers", "steals", "blocks", "passes", "possessions",
    "free_throws", "fouls", "minutes",
]


def _coerce_track_id(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def outcome_bucket(shot: dict) -> str:
    """made / missed / unresolved, from the raw pipeline outcome."""

    outcome = shot.get("outcome")
    if outcome == MADE:
        return MADE
    if outcome == MISSED:
        return MISSED
    return UNRESOLVED


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


def number_by_stable(numbers_document: dict | None) -> dict[str, str]:
    """`stable_player_id -> jersey number`, confirmed v2 readings only."""

    if not numbers_document:
        return {}
    mapping: dict[str, str] = {}
    for player in numbers_document.get("players") or []:
        if player.get("status") != "confirmed":
            continue
        number = player.get("number")
        stable_id = player.get("stable_player_id")
        if stable_id is not None and number not in (None, "", "unknown"):
            mapping[str(stable_id)] = str(number)
    return mapping


def _valid_number(number) -> bool:
    return number not in (None, "", "unknown")


def jersey_reads(numbers_document: dict | None) -> tuple[dict[str, dict], dict[int, dict]]:
    """`(by stable_player_id, by track_id)` -> {status, support_count}, any status.

    `number_by_*` keep only confirmed numbers; this keeps how sure the read was,
    so a client can tell "no number seen" from "two candidates disagreed".
    """

    by_stable: dict[str, dict] = {}
    by_track: dict[int, dict] = {}
    for player in (numbers_document or {}).get("players") or []:
        if player.get("stable_player_id") is not None:
            by_stable[str(player["stable_player_id"])] = {
                "status": player.get("status") or "unknown",
                "support_count": int(player.get("support_count") or 0),
            }
    for track in (numbers_document or {}).get("tracks") or []:
        track_id = _coerce_track_id(track.get("track_id"))
        if track_id is not None:
            by_track[track_id] = {
                "status": track.get("status") or "unknown",
                "support_count": int(track.get("support_count") or 0),
            }
    return by_stable, by_track


def summary_players_by_stable(summary_document: dict | None) -> dict[str, dict]:
    """`stable_player_id -> player entry` from the pipeline's player_summary.json."""

    mapping: dict[str, dict] = {}
    for entry in (summary_document or {}).get("players") or []:
        if isinstance(entry, dict) and entry.get("stable_player_id") is not None:
            mapping[str(entry["stable_player_id"])] = entry
    return mapping


def track_to_stable_from_summary(summary_players: dict[str, dict]) -> dict[int, str]:
    """`raw track_id -> stable_player_id`, from each player's listed track ids."""

    mapping: dict[int, str] = {}
    for stable_id, entry in summary_players.items():
        for raw in entry.get("track_ids") or []:
            track_id = _coerce_track_id(raw)
            if track_id is not None:
                mapping[track_id] = stable_id
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
    track_to_stable: dict[int, str] | None = None,
    observations_by_stable: dict[str, int] | None = None,
    summary_players: dict[str, dict] | None = None,
    ball_summary: dict | None = None,
    positions_source: str | None = None,
    positions_truncated: bool = False,
    fps: float | None = None,
) -> GameStats:
    """Assemble the box score for one processed video.

    When `roster` (jersey number -> roster player) and `our_team_side` are given,
    tracks on that side are tied to the scout's real players by number.

    `track_to_stable` turns v2 output into real players: v2 emits many segmented
    `track_id`s per person, so players are grouped by `stable_player_id`. Same-team
    same-number fragments are then merged, and `observations_by_stable` (frames
    per player) picks the five most-present per team as the ten on court. Without
    `track_to_stable` (v1), grouping stays per `track_id` exactly as before.

    `summary_players` (stable id -> entry of player_summary.json) is the newer,
    complete source for the same facts plus time on screen, distance and jersey
    evidence; when given it supplies the player list, ids and observations.
    """

    teams_of = team_by_track(teams_document)
    numbers_of = number_by_track(numbers_document, stable_to_track=stable_to_track)
    numbers_stable = number_by_stable(numbers_document)
    reads_stable, reads_track = jersey_reads(numbers_document)
    summary_players = summary_players or {}
    track_to_stable = dict(track_to_stable or {})
    if summary_players:
        for track_id, stable_id in track_to_stable_from_summary(summary_players).items():
            track_to_stable.setdefault(track_id, stable_id)
    observations_by_stable = observations_by_stable or {}

    def identity(track_id: int | None, stable_id: str | None = None):
        if stable_id is None and track_id is not None:
            stable_id = track_to_stable.get(track_id)
        return (stable_id, stable_id) if stable_id is not None else (track_id, None)

    def jersey_for(track_id: int | None, stable_id: str | None) -> str | None:
        if stable_id is not None:
            number = numbers_stable.get(stable_id)
            if number is None:
                jersey = (summary_players.get(stable_id) or {}).get("jersey") or {}
                if jersey.get("status") == "confirmed" and _valid_number(jersey.get("number")):
                    number = str(jersey["number"])
            return number
        return numbers_of.get(track_id) if track_id is not None else None

    players: dict = {}
    teams: dict[int, TeamStats] = {}
    shot_rows: list[dict] = []

    raw_shots = (shots_document or {}).get("shots") or []
    unattributed = 0
    unprojected = 0
    outcomes = {MADE: 0, MISSED: 0, UNRESOLVED: 0}
    unresolved_scored = 0
    needing_review = 0

    def player_for(track_id: int | None, team_id: int | None, stable_id: str | None = None):
        key, stable_id = identity(track_id, stable_id)
        player = players.get(key)
        if player is None:
            info = summary_players.get(stable_id) if stable_id else None
            info = info or {}
            if team_id is None:
                team_id = info.get("team_id")
            if track_id is None:
                listed = info.get("track_ids") or []
                track_id = _coerce_track_id(listed[0]) if listed else None
            observations = info.get("frames_observed")
            if observations is None:
                observations = observations_by_stable.get(stable_id, 0) if stable_id else 0
            seconds = info.get("seconds_observed")
            if seconds is None and fps and observations:
                seconds = round(observations / fps, 2)
            read = (reads_stable.get(stable_id) if stable_id else reads_track.get(track_id)) or {}
            jersey = info.get("jersey") or {}
            player = PlayerStats(
                track_id=-1 if track_id is None else track_id,
                stable_player_id=stable_id,
                team_id=None if team_id is None else int(team_id),
                jersey_number=jersey_for(track_id, stable_id),
                observations=int(observations or 0),
                seconds_observed=seconds,
                distance_m=info.get("distance_m"),
                jersey_status=jersey.get("status") or read.get("status") or "unknown",
                jersey_support_count=int(
                    jersey.get("support_count") or read.get("support_count") or 0
                ),
                team_agreement=info.get("team_agreement"),
            )
            players[key] = player
        elif player.team_id is None and team_id is not None:
            player.team_id = int(team_id)
        return player

    for shot in raw_shots:
        court_xy = shot.get("shot_origin_court_xy_m")
        bucket = outcome_bucket(shot)
        outcomes[bucket] += 1
        made = bucket == MADE

        # A shot the homography could not place cannot be scored, because its
        # point value depends on where it was taken from.
        if not court_xy or len(court_xy) < 2 or not is_on_court((court_xy[0], court_xy[1])):
            unprojected += 1
            continue

        location = describe_shot((float(court_xy[0]), float(court_xy[1])))
        track_id = _coerce_track_id(shot.get("shooter_track_id"))
        # The pipeline names the stable shooter directly; the track map is only
        # the fallback for jobs that predate that field.
        stable_id = shot.get("shooter_stable_player_id")
        stable_id = None if stable_id is None else str(stable_id)
        if stable_id is None and track_id is not None:
            stable_id = track_to_stable.get(track_id)
        team_id = shot.get("shooter_team_id")
        if team_id is None and track_id is not None:
            team_id = teams_of.get(track_id)
        if team_id is None and stable_id is not None:
            team_id = (summary_players.get(stable_id) or {}).get("team_id")

        def record(tally: ShotTally) -> None:
            if bucket == UNRESOLVED:
                tally.add_unresolved(zone=location.zone)
            else:
                tally.add(
                    made=made,
                    points=location.points,
                    zone=location.zone,
                    shot_type=shot.get("shot_type"),
                )

        if track_id is None and stable_id is None:
            unattributed += 1
        else:
            player = player_for(track_id, team_id, stable_id)
            stable_id = player.stable_player_id
            record(player.shooting)

        # A shot with a team but no shooter still counts for the team.
        if team_id is not None:
            team = teams.setdefault(int(team_id), TeamStats(team_id=int(team_id)))
            record(team.shooting)

        if bucket == UNRESOLVED:
            unresolved_scored += 1
        if shot.get("needs_review") is True:
            needing_review += 1

        shot_rows.append(
            {
                "shot_id": shot.get("event_id"),
                "track_id": track_id,
                "stable_player_id": stable_id,
                "team_id": None if team_id is None else int(team_id),
                "jersey_number": jersey_for(track_id, stable_id),
                "made": made,
                # The raw outcome is kept so a shot chart can tell a miss (draw
                # red) from an undetermined result (draw neither), which the
                # made boolean alone collapses together.
                "outcome": shot.get("outcome"),
                # "detected" / "inferred" (a make read from the ball's path past
                # the rim) / "timeout" / "unresolved"; an inferred make is counted
                # as made, and this is how a client can still mark it.
                "outcome_confidence": shot.get("outcome_confidence"),
                "outcome_source": shot.get("outcome_source"),
                "points": location.points,
                "zone": location.zone,
                "distance_m": location.distance_m,
                "court_x_m": round(float(court_xy[0]), 2),
                "court_y_m": round(float(court_xy[1]), 2),
                "timestamp_seconds": shot.get("start_timestamp_seconds"),
                "release_timestamp_seconds": shot.get("release_timestamp_seconds"),
                "resolved_timestamp_seconds": shot.get("resolved_timestamp_seconds"),
                "shot_type": shot.get("shot_type"),
                # How the shooter was chosen. "nearest_player_bbox_to_shot_anchor"
                # is a proximity guess, so a client may want to flag it.
                "attribution": shot.get("shooter_attribution_method"),
                "shooter_candidates": shot.get("shooter_candidates") or [],
                # The pipeline's own verdict that a person should check this shot.
                "needs_review": shot.get("needs_review"),
            }
        )

    # Every tracked player appears, not only those who shot, so the interface can
    # list a full squad rather than only scorers.
    if summary_players:
        for stable_id, info in sorted(summary_players.items()):
            player = player_for(None, info.get("team_id"), stable_id)
            if player.team_id is None:
                # No dominant team in the summary: fall back to the side most of
                # this player's tracks were assigned to.
                votes: dict[int, int] = {}
                for raw in info.get("track_ids") or []:
                    side = teams_of.get(_coerce_track_id(raw))
                    if side is not None:
                        votes[side] = votes.get(side, 0) + 1
                if votes:
                    player.team_id = max(votes, key=votes.get)
        for team_id in sorted(set(teams_of.values())):
            teams.setdefault(team_id, TeamStats(team_id=team_id))
        for player in players.values():
            if player.team_id is not None:
                teams.setdefault(player.team_id, TeamStats(team_id=player.team_id))
    else:
        for track_id, team_id in sorted(teams_of.items()):
            player_for(track_id, team_id)
            teams.setdefault(team_id, TeamStats(team_id=team_id))

    # v2 fragments one player into several stable ids that still read the same
    # number; merge those on (team, confirmed number) so a player is counted once.
    # The shots were tagged with the pre-merge stable id, so re-point them at the
    # surviving player — otherwise a per-player chart would miss a sibling
    # fragment's shots and the shot's roster label would not resolve.
    if track_to_stable:
        players, fragment_remap = _merge_number_fragments(players)
        if fragment_remap:
            for row in shot_rows:
                primary = fragment_remap.get(row["stable_player_id"])
                if primary is not None:
                    row["stable_player_id"] = primary

    # The ten on court are the five most-tracked players per team.
    _mark_on_court(players)

    for player in players.values():
        if player.team_id is not None and player.team_id in teams:
            teams[player.team_id].player_count += 1

    for player in players.values():
        _link_roster(player, roster=roster, our_team_side=our_team_side)

    # Stamp the resolved roster identity onto shot rows so a chart can label a
    # marker without a second lookup. Join on the shot's player key.
    roster_of = {
        (p.stable_player_id if p.stable_player_id is not None else p.track_id): (
            p.roster_player_id,
            p.roster_name,
        )
        for p in players.values()
    }
    for row in shot_rows:
        key = row["stable_player_id"] if row["stable_player_id"] is not None else row["track_id"]
        row["roster_player_id"], row["roster_name"] = roster_of.get(key, (None, None))

    identified = sum(1 for player in players.values() if player.jersey_number)
    linked_count = sum(1 for player in players.values() if player.roster_player_id)
    on_court_count = sum(1 for player in players.values() if player.on_court)
    ordered = sorted(
        players.values(),
        key=lambda p: (not p.on_court, p.team_id if p.team_id is not None else 99, -p.observations),
    )
    ball_frames = (ball_summary or {}).get("frames") or 0
    ball_visibility = (
        round(100.0 * (ball_summary or {}).get("detected_frames", 0) / ball_frames, 1)
        if ball_frames > 0
        else None
    )
    measures = ["shooting"]
    if summary_players:
        measures += ["seconds_observed", "distance"]
    return GameStats(
        teams=[teams[key] for key in sorted(teams)],
        players=ordered,
        shots=shot_rows,
        coverage={
            "shots_detected": len(raw_shots),
            "shots_scored": len(shot_rows),
            "shots_without_court_position": unprojected,
            "shots_without_shooter": unattributed,
            # Outcomes over every detected shot; `unresolved_attempts` counts only
            # the located ones, i.e. the ones the per-player tallies could place.
            "shots_by_outcome": dict(outcomes),
            "unresolved_attempts": unresolved_scored,
            "shots_needing_review": needing_review,
            "players_tracked": len(players),
            # The five most-present players per team: the ten actually on court,
            # versus refs/bench/fragments that also get tracked.
            "players_on_court": on_court_count,
            # TODO(jersey-numbers): low today; UI can watch this ratio to decide
            # whether to show numbers or fall back to "Player N".
            "players_with_jersey_number": identified,
            # How many tracks were tied to a real roster player (own team only).
            "players_linked_to_roster": linked_count,
            # Where players and time on screen came from, and whether that source
            # was cut short (only the legacy per-frame file has a row cap).
            "positions_source": positions_source,
            "positions_truncated": bool(positions_truncated),
            # Share of frames where the ball was detected: low values mean made
            # and missed shots are being guessed from little evidence.
            "ball_visibility_pct": ball_visibility,
            # Stated plainly so the interface never implies a complete stat line.
            "measures": measures,
            "not_measured": list(NOT_MEASURED),
        },
    )


def _merge_number_fragments(players: dict) -> tuple[dict, dict]:
    """Collapse players that share a team and a confirmed number into one.

    v2 can split a single player across segments into several stable ids that all
    read, say, #7 on team 1. Those are the same person; merge their shooting and
    observations so the box score counts them once. Players with no number, or a
    unique (team, number), are left untouched.

    Returns the merged players plus a remap of each merged-away player key to the
    surviving one, so shot rows tagged with the old id can be re-pointed.
    """

    merged: dict = {}
    remap: dict = {}
    by_number: dict[tuple[int, str], object] = {}
    for key, player in players.items():
        if player.jersey_number is None or player.team_id is None:
            merged[key] = player
            continue
        number_key = (player.team_id, player.jersey_number)
        primary_key = by_number.get(number_key)
        if primary_key is None:
            by_number[number_key] = key
            merged[key] = player
            continue
        remap[key] = primary_key
        primary = merged[primary_key]
        primary.observations += player.observations
        if player.seconds_observed is not None:
            primary.seconds_observed = round((primary.seconds_observed or 0.0) + player.seconds_observed, 2)
        if player.distance_m is not None:
            primary.distance_m = round((primary.distance_m or 0.0) + player.distance_m, 2)
        primary.jersey_support_count += player.jersey_support_count
        primary.shooting.merge(player.shooting)
    return merged, remap


def _mark_on_court(players: dict) -> None:
    """Flag the five most-tracked players per team as on court (ten total).

    Only meaningful when observations are known (v2); with no observation counts
    nothing is flagged and the client falls back to listing everyone.
    """

    by_team: dict[int, list[PlayerStats]] = {}
    for player in players.values():
        if player.team_id is None or player.observations <= 0:
            continue
        by_team.setdefault(player.team_id, []).append(player)
    for roster in by_team.values():
        roster.sort(key=lambda p: p.observations, reverse=True)
        for player in roster[:5]:
            player.on_court = True


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
    stable_player_id: str | None = None,
    roster: dict[str, dict] | None = None,
    our_team_side: int | None = None,
    stable_to_track: dict[str, int] | None = None,
    track_to_stable: dict[int, str] | None = None,
    observations_by_stable: dict[str, int] | None = None,
    **identity_context,
) -> dict:
    """Every located shot as a court marker, grouped by the player who took it.

    Built on top of the box score so a marker is scored by exactly the same
    rules as the totals it must agree with. Each marker carries `made` and
    `result` for colouring (made green, missed red) and its court position in
    metres; `court` ships the geometry needed to draw the floor and arc under
    them. Narrow to one player with `stable_player_id` (v2) or `track_id` (v1).
    """

    game = build_game_stats(
        shots_document=shots_document,
        teams_document=teams_document,
        numbers_document=numbers_document,
        roster=roster,
        our_team_side=our_team_side,
        stable_to_track=stable_to_track,
        track_to_stable=track_to_stable,
        observations_by_stable=observations_by_stable,
        **identity_context,
    ).to_dict()

    def player_key(entry: dict):
        return entry["stable_player_id"] if entry.get("stable_player_id") is not None else entry["track_id"]

    display_of = {player_key(p): p["display_name"] for p in game["players"]}
    markers: list[dict] = []
    per_player: dict = {}

    for row in game["shots"]:
        if track_id is not None and row["track_id"] != track_id:
            continue
        if stable_player_id is not None and row.get("stable_player_id") != stable_player_id:
            continue
        marker = {
            "shot_id": row["shot_id"],
            "track_id": row["track_id"],
            "stable_player_id": row.get("stable_player_id"),
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
            "outcome_confidence": row["outcome_confidence"],
            "needs_review": row["needs_review"],
        }
        markers.append(marker)
        if row["track_id"] is not None or row["stable_player_id"] is not None:
            key = player_key(row)
            bucket = per_player.setdefault(
                key,
                {
                    "track_id": row["track_id"],
                    "stable_player_id": row.get("stable_player_id"),
                    "team_id": row["team_id"],
                    "jersey_number": row["jersey_number"],
                    "display_name": display_of.get(key, f"Player {row['track_id']}"),
                    "shots": [],
                },
            )
            bucket["shots"].append(marker)

    return {
        "court": court_reference(),
        "shots": markers,
        "players": [per_player[key] for key in sorted(per_player, key=str)],
        "coverage": {
            **game["coverage"],
            "shots_charted": len(markers),
            "filtered_to_track_id": track_id,
            "filtered_to_stable_player_id": stable_player_id,
        },
    }


def build_shot_events(
    *,
    shots_document: dict | None,
    teams_document: dict | None,
    numbers_document: dict | None,
    track_to_stable: dict[int, str] | None = None,
    summary_players: dict[str, dict] | None = None,
) -> list[dict]:
    """Every detected shot as a timeline event, located or not.

    Unlike the box score this keeps shots the homography could not place (their
    court position is null): a timeline of what happened should not lose them.
    The time is the moment of release when the pipeline found one, otherwise the
    detector's start of the shot.
    """

    teams_of = team_by_track(teams_document)
    numbers_stable = number_by_stable(numbers_document)
    numbers_of = number_by_track(numbers_document)
    track_to_stable = track_to_stable or {}
    events: list[dict] = []
    for shot in (shots_document or {}).get("shots") or []:
        track_id = _coerce_track_id(shot.get("shooter_track_id"))
        stable_id = shot.get("shooter_stable_player_id")
        stable_id = None if stable_id is None else str(stable_id)
        if stable_id is None and track_id is not None:
            stable_id = track_to_stable.get(track_id)
        team_id = shot.get("shooter_team_id")
        if team_id is None and track_id is not None:
            team_id = teams_of.get(track_id)
        jersey = numbers_stable.get(stable_id) if stable_id is not None else numbers_of.get(track_id)
        if jersey is None and stable_id is not None:
            read = (summary_players or {}).get(stable_id, {}).get("jersey") or {}
            if read.get("status") == "confirmed" and _valid_number(read.get("number")):
                jersey = str(read["number"])

        court_xy = shot.get("shot_origin_court_xy_m")
        located = bool(court_xy) and len(court_xy) >= 2 and is_on_court((court_xy[0], court_xy[1]))
        release = shot.get("release_timestamp_seconds")
        events.append(
            {
                "type": "shot",
                "event_id": shot.get("event_id"),
                "timestamp_seconds": release if release is not None else shot.get("start_timestamp_seconds"),
                "end_timestamp_seconds": shot.get("end_timestamp_seconds"),
                "outcome": outcome_bucket(shot),
                "outcome_confidence": shot.get("outcome_confidence"),
                "shot_type": shot.get("shot_type"),
                "stable_player_id": stable_id,
                "team_id": None if team_id is None else int(team_id),
                "jersey_number": jersey,
                "court_x_m": round(float(court_xy[0]), 2) if located else None,
                "court_y_m": round(float(court_xy[1]), 2) if located else None,
                "needs_review": shot.get("needs_review"),
            }
        )
    return events


def build_possession_events(rows: list[dict], *, fps: float | None) -> list[dict]:
    """Experimental ball-handler changes, from the per-frame possession output.

    Only frames the pipeline CONFIRMED a holder on count; a change of confirmed
    holder is a `pass` when both are on the same team and a `possession_transfer`
    otherwise. These are a hint for a timeline and feed no statistic.
    """

    events: list[dict] = []
    previous: dict | None = None
    for row in sorted(rows, key=lambda r: r.get("frame_index") or 0):
        if row.get("status") != "confirmed":
            continue
        holder = row.get("stable_player_id")
        if holder is None:
            holder = row.get("player_track_id")
        if holder is None:
            continue
        if previous is not None and holder != previous["holder"]:
            timestamp = row.get("timestamp_seconds")
            if timestamp is None and fps and row.get("frame_index") is not None:
                timestamp = round(row["frame_index"] / fps, 3)
            if timestamp is not None:
                from_team, to_team = previous["team_id"], row.get("team_id")
                events.append(
                    {
                        "type": "pass" if from_team is not None and from_team == to_team else "possession_transfer",
                        "experimental": True,
                        "event_id": f"possession-{row.get('frame_index')}",
                        "timestamp_seconds": timestamp,
                        "end_timestamp_seconds": None,
                        "from_stable_player_id": previous["stable_player_id"],
                        "to_stable_player_id": row.get("stable_player_id"),
                        "from_team_id": from_team,
                        "to_team_id": to_team,
                        "confidence": row.get("confidence"),
                    }
                )
        previous = {
            "holder": holder,
            "stable_player_id": row.get("stable_player_id"),
            "team_id": row.get("team_id"),
        }
    return events
