from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from src.application.jobs.use_cases import RecordJobProgressCommand, RecordJobProgressUseCase, SetJobTeamSideUseCase
from src.application.stats.player_analysis import (
    GetPlayerAnalysisStatsUseCase,
    GetPlayerShotChartUseCase,
    ResyncTeamAnalysesUseCase,
    SyncPlayerAnalysisUseCase,
    safe_sync,
)
from src.application.video.use_cases import DeleteVideoCommand, DeleteVideoUseCase
from src.infrastructure.players.postgres_player_repository import PostgresPlayerRepository
from src.infrastructure.video.postgres_video_repository import PostgresVideoRepository
from src.domain.jobs.entities import JobStatus
from src.domain.stats.player_analysis import PlayerGameRow, PlayerShotRow
from src.infrastructure.jobs.postgres_job_repository import PostgresJobRepository
from src.infrastructure.stats.postgres_player_analysis_repository import PostgresPlayerAnalysisRepository
from src.interfaces.http.bootstrap.dependencies import OperationConnection, PsycopgUnitOfWork

pytestmark = pytest.mark.integration


def _dsn() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for integration tests")
    return database_url


ROOT = Path(__file__).resolve().parents[2]


def _apply_migrations() -> None:
    """Run the deploy script itself, so an edited migration cannot be silently skipped here."""

    spec = importlib.util.spec_from_file_location("apply_migrations", ROOT / "scripts" / "apply_migrations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = Path.cwd()
    os.chdir(ROOT)  # the script finds the migration folders relative to the repository root
    try:
        module.main()
    finally:
        os.chdir(previous)


@pytest.fixture(scope="session", autouse=True)
def _schema_ready() -> None:
    _dsn()
    try:
        _apply_migrations()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


@pytest.fixture(autouse=True)
def _clean() -> None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE players RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE auth_refresh_sessions, users RESTART IDENTITY CASCADE")
        conn.commit()


class World:
    """A user with a team, two roster players, a video and one finished job."""

    def __init__(self) -> None:
        self.user = f"user-{uuid4().hex[:8]}"
        self.team = str(uuid4())
        self.brown = str(uuid4())
        self.white = str(uuid4())
        self.video = str(uuid4())
        self.job = str(uuid4())
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (id, email_normalized, password_hash, created_at, updated_at) "
                            "VALUES (%s, %s, 'h', NOW(), NOW())", (self.user, f"{self.user}@example.com"))
                cur.execute("INSERT INTO teams (id, name, short_name, city, country, owner_user_id, created_at) "
                            "VALUES (%s, 'Celtics', 'BOS', 'Boston', 'USA', %s, NOW())", (self.team, self.user))
                for pid, first, number in ((self.brown, "Jaylen", "7"), (self.white, "Derrick", "9")):
                    cur.execute(
                        "INSERT INTO players (id, first_name, last_name, birth_date, height_cm, weight_kg, "
                        "primary_position, jersey_number, owner_user_id, team_id) "
                        "VALUES (%s, %s, 'Test', '1996-01-01', 198, 100, 'G', %s, %s, %s)",
                        (pid, first, number, self.user, self.team))
                self.add_video(cur, self.video, "brown3pt")
                self.add_job(cur, self.job, self.video, "DONE", side=1)
            conn.commit()

    def add_video(self, cur, video_id: str, title: str) -> None:
        cur.execute("INSERT INTO videos (id, team_id, owner_user_id, storage_key, title, status, duration_ms, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 'READY', 1000, NOW(), NOW())",
                    (video_id, self.team, self.user, f"videos/{video_id}.mp4", title))

    def add_job(self, cur, job_id: str, video_id: str, status: str, side: int | None = None, *,
                minutes: int = 0) -> None:
        # `minutes` moves created_at, so "older" and "newer" jobs of one video are unambiguous.
        cur.execute("INSERT INTO processing_jobs (id, video_id, team_id, requested_by_user_id, status, results_key, "
                    "our_team_side, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, "
                    "NOW() + make_interval(mins => %s), NOW())",
                    (job_id, video_id, self.team, self.user, status, f"results/{job_id}/", side, minutes))

    def add_extra_video(self, title: str, *, side: int | None = 1, status: str = "DONE") -> tuple[str, str]:
        """A new video with one job; returns (video_id, job_id)."""

        video, job = str(uuid4()), str(uuid4())
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                self.add_video(cur, video, title)
                self.add_job(cur, job, video, status, side=side)
            conn.commit()
        return video, job

    def add_job_for(self, video_id: str, status: str = "DONE", side: int | None = 1, *, minutes: int = 0) -> str:
        job = str(uuid4())
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                self.add_job(cur, job, video_id, status, side=side, minutes=minutes)
            conn.commit()
        return job


def _repo() -> PostgresPlayerAnalysisRepository:
    return PostgresPlayerAnalysisRepository(connection=OperationConnection(_dsn()))


def _game(world: World, player: str, *, points=3, fgm=1, fga=1, three_m=1, three_a=1, job=None, video=None, seconds=10.5):
    return PlayerGameRow(player, job or world.job, video or world.video, world.user, "7", seconds, 21.0,
                         points, fgm, fga, 0, 0, three_m, three_a, 0)


def _shot(world: World, player: str, shot_id: int, outcome: str, x: float, y: float, *, job=None, video=None,
          points=3, zone="corner_three"):
    return PlayerShotRow(player, job or world.job, video or world.video, world.user, shot_id, outcome, points, zone,
                         "jump_shot", 7.4, x, y, 6.6, "action_box_vote", False)


def _replace(repo, world: World, *, games, shots, job=None, video=None, side=1):
    return repo.replace_video(video_id=video or world.video, job_id=job or world.job, expected_side=side,
                              games=games, shots=shots)


def _stats_of(player_id: str) -> dict:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT stats FROM players WHERE id = %s", (player_id,))
            return cur.fetchone()["stats"]


def test_a_video_is_kept_and_the_player_totals_are_filled() -> None:
    world = World()
    result = _replace(
        _repo(), world,
        games=[_game(world, world.brown)],
        shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)],
    )
    assert (result.status, result.players) == ("ok", [world.brown])

    stats = _stats_of(world.brown)
    assert stats["games_played"] == 1
    assert stats["points"] == {"total": 3, "per_game": 3}
    assert stats["three_point"]["made_total"] == 1 and stats["three_point"]["attempted_total"] == 1
    assert stats["three_point"]["percentage"] == 100
    assert stats["field_goals"]["made_total"] == 1
    # Not measured by the analysis: stays as it was.
    assert stats["rebounds"] == {"total": 0, "per_game": 0}
    assert stats["assists"] == {"total": 0, "per_game": 0}


def test_shots_come_back_with_court_positions_and_outcomes() -> None:
    world = World()
    repo = _repo()
    _replace(
        repo, world,
        games=[_game(world, world.brown, points=3, fgm=1, fga=2, three_m=1, three_a=2)],
        shots=[_shot(world, world.brown, 2, "missed", 20.0, 5.0), _shot(world, world.brown, 1, "made", 23.8, 14.4)],
    )
    shots = repo.list_shots(owner_user_id=world.user, player_id=world.brown)
    assert [(s["shot_id"], s["outcome"]) for s in shots] == [(1, "made"), (2, "missed")]
    assert (shots[0]["court_x_m"], shots[0]["court_y_m"]) == (23.8, 14.4)
    assert shots[0]["video_title"] == "brown3pt"
    totals = repo.totals(owner_user_id=world.user, player_id=world.brown)
    assert totals["games"] == 1 and totals["points"] == 3
    assert totals["three_point"] == {"made": 1, "attempted": 2, "pct": 0.5}
    assert totals["by_zone"]["corner_three"] == {"made": 1, "attempted": 2, "unresolved_attempts": 0, "pct": 0.5}


def test_two_videos_add_up_and_a_reanalysis_replaces_instead_of_doubling() -> None:
    world = World()
    repo = _repo()
    second_video, second_job = str(uuid4()), str(uuid4())
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            world.add_video(cur, second_video, "brown2pts")
            world.add_job(cur, second_job, second_video, "DONE", side=1)
        conn.commit()
    _replace(repo, world, games=[_game(world, world.brown)],
                       shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)])
    _replace(
        repo, world, job=second_job, video=second_video,
        games=[PlayerGameRow(world.brown, second_job, second_video, world.user, "7", 12.0, 18.0, 2, 1, 1, 1, 1, 0, 0, 0)],
        shots=[_shot(world, world.brown, 1, "made", 6.0, 7.0, job=second_job, video=second_video, points=2, zone="paint")])

    assert _stats_of(world.brown)["games_played"] == 2
    assert _stats_of(world.brown)["points"]["total"] == 5
    assert len(repo.list_shots(owner_user_id=world.user, player_id=world.brown)) == 2

    # Analysing the first video again must replace its rows, not add to them.
    _replace(repo, world, games=[_game(world, world.brown)],
                       shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)])
    assert _stats_of(world.brown)["points"]["total"] == 5
    assert len(repo.list_shots(owner_user_id=world.user, player_id=world.brown)) == 2


def test_a_player_no_longer_linked_in_the_new_analysis_is_reset() -> None:
    world = World()
    repo = _repo()
    _replace(repo, world, games=[_game(world, world.brown)], shots=[])
    assert _stats_of(world.brown)["games_played"] == 1
    _replace(repo, world, games=[_game(world, world.white, points=0, fgm=0, fga=0, three_m=0, three_a=0)], shots=[])
    assert _stats_of(world.brown)["games_played"] == 0 and _stats_of(world.brown)["points"]["total"] == 0
    assert _stats_of(world.white)["games_played"] == 1


def test_a_deleted_video_stops_counting() -> None:
    world = World()
    repo = _repo()
    _replace(repo, world, games=[_game(world, world.brown)],
                       shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)])
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE videos SET deleted_at = NOW() WHERE id = %s", (world.video,))
        conn.commit()
    assert repo.list_shots(owner_user_id=world.user, player_id=world.brown) == []
    assert repo.totals(owner_user_id=world.user, player_id=world.brown)["games"] == 0


def test_rows_go_with_the_player_and_are_private_to_the_owner() -> None:
    world = World()
    repo = _repo()
    _replace(repo, world, games=[_game(world, world.brown)],
                       shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)])
    assert repo.list_shots(owner_user_id="someone-else", player_id=world.brown) == []
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM players WHERE id = %s", (world.brown,))
            cur.execute("SELECT COUNT(*) FROM player_analysis_shots")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM player_analysis_games")
            assert cur.fetchone()[0] == 0
        conn.commit()


def _stats_document(world: World, *, linked: bool = True) -> dict:
    roster_id = world.brown if linked else None
    return {
        "players": [{"roster_player_id": roster_id, "jersey_number": "7", "seconds_observed": 10.5, "distance_m": 21.0,
                     "points": 3, "field_goals_made": 1, "field_goals_attempted": 1, "three_point_made": 1,
                     "three_point_attempted": 1, "two_point_made": 0, "two_point_attempted": 0,
                     "unresolved_attempts": 0},
                    {"roster_player_id": None, "jersey_number": "27", "points": 0}],
        "shots": [{"shot_id": 1, "roster_player_id": roster_id, "made": True, "outcome": "made", "points": 3,
                   "zone": "corner_three", "shot_type": "jump_shot", "distance_m": 7.4, "court_x_m": 23.8,
                   "court_y_m": 14.4, "timestamp_seconds": 6.6, "attribution": "action_box_vote",
                   "needs_review": False},
                  {"shot_id": 2, "roster_player_id": None, "made": False, "outcome": "missed", "points": 2,
                   "zone": "paint", "court_x_m": 5.0, "court_y_m": 7.0}],
    }


def test_finishing_a_job_keeps_the_roster_players_rows() -> None:
    world = World()
    dsn_connection = OperationConnection(_dsn())
    jobs = PostgresJobRepository(connection=dsn_connection)
    analysis = PostgresPlayerAnalysisRepository(connection=dsn_connection)
    sync = SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=lambda **_: _stats_document(world), analysis=analysis)
    new_video, new_job = str(uuid4()), str(uuid4())
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            world.add_video(cur, new_video, "second")
            world.add_job(cur, new_job, new_video, "RUNNING", side=1)
        conn.commit()
    record = RecordJobProgressUseCase(jobs=jobs, uow=PsycopgUnitOfWork(dsn_connection),
                                      on_done=lambda job: safe_sync(sync, job.id))
    record.execute(RecordJobProgressCommand(job_id=new_job, status=JobStatus.DONE, results_key="results/x/",
                                            artifacts=[], summary={}))

    shots = analysis.list_shots(owner_user_id=world.user, player_id=world.brown)
    assert [(s["shot_id"], s["outcome"]) for s in shots] == [(1, "made")]  # the unlinked shot is not kept
    assert _stats_of(world.brown)["points"]["total"] == 3


def test_a_failing_sync_never_fails_the_job_callback() -> None:
    world = World()
    connection = OperationConnection(_dsn())
    jobs = PostgresJobRepository(connection=connection)

    def boom(**_):
        raise RuntimeError("storage down")

    sync = SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=boom, analysis=PostgresPlayerAnalysisRepository(connection=connection))
    new_video, new_job = str(uuid4()), str(uuid4())
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            world.add_video(cur, new_video, "second")
            world.add_job(cur, new_job, new_video, "RUNNING", side=1)
        conn.commit()
    record = RecordJobProgressUseCase(jobs=jobs, uow=PsycopgUnitOfWork(connection),
                                      on_done=lambda job: safe_sync(sync, job.id))
    job = record.execute(RecordJobProgressCommand(job_id=new_job, status=JobStatus.DONE, results_key="results/x/",
                                                  artifacts=[], summary={}))
    assert job.status is JobStatus.DONE


def test_setting_our_team_later_links_the_players() -> None:
    world = World()
    connection = OperationConnection(_dsn())
    jobs = PostgresJobRepository(connection=connection)
    analysis = PostgresPlayerAnalysisRepository(connection=connection)
    sync = SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=lambda **_: _stats_document(world), analysis=analysis)
    new_video, new_job = str(uuid4()), str(uuid4())
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            world.add_video(cur, new_video, "second")
            world.add_job(cur, new_job, new_video, "DONE", side=None)
        conn.commit()
    # Finished without a side: nothing to keep yet.
    assert sync.execute(new_job).status == "no_side"
    assert analysis.list_shots(owner_user_id=world.user, player_id=world.brown) == []

    class _Access:
        def assert_access(self, **_): return None

    set_side = SetJobTeamSideUseCase(jobs=jobs, team_access=_Access(), on_changed=lambda job: safe_sync(sync, job.id))
    set_side.execute(user_id=world.user, team_id=world.team, job_id=new_job, our_team_side=1)
    assert len(analysis.list_shots(owner_user_id=world.user, player_id=world.brown)) == 1


def test_an_older_analysis_does_not_overwrite_a_newer_one() -> None:
    world = World()
    connection = OperationConnection(_dsn())
    jobs = PostgresJobRepository(connection=connection)
    analysis = PostgresPlayerAnalysisRepository(connection=connection)
    calls: list[str] = []

    def reader(**kwargs):
        calls.append(kwargs["job_id"])
        return _stats_document(world)

    sync = SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=reader, analysis=analysis)
    newer = str(uuid4())
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            world.add_job(cur, newer, world.video, "DONE", side=1)  # a later job for the same video
        conn.commit()
    assert sync.execute(world.job).status == "not_latest"  # the older one is ignored
    assert calls == []
    assert sync.execute(newer).shots_kept == 1  # the newest one is kept
    assert calls == [newer]


# ---------------------------------------------------------------------------------------------
# Races: real threads, with the interleavings forced.
# ---------------------------------------------------------------------------------------------


class _HookRepo(PostgresPlayerAnalysisRepository):
    """The real repository; `hook` runs right before a player's totals are recomputed, i.e. while
    the transaction holds its locks and has not committed."""

    def __init__(self, connection, hook=None) -> None:
        super().__init__(connection)
        self.hook = hook

    def _refresh_player_stats(self, cur, player_id):
        if self.hook is not None:
            self.hook(player_id)
        return super()._refresh_player_stats(cur, player_id)


def _sync_for(reader, hook=None) -> SyncPlayerAnalysisUseCase:
    connection = OperationConnection(_dsn())
    return SyncPlayerAnalysisUseCase(jobs=PostgresJobRepository(connection=connection), game_stats=reader,
                                     analysis=_HookRepo(connection, hook))


def _doc(player: str, *, shots: int, made: int, points: int | None = None) -> dict:
    """A game stats document for one linked player taking `shots` three-pointers, `made` of them in."""

    return {
        "players": [{"roster_player_id": player, "jersey_number": "7", "seconds_observed": 10.0, "distance_m": 5.0,
                     "points": made * 3 if points is None else points, "field_goals_made": made,
                     "field_goals_attempted": shots, "three_point_made": made, "three_point_attempted": shots,
                     "two_point_made": 0, "two_point_attempted": 0, "unresolved_attempts": 0}],
        "shots": [{"shot_id": i + 1, "roster_player_id": player, "made": i < made,
                   "outcome": "made" if i < made else "missed", "points": 3, "zone": "above_the_break",
                   "shot_type": "jump_shot", "distance_m": 7.0, "court_x_m": 20.0 + i, "court_y_m": 7.0,
                   "timestamp_seconds": float(i)} for i in range(shots)],
    }


def _in_thread(name: str, fn, out: dict) -> threading.Thread:
    def target() -> None:
        try:
            out[name] = fn()
        except BaseException as exc:  # noqa: BLE001 - the test reports it instead of losing it
            out[name] = exc

    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _wait_until(condition, *, timeout: float = 15.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _someone_waits_on_a_lock() -> bool:
    """True while another session of this database is blocked on a lock (proof the race is real)."""

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock'")
            return cur.fetchone()[0] > 0


def _join(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), f"{thread.name} did not finish (deadlock?)"


def _count(sql: str, *params) -> int:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]


def test_t1_two_videos_of_one_player_synced_in_parallel_add_up_in_players_stats() -> None:
    world = World()
    video_b, job_b = world.add_extra_video("second")
    docs = {world.job: _doc(world.brown, shots=4, made=4), job_b: _doc(world.brown, shots=6, made=1)}
    entered, release = threading.Event(), threading.Event()

    def hold(_player: str) -> None:  # the first sync stops with the player locked, before it commits
        entered.set()
        assert release.wait(30)

    out: dict = {}
    first = _in_thread("A", lambda: _sync_for(lambda **kw: docs[kw["job_id"]], hold).execute(world.job), out)
    assert entered.wait(15)
    second = _in_thread("B", lambda: _sync_for(lambda **kw: docs[kw["job_id"]]).execute(job_b), out)
    _wait_until(_someone_waits_on_a_lock, what="the second sync to queue behind the first")
    assert "B" not in out  # it really is waiting, not racing past
    release.set()
    _join(first, second)

    assert out["A"].status == "ok" and out["B"].status == "ok", out
    stats = _stats_of(world.brown)
    assert stats["games_played"] == 2
    assert stats["field_goals"]["attempted_total"] == 10 and stats["field_goals"]["made_total"] == 5
    assert stats["points"]["total"] == 15


def test_t3_an_older_jobs_slow_sync_finishing_late_does_not_overwrite_the_newer_one() -> None:
    world = World()  # world.job is the older DONE job of world.video
    docs = {world.job: _doc(world.brown, shots=1, made=1)}
    read_done, gate = threading.Event(), threading.Event()

    def slow_reader(**kw):
        document = docs[kw["job_id"]]
        read_done.set()  # the older job has already passed its "latest DONE" pre-check
        assert gate.wait(30)
        return document

    out: dict = {}
    older = _in_thread("old", lambda: _sync_for(slow_reader).execute(world.job), out)
    assert read_done.wait(15)
    newer_job = world.add_job_for(world.video, minutes=5)
    docs[newer_job] = _doc(world.brown, shots=3, made=0)
    assert _sync_for(lambda **kw: docs[kw["job_id"]]).execute(newer_job).status == "ok"
    gate.set()
    _join(older)

    assert out["old"].status == "not_latest"
    assert {row for row in _jobs_with_shots(world.video)} == {newer_job}
    assert _count("SELECT COUNT(*) FROM player_analysis_shots WHERE video_id = %s", world.video) == 3
    assert _stats_of(world.brown)["field_goals"]["attempted_total"] == 3


def _jobs_with_shots(video: str) -> set[str]:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT job_id FROM player_analysis_shots WHERE video_id = %s", (video,))
            return {str(row[0]) for row in cur.fetchall()}


def test_t4_two_jobs_of_one_video_overlapping_leave_exactly_one_set_of_rows() -> None:
    world = World()
    docs = {world.job: _doc(world.brown, shots=1, made=1)}
    entered, release = threading.Event(), threading.Event()

    def hold(_player: str) -> None:  # the older sync is inside its transaction, lock held
        entered.set()
        assert release.wait(30)

    out: dict = {}
    older = _in_thread("old", lambda: _sync_for(lambda **kw: docs[kw["job_id"]], hold).execute(world.job), out)
    assert entered.wait(15)
    newer_job = world.add_job_for(world.video, minutes=5)  # lands while the older one is mid-transaction
    docs[newer_job] = _doc(world.brown, shots=2, made=2)
    newer = _in_thread("new", lambda: _sync_for(lambda **kw: docs[kw["job_id"]]).execute(newer_job), out)
    _wait_until(_someone_waits_on_a_lock, what="the newer sync to queue behind the older one")
    assert "new" not in out
    release.set()
    _join(older, newer)

    assert out["old"].status == "ok" and out["new"].status == "ok", out
    assert _jobs_with_shots(world.video) == {newer_job}
    assert _count("SELECT COUNT(*) FROM player_analysis_shots WHERE video_id = %s", world.video) == 2
    assert _count("SELECT COUNT(*) FROM player_analysis_games WHERE video_id = %s", world.video) == 1
    assert _stats_of(world.brown)["games_played"] == 1
    assert _stats_of(world.brown)["field_goals"]["attempted_total"] == 2


def test_t4b_overlapping_jobs_linking_different_players_still_leave_one_set_of_rows() -> None:
    # No player in common, so only the per-video lock keeps the two replaces from interleaving.
    world = World()
    docs = {world.job: _doc(world.brown, shots=1, made=1)}
    entered, release = threading.Event(), threading.Event()

    def hold(_player: str) -> None:
        entered.set()
        assert release.wait(30)

    out: dict = {}
    older = _in_thread("old", lambda: _sync_for(lambda **kw: docs[kw["job_id"]], hold).execute(world.job), out)
    assert entered.wait(15)
    newer_job = world.add_job_for(world.video, minutes=5)
    docs[newer_job] = _doc(world.white, shots=2, made=2)
    newer = _in_thread("new", lambda: _sync_for(lambda **kw: docs[kw["job_id"]]).execute(newer_job), out)
    _wait_until(_someone_waits_on_a_lock, what="the newer sync to queue behind the older one")
    release.set()
    _join(older, newer)

    assert out["old"].status == "ok" and out["new"].status == "ok", out
    assert _jobs_with_shots(world.video) == {newer_job}
    assert _count("SELECT COUNT(*) FROM player_analysis_games WHERE video_id = %s", world.video) == 1
    assert _stats_of(world.brown)["games_played"] == 0 and _stats_of(world.white)["games_played"] == 1


def test_t5_twelve_parallel_syncs_of_twelve_videos_of_one_player_lose_nothing() -> None:
    world = World()
    docs, jobs = {}, []
    for index in range(12):
        _, job = world.add_extra_video(f"clip-{index}")
        docs[job] = _doc(world.brown, shots=2, made=1)
        jobs.append(job)
    start = threading.Barrier(12, timeout=30)
    out: dict = {}

    def run(job: str):
        start.wait()
        return _sync_for(lambda **kw: docs[kw["job_id"]]).execute(job)

    threads = [_in_thread(job, lambda job=job: run(job), out) for job in jobs]
    _join(*threads)

    failures = {job: result for job, result in out.items() if getattr(result, "status", None) != "ok"}
    assert not failures, failures
    stats = _stats_of(world.brown)
    assert stats["games_played"] == 12
    assert stats["field_goals"]["attempted_total"] == 24 and stats["field_goals"]["made_total"] == 12
    assert stats["points"]["total"] == 36
    assert _count("SELECT COUNT(*) FROM player_analysis_games WHERE player_id = %s", world.brown) == 12
    assert _count("SELECT COUNT(*) FROM player_analysis_shots WHERE player_id = %s", world.brown) == 24


def test_two_players_in_opposite_orders_do_not_deadlock() -> None:
    # Both videos link both players; the locks are taken in a stable order whatever the row order is.
    world = World()
    video_b, job_b = world.add_extra_video("second")
    both = {"players": [], "shots": []}
    for pid in (world.brown, world.white):
        both["players"].append(_doc(pid, shots=1, made=1)["players"][0])
    docs = {world.job: both, job_b: {"players": list(reversed(both["players"])), "shots": []}}
    start = threading.Barrier(2, timeout=30)
    out: dict = {}

    def run(job: str):
        start.wait()
        return _sync_for(lambda **kw: docs[kw["job_id"]]).execute(job)

    _join(_in_thread("a", lambda: run(world.job), out), _in_thread("b", lambda: run(job_b), out))
    assert out["a"].status == "ok" and out["b"].status == "ok", out
    assert _stats_of(world.brown)["games_played"] == 2 and _stats_of(world.white)["games_played"] == 2


# ---------------------------------------------------------------------------------------------
# The checks inside the lock.
# ---------------------------------------------------------------------------------------------


def test_replace_reports_not_latest_and_changes_nothing() -> None:
    world = World()
    repo = _repo()
    newer = world.add_job_for(world.video, minutes=5)
    result = _replace(repo, world, games=[_game(world, world.brown)], shots=[])
    assert (result.status, result.players) == ("not_latest", [])
    assert _count("SELECT COUNT(*) FROM player_analysis_games") == 0
    assert _replace(repo, world, job=newer, games=[_game(world, world.brown, job=newer)], shots=[]).status == "ok"
    # An unknown job or a job that is not DONE is not the latest either.
    assert _replace(repo, world, job=str(uuid4()), games=[], shots=[]).status == "not_latest"


def test_replace_reports_side_changed_and_changes_nothing() -> None:
    world = World()  # the job's side is 1
    repo = _repo()
    result = _replace(repo, world, games=[_game(world, world.brown)], shots=[], side=0)
    assert result.status == "side_changed"
    assert _count("SELECT COUNT(*) FROM player_analysis_games") == 0
    assert _replace(repo, world, games=[], shots=[], side=None).status == "side_changed"
    assert _replace(repo, world, games=[_game(world, world.brown)], shots=[], side=1).status == "ok"


def test_a_side_changed_while_the_slow_read_ran_is_caught_and_the_new_sync_wins() -> None:
    world = World()
    read_done, gate = threading.Event(), threading.Event()
    docs = {"first": _doc(world.brown, shots=1, made=1)}

    def slow_reader(**_):
        document = docs["first"]
        read_done.set()
        assert gate.wait(30)
        return document

    out: dict = {}
    thread = _in_thread("slow", lambda: _sync_for(slow_reader).execute(world.job), out)
    assert read_done.wait(15)
    with psycopg.connect(_dsn()) as conn:  # the scout flips the side meanwhile
        with conn.cursor() as cur:
            cur.execute("UPDATE processing_jobs SET our_team_side = 0 WHERE id = %s", (world.job,))
        conn.commit()
    assert _sync_for(lambda **_: _doc(world.white, shots=2, made=0)).execute(world.job).status == "ok"
    gate.set()
    _join(thread)
    assert out["slow"].status == "side_changed"
    assert _count("SELECT COUNT(*) FROM player_analysis_games WHERE player_id = %s", world.white) == 1
    assert _count("SELECT COUNT(*) FROM player_analysis_games WHERE player_id = %s", world.brown) == 0


def test_rows_of_a_player_deleted_meanwhile_are_dropped_instead_of_failing() -> None:
    world = World()
    ghost = str(uuid4())
    result = _replace(_repo(), world, games=[_game(world, world.brown), _game(world, ghost)],
                      shots=[_shot(world, ghost, 1, "made", 1.0, 1.0)])
    assert (result.status, result.players) == ("ok", [world.brown])
    assert _count("SELECT COUNT(*) FROM player_analysis_shots") == 0


# ---------------------------------------------------------------------------------------------
# Schema checks, new columns, harness.
# ---------------------------------------------------------------------------------------------


def test_the_migrations_apply_again_without_error() -> None:
    _apply_migrations()  # everything is recorded: nothing runs twice, nothing breaks


def test_the_006_migration_is_safe_to_run_twice() -> None:
    sql = (ROOT / "src/infrastructure/jobs/migrations/006_player_analysis_stats.sql").read_text(encoding="utf-8")
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(sql)
        conn.commit()


def test_games_are_keyed_by_video_and_player_with_player_first_indexes() -> None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
                        "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = 'player_analysis_games'::regclass "
                        "AND i.indisprimary ORDER BY a.attname")
            assert [row[0] for row in cur.fetchall()] == ["player_id", "video_id"]
            cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename IN "
                        "('player_analysis_games', 'player_analysis_shots')")
            defs = [row[0] for row in cur.fetchall()]
    assert any("ON public.player_analysis_games USING btree (player_id" in d for d in defs)
    assert any("ON public.player_analysis_shots USING btree (player_id" in d for d in defs)
    assert any("ON public.player_analysis_shots USING btree (job_id)" in d for d in defs)


def _expect_check_violation(sql: str, params: tuple) -> None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(sql, params)


_SHOT_INSERT = ("INSERT INTO player_analysis_shots (player_id, job_id, video_id, owner_user_id, outcome, "
                "shot_value, court_x_m, court_y_m{extra}) VALUES (%s, %s, %s, %s, %s, %s, 1, 1{values})")


@pytest.mark.parametrize("outcome, value, extra, extra_value", [
    ("scored", 3, "", None),
    ("made", 1, "", None),
    ("made", 3, ", outcome_confidence", "sure"),
])
def test_the_shot_table_rejects_values_outside_the_contract(outcome, value, extra, extra_value) -> None:
    world = World()
    sql = _SHOT_INSERT.format(extra=extra, values=", %s" if extra else "")
    params = (world.brown, world.job, world.video, world.user, outcome, value) + ((extra_value,) if extra else ())
    _expect_check_violation(sql, params)


@pytest.mark.parametrize("columns", [
    "field_goals_made, field_goals_attempted = 2, 1",
    "two_point_made, two_point_attempted = 1, 0",
    "three_point_made, three_point_attempted = 3, 2",
])
def test_the_game_table_rejects_more_made_than_attempted(columns) -> None:
    world = World()
    names, values = columns.split(" = ")
    first, second = [v.strip() for v in names.split(",")], [int(v) for v in values.split(",")]
    sql = (f"INSERT INTO player_analysis_games (player_id, job_id, video_id, owner_user_id, {first[0]}, {first[1]}) "
           "VALUES (%s, %s, %s, %s, %s, %s)")
    _expect_check_violation(sql, (world.brown, world.job, world.video, world.user, *second))


def test_a_video_keeps_one_row_per_player() -> None:
    world = World()
    _replace(_repo(), world, games=[_game(world, world.brown)], shots=[])
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("INSERT INTO player_analysis_games (player_id, job_id, video_id, owner_user_id) "
                            "VALUES (%s, %s, %s, %s)", (world.brown, world.job, world.video, world.user))


def test_the_detail_columns_and_the_calc_version_are_stored_and_served() -> None:
    world = World()
    repo = _repo()
    shot = PlayerShotRow(world.brown, world.job, world.video, world.user, 1, "made", 3, "above_the_break",
                         "jump_shot", 7.4, 20.0, 7.0, 6.6, "action_box_vote", False, "ball_path", "inferred",
                         6.1, 7.2, [{"track_id": 3, "score": 0.4}])
    _replace(repo, world, games=[_game(world, world.brown)], shots=[shot])
    row = repo.list_shots(owner_user_id=world.user, player_id=world.brown)[0]
    assert (row["shot_value"], row["outcome_source"], row["outcome_confidence"]) == (3, "ball_path", "inferred")
    assert (row["release_timestamp_seconds"], row["resolved_timestamp_seconds"]) == (6.1, 7.2)
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT shooter_candidates, calc_version FROM player_analysis_shots")
            assert cur.fetchone() == ([{"track_id": 3, "score": 0.4}], 2)
            cur.execute("SELECT calc_version FROM player_analysis_games")
            assert cur.fetchone() == (2,)
    totals = repo.totals(owner_user_id=world.user, player_id=world.brown)
    assert totals["seconds_on_screen"] == 10.5 and "seconds_observed" not in totals
    assert totals["videos"][0]["seconds_on_screen"] == 10.5


# ---------------------------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------------------------


def _sync_doc(world: World, document: dict):
    sync = _sync_for(lambda **_: document)
    return sync, sync.execute(world.job)


def test_a_shot_with_a_nan_coordinate_is_not_stored_and_the_chart_still_works() -> None:
    world = World()
    document = _doc(world.brown, shots=2, made=1)
    document["shots"][0]["court_x_m"] = float("nan")
    document["shots"][1]["distance_m"] = float("inf")
    document["shots"].append({**document["shots"][1], "shot_id": 9, "distance_m": 7.0})
    _, result = _sync_doc(world, document)
    assert (result.status, result.shots_kept, result.shots_skipped) == ("ok", 1, 2)
    connection = OperationConnection(_dsn())
    chart = GetPlayerShotChartUseCase(players=PostgresPlayerRepository(connection=connection),
                                      analysis=PostgresPlayerAnalysisRepository(connection=connection)
                                      ).execute(user_id=world.user, player_id=world.brown)
    assert [s["shot_id"] for s in chart["shots"]] == [9]
    json.dumps(chart, allow_nan=False)  # the response is valid JSON


def test_text_with_nul_characters_is_stored_without_them() -> None:
    world = World()
    document = _doc(world.brown, shots=1, made=1)
    document["players"][0]["jersey_number"] = "7\x00"
    document["shots"][0].update(zone="above\x00_the_break", shot_type="jump\x00shot", attribution="a\x00b",
                                outcome_source="x\x00y", shooter_candidates=[{"name": "n\x00m"}])
    _, result = _sync_doc(world, document)
    assert result.status == "ok"
    row = _repo().list_shots(owner_user_id=world.user, player_id=world.brown)[0]
    assert (row["zone"], row["shot_type"], row["attribution"], row["outcome_source"]) == (
        "above_the_break", "jumpshot", "ab", "xy")
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT jersey_number FROM player_analysis_games")
            assert cur.fetchone()[0] == "7"
            cur.execute("SELECT shooter_candidates FROM player_analysis_shots")
            assert cur.fetchone()[0] == [{"name": "nm"}]


def test_a_repeated_shot_id_in_one_video_does_not_break_the_sync() -> None:
    world = World()
    document = _doc(world.brown, shots=3, made=1)
    for shot in document["shots"]:
        shot["shot_id"] = 1
    _, result = _sync_doc(world, document)
    assert (result.status, result.shots_kept) == ("ok", 3)
    shots = _repo().list_shots(owner_user_id=world.user, player_id=world.brown)
    assert sorted(s["shot_id"] is None for s in shots) == [False, True, True]


def test_two_tracks_for_one_roster_player_become_one_summed_game_row() -> None:
    world = World()
    one = _doc(world.brown, shots=1, made=1)["players"][0]
    two = {**one, "jersey_number": None, "seconds_observed": 4.0, "points": 2, "field_goals_made": 1,
           "field_goals_attempted": 2, "three_point_made": 0, "three_point_attempted": 0, "two_point_made": 1,
           "two_point_attempted": 2}
    _, result = _sync_doc(world, {"players": [one, two], "shots": []})
    assert result.status == "ok"
    totals = _repo().totals(owner_user_id=world.user, player_id=world.brown)
    assert totals["games"] == 1 and totals["points"] == 5
    assert totals["field_goals"] == {"made": 2, "attempted": 3, "pct": 0.667}
    assert totals["seconds_on_screen"] == 14.0
    assert _stats_of(world.brown)["points"]["total"] == 5


@pytest.mark.parametrize("corrupt", ["[1, 2]", "42", '"text"', "null", "true"])
def test_a_players_stats_that_is_not_an_object_does_not_stop_the_sync(corrupt) -> None:
    world = World()
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE players SET stats = %s::jsonb WHERE id = %s", (corrupt, world.brown))
        conn.commit()
    _, result = _sync_doc(world, _doc(world.brown, shots=2, made=1))
    assert result.status == "ok"
    stats = _stats_of(world.brown)
    assert stats["games_played"] == 1 and stats["field_goals"]["attempted_total"] == 2
    assert stats["rebounds"] == {"total": 0, "per_game": 0}  # the empty profile fields are back


# ---------------------------------------------------------------------------------------------
# Deleting a video, shot keys, the sync status, the roster re-sync.
# ---------------------------------------------------------------------------------------------


class _Access:
    def assert_access(self, **_):
        return None


class _Storage:
    def delete_video(self, key: str) -> None:
        return None


def test_soft_deleting_a_video_takes_it_out_of_the_players_stats() -> None:
    world = World()
    video_b, job_b = world.add_extra_video("second")
    docs = {world.job: _doc(world.brown, shots=4, made=4), job_b: _doc(world.brown, shots=2, made=1)}
    for job in (world.job, job_b):
        assert _sync_for(lambda **kw: docs[kw["job_id"]]).execute(job).status == "ok"
    assert _stats_of(world.brown)["games_played"] == 2

    connection = OperationConnection(_dsn())
    delete = DeleteVideoUseCase(
        videos=PostgresVideoRepository(connection=connection), storage=_Storage(), team_access=_Access(),
        uow=PsycopgUnitOfWork(connection),
        on_deleted=PostgresPlayerAnalysisRepository(connection=connection).refresh_players_for_video)
    delete.execute(DeleteVideoCommand(user_id=world.user, team_id=world.team, video_id=world.video))

    stats = _stats_of(world.brown)
    assert stats["games_played"] == 1
    assert stats["field_goals"]["attempted_total"] == 2 and stats["field_goals"]["made_total"] == 1
    assert stats["points"]["total"] == 3


def test_refreshing_a_video_nobody_has_rows_for_does_nothing() -> None:
    assert _repo().refresh_players_for_video(str(uuid4())) == []


def test_shot_keys_are_unique_across_videos_that_share_shot_ids() -> None:
    world = World()
    video_b, job_b = world.add_extra_video("second")
    for job in (world.job, job_b):
        assert _sync_for(lambda **_: _doc(world.brown, shots=2, made=1)).execute(job).status == "ok"
    connection = OperationConnection(_dsn())
    chart = GetPlayerShotChartUseCase(players=PostgresPlayerRepository(connection=connection),
                                      analysis=PostgresPlayerAnalysisRepository(connection=connection)
                                      ).execute(user_id=world.user, player_id=world.brown)
    keys = [s["shot_key"] for s in chart["shots"]]
    assert len(keys) == 4 and len(set(keys)) == 4
    assert sorted(s["shot_id"] for s in chart["shots"]) == [1, 1, 2, 2]


def test_setting_the_side_on_an_older_job_reports_not_latest() -> None:
    world = World()
    newer = world.add_job_for(world.video, minutes=5, side=None)
    connection = OperationConnection(_dsn())
    jobs = PostgresJobRepository(connection=connection)
    sync = _sync_for(lambda **_: _doc(world.brown, shots=1, made=1))
    set_side = SetJobTeamSideUseCase(jobs=jobs, team_access=_Access(),
                                     on_changed=lambda job: safe_sync(sync, job.id).status)
    _, status = set_side.execute_and_sync(user_id=world.user, team_id=world.team, job_id=world.job, our_team_side=0)
    assert status == "not_latest"
    _, status = set_side.execute_and_sync(user_id=world.user, team_id=world.team, job_id=newer, our_team_side=1)
    assert status == "ok"


def test_the_done_callback_of_a_rerun_clears_the_videos_rows_until_its_side_is_set() -> None:
    world = World()
    assert _sync_for(lambda **_: _doc(world.brown, shots=2, made=1)).execute(world.job).status == "ok"
    assert _stats_of(world.brown)["games_played"] == 1
    rerun = world.add_job_for(world.video, minutes=5, side=None)
    assert _sync_for(lambda **_: _doc(world.brown, shots=2, made=1)).execute(rerun).status == "no_side"
    assert _stats_of(world.brown)["games_played"] == 0
    assert _count("SELECT COUNT(*) FROM player_analysis_shots") == 0


def test_the_team_listing_for_a_resync_is_bounded_newest_first_and_needs_a_side() -> None:
    world = World()  # one DONE job with a side already
    jobs = PostgresJobRepository(connection=OperationConnection(_dsn()))
    created = []
    for index in range(3):
        video, job = world.add_extra_video(f"v{index}")
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE processing_jobs SET created_at = NOW() + make_interval(mins => %s) WHERE id = %s",
                            (index + 1, job))
            conn.commit()
        created.append(job)
    world.add_extra_video("no side", side=None)
    world.add_extra_video("running", status="RUNNING")
    listed = jobs.list_done_with_side_by_team(team_id=world.team, limit=3)
    assert [job.id for job in listed] == list(reversed(created))
    assert len(jobs.list_done_with_side_by_team(team_id=world.team, limit=20)) == 4
    assert jobs.list_done_with_side_by_team(team_id=str(uuid4()), limit=20) == []


def test_changing_a_jersey_and_resyncing_moves_the_rows_to_the_new_link() -> None:
    world = World()  # brown wears 7, white wears 9
    connection = OperationConnection(_dsn())

    def reader(**_):
        # What the box score does: the roster player is whoever wears the confirmed number now.
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM players WHERE team_id = %s AND jersey_number = '7'", (world.team,))
                row = cur.fetchone()
        return _doc(str(row[0]), shots=2, made=1) if row else {"players": [], "shots": []}

    sync = _sync_for(reader)
    assert sync.execute(world.job).status == "ok"
    assert _stats_of(world.brown)["games_played"] == 1
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE players SET jersey_number = '8' WHERE id = %s", (world.brown,))
            cur.execute("UPDATE players SET jersey_number = '7' WHERE id = %s", (world.white,))
        conn.commit()

    resync = ResyncTeamAnalysesUseCase(jobs=PostgresJobRepository(connection=connection), sync=sync)
    assert resync.execute(world.team) == 1

    assert _stats_of(world.brown)["games_played"] == 0
    assert _stats_of(world.white)["games_played"] == 1
    assert _stats_of(world.white)["field_goals"]["attempted_total"] == 2
    shots = _repo().list_shots(owner_user_id=world.user, player_id=world.white)
    assert len(shots) == 2 and _repo().list_shots(owner_user_id=world.user, player_id=world.brown) == []


# ---------------------------------------------------------------------------------------------
# The real clips: the response models accept what the real analyses produce.
# ---------------------------------------------------------------------------------------------

REAL_RESULTS = Path("/home/fede/tpf/analysis-results")
REAL_CLIPS = {"brown3pt": "86f87c1b-ad65-414a-83c2-63e0f6cd088f", "brown2pts": "804f1784-b097-47a2-a69a-857128731159"}


class _DirReader:
    """Reads a job's result files from the saved analysis folders instead of object storage."""

    def read_json(self, *, results_key, filename):
        path = REAL_RESULTS / results_key / filename
        return json.loads(path.read_text()) if path.exists() else None

    def read_jsonl(self, *, results_key, filename, max_lines):
        path = REAL_RESULTS / results_key / filename
        lines = path.read_text().splitlines() if path.exists() else []
        return [json.loads(line) for line in lines if line.strip()][:max_lines]


@pytest.mark.skipif(not all((REAL_RESULTS / job).exists() for job in REAL_CLIPS.values()),
                    reason="the saved analysis results are not on this machine")
def test_the_response_models_accept_the_real_brown_clips() -> None:
    from src.application.stats.use_cases import GetGameStatsUseCase
    from src.interfaces.http.schemas.player_analysis import AnalysisStatsResponse, ShotChartResponse

    world = World()
    connection = OperationConnection(_dsn())
    jobs = PostgresJobRepository(connection=connection)
    players = PostgresPlayerRepository(connection=connection)
    analysis = PostgresPlayerAnalysisRepository(connection=connection)
    game = GetGameStatsUseCase(jobs=jobs, artifacts=_DirReader(), team_access=_Access(), roster=players)
    sync = SyncPlayerAnalysisUseCase(jobs=jobs, game_stats=game.execute, analysis=analysis)
    for title, job in REAL_CLIPS.items():
        shots = json.loads((REAL_RESULTS / job / "projected_shots.json").read_text())["shots"]
        side = shots[0]["shooter_team_id"]
        video = str(uuid4())
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                world.add_video(cur, video, title)
                cur.execute("INSERT INTO processing_jobs (id, video_id, team_id, requested_by_user_id, status, "
                            "results_key, our_team_side, created_at, updated_at) "
                            "VALUES (%s, %s, %s, %s, 'DONE', %s, %s, NOW(), NOW())",
                            (job, video, world.team, world.user, job, side))
            conn.commit()
        assert sync.execute(job).status == "ok"

    chart = GetPlayerShotChartUseCase(players=players, analysis=analysis).execute(user_id=world.user,
                                                                                 player_id=world.brown)
    totals = GetPlayerAnalysisStatsUseCase(players=players, analysis=analysis).execute(user_id=world.user,
                                                                                     player_id=world.brown)
    parsed_chart, parsed_totals = ShotChartResponse.model_validate(chart), AnalysisStatsResponse.model_validate(totals)
    assert parsed_chart.coverage.shots_charted == len(chart["shots"]) > 0
    assert len({shot.shot_key for shot in parsed_chart.shots}) == len(chart["shots"])
    assert parsed_totals.games == 2 and parsed_totals.calc_version == 2
    json.dumps(parsed_chart.model_dump(mode="json"), allow_nan=False)
    json.dumps(parsed_totals.model_dump(mode="json"), allow_nan=False)
