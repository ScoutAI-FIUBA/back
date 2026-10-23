"""Read a finished job's output and answer the questions the interface asks.

    GetGameStatsUseCase       what happened in the game
    GetCourtPositionsUseCase  where players were on the court
    GetEventsUseCase          the game as a timeline of events

All read the small structured files the pipeline wrote and do the interpretation
here, so the interface receives finished answers rather than raw analysis output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.application.jobs.errors import (
    JOB_NOT_FINISHED,
    JOB_NOT_FOUND,
    RESULTS_NOT_AVAILABLE,
    JobError,
)
from src.application.jobs.ports import JobRepositoryPort, TeamAccessPort
from src.application.stats.aggregation import (
    build_game_stats,
    build_possession_events,
    build_shot_chart,
    build_shot_events,
    build_v3_events,
    number_by_stable,
    number_by_track,
    outcome_bucket,
    summary_players_by_stable,
    team_by_track,
    track_to_stable_from_summary,
)
from src.application.stats.ports import ArtifactReadError, ArtifactReaderPort, RosterReaderPort
from src.domain.stats.court import COURT_LENGTH_M, COURT_WIDTH_M, is_on_court, step_distance
from src.domain.stats.similarity import (
    FEATURE_VERSION,
    build_clip_features,
    feature_similarity,
    resample_rows,
    rows_from_player_paths,
)
from src.domain.jobs.entities import JobStatus

SHOTS_FILE = "projected_shots.json"
TEAMS_FILE = "teams.json"
NUMBERS_FILE = "numbers.json"
# Written by newer pipeline runs: one entry per stable player (ids, team, time on
# screen, distance, jersey evidence) and their court path at 5 Hz. Read first, so
# a whole game fits in a web request; the per-frame file below is the legacy
# fallback and is capped.
SUMMARY_FILE = "player_summary.json"
PATHS_FILE = "player_paths.jsonl"
RESULTS_FILE = "results.json"
POSSESSION_EVENTS_FILE = "possession_events.jsonl"
POSSESSION_V3_FILE = "possession_events_v3.jsonl"
POSITIONS_SOURCE_SUMMARY = "player_summary"
POSITIONS_SOURCE_TRACKS = "projected_tracks"
# The two pipelines name their position output differently, and use a different
# key for the player identifier. A caller should not have to know which pipeline
# produced a job, so both are accepted.
POSITIONS_FILES = ("projected_tracks.jsonl", "player_positions.jsonl")
TRACK_ID_KEYS = ("track_id", "player_id")

# Upper bound on position records read for one response. A ten-second clip
# produces ~120; a full game at the same rate would be far more, and a web
# request must not try to hold all of it.
MAX_POSITION_RECORDS = 20_000
# One path line per player, so a few hundred is already far above any game.
MAX_PATH_LINES = 500
# Possession output is one row per frame; a cap keeps a long game bounded.
MAX_POSSESSION_RECORDS = 60_000
# Most events one /events response carries.
MAX_EVENTS = 500


def roster_by_number(players: list) -> dict[str, dict]:
    """`jersey number -> roster player` for one team.

    A number worn by two players on the same team is dropped rather than guessed
    at: linking a shot to the wrong player is worse than leaving it anonymous.
    """

    seen: dict[str, int] = {}
    mapping: dict[str, dict] = {}
    for player in players:
        number = getattr(player, "jersey_number", None)
        if not number:
            continue
        seen[number] = seen.get(number, 0) + 1
        mapping[number] = {
            "player_id": player.id,
            "name": f"{player.first_name} {player.last_name}".strip(),
        }
    return {number: value for number, value in mapping.items() if seen[number] == 1}


def _numbers_need_stable_map(numbers_document: dict | None) -> bool:
    """True only when numbers are the v2 shape with at least one confirmed read.

    Lets the game-stats read skip the extra projected-tracks fetch for v1 output
    and for v2 output that confirmed nothing (the common case today).
    """

    if not numbers_document:
        return False
    return any(
        player.get("status") == "confirmed" and player.get("number") not in (None, "", "unknown")
        for player in numbers_document.get("players") or []
    )


def stable_to_track_from_rows(rows: list[dict]) -> dict[str, int]:
    """`stable_player_id -> track_id`, from projected-track rows that carry both."""

    mapping: dict[str, int] = {}
    for row in rows:
        stable_id = row.get("stable_player_id")
        track_id = row.get("track_id", row.get("player_id"))
        if stable_id is None or track_id is None:
            continue
        try:
            mapping[str(stable_id)] = int(track_id)
        except (TypeError, ValueError):
            continue
    return mapping


def track_to_stable_from_rows(rows: list[dict]) -> dict[int, str]:
    """`track_id -> stable_player_id`, for grouping v2's many segmented tracks."""

    mapping: dict[int, str] = {}
    for row in rows:
        stable_id = row.get("stable_player_id")
        track_id = row.get("track_id", row.get("player_id"))
        if stable_id is None or track_id is None:
            continue
        try:
            mapping[int(track_id)] = str(stable_id)
        except (TypeError, ValueError):
            continue
    return mapping


def observations_by_stable_from_rows(rows: list[dict]) -> dict[str, int]:
    """`stable_player_id -> frames tracked`, to rank who was actually on court."""

    counts: dict[str, int] = {}
    for row in rows:
        stable_id = row.get("stable_player_id")
        if stable_id is not None:
            counts[str(stable_id)] = counts.get(str(stable_id), 0) + 1
    return counts


def _is_v2_output(teams_document: dict | None, numbers_document: dict | None) -> bool:
    """Whether the output is the v2 (SAM 3.1) shape that groups by stable id."""

    return bool(
        (teams_document or {}).get("assignments_by_track_id") is not None
        or (numbers_document or {}).get("players") is not None
    )


@dataclass
class _Identity:
    """Who the players are, from the best source the job has."""

    track_to_stable: dict[int, str] = field(default_factory=dict)
    observations: dict[str, int] = field(default_factory=dict)
    summary_players: dict[str, dict] = field(default_factory=dict)
    summary_document: dict | None = None
    positions_source: str | None = None
    positions_truncated: bool = False


def read_summary(artifacts: "ArtifactReaderPort", results_key: str) -> dict | None:
    """player_summary.json when the job has a usable one, else None.

    An unreadable or oversized summary is treated as absent: the legacy per-frame
    file can still answer, so a bad optional artifact should not fail the request.
    """

    try:
        document = artifacts.read_json(results_key=results_key, filename=SUMMARY_FILE)
    except ArtifactReadError:
        return None
    if not document or not isinstance(document.get("players"), list) or not document["players"]:
        return None
    return document


def read_video_info(artifacts: "ArtifactReaderPort", results_key: str) -> dict:
    """`{fps, duration_seconds}` from results.json's `video` block; None when unknown."""

    try:
        document = artifacts.read_json(results_key=results_key, filename=RESULTS_FILE)
    except ArtifactReadError:
        document = None
    video = (document or {}).get("video")
    video = video if isinstance(video, dict) else {}

    def number(value):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None

    return {"fps": number(video.get("fps")), "duration_seconds": number(video.get("duration_seconds"))}


def _load_identity(
    artifacts: "ArtifactReaderPort",
    results_key: str,
    teams_document: dict | None,
    numbers_document: dict | None,
) -> _Identity:
    """Player ids, observations and the source they came from.

    Prefers player_summary.json (complete for any game length). Otherwise, for v2
    output only, reads the capped per-frame projected tracks and reports when the
    cap was hit. v1 jobs skip both reads.
    """

    summary = read_summary(artifacts, results_key)
    if summary is not None:
        players = summary_players_by_stable(summary)
        return _Identity(
            track_to_stable=track_to_stable_from_summary(players),
            observations={
                stable_id: int(entry.get("frames_observed") or 0)
                for stable_id, entry in players.items()
            },
            summary_players=players,
            summary_document=summary,
            positions_source=POSITIONS_SOURCE_SUMMARY,
        )
    if not _is_v2_output(teams_document, numbers_document):
        return _Identity()
    try:
        rows = read_position_rows(artifacts, results_key)
    except ArtifactReadError:
        return _Identity()
    return _Identity(
        track_to_stable=track_to_stable_from_rows(rows),
        observations=observations_by_stable_from_rows(rows),
        positions_source=POSITIONS_SOURCE_TRACKS if rows else None,
        positions_truncated=len(rows) >= MAX_POSITION_RECORDS,
    )


def _identity_kwargs(identity: _Identity, video: dict) -> dict:
    """The identity-related arguments `build_game_stats` takes, from one lookup."""

    return {
        "track_to_stable": identity.track_to_stable,
        "observations_by_stable": identity.observations,
        "summary_players": identity.summary_players,
        "ball_summary": (identity.summary_document or {}).get("ball"),
        "positions_source": identity.positions_source,
        "positions_truncated": identity.positions_truncated,
        "fps": video.get("fps") or (identity.summary_document or {}).get("fps"),
    }


def read_position_rows(artifacts: "ArtifactReaderPort", results_key: str) -> list[dict]:
    """Projected-track rows from whichever position file the pipeline wrote."""

    for candidate in POSITIONS_FILES:
        rows = artifacts.read_jsonl(
            results_key=results_key, filename=candidate, max_lines=MAX_POSITION_RECORDS
        )
        if rows:
            return rows
    return []


class _FinishedJobLoader:
    """Shared guard: the caller may see this job, and it has finished."""

    def __init__(self, *, jobs: JobRepositoryPort, team_access: TeamAccessPort) -> None:
        self._jobs = jobs
        self._team_access = team_access

    def load(self, *, user_id: str, team_id: str, job_id: str):
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        job = self._jobs.get_by_id(job_id=job_id, team_id=team_id)
        if job is None:
            raise JobError(code=JOB_NOT_FOUND, message="Job not found.")
        if job.status is not JobStatus.DONE:
            raise JobError(
                code=JOB_NOT_FINISHED,
                message=f"Job is {job.status.value}; statistics are not available yet.",
            )
        if not job.results_key:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message="Job recorded no results location.")
        return job


class GetGameStatsUseCase:
    """The box score for one processed video."""

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
        roster: RosterReaderPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts
        self._roster = roster

    def execute(self, *, user_id: str, team_id: str, job_id: str) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        try:
            shots = self._artifacts.read_json(results_key=key, filename=SHOTS_FILE)
            teams = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        if shots is None and teams is None:
            raise JobError(
                code=RESULTS_NOT_AVAILABLE,
                message="This job produced no analysis output.",
            )

        roster = self._roster_for(job, user_id=user_id)
        identity = _load_identity(self._artifacts, key, teams, numbers)
        video = read_video_info(self._artifacts, key)
        stats = build_game_stats(
            shots_document=shots,
            teams_document=teams,
            numbers_document=numbers,
            roster=roster,
            our_team_side=job.our_team_side,
            **_identity_kwargs(identity, video),
        )
        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "our_team_side": job.our_team_side,
            "video": video,
            **stats.to_dict(),
        }

    def _roster_for(self, job, *, user_id: str) -> dict[str, dict] | None:
        if job.our_team_side is None:
            return None
        players = self._roster.list_by_owner_and_team(owner_user_id=user_id, team_id=job.team_id)
        return roster_by_number(players)


class GetShotChartUseCase:
    """Every located shot as a court marker, for a shot chart.

    The same shots the box score counts, reshaped for drawing: each carries its
    court position and whether it went in, and the response ships the court
    geometry needed to render the floor and three-point line under them.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
        roster: RosterReaderPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts
        self._roster = roster

    def execute(
        self,
        *,
        user_id: str,
        team_id: str,
        job_id: str,
        track_id: int | None = None,
        stable_player_id: str | None = None,
    ) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        try:
            shots = self._artifacts.read_json(results_key=key, filename=SHOTS_FILE)
            teams = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        if shots is None and teams is None:
            raise JobError(
                code=RESULTS_NOT_AVAILABLE,
                message="This job produced no analysis output.",
            )

        roster = None
        if job.our_team_side is not None:
            roster = roster_by_number(
                self._roster.list_by_owner_and_team(owner_user_id=user_id, team_id=job.team_id)
            )
        identity = _load_identity(self._artifacts, key, teams, numbers)
        video = read_video_info(self._artifacts, key)
        chart = build_shot_chart(
            shots_document=shots,
            teams_document=teams,
            numbers_document=numbers,
            track_id=track_id,
            stable_player_id=stable_player_id,
            roster=roster,
            our_team_side=job.our_team_side,
            **_identity_kwargs(identity, video),
        )
        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "our_team_side": job.our_team_side,
            **chart,
        }


class GetTeamSidesUseCase:
    """Break the two pipeline sides down so the scout can pick their own team.

    The pipeline labels players side 0 and side 1 with no idea which is which,
    and we do not read jersey colours. But we do know our own roster's numbers,
    so the side whose read numbers overlap our roster more is almost certainly
    ours — surfaced as a suggestion the scout confirms.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
        roster: RosterReaderPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts
        self._roster = roster

    def execute(self, *, user_id: str, team_id: str, job_id: str) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        try:
            teams = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        teams_of = team_by_track(teams)
        roster_numbers = set(
            roster_by_number(
                self._roster.list_by_owner_and_team(owner_user_id=user_id, team_id=job.team_id)
            )
        )

        # v2 reads jersey numbers against stable_player_id, not track_id, so a
        # side's numbers have to be gathered per player or they come back empty
        # even when every number is known. v1 keeps the track-level grouping.
        if _is_v2_output(teams, numbers):
            sides = self._sides_by_stable_player(key, teams_of, numbers)
        else:
            sides = self._sides_by_track(teams_of, numbers)

        for entry in sides.values():
            entry["numbers"] = sorted(set(entry["numbers"]))
            entry["roster_matches"] = sum(1 for n in entry["numbers"] if n in roster_numbers)

        ordered = [sides[side] for side in sorted(sides)]
        best = max(ordered, key=lambda e: e["roster_matches"], default=None)
        # Only a positive, unambiguous overlap is worth suggesting; ties or no
        # matches leave the choice entirely to the scout.
        suggested = None
        if best is not None and best["roster_matches"] > 0:
            top = [e for e in ordered if e["roster_matches"] == best["roster_matches"]]
            if len(top) == 1:
                suggested = best["team_side"]

        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "our_team_side": job.our_team_side,
            "suggested_team_side": suggested,
            "sides": ordered,
            "roster_numbers_known": len(roster_numbers),
        }

    def _sides_by_track(self, teams_of: dict[int, int], numbers: dict | None) -> dict[int, dict]:
        """v1 grouping: one track is one player, so count and read by track."""

        numbers_of = number_by_track(numbers)
        sides: dict[int, dict] = {}
        for track_id, side in teams_of.items():
            entry = sides.setdefault(side, {"team_side": side, "track_count": 0, "numbers": []})
            entry["track_count"] += 1
            number = numbers_of.get(track_id)
            if number is not None:
                entry["numbers"].append(number)
        return sides

    def _sides_by_stable_player(
        self, results_key: str, teams_of: dict[int, int], numbers: dict | None
    ) -> dict[int, dict]:
        """v2 grouping: collapse the many segmented tracks into stable players.

        Numbers live on stable_player_id, and each player appears as many
        segmented track_ids. Bridge the two through the projected tracks: assign
        each player to the side its tracks mostly fall on, then read its number.
        Without that bridge we fall back to track grouping so a side still shows.
        """

        summary = read_summary(self._artifacts, results_key)
        if summary is not None:
            track_to_stable = track_to_stable_from_summary(summary_players_by_stable(summary))
        else:
            try:
                rows = read_position_rows(self._artifacts, results_key)
            except ArtifactReadError:
                rows = []
            track_to_stable = track_to_stable_from_rows(rows)
        if not track_to_stable:
            return self._sides_by_track(teams_of, numbers)

        numbers_of_stable = number_by_stable(numbers)
        # One player's tracks can be split across sides by a mislabel; the side
        # most of its tracks fall on wins.
        side_votes: dict[str, dict[int, int]] = {}
        for track_id, side in teams_of.items():
            stable = track_to_stable.get(track_id)
            if stable is None:
                continue
            votes = side_votes.setdefault(stable, {})
            votes[side] = votes.get(side, 0) + 1

        sides: dict[int, dict] = {}
        for stable, votes in side_votes.items():
            side = max(votes, key=votes.get)
            entry = sides.setdefault(side, {"team_side": side, "track_count": 0, "numbers": []})
            # Distinct players, not segments, so the count reads like a lineup.
            entry["track_count"] += 1
            number = numbers_of_stable.get(stable)
            if number is not None:
                entry["numbers"].append(number)
        return sides


class GetSimilarClipsUseCase:
    """Rank other finished clips by how similar their play is to this one.

    Each clip is reduced to a spatial feature vector (shot locations + movement)
    the first time it is needed and cached on the job, so ranking is cheap in
    memory and never re-reads storage once warm. Similarity is on shape of play,
    never player identity, which is unreliable across clips.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._jobs = jobs
        self._artifacts = artifacts

    def execute(
        self,
        *,
        user_id: str,
        team_id: str,
        job_id: str,
        limit: int = 5,
        movement_weight: float = 0.5,
    ) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        target = self._features_for(job, team_id=team_id)
        if target is None:
            raise JobError(
                code=RESULTS_NOT_AVAILABLE,
                message="This job produced no analysis output to compare.",
            )

        results: list[dict] = []
        for other in self._jobs.list_done_by_team(team_id=team_id):
            if other.id == job.id:
                continue
            features = self._features_for(other, team_id=team_id)
            if features is None:
                continue
            similarity = feature_similarity(target, features, movement_weight=movement_weight)
            results.append(
                {
                    "job_id": other.id,
                    "video_id": other.video_id,
                    **similarity,
                }
            )

        results.sort(key=lambda row: row["score"], reverse=True)
        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "movement_weight": movement_weight,
            "results": results[: max(1, int(limit))],
            "candidates_compared": len(results),
        }

    def _features_for(self, job, *, team_id: str) -> dict | None:
        if isinstance(job.features, dict) and job.features.get("version") == FEATURE_VERSION:
            return job.features
        if not job.results_key:
            return None
        try:
            shots = self._artifacts.read_json(results_key=job.results_key, filename=SHOTS_FILE)
            position_rows = self._read_position_rows(job.results_key)
        except ArtifactReadError:
            return None
        if shots is None and not position_rows:
            return None
        features = build_clip_features(shots_document=shots, position_rows=position_rows)
        self._jobs.set_features(job_id=job.id, team_id=team_id, features=features)
        return features

    def _read_position_rows(self, results_key: str) -> list[dict]:
        """Positions at 5 Hz, from the player paths when present, else the legacy file."""

        summary = read_summary(self._artifacts, results_key)
        if summary is not None:
            paths = self._artifacts.read_jsonl(
                results_key=results_key, filename=PATHS_FILE, max_lines=MAX_PATH_LINES
            )
            if paths:
                return rows_from_player_paths(paths, fps=float(summary.get("fps") or 30.0))
        rows = read_position_rows(self._artifacts, results_key)
        fps = (summary or {}).get("fps") or read_video_info(self._artifacts, results_key)["fps"]
        return resample_rows(rows, fps=float(fps)) if fps else rows


class GetCourtPositionsUseCase:
    """Where each tracked player was on the court, in metres.

    Returns one path per player rather than the pipeline's per-frame rows, since
    that is what a court diagram or heatmap actually draws.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts

    def execute(
        self, *, user_id: str, team_id: str, job_id: str, sample_every: int = 1
    ) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        from_paths = self._from_player_paths(job, sample_every=sample_every)
        if from_paths is not None:
            return from_paths

        rows: list[dict] = []
        source_file: str | None = None
        try:
            for candidate in POSITIONS_FILES:
                rows = self._artifacts.read_jsonl(
                    results_key=key, filename=candidate, max_lines=MAX_POSITION_RECORDS
                )
                if rows:
                    source_file = candidate
                    break
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        try:
            teams_document = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers_document = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc
        teams_of = team_by_track(teams_document)
        numbers_of = number_by_track(numbers_document)
        numbers_stable = number_by_stable(numbers_document)

        sample_every = max(1, int(sample_every))
        paths: dict = {}
        movement: dict = {}
        discarded = 0
        seen_per_player: dict = {}

        for row in rows:
            court_xy = row.get("court_xy_m")
            track_id = next(
                (row[key_] for key_ in TRACK_ID_KEYS if row.get(key_) is not None), None
            )
            if track_id is None or not court_xy or len(court_xy) < 2:
                continue

            # Bad homography can throw a player far off the court; those points
            # would distort a heatmap badly, so they are dropped rather than drawn.
            if not is_on_court((court_xy[0], court_xy[1])):
                discarded += 1
                continue

            track_id = int(track_id)
            # v2 splits a player across many segmented track_ids but tags each row
            # with a stable_player_id; group the path by that so one player is one
            # path, not a dozen fragments. v1 rows have no stable id -> by track.
            stable_id = row.get("stable_player_id")
            pkey = str(stable_id) if stable_id is not None else track_id
            jersey = numbers_stable.get(str(stable_id)) if stable_id is not None else numbers_of.get(track_id)
            point = (float(court_xy[0]), float(court_xy[1]))
            path = paths.setdefault(
                pkey,
                {
                    "track_id": track_id,
                    "stable_player_id": stable_id,
                    # player_positions rows carry the team directly; the stats
                    # pipeline's rows do not, so fall back to the assignments file.
                    "team_id": row.get("team_id", teams_of.get(track_id)),
                    "jersey_number": jersey,
                    "positions": [],
                },
            )

            # Movement is accumulated over every on-court point, before sampling:
            # distance summed from a downsampled path would understate how far a
            # player actually ran.
            summary = movement.setdefault(
                pkey, {"samples": 0, "sum_x": 0.0, "sum_y": 0.0, "distance_m": 0.0, "prev": None}
            )
            if summary["prev"] is not None:
                summary["distance_m"] += step_distance(summary["prev"], point)
            summary["prev"] = point
            summary["samples"] += 1
            summary["sum_x"] += point[0]
            summary["sum_y"] += point[1]

            index = seen_per_player.get(pkey, 0)
            seen_per_player[pkey] = index + 1
            if index % sample_every:
                continue

            path["positions"].append(
                {
                    "frame_index": row.get("frame_index"),
                    "x_m": round(point[0], 2),
                    "y_m": round(point[1], 2),
                }
            )

        for pkey, path in paths.items():
            summary = movement[pkey]
            samples = summary["samples"]
            path["movement"] = {
                "samples": samples,
                "distance_m": round(summary["distance_m"], 2),
                "average_position": {
                    "x_m": round(summary["sum_x"] / samples, 2),
                    "y_m": round(summary["sum_y"] / samples, 2),
                },
            }

        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "court": {"length_m": COURT_LENGTH_M, "width_m": COURT_WIDTH_M},
            "players": [paths[key_] for key_ in sorted(paths, key=str)],
            "coverage": {
                "source_file": source_file,
                "records_read": len(rows),
                "records_off_court": discarded,
                "sample_every": sample_every,
                "truncated": len(rows) >= MAX_POSITION_RECORDS,
                # Same fact under the name the stats response uses; true means
                # the paths stop at the row cap and later play is missing.
                "positions_truncated": len(rows) >= MAX_POSITION_RECORDS,
                "positions_source": POSITIONS_SOURCE_TRACKS,
            },
        }

    def _from_player_paths(self, job, *, sample_every: int) -> dict | None:
        """Court paths from the 5 Hz player paths, or None when the job has none.

        Distance and average position come from the pipeline's summary, which saw
        every frame, so thinning the response with `sample_every` never changes
        them.
        """

        key = job.results_key
        summary = read_summary(self._artifacts, key)
        if summary is None:
            return None
        try:
            path_rows = self._artifacts.read_jsonl(
                results_key=key, filename=PATHS_FILE, max_lines=MAX_PATH_LINES
            )
        except ArtifactReadError:
            return None
        if not path_rows:
            return None

        try:
            teams_document = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers_document = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError:
            return None
        teams_of = team_by_track(teams_document)
        numbers_stable = number_by_stable(numbers_document)
        summary_players = summary_players_by_stable(summary)

        sample_every = max(1, int(sample_every))
        paths: dict = {}
        discarded = 0
        records = 0
        for line in path_rows:
            stable_id = line.get("stable_player_id")
            if stable_id is None:
                continue
            stable_id = str(stable_id)
            info = summary_players.get(stable_id) or {}
            listed = info.get("track_ids") or []
            jersey = info.get("jersey") or {}
            number = numbers_stable.get(stable_id)
            if number is None and jersey.get("status") == "confirmed" and jersey.get("number"):
                number = str(jersey["number"])
            team = line.get("team_id", info.get("team_id"))
            if team is None:
                votes = [teams_of[int(t)] for t in listed if int(t) in teams_of]
                team = max(set(votes), key=votes.count) if votes else None

            positions: list[dict] = []
            on_court: list[tuple[float, float]] = []
            for point in line.get("points") or []:
                if len(point) < 3:
                    continue
                xy = (float(point[1]), float(point[2]))
                if not is_on_court(xy):
                    discarded += 1
                    continue
                records += 1
                on_court.append(xy)
                if (len(on_court) - 1) % sample_every == 0:
                    positions.append(
                        {"frame_index": point[0], "x_m": round(xy[0], 2), "y_m": round(xy[1], 2)}
                    )

            average = info.get("avg_xy_m")
            if not average and on_court:
                average = [
                    sum(p[0] for p in on_court) / len(on_court),
                    sum(p[1] for p in on_court) / len(on_court),
                ]
            distance = info.get("distance_m")
            if distance is None:
                distance = sum(step_distance(a, b) for a, b in zip(on_court, on_court[1:]))
            paths[stable_id] = {
                "track_id": int(listed[0]) if listed else None,
                "stable_player_id": stable_id,
                "team_id": team,
                "jersey_number": number,
                "jersey_status": jersey.get("status") or "unknown",
                "seconds_observed": info.get("seconds_observed"),
                "positions": positions,
                "movement": {
                    "samples": len(on_court),
                    "distance_m": round(float(distance), 2),
                    "average_position": (
                        {"x_m": round(average[0], 2), "y_m": round(average[1], 2)}
                        if average
                        else None
                    ),
                },
            }

        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "court": {"length_m": COURT_LENGTH_M, "width_m": COURT_WIDTH_M},
            "players": [paths[key_] for key_ in sorted(paths)],
            "coverage": {
                "source_file": PATHS_FILE,
                "records_read": records + discarded,
                "records_off_court": discarded,
                "sample_every": sample_every,
                "truncated": False,
                "positions_truncated": False,
                "positions_source": POSITIONS_SOURCE_SUMMARY,
                "source_hz": 5,
            },
        }


class GetEventsUseCase:
    """The game as a timeline: every shot, plus experimental possession changes.

    Shots come from the same detection the box score counts. Possession events are
    read only when the pipeline wrote them, are flagged `experimental`, and are
    never summed into any total.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts

    def execute(self, *, user_id: str, team_id: str, job_id: str) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        try:
            shots = self._artifacts.read_json(results_key=key, filename=SHOTS_FILE)
            teams = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        if shots is None and teams is None:
            raise JobError(
                code=RESULTS_NOT_AVAILABLE,
                message="This job produced no analysis output.",
            )

        summary = read_summary(self._artifacts, key)
        summary_players = summary_players_by_stable(summary) if summary else {}
        track_to_stable = track_to_stable_from_summary(summary_players)
        # Only jobs whose shots carry no stable shooter need the legacy track map.
        needs_map = not summary_players and any(
            shot.get("shooter_stable_player_id") is None and shot.get("shooter_track_id") is not None
            for shot in (shots or {}).get("shots") or []
        )
        if needs_map:
            track_to_stable = _load_identity(self._artifacts, key, teams, numbers).track_to_stable
        video = read_video_info(self._artifacts, key)
        shot_events = build_shot_events(
            shots_document=shots,
            teams_document=teams,
            numbers_document=numbers,
            track_to_stable=track_to_stable,
            summary_players=summary_players,
        )

        possession_events, possession_truncated, possession_source = self._possession_events(key, video["fps"])

        # Shots are the dependable part, so they win the room when over the cap.
        shot_events = shot_events[:MAX_EVENTS]
        possession_events = possession_events[: MAX_EVENTS - len(shot_events)]
        events = sorted(
            [*shot_events, *possession_events],
            key=lambda event: (
                event["timestamp_seconds"] is None,
                event["timestamp_seconds"] or 0.0,
                event["type"] != "shot",
                str(event["event_id"]),
            ),
        )
        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "video": video,
            "events": events,
            "coverage": {
                "shot_events": len(shot_events),
                "experimental_events": len(possession_events),
                "possession_input_truncated": possession_truncated,
                "possession_source": possession_source,
                "max_events": MAX_EVENTS,
            },
        }

    def _possession_events(self, results_key: str, fps: float | None) -> tuple[list[dict], bool, str]:
        """(events, input_was_cut_short, source); v3 first, legacy when v3 yields nothing."""

        v3_events, v3_truncated = self._read_possession(results_key, POSSESSION_V3_FILE, build_v3_events, fps)
        if v3_events:
            return v3_events, v3_truncated, "v3"
        events, truncated = self._read_possession(results_key, POSSESSION_EVENTS_FILE, build_possession_events, fps)
        events = [{**event, "source": "legacy_holder_change"} for event in events]
        return events, truncated, "legacy" if events else "none"

    def _read_possession(self, results_key: str, filename: str, build, fps: float | None) -> tuple[list[dict], bool]:
        try:
            rows = self._artifacts.read_jsonl(
                results_key=results_key,
                filename=filename,
                max_lines=MAX_POSSESSION_RECORDS,
            )
        except ArtifactReadError:
            # Optional and experimental: an oversized file must not hide the shots.
            return [], False
        return build(rows, fps=fps), len(rows) >= MAX_POSSESSION_RECORDS
