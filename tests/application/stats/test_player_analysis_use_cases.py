from types import SimpleNamespace as NS

import pytest

from src.application.players.errors import PlayerError
from src.application.stats.player_analysis import (
    GetPlayerAnalysisStatsUseCase,
    GetPlayerShotChartUseCase,
    ReplaceResult,
    ResyncTeamAnalysesUseCase,
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
        self.status = status

    def replace_video(self, *, video_id, job_id, expected_side, games, shots):
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
    def __init__(self, fail_on=()):
        self.ids, self.fail_on = [], fail_on

    def execute(self, job_id):
        self.ids.append(job_id)
        if job_id in self.fail_on:
            raise RuntimeError("boom")
        return SyncResult("ok")


def test_a_team_resync_walks_its_latest_analyses_and_survives_failures():
    jobs, sync = Jobs(_job()), _Sync(fail_on=("a",))
    done = ResyncTeamAnalysesUseCase(jobs=jobs, sync=sync, limit=20).execute("team-1")
    assert jobs.listed == [("team-1", 20)] and sync.ids == ["a", "b"] and done == 1


def test_a_team_resync_never_raises():
    class Broken(Jobs):
        def list_done_with_side_by_team(self, **_):
            raise RuntimeError("db down")

    assert ResyncTeamAnalysesUseCase(jobs=Broken(_job()), sync=_Sync()).execute("team-1") == 0
    assert ResyncTeamAnalysesUseCase(jobs=Jobs(_job()), sync=_Sync()).execute(None) == 0
    assert ResyncTeamAnalysesUseCase(jobs=Jobs(_job()), sync=None).execute("team-1") == 0


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
