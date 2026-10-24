from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from src.application.video.errors import (
    MATCH_NOT_FOUND,
    TEAM_NOT_FOUND,
    VIDEO_NOT_FOUND,
    VIDEO_TEAM_NOT_IN_MATCH,
    VideoError,
    video_error_http_status,
)
from src.application.video.use_cases import SetVideoMatchCommand, SetVideoMatchUseCase
from src.domain.video.entities import Video, VideoStatus

HOME, AWAY, OTHER_TEAM = "team-home", "team-away", "team-other"


def _video(video_id: str, team_id: str, status: VideoStatus = VideoStatus.READY) -> Video:
    now = datetime.now(timezone.utc)
    return Video(
        id=video_id, team_id=team_id, owner_user_id="user-1", storage_key=f"videos/{video_id}",
        title="V", description=None, status=status, mime_type=None, size_bytes=None, duration_ms=None,
        etag=None, upload_expires_at=None, multipart_upload_id=None, deleted_at=None,
        created_at=now, updated_at=now,
    )


class _Repo:
    def __init__(self) -> None:
        self.by_id: dict[str, Video] = {}

    def get_by_id(self, *, video_id: str, team_id: str):
        v = self.by_id.get(video_id)
        return v if v and v.team_id == team_id and v.deleted_at is None else None

    def set_match(self, *, video_id: str, team_id: str, match_id):
        v = self.get_by_id(video_id=video_id, team_id=team_id)
        if v is None:
            return None
        self.by_id[video_id] = replace(v, match_id=match_id)
        return self.by_id[video_id]


class _Matches:
    def __init__(self) -> None:
        self.teams = {("m1", "user-1"): (HOME, AWAY), ("m2", "user-1"): (HOME, OTHER_TEAM), ("mx", "user-2"): (HOME, AWAY)}

    def get_teams(self, *, match_id: str, owner_user_id: str):
        return self.teams.get((match_id, owner_user_id))


class _Access:
    def assert_access(self, *, user_id: str, team_id: str) -> None:
        if user_id != "user-1" or team_id.startswith("foreign"):
            raise VideoError(code=TEAM_NOT_FOUND, message="Team not found")


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestSetVideoMatch(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _Repo()
        for vid, team in (("v-home", HOME), ("v-away", AWAY), ("v-other", OTHER_TEAM)):
            self.repo.by_id[vid] = _video(vid, team)
        self.uc = SetVideoMatchUseCase(videos=self.repo, matches=_Matches(), team_access=_Access(), uow=_Uow())

    def _run(self, video_id: str, team_id: str, match_id, user_id: str = "user-1") -> Video:
        return self.uc.execute(SetVideoMatchCommand(user_id=user_id, team_id=team_id, video_id=video_id, match_id=match_id))

    def test_links_home_team_and_away_team_videos(self) -> None:
        self.assertEqual(self._run("v-home", HOME, "m1").match_id, "m1")
        self.assertEqual(self._run("v-away", AWAY, "m1").match_id, "m1")

    def test_one_match_can_hold_several_videos(self) -> None:
        self.repo.by_id["v-home-2"] = _video("v-home-2", HOME)
        self._run("v-home", HOME, "m1")
        self._run("v-home-2", HOME, "m1")
        self._run("v-away", AWAY, "m1")
        self.assertEqual({v.id for v in self.repo.by_id.values() if v.match_id == "m1"}, {"v-home", "v-home-2", "v-away"})

    def test_other_users_match_is_404_and_leaves_video_untouched(self) -> None:
        with self.assertRaises(VideoError) as ctx:
            self._run("v-home", HOME, "mx")
        self.assertEqual(ctx.exception.code, MATCH_NOT_FOUND)
        self.assertEqual(video_error_http_status(ctx.exception.code), 404)
        self.assertIsNone(self.repo.by_id["v-home"].match_id)

    def test_unknown_match_is_404(self) -> None:
        with self.assertRaises(VideoError) as ctx:
            self._run("v-home", HOME, "nope")
        self.assertEqual(ctx.exception.code, MATCH_NOT_FOUND)

    def test_video_team_not_in_match_is_422(self) -> None:
        with self.assertRaises(VideoError) as ctx:
            self._run("v-other", OTHER_TEAM, "m1")
        self.assertEqual(ctx.exception.code, VIDEO_TEAM_NOT_IN_MATCH)
        self.assertEqual(video_error_http_status(ctx.exception.code), 422)
        self.assertIsNone(self.repo.by_id["v-other"].match_id)

    def test_wrong_team_id_for_the_video_is_404(self) -> None:
        with self.assertRaises(VideoError) as ctx:
            self._run("v-home", AWAY, "m1")
        self.assertEqual(ctx.exception.code, VIDEO_NOT_FOUND)

    def test_team_not_owned_is_404(self) -> None:
        with self.assertRaises(VideoError) as ctx:
            self._run("v-home", "foreign-team", "m1")
        self.assertEqual(ctx.exception.code, TEAM_NOT_FOUND)

    def test_deleted_video_is_rejected(self) -> None:
        self.repo.by_id["v-home"] = replace(
            self.repo.by_id["v-home"], status=VideoStatus.DELETED, deleted_at=datetime.now(timezone.utc)
        )
        with self.assertRaises(VideoError) as ctx:
            self._run("v-home", HOME, "m1")
        self.assertEqual(ctx.exception.code, VIDEO_NOT_FOUND)

    def test_null_clears_the_link(self) -> None:
        self._run("v-home", HOME, "m1")
        self.assertIsNone(self._run("v-home", HOME, None).match_id)

    def test_relinking_overwrites_previous_match(self) -> None:
        self._run("v-home", HOME, "m1")
        self.assertEqual(self._run("v-home", HOME, "m2").match_id, "m2")
