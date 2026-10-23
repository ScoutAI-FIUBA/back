"""The sync must not keep a partial answer when object storage fails on ANY file; the screens still degrade."""

from __future__ import annotations

import pytest

from src.application.stats.player_analysis import (
    CatchUpPlayerAnalysisUseCase,
    SyncPlayerAnalysisUseCase,
    safe_sync,
    strict_game_stats_reader,
)
from src.application.stats.ports import ArtifactReadError, ArtifactStorageError
from src.application.stats.use_cases import GetGameStatsUseCase
from tests.application.stats.test_player_analysis_use_cases import Analysis, Jobs, _job
from tests.application.stats.test_stats_use_cases import (
    NUMBERS,
    SHOTS,
    TEAMS,
    FakeAccess,
    FakeJobs,
    FakeReader,
    FakeRoster,
    build_job,
)

DOCS = {"projected_shots.json": SHOTS, "teams.json": TEAMS, "numbers.json": NUMBERS}
# numbers.json with a `players` list makes the job "v2", which is when the positions file is read.
V2_DOCS = {**DOCS, "numbers.json": {**NUMBERS, "players": []}}


class _StorageFailsOn(FakeReader):
    def __init__(self, documents, failing_file, **kwargs):
        super().__init__(documents, **kwargs)
        self.failing_file = failing_file

    def read_json(self, *, results_key, filename):
        if filename == self.failing_file:
            raise ArtifactStorageError("throttled")
        return super().read_json(results_key=results_key, filename=filename)

    def read_jsonl(self, *, results_key, filename, max_lines):
        if self.failing_file == "positions":
            raise ArtifactStorageError("throttled")
        return super().read_jsonl(results_key=results_key, filename=filename, max_lines=max_lines)


CASES = [("player_summary.json", DOCS), ("results.json", DOCS), ("positions", V2_DOCS)]


def _endpoint(reader):
    return GetGameStatsUseCase(jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess(),
                               roster=FakeRoster())


def _sync(reader):
    analysis = Analysis()
    game = strict_game_stats_reader(jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess(),
                                    roster=FakeRoster())
    return SyncPlayerAnalysisUseCase(jobs=Jobs(_job()), game_stats=game, analysis=analysis), analysis


@pytest.mark.parametrize("failing_file,docs", CASES)
def test_the_screen_degrades_but_the_sync_fails_and_touches_no_rows(failing_file, docs) -> None:
    reader = _StorageFailsOn(docs, failing_file)
    assert _endpoint(reader).execute(user_id="u1", team_id="t1", job_id="j1")["teams"]  # still answers
    sync, analysis = _sync(_StorageFailsOn(docs, failing_file))
    assert safe_sync(sync, "j1").status == "failed"
    assert analysis.calls == []  # nothing was replaced, nothing marked


def test_the_sync_works_when_storage_is_fine_or_a_file_is_simply_missing() -> None:
    sync, analysis = _sync(FakeReader(DOCS))  # optional files absent: ordinary
    assert safe_sync(sync, "j1").status in ("ok", "no_side")
    assert len(analysis.calls) == 1


def test_a_bad_file_that_is_not_a_storage_failure_keeps_degrading_in_the_sync() -> None:
    class _BadJson(FakeReader):
        def read_json(self, *, results_key, filename):
            if filename == "player_summary.json":
                raise ArtifactReadError("not valid JSON")
            return super().read_json(results_key=results_key, filename=filename)

    sync, analysis = _sync(_BadJson(DOCS))
    assert safe_sync(sync, "j1").status != "failed" and len(analysis.calls) == 1


def test_the_catch_up_memoises_such_a_failure() -> None:
    sync, analysis = _sync(_StorageFailsOn(DOCS, "player_summary.json"))

    class _Pending:
        def list_player_stats_pending(self, **_):
            return [_job()]

    catch_up = CatchUpPlayerAnalysisUseCase(jobs=_Pending(), sync=sync)
    assert catch_up.execute() == 0 and catch_up.execute() == 0
    assert analysis.calls == []
