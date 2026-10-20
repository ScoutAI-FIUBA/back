from types import SimpleNamespace as NS

import pytest

from src.application.players.errors import PlayerError
from src.application.stats.player_analysis import (
    GetPlayerAnalysisStatsUseCase,
    GetPlayerShotChartUseCase,
    SyncPlayerAnalysisUseCase,
    safe_sync,
)
from src.domain.jobs.entities import JobStatus


def _job(job_id="j1", status=JobStatus.DONE, side=1, key="results/j1/"):
    return NS(id=job_id, video_id="v1", team_id="t1", requested_by_user_id="u1", status=status,
              results_key=key, our_team_side=side)


class Jobs:
    def __init__(self, job, others=()):
        self.job, self.others = job, list(others)

    def get_by_id_unscoped(self, *, job_id):
        return self.job if self.job and self.job.id == job_id else None

    def list_by_video(self, *, video_id, team_id):
        return [*self.others, self.job]  # newest first


class Analysis:
    def __init__(self):
        self.calls = []

    def replace_video(self, *, video_id, games, shots):
        self.calls.append((video_id, games, shots))
        return []


STATS = {
    "players": [{"roster_player_id": "p-brown", "jersey_number": "7", "points": 3, "field_goals_made": 1,
                 "field_goals_attempted": 1, "three_point_made": 1, "three_point_attempted": 1},
                {"roster_player_id": None, "jersey_number": "27"}],
    "shots": [{"shot_id": 1, "roster_player_id": "p-brown", "made": True, "outcome": "made", "points": 3,
               "zone": "corner_three", "court_x_m": 23.8, "court_y_m": 14.4},
              {"shot_id": 2, "roster_player_id": None, "made": False, "outcome": "missed", "points": 2,
               "court_x_m": 5.0, "court_y_m": 7.0},
              {"shot_id": 3, "roster_player_id": "p-brown", "made": False, "outcome": "unknown", "points": 2,
               "court_x_m": None, "court_y_m": None}],
}


def test_only_roster_players_shots_with_a_court_position_are_kept():
    analysis = Analysis()
    kept = SyncPlayerAnalysisUseCase(jobs=Jobs(_job()), game_stats=lambda **_: STATS, analysis=analysis).execute("j1")
    assert kept == 1
    _, games, shots = analysis.calls[0]
    assert [g.player_id for g in games] == ["p-brown"] and games[0].points == 3
    assert [(s.shot_id, s.outcome) for s in shots] == [(1, "made")]


@pytest.mark.parametrize("job", [_job(status=JobStatus.RUNNING), _job(key=None), None])
def test_a_job_that_is_not_finished_with_results_is_ignored(job):
    analysis = Analysis()
    assert SyncPlayerAnalysisUseCase(jobs=Jobs(job), game_stats=lambda **_: STATS, analysis=analysis).execute("j1") == 0
    assert analysis.calls == []


def test_without_a_team_side_the_videos_rows_are_cleared_not_kept():
    analysis = Analysis()
    reads = []
    SyncPlayerAnalysisUseCase(jobs=Jobs(_job(side=None)), game_stats=lambda **k: reads.append(k) or STATS,
                              analysis=analysis).execute("j1")
    assert reads == [] and analysis.calls == [("v1", [], [])]


def test_an_older_job_is_ignored_when_a_newer_one_is_done():
    analysis = Analysis()
    older, newer = _job("old"), _job("new")
    jobs = Jobs(older, others=[newer])
    assert SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=lambda **_: STATS, analysis=analysis).execute("old") == 0
    assert analysis.calls == []


def test_safe_sync_swallows_every_error_and_accepts_no_sync():
    def boom(**_):
        raise RuntimeError("storage down")

    safe_sync(SyncPlayerAnalysisUseCase(jobs=Jobs(_job()), game_stats=boom, analysis=Analysis()), "j1")
    safe_sync(None, "j1")


class Players:
    def get_by_id(self, *, player_id, owner_user_id):
        return NS(id=player_id) if owner_user_id == "u1" else None


class Reader:
    def list_shots(self, *, owner_user_id, player_id):
        base = {"job_id": "j", "video_id": "v", "video_title": "t", "points": 3, "zone": "z", "shot_type": "jump_shot",
                "distance_m": 7.0, "timestamp_seconds": 1.0, "attribution": None, "needs_review": None}
        return [{**base, "shot_id": 1, "outcome": "made", "court_x_m": 1.0, "court_y_m": 2.0},
                {**base, "shot_id": 2, "outcome": "missed", "court_x_m": 3.0, "court_y_m": 4.0},
                {**base, "shot_id": 3, "outcome": "unresolved", "court_x_m": 5.0, "court_y_m": 6.0}]

    def totals(self, *, owner_user_id, player_id):
        return {"games": 1}


def test_the_chart_colours_made_missed_and_leaves_unresolved_as_neither():
    chart = GetPlayerShotChartUseCase(players=Players(), analysis=Reader()).execute(user_id="u1", player_id="p")
    assert [s["result"] for s in chart["shots"]] == ["made", "missed", "unknown"]
    assert [s["made"] for s in chart["shots"]] == [True, False, False]
    assert (chart["shots"][0]["x_m"], chart["shots"][0]["y_m"]) == (1.0, 2.0)
    assert chart["coverage"] == {"shots_charted": 3, "made": 1, "missed": 1, "unresolved": 1, "videos": 1}
    assert "court" in chart


def test_other_users_players_are_not_found():
    with pytest.raises(PlayerError):
        GetPlayerShotChartUseCase(players=Players(), analysis=Reader()).execute(user_id="u2", player_id="p")
    with pytest.raises(PlayerError):
        GetPlayerAnalysisStatsUseCase(players=Players(), analysis=Reader()).execute(user_id="u2", player_id="p")
