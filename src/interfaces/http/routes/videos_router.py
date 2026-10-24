from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.video.errors import VideoError, video_error_http_status
from src.application.video.use_cases import (
    AbortVideoUploadCommand,
    AbortVideoUploadUseCase,
    CompleteVideoUploadCommand,
    CompleteVideoUploadUseCase,
    DeleteVideoCommand,
    DeleteVideoUseCase,
    GetVideoUseCase,
    InitVideoUploadCommand,
    InitVideoUploadUseCase,
    ListVideosUseCase,
    SetVideoMatchCommand,
    SetVideoMatchUseCase,
    UpdateVideoCommand,
    UpdateVideoUseCase,
)


class InitUploadPayload(BaseModel):
    team_id: UUID
    title: str = Field(min_length=1, max_length=180)
    description: str | None = None
    content_type: str | None = None
    part_count: int = Field(default=3, ge=1, le=1000)


class MultipartPartPayload(BaseModel):
    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1)


class CompleteUploadPayload(BaseModel):
    team_id: UUID
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    upload_id: str = Field(min_length=1)
    parts: list[MultipartPartPayload] = Field(min_length=1)


class AbortUploadPayload(BaseModel):
    team_id: UUID
    upload_id: str = Field(min_length=1)


class UpdateVideoPayload(BaseModel):
    team_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = None
    player_ids: list[UUID] | None = None


class SetVideoMatchPayload(BaseModel):
    team_id: UUID
    match_id: UUID | None


def _video_to_dict(video) -> dict[str, object]:
    return {
        "id": video.id,
        "team_id": video.team_id,
        "owner_user_id": video.owner_user_id,
        "storage_key": video.storage_key,
        "title": video.title,
        "description": video.description,
        "status": video.status.value,
        "mime_type": video.mime_type,
        "size_bytes": video.size_bytes,
        "duration_ms": video.duration_ms,
        "etag": video.etag,
        "upload_expires_at": video.upload_expires_at.isoformat() if video.upload_expires_at else None,
        "created_at": video.created_at.isoformat(),
        "updated_at": video.updated_at.isoformat(),
        "match_id": video.match_id,
    }


def create_videos_router(
    *,
    init_upload_use_case: InitVideoUploadUseCase,
    complete_upload_use_case: CompleteVideoUploadUseCase,
    abort_upload_use_case: AbortVideoUploadUseCase,
    list_videos_use_case: ListVideosUseCase,
    get_video_use_case: GetVideoUseCase,
    update_video_use_case: UpdateVideoUseCase,
    delete_video_use_case: DeleteVideoUseCase,
    set_video_match_use_case: SetVideoMatchUseCase,
) -> APIRouter:
    router = APIRouter(prefix="/videos", tags=["videos"])

    @router.post("/upload/init", status_code=HTTPStatus.CREATED, response_model=None)
    def init_upload(payload: InitUploadPayload, request: Request):
        try:
            user_id = str(request.state.user_id)
            video, upload_id, part_urls = init_upload_use_case.execute(
                InitVideoUploadCommand(
                    user_id=user_id,
                    team_id=str(payload.team_id),
                    title=payload.title,
                    description=payload.description,
                    content_type=payload.content_type,
                    part_count=payload.part_count,
                )
            )
            return {
                "video_id": video.id,
                "storage_key": video.storage_key,
                "upload_id": upload_id,
                "parts": part_urls,
                # Expires-at is persisted on init so clients know upload window.
                "expires_at": video.upload_expires_at.isoformat() if video.upload_expires_at else None,
                "status": video.status.value,
            }
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/{video_id}/upload/complete", response_model=None)
    def complete_upload(video_id: UUID, payload: CompleteUploadPayload, request: Request):
        try:
            video = complete_upload_use_case.execute(
                CompleteVideoUploadCommand(
                    user_id=str(request.state.user_id),
                    team_id=str(payload.team_id),
                    video_id=str(video_id),
                    mime_type=payload.mime_type,
                    size_bytes=payload.size_bytes,
                    duration_ms=payload.duration_ms,
                    multipart_upload_id=payload.upload_id,
                    parts=[{"PartNumber": part.part_number, "ETag": part.etag} for part in payload.parts],
                )
            )
            return {"video": _video_to_dict(video)}
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/{video_id}/upload/abort", status_code=HTTPStatus.NO_CONTENT, response_model=None)
    def abort_upload(video_id: UUID, payload: AbortUploadPayload, request: Request):
        try:
            abort_upload_use_case.execute(
                AbortVideoUploadCommand(
                    user_id=str(request.state.user_id),
                    team_id=str(payload.team_id),
                    video_id=str(video_id),
                    multipart_upload_id=payload.upload_id,
                )
            )
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("", response_model=None)
    def list_videos(team_id: UUID, request: Request, status: str | None = None):
        try:
            videos = list_videos_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                status=status,
            )
            return {"videos": [_video_to_dict(video) for video in videos]}
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{video_id}", response_model=None)
    def get_video(video_id: UUID, team_id: UUID, request: Request):
        try:
            video, playback_url, thumbnail_url = get_video_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                video_id=str(video_id),
            )
            return {
                "video": _video_to_dict(video),
                "presigned_playback_url": playback_url,
                "presigned_thumbnail_url": thumbnail_url,
            }
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.patch("/{video_id}", response_model=None)
    def update_video(video_id: UUID, payload: UpdateVideoPayload, request: Request):
        try:
            video = update_video_use_case.execute(
                UpdateVideoCommand(
                    user_id=str(request.state.user_id),
                    team_id=str(payload.team_id),
                    video_id=str(video_id),
                    title=payload.title,
                    description=payload.description,
                    player_ids=[str(player_id) for player_id in payload.player_ids] if payload.player_ids else None,
                )
            )
            return {"video": _video_to_dict(video)}
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.put("/{video_id}/match", response_model=None)
    def set_video_match(video_id: UUID, payload: SetVideoMatchPayload, request: Request):
        # Dedicated endpoint: PATCH treats a missing/None field as "unchanged", but here
        # an explicit null must clear the link.
        try:
            video = set_video_match_use_case.execute(
                SetVideoMatchCommand(
                    user_id=str(request.state.user_id),
                    team_id=str(payload.team_id),
                    video_id=str(video_id),
                    match_id=str(payload.match_id) if payload.match_id is not None else None,
                )
            )
            return {"video": _video_to_dict(video)}
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    @router.delete("/{video_id}", response_model=None)
    def delete_video(video_id: UUID, team_id: UUID, request: Request):
        try:
            result = delete_video_use_case.execute(
                DeleteVideoCommand(
                    user_id=str(request.state.user_id),
                    team_id=str(team_id),
                    video_id=str(video_id),
                )
            )
            if result.get("compensation_pending"):
                return JSONResponse(status_code=HTTPStatus.ACCEPTED, content=result)
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except VideoError as exc:
            return JSONResponse(status_code=video_error_http_status(exc.code), content=exc.to_envelope())

    return router
