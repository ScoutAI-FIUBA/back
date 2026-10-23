from types import SimpleNamespace as NS

import pytest

from src.application.players.errors import PlayerError
from contextlib import contextmanager

from src.application.stats.player_analysis import (
    CatchUpPlayerAnalysisUseCase,
    GetPlayerAnalysisStatsUseCase,
    GetPlayerShotChartUseCase,
    ReplaceResult,
    SyncPlayerAnalysisUseCase,
    SyncResult,
    safe_sync,
)
from src.domain.jobs.entities import JobStatus


def _job(job_id="j1", status=JobStatus.DONE, side=1, key="results/j1/"):
    return NS(id=job_id, video_id="v1", team_id="t1", requested_by_user_id="u1", status=status,
              results_key=key, our_team_side=side)


class Jobs:
    def __init__(self, job, others=()):
        self.job, self.others = job, list(others)
        self.listed = []

    def get_by_id_unscoped(self, *, job_id):
        return self.job if self.job and self.job.id == job_id else None

    def list_by_video(self, *, video_id, team_id):
        return [*self.others, self.job]  # newest first

    def list_done_with_side_by_team(self, *, team_id, limit):
        self.listed.append((team_id, limit))
        return [NS(id="a"), NS(id="b")]


class Analysis:
    def __init__(self, status="ok"):
        self.calls = []
        self.superseded = []
        self.clock_reads = []
        self.started = []
        self.status = status

    def database_now(self):
        self.clock_reads.append(len(self.calls))  # how many replaces had happened when the clock was read
        return "db-clock"

    def mark_superseded(self, *, video_id, job_id, started=None):
        self.superseded.append((job_id, started))
        return True

    def replace_video(self, *, video_id, job_id, expected_side, games, shots, started=None):
        self.started.append(started)
        self.calls.append((video_id, games, shots, job_id, expected_side))
        return ReplaceResult(self.status)


def _shot(shot_id, **overrides):
    return {"shot_id": shot_id, "roster_player_id": "p-brown", "made": True, "outcome": "made", "points": 3,
            "zone": "corner_three", "distance_m": 7.0, "court_x_m": 23.8, "court_y_m": 14.4, **overrides}


STATS = {
    "players": [{"roster_player_id": "p-brown", "jersey_number": "7", "points": 3, "field_goals_made": 1,
                 "field_goals_attempted": 1, "three_point_made": 1, "three_point_attempted": 1},
                {"roster_player_id": None, "jersey_number": "27"}],
    "shots": [_shot(1),
              {"shot_id": 2, "roster_player_id": None, "made": False, "outcome": "missed", "points": 2,
               "distance_m": 5.0, "court_x_m": 5.0, "court_y_m": 7.0},
              {"shot_id": 3, "roster_player_id": "p-brown", "made": False, "outcome": "unknown", "points": 2,
               "court_x_m": None, "court_y_m": None}],
}


def _sync(stats, *, job=None, analysis=None):
    analysis = analysis or Analysis()
    result = SyncPlayerAnalysisUseCase(jobs=Jobs(job or _job()), game_stats=lambda **_: stats,
                                       analysis=analysis).execute("j1")
    return result, analysis


def test_only_roster_players_shots_with_a_court_position_are_kept():
    result, analysis = _sync(STATS)
    assert (result.status, result.shots_kept) == ("ok", 1)
    _, games, shots, job_id, expected_side = analysis.calls[0]
    assert (job_id, expected_side) == ("j1", 1)  # the replace re-checks both inside its lock
    assert [g.player_id for g in games] == ["p-brown"] and games[0].points == 3
    assert [(s.shot_id, s.outcome) for s in shots] == [(1, "made")]


def test_a_shot_carries_its_detail_columns():
    row = _shot(1, outcome_source="ball_path", outcome_confidence="inferred", release_timestamp_seconds=6.1,
                resolved_timestamp_seconds=7.2, shooter_candidates=[{"track_id": 3}], timestamp_seconds=6.0)
    _, analysis = _sync({"players": [], "shots": [row]})
    shot = analysis.calls[0][2][0]
    assert (shot.shot_value, shot.outcome_source, shot.outcome_confidence) == (3, "ball_path", "inferred")
    assert (shot.release_timestamp_seconds, shot.resolved_timestamp_seconds) == (6.1, 7.2)
    assert shot.shooter_candidates == [{"track_id": 3}]


def test_roster_ids_that_arrive_as_uuid_objects_are_kept_as_text():
    # The roster repository hands out UUID objects; the rows and the repository compare text.
    from uuid import UUID

    pid = UUID("00000000-0000-4000-8000-000000000001")
    _, analysis = _sync({"players": [{"roster_player_id": pid, "points": 1}], "shots": [_shot(1, roster_player_id=pid)]})
    _, games, shots, *_ = analysis.calls[0]
    assert [g.player_id for g in games] == [str(pid)] and [s.player_id for s in shots] == [str(pid)]


def test_an_unknown_outcome_confidence_is_dropped_instead_of_failing_the_row():
    _, analysis = _sync({"players": [], "shots": [_shot(1, outcome_confidence="mystery")]})
    assert analysis.calls[0][2][0].outcome_confidence is None


def test_two_tracks_linked_to_the_same_roster_player_add_up():
    # v1 output can hold two tracks that both confirmed the same jersey: one roster player.
    stats = {"players": [
        {"roster_player_id": "p7", "jersey_number": None, "seconds_observed": 10.0, "distance_m": 5.0, "points": 3,
         "field_goals_made": 1, "field_goals_attempted": 1, "three_point_made": 1, "three_point_attempted": 1},
        {"roster_player_id": "p7", "jersey_number": "7", "seconds_observed": 4.5, "distance_m": None, "points": 2,
         "field_goals_made": 1, "field_goals_attempted": 2, "two_point_made": 1, "two_point_attempted": 2,
         "unresolved_attempts": 1},
        {"roster_player_id": "p7", "jersey_number": "8", "seconds_observed": None},
    ], "shots": []}
    _, analysis = _sync(stats)
    games = analysis.calls[0][1]
    assert len(games) == 1
    game = games[0]
    assert (game.points, game.field_goals_made, game.field_goals_attempted) == (5, 2, 3)
    assert (game.two_point_made, game.two_point_attempted) == (1, 2)
    assert (game.three_point_made, game.three_point_attempted, game.unresolved_attempts) == (1, 1, 1)
    assert (game.seconds_on_screen, game.distance_m) == (14.5, 5.0)
    assert game.jersey_number == "7"  # the first non-null one, never overwritten by a later one


@pytest.mark.parametrize("override", [
    {"court_x_m": float("nan")}, {"court_y_m": float("inf")}, {"points": float("nan")}, {"points": None},
    {"points": 5}, {"distance_m": float("-inf")}, {"distance_m": None}, {"court_x_m": "far"},
])
def test_shots_with_unusable_numbers_are_skipped_and_counted(override):
    result, analysis = _sync({"players": [], "shots": [_shot(1, **override), _shot(2)]})
    assert (result.shots_kept, result.shots_skipped) == (1, 1)
    assert [s.shot_id for s in analysis.calls[0][2]] == [2]


def test_a_repeated_shot_id_keeps_the_shot_but_drops_the_second_id():
    _, analysis = _sync({"players": [], "shots": [_shot(1), _shot(1, court_x_m=3.0), _shot(None), _shot(None)]})
    assert [s.shot_id for s in analysis.calls[0][2]] == [1, None, None, None]


def test_non_finite_timestamps_are_stored_as_unknown():
    _, analysis = _sync({"players": [], "shots": [_shot(1, timestamp_seconds=float("nan"),
                                                        release_timestamp_seconds=float("inf"))]})
    shot = analysis.calls[0][2][0]
    assert (shot.timestamp_seconds, shot.release_timestamp_seconds) == (None, None)


@pytest.mark.parametrize("job", [_job(status=JobStatus.RUNNING), _job(key=None)])
def test_a_job_that_is_not_finished_with_results_is_not_ready(job):
    result, analysis = _sync(STATS, job=job)
    assert result.status == "not_ready" and analysis.calls == []


def test_an_unknown_job_is_reported():
    analysis = Analysis()
    result = SyncPlayerAnalysisUseCase(jobs=Jobs(None), game_stats=lambda **_: STATS, analysis=analysis).execute("j1")
    assert result.status == "job_not_found" and analysis.calls == []


def test_without_a_team_side_the_videos_rows_are_cleared_not_kept():
    analysis = Analysis()
    reads = []
    result = SyncPlayerAnalysisUseCase(jobs=Jobs(_job(side=None)), game_stats=lambda **k: reads.append(k) or STATS,
                                       analysis=analysis).execute("j1")
    assert reads == [] and analysis.calls == [("v1", [], [], "j1", None)]
    assert result.status == "no_side"


def test_an_older_job_is_ignored_when_a_newer_one_is_done():
    analysis = Analysis()
    older, newer = _job("old"), _job("new")
    jobs = Jobs(older, others=[newer])
    result = SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=lambda **_: STATS, analysis=analysis).execute("old")
    assert result.status == "not_latest" and analysis.calls == []
    assert analysis.superseded == [("old", "db-clock")]  # nothing left to do for it: marked, so the catch-up skips it


@pytest.mark.parametrize("status", ["not_latest", "side_changed"])
def test_a_replace_that_lost_the_race_is_reported_as_it_said(status):
    result, _ = _sync(STATS, analysis=Analysis(status))
    assert (result.status, result.shots_kept) == (status, 0)


def test_safe_sync_returns_the_result_and_swallows_every_error():
    def boom(**_):
        raise RuntimeError("storage down")

    assert safe_sync(SyncPlayerAnalysisUseCase(jobs=Jobs(_job()), game_stats=boom, analysis=Analysis()), "j1").status == "failed"
    assert safe_sync(SyncPlayerAnalysisUseCase(jobs=Jobs(_job()), game_stats=lambda **_: STATS,
                                               analysis=Analysis()), "j1").status == "ok"
    assert safe_sync(None, "j1") is None


class _Sync:
    def __init__(self, fail_on=(), statuses=None):
        self.ids, self.fail_on, self.statuses = [], fail_on, statuses or {}

    def execute(self, job_id):
        self.ids.append(job_id)
        if job_id in self.fail_on:
            raise RuntimeError("boom")
        return SyncResult(self.statuses.get(job_id, "ok"))


class _PendingJobs:
    def __init__(self, pending=("a", "b")):
        self.pending, self.calls, self.cleared = list(pending), [], []

    def list_player_stats_pending(self, *, user_id, team_id, version, limit):
        self.calls.append((user_id, team_id, version, limit))
        return [NS(id=job_id) for job_id in self.pending][:limit]

    def clear_player_stats_synced(self, *, team_id):
        self.cleared.append(team_id)


class _Lock:
    def __init__(self, free=True):
        self.free, self.taken = free, 0

    @contextmanager
    def try_acquire(self):
        self.taken += 1
        yield self.free


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_catch_up_syncs_each_pending_analysis_and_survives_failures():
    jobs, sync = _PendingJobs(), _Sync(fail_on=("a",))
    done = CatchUpPlayerAnalysisUseCase(jobs=jobs, sync=sync).execute(team_id="team-1", limit=50)
    assert jobs.calls == [(None, "team-1", 2, 50)] and sync.ids == ["a", "b"] and done == 1


def test_not_latest_and_no_side_count_as_done_but_side_changed_does_not():
    sync = _Sync(statuses={"a": "not_latest", "b": "no_side", "c": "side_changed"})
    done = CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(("a", "b", "c")), sync=sync).execute()
    assert done == 2 and sync.ids == ["a", "b", "c"]


def test_a_failed_analysis_is_not_retried_inside_the_memo_window_but_after_it():
    clock, sync = _Clock(), _Sync(fail_on=("a",))
    catch_up = CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(("a", "b")), sync=sync, clock=clock)
    catch_up.execute()
    catch_up.execute()
    assert sync.ids == ["a", "b", "b"]
    clock.now += 601
    catch_up.execute()
    assert sync.ids == ["a", "b", "b", "a", "b"]


def test_a_catch_up_skips_when_another_run_holds_the_lock():
    sync, lock = _Sync(), _Lock(free=False)
    jobs = _PendingJobs()
    assert CatchUpPlayerAnalysisUseCase(jobs=jobs, sync=sync, lock=lock).execute() == 0
    assert lock.taken == 1 and jobs.calls == [] and sync.ids == []


def test_a_job_already_in_flight_is_not_synced_twice():
    catch_up = CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(("a",)), sync=_Sync())
    assert catch_up._begin("a") is True
    assert catch_up._begin("a") is False
    catch_up._end("a")
    assert catch_up._begin("a") is True


def test_a_catch_up_never_raises():
    class Broken(_PendingJobs):
        def list_player_stats_pending(self, **_):
            raise RuntimeError("db down")

    class BrokenLock:
        def try_acquire(self):
            raise RuntimeError("no connection")

    assert CatchUpPlayerAnalysisUseCase(jobs=Broken(), sync=_Sync()).execute() == 0
    assert CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(), sync=_Sync(), lock=BrokenLock()).execute() == 0
    assert CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(), sync=None).execute() == 0
    assert CatchUpPlayerAnalysisUseCase(jobs=Broken(), sync=_Sync()).pending("u1") is False


def test_pending_asks_once_per_window_per_user_and_ignores_memoised_failures():
    clock, jobs = _Clock(), _PendingJobs(("a",))
    catch_up = CatchUpPlayerAnalysisUseCase(jobs=jobs, sync=_Sync(fail_on=("a",)), clock=clock)
    assert catch_up.pending("u1") is True
    assert catch_up.pending("u1") is False  # inside the window: already scheduled
    assert catch_up.pending("u2") is True   # another user has their own window
    assert len(jobs.calls) == 2
    catch_up.execute()                       # "a" fails and is memoised
    clock.now += 61
    assert catch_up.pending("u1") is False   # only a memoised failure is left
    assert jobs.calls[-1][3] == 2           # asked for one more row than the memoised failures
    clock.now += 600
    assert catch_up.pending("u1") is True


def test_invalidating_a_team_clears_its_markers_and_never_raises():
    jobs = _PendingJobs()
    catch_up = CatchUpPlayerAnalysisUseCase(jobs=jobs, sync=_Sync())
    catch_up.invalidate_team("team-1")
    catch_up.invalidate_team(None)
    assert jobs.cleared == ["team-1"]

    class Broken(_PendingJobs):
        def clear_player_stats_synced(self, **_):
            raise RuntimeError("db down")

    CatchUpPlayerAnalysisUseCase(jobs=Broken(), sync=_Sync()).invalidate_team("team-1")


class Players:
    def get_by_id(self, *, player_id, owner_user_id):
        return NS(id=player_id, first_name="Jaylen", last_name="Brown", jersey_number="7",
                  team_id="t1") if owner_user_id == "u1" else None


class Reader:
    def __init__(self, rows=None):
        self.rows = rows

    def list_shots(self, *, owner_user_id, player_id):
        base = {"job_id": "j", "video_id": "v", "video_title": "t", "shot_value": 3, "zone": "z",
                "shot_type": "jump_shot", "distance_m": 7.0, "timestamp_seconds": 1.23456, "attribution": None,
                "needs_review": None}
        return self.rows or [
            {**base, "id": 10, "shot_id": 1, "outcome": "made", "court_x_m": 1.0, "court_y_m": 2.0},
            {**base, "id": 11, "shot_id": 2, "outcome": "missed", "court_x_m": 3.0, "court_y_m": 4.0},
            {**base, "id": 12, "shot_id": 3, "outcome": "unresolved", "court_x_m": 5.0, "court_y_m": 6.0}]

    def totals(self, *, owner_user_id, player_id):
        return {"games": 1}


def test_the_chart_colours_made_missed_and_leaves_unresolved_as_neither():
    chart = GetPlayerShotChartUseCase(players=Players(), analysis=Reader()).execute(user_id="u1", player_id="p")
    assert [s["result"] for s in chart["shots"]] == ["made", "missed", "unknown"]
    assert [s["made"] for s in chart["shots"]] == [True, False, False]
    assert (chart["shots"][0]["x_m"], chart["shots"][0]["y_m"]) == (1.0, 2.0)
    assert chart["coverage"] == {"shots_charted": 3, "made": 1, "missed": 1, "unresolved": 1, "videos": 1}
    assert "court" in chart and chart["calc_version"] == 2
    assert chart["player"] == {"id": "p", "first_name": "Jaylen", "last_name": "Brown", "jersey_number": "7",
                               "team_id": "t1"}


def test_the_chart_rounds_the_timestamp_and_keys_every_shot_uniquely():
    base = {"video_title": "t", "shot_value": 2, "zone": "z", "shot_type": None, "distance_m": 1.0,
            "timestamp_seconds": None, "attribution": None, "needs_review": None, "outcome": "made",
            "court_x_m": 1.0, "court_y_m": 2.0}
    rows = [{**base, "id": 1, "job_id": "jobA", "video_id": "vA", "shot_id": 1, "timestamp_seconds": 6.6666},
            {**base, "id": 2, "job_id": "jobB", "video_id": "vB", "shot_id": 1},   # same shot id, other video
            {**base, "id": 3, "job_id": "jobB", "video_id": "vB", "shot_id": None},
            {**base, "id": 4, "job_id": "jobB", "video_id": "vB", "shot_id": None}]
    chart = GetPlayerShotChartUseCase(players=Players(), analysis=Reader(rows)).execute(user_id="u1", player_id="p")
    keys = [s["shot_key"] for s in chart["shots"]]
    assert keys == ["jobA:1", "jobB:1", "jobB:row3", "jobB:row4"] and len(set(keys)) == 4
    assert chart["shots"][0]["timestamp_seconds"] == 6.67 and chart["shots"][1]["timestamp_seconds"] is None


def test_the_totals_carry_the_calc_version():
    totals = GetPlayerAnalysisStatsUseCase(players=Players(), analysis=Reader()).execute(user_id="u1", player_id="p")
    assert totals["calc_version"] == 2 and totals["games"] == 1


def test_other_users_players_are_not_found():
    with pytest.raises(PlayerError):
        GetPlayerShotChartUseCase(players=Players(), analysis=Reader()).execute(user_id="u2", player_id="p")
    with pytest.raises(PlayerError):
        GetPlayerAnalysisStatsUseCase(players=Players(), analysis=Reader()).execute(user_id="u2", player_id="p")


def test_the_database_clock_is_read_before_the_slow_part_and_handed_to_the_replace():
    order = []
    analysis = Analysis()
    original = analysis.database_now
    analysis.database_now = lambda: (order.append("clock"), original())[1]

    def reader(**_):
        order.append("read")
        return STATS

    SyncPlayerAnalysisUseCase(jobs=Jobs(_job()), game_stats=reader, analysis=analysis).execute("j1")
    assert order == ["clock", "read"] and analysis.started == ["db-clock"]


def test_a_failing_job_is_logged_loudly_once_and_quietly_after(caplog):
    import logging

    clock = _Clock()
    catch_up = CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(("a",)), sync=_Sync(fail_on=("a",)), clock=clock)
    with caplog.at_level(logging.DEBUG, logger="src.application.stats.player_analysis"):
        catch_up.execute()
        clock.now += 601
        catch_up.execute()
        clock.now += 601
        catch_up.execute()
    sync_logs = [r for r in caplog.records if "Could not sync" in r.getMessage()]
    assert [r.levelno for r in sync_logs] == [logging.WARNING, logging.DEBUG, logging.DEBUG]


def test_a_stale_replace_is_neither_done_nor_a_failure_and_is_retried_at_once():
    clock = _Clock()
    sync = _Sync(statuses={"a": "stale"})
    catch_up = CatchUpPlayerAnalysisUseCase(jobs=_PendingJobs(("a",)), sync=sync, clock=clock)
    assert catch_up.execute() == 0 and catch_up.execute() == 0
    assert sync.ids == ["a", "a"]  # no failure memo: the next run redoes it


def test_a_stale_result_is_reported_publicly_as_side_changed():
    from src.application.stats.player_analysis import PUBLIC_STATUS

    assert PUBLIC_STATUS["stale"] == "side_changed"
    assert _sync(STATS, analysis=Analysis("stale"))[0].status == "stale"
