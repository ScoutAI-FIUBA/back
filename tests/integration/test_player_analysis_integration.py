from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from src.application.jobs.use_cases import RecordJobProgressCommand, RecordJobProgressUseCase, SetJobTeamSideUseCase
from src.application.stats.player_analysis import SyncPlayerAnalysisUseCase, safe_sync
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


@pytest.fixture(scope="session", autouse=True)
def _schema_ready() -> None:
    dirs = [Path(f"src/infrastructure/{name}/migrations") for name in
            ("auth", "players", "team", "matches", "video", "clip_collections", "jobs", "ownership")]
    try:
        with psycopg.connect(_dsn()) as conn:
            with conn.cursor() as cur:
                for directory in dirs:
                    for file in sorted(directory.glob("*.sql")):
                        cur.execute(file.read_text(encoding="utf-8"))
            conn.commit()
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

    def add_job(self, cur, job_id: str, video_id: str, status: str, side: int | None = None) -> None:
        cur.execute("INSERT INTO processing_jobs (id, video_id, team_id, requested_by_user_id, status, results_key, "
                    "our_team_side, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())",
                    (job_id, video_id, self.team, self.user, status, f"results/{job_id}/", side))


def _repo() -> PostgresPlayerAnalysisRepository:
    return PostgresPlayerAnalysisRepository(connection=OperationConnection(_dsn()))


def _game(world: World, player: str, *, points=3, fgm=1, fga=1, three_m=1, three_a=1, job=None, video=None, seconds=10.5):
    return PlayerGameRow(player, job or world.job, video or world.video, world.user, "7", seconds, 21.0,
                         points, fgm, fga, 0, 0, three_m, three_a, 0)


def _shot(world: World, player: str, shot_id: int, outcome: str, x: float, y: float, *, job=None, video=None,
          points=3, zone="corner_three"):
    return PlayerShotRow(player, job or world.job, video or world.video, world.user, shot_id, outcome, points, zone,
                         "jump_shot", 7.4, x, y, 6.6, "action_box_vote", False)


def _stats_of(player_id: str) -> dict:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT stats FROM players WHERE id = %s", (player_id,))
            return cur.fetchone()["stats"]


def test_a_video_is_kept_and_the_player_totals_are_filled() -> None:
    world = World()
    affected = _repo().replace_video(
        video_id=world.video,
        games=[_game(world, world.brown)],
        shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)],
    )
    assert affected == [world.brown]

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
    repo.replace_video(
        video_id=world.video,
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
    repo.replace_video(video_id=world.video, games=[_game(world, world.brown)],
                       shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)])
    two_point = dict(points=2, fgm=1, fga=1, three_m=0, three_a=0, job=second_job, video=second_video)
    repo.replace_video(
        video_id=second_video,
        games=[PlayerGameRow(world.brown, second_job, second_video, world.user, "7", 12.0, 18.0, 2, 1, 1, 1, 1, 0, 0, 0)],
        shots=[_shot(world, world.brown, 1, "made", 6.0, 7.0, job=second_job, video=second_video, points=2, zone="paint")])

    assert _stats_of(world.brown)["games_played"] == 2
    assert _stats_of(world.brown)["points"]["total"] == 5
    assert len(repo.list_shots(owner_user_id=world.user, player_id=world.brown)) == 2

    # Analysing the first video again must replace its rows, not add to them.
    repo.replace_video(video_id=world.video, games=[_game(world, world.brown)],
                       shots=[_shot(world, world.brown, 1, "made", 23.8, 14.4)])
    assert _stats_of(world.brown)["points"]["total"] == 5
    assert len(repo.list_shots(owner_user_id=world.user, player_id=world.brown)) == 2
    del two_point


def test_a_player_no_longer_linked_in_the_new_analysis_is_reset() -> None:
    world = World()
    repo = _repo()
    repo.replace_video(video_id=world.video, games=[_game(world, world.brown)], shots=[])
    assert _stats_of(world.brown)["games_played"] == 1
    repo.replace_video(video_id=world.video, games=[_game(world, world.white, points=0, fgm=0, fga=0, three_m=0, three_a=0)], shots=[])
    assert _stats_of(world.brown)["games_played"] == 0 and _stats_of(world.brown)["points"]["total"] == 0
    assert _stats_of(world.white)["games_played"] == 1


def test_a_deleted_video_stops_counting() -> None:
    world = World()
    repo = _repo()
    repo.replace_video(video_id=world.video, games=[_game(world, world.brown)],
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
    repo.replace_video(video_id=world.video, games=[_game(world, world.brown)],
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
    assert sync.execute(new_job) == 0
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
    assert sync.execute(world.job) == 0          # the older one is ignored
    assert calls == []
    assert sync.execute(newer) == 1              # the newest one is kept
    assert calls == [newer]
