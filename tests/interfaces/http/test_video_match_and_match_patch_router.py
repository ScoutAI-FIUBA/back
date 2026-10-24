from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.matches.use_cases import GetMatchUseCase, UpdateMatchDetailsUseCase
from src.application.video.errors import TEAM_NOT_FOUND, VideoError
from src.application.video.use_cases import ListVideosUseCase, SetVideoMatchUseCase
from src.domain.matches.entities import Match
from src.domain.video.entities import Video, VideoStatus
from src.interfaces.http.routes.matches_router import create_matches_router
from src.interfaces.http.routes.videos_router import create_videos_router

HOME = "00000000-0000-4000-8000-000000000010"
AWAY = "00000000-0000-4000-8000-000000000020"
OTHER = "00000000-0000-4000-8000-000000000030"
MATCH = "00000000-0000-4000-8000-000000000001"
FOREIGN_MATCH = "00000000-0000-4000-8000-000000000002"
VIDEO = "00000000-0000-4000-8000-0000000000a1"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class _Access:
    def assert_access(self, *, user_id, team_id):
        if team_id not in (HOME, AWAY, OTHER):
            raise VideoError(code=TEAM_NOT_FOUND, message="Team not found")


class _Videos:
    def __init__(self) -> None:
        self.video = Video(
            id=VIDEO, team_id=HOME, owner_user_id="user-1", storage_key="k", title="T", description=None,
            status=VideoStatus.READY, mime_type=None, size_bytes=None, duration_ms=None, etag=None,
            upload_expires_at=None, multipart_upload_id=None, deleted_at=None, created_at=NOW, updated_at=NOW,
        )

    def get_by_id(self, *, video_id, team_id):
        return self.video if (video_id, team_id) == (VIDEO, self.video.team_id) else None

    def list_by_team(self, *, team_id, status=None):
        return [self.video] if team_id == self.video.team_id else []

    def set_match(self, *, video_id, team_id, match_id):
        self.video = replace(self.video, match_id=match_id)
        return self.video


class _Matches:
    def __init__(self) -> None:
        self.match = Match(
            id=MATCH, owner_user_id="user-1", home_team_id=HOME, away_team_id=AWAY,
            match_date=date(2024, 1, 1), description="old", winner_team_id=HOME, stats={"s": 1},
            created_at=NOW, updated_at=NOW,
        )

    def get_teams(self, *, match_id, owner_user_id):
        return (HOME, AWAY) if (match_id, owner_user_id) == (MATCH, "user-1") else None

    def get_by_id(self, *, match_id, owner_user_id):
        return self.match if (match_id, owner_user_id) == (MATCH, "user-1") else None

    def update_details(self, *, match_id, owner_user_id, match_date, update_description, description):
        found = self.get_by_id(match_id=match_id, owner_user_id=owner_user_id)
        if found is None:
            return None
        self.match = replace(
            found,
            match_date=match_date or found.match_date,
            description=description if update_description else found.description,
        )
        return self.match


class _Unused:
    def execute(self, *a, **k):  # pragma: no cover
        raise AssertionError("not used")


def _app(videos: _Videos, matches: _Matches) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    access = _Access()
    app.include_router(
        create_videos_router(
            init_upload_use_case=_Unused(), complete_upload_use_case=_Unused(), abort_upload_use_case=_Unused(),
            list_videos_use_case=ListVideosUseCase(videos=videos, team_access=access),
            get_video_use_case=_Unused(), update_video_use_case=_Unused(), delete_video_use_case=_Unused(),
            set_video_match_use_case=SetVideoMatchUseCase(
                videos=videos, matches=matches, team_access=access, uow=_Uow()
            ),
        )
    )
    app.include_router(
        create_matches_router(
            create_match_use_case=_Unused(), list_matches_use_case=_Unused(),
            get_match_use_case=GetMatchUseCase(matches=matches),
            replace_match_stats_use_case=_Unused(), get_match_stats_use_case=_Unused(),
            update_match_use_case=UpdateMatchDetailsUseCase(matches=matches, uow=_Uow()),
        )
    )
    return app


class TestVideoMatchRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.videos, self.matches = _Videos(), _Matches()
        self.client = TestClient(_app(self.videos, self.matches))

    def test_match_id_in_list_and_set_responses(self) -> None:
        self.assertIsNone(self.client.get(f"/videos?team_id={HOME}").json()["videos"][0]["match_id"])
        put = self.client.put(f"/videos/{VIDEO}/match", json={"team_id": HOME, "match_id": MATCH})
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.json()["video"]["match_id"], MATCH)
        self.assertEqual(self.client.get(f"/videos?team_id={HOME}").json()["videos"][0]["match_id"], MATCH)

    def test_null_clears(self) -> None:
        self.client.put(f"/videos/{VIDEO}/match", json={"team_id": HOME, "match_id": MATCH})
        put = self.client.put(f"/videos/{VIDEO}/match", json={"team_id": HOME, "match_id": None})
        self.assertEqual(put.status_code, 200)
        self.assertIsNone(put.json()["video"]["match_id"])

    def test_error_codes(self) -> None:
        put = lambda body: self.client.put(f"/videos/{VIDEO}/match", json=body)  # noqa: E731
        r = put({"team_id": HOME, "match_id": FOREIGN_MATCH})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "MATCH_NOT_FOUND"))
        self.videos.video = replace(self.videos.video, team_id=OTHER)
        r = self.client.put(f"/videos/{VIDEO}/match", json={"team_id": OTHER, "match_id": MATCH})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "VIDEO_TEAM_NOT_IN_MATCH"))
        r = put({"team_id": HOME, "match_id": MATCH})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "VIDEO_NOT_FOUND"))

    def test_bad_uuid_and_missing_fields_are_422(self) -> None:
        self.assertEqual(self.client.put(f"/videos/{VIDEO}/match", json={"team_id": HOME, "match_id": "x"}).status_code, 422)
        self.assertEqual(self.client.put(f"/videos/{VIDEO}/match", json={"team_id": "x", "match_id": None}).status_code, 422)
        self.assertEqual(self.client.put(f"/videos/{VIDEO}/match", json={"team_id": HOME}).status_code, 422)
        self.assertEqual(self.client.put("/videos/not-a-uuid/match", json={"team_id": HOME, "match_id": None}).status_code, 422)


class TestPatchMatchRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.matches = _Matches()
        self.client = TestClient(_app(_Videos(), self.matches))

    def patch(self, body, match_id=MATCH):
        return self.client.patch(f"/matches/{match_id}", json=body)

    def test_updates_date_and_description_keeping_the_rest(self) -> None:
        r = self.patch({"match_date": "2025-02-03", "description": "new"})
        self.assertEqual(r.status_code, 200)
        m = r.json()["match"]
        self.assertEqual((m["match_date"], m["description"]), ("2025-02-03", "new"))
        self.assertEqual((m["home_team_id"], m["away_team_id"], m["winner_team_id"], m["stats"]), (HOME, AWAY, HOME, {"s": 1}))

    def test_null_description_clears_and_omitted_keeps(self) -> None:
        self.assertIsNone(self.patch({"description": None}).json()["match"]["description"])
        self.matches.match = replace(self.matches.match, description="keep")
        m = self.patch({"match_date": "2025-02-03"}).json()["match"]
        self.assertEqual(m["description"], "keep")
        self.assertEqual(self.patch({"description": "d"}).json()["match"]["match_date"], "2025-02-03")

    def test_validation(self) -> None:
        self.assertEqual(self.patch({"description": "x" * 2000}).status_code, 200)
        self.assertEqual(self.patch({"description": "x" * 2001}).status_code, 422)
        self.assertEqual(self.patch({"match_date": "nope"}).status_code, 422)
        self.assertEqual(self.patch({"match_date": None}).status_code, 422)

    def test_other_users_match_is_404(self) -> None:
        r = self.patch({"description": "hack"}, match_id=FOREIGN_MATCH)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "MATCH_NOT_FOUND"))
        self.assertEqual(self.patch({}, match_id=FOREIGN_MATCH).status_code, 404)

    def test_teams_cannot_be_edited_and_no_delete_route(self) -> None:
        for body in (
            {"home_team_id": OTHER},
            {"away_team_id": OTHER},
            {"winner_team_id": OTHER},
            {"stats": {"x": 1}},
            {"description": "ok", "home_team_id": OTHER},
        ):
            self.assertEqual(self.patch(body).status_code, 422, body)
        self.assertEqual(self.matches.match.description, "old")
        self.assertEqual(self.matches.match.home_team_id, HOME)
        self.assertEqual(self.matches.match.winner_team_id, HOME)
        self.assertEqual(self.client.delete(f"/matches/{MATCH}").status_code, 405)
        paths_methods = {(r.path, m) for r in self.client.app.routes if hasattr(r, "methods") for m in r.methods}
        self.assertNotIn(("/matches/{match_id}", "DELETE"), paths_methods)
