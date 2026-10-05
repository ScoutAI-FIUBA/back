from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.clip_collections.errors import ClipCollectionError, clip_collection_error_http_status
from src.application.clip_collections.use_cases import (
    AddClipBatchCommand,
    AddClipCommand,
    AddClipBatchUseCase,
    AddClipUseCase,
    CreateClipCollectionCommand,
    CreateClipCollectionUseCase,
    DeleteClipCollectionItemCommand,
    DeleteClipCollectionItemUseCase,
    ExportClipItemCommand,
    ExportClipItemUseCase,
    GetClipCollectionDetailUseCase,
    ListClipCollectionsUseCase,
    UpdateClipDescriptionCommand,
    UpdateClipDescriptionUseCase,
)


class CreateCollectionPayload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str | None = None


class ClipPayload(BaseModel):
    start_ms: int
    end_ms: int
    description: str | None = Field(default=None, max_length=200)


class AddClipBatchPayload(BaseModel):
    clips: list[ClipPayload] = Field(min_length=1)


class UpdateClipPayload(BaseModel):
    description: str | None = Field(default=None, max_length=200)


def _collection_to_dict(collection) -> dict[str, object]:
    return {
        "id": collection.id,
        "video_id": collection.video_id,
        "team_id": collection.team_id,
        "owner_user_id": collection.owner_user_id,
        "name": collection.name,
        "description": collection.description,
        "created_at": collection.created_at.isoformat(),
        "updated_at": collection.updated_at.isoformat(),
    }


def _item_to_dict(item) -> dict[str, object]:
    return {
        "id": item.id,
        "collection_id": item.collection_id,
        "start_ms": item.start_ms,
        "end_ms": item.end_ms,
        "description": item.description,
        "position": item.position,
        "created_at": item.created_at.isoformat(),
    }


def create_clip_collections_router(
    *,
    create_collection_use_case: CreateClipCollectionUseCase,
    list_collections_use_case: ListClipCollectionsUseCase,
    get_collection_detail_use_case: GetClipCollectionDetailUseCase,
    add_clip_use_case: AddClipUseCase,
    add_clip_batch_use_case: AddClipBatchUseCase,
    delete_item_use_case: DeleteClipCollectionItemUseCase,
    export_clip_item_use_case: ExportClipItemUseCase,
    update_clip_description_use_case: UpdateClipDescriptionUseCase,
) -> APIRouter:
    router = APIRouter(prefix="/videos/{video_id}/collections", tags=["clip-collections"])

    @router.post("", status_code=HTTPStatus.CREATED, response_model=None)
    def create_collection(video_id: UUID, payload: CreateCollectionPayload, request: Request):
        try:
            collection = create_collection_use_case.execute(
                CreateClipCollectionCommand(
                    user_id=str(request.state.user_id),
                    video_id=str(video_id),
                    name=payload.name,
                    description=payload.description,
                )
            )
            return {"collection": _collection_to_dict(collection)}
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("", response_model=None)
    def list_collections(video_id: UUID, request: Request):
        try:
            collections = list_collections_use_case.execute(user_id=str(request.state.user_id), video_id=str(video_id))
            return {"collections": [_collection_to_dict(collection) for collection in collections]}
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{collection_id}", response_model=None)
    def get_collection_detail(video_id: UUID, collection_id: UUID, request: Request):
        try:
            collection, items = get_collection_detail_use_case.execute(
                user_id=str(request.state.user_id),
                video_id=str(video_id),
                collection_id=str(collection_id),
            )
            return {
                "collection": _collection_to_dict(collection),
                "items": [_item_to_dict(item) for item in items],
            }
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/{collection_id}/clips", status_code=HTTPStatus.CREATED, response_model=None)
    def add_clip(video_id: UUID, collection_id: UUID, payload: ClipPayload, request: Request):
        try:
            item = add_clip_use_case.execute(
                AddClipCommand(
                    user_id=str(request.state.user_id),
                    video_id=str(video_id),
                    collection_id=str(collection_id),
                    start_ms=payload.start_ms,
                    end_ms=payload.end_ms,
                    description=payload.description,
                )
            )
            return {"item": _item_to_dict(item)}
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/{collection_id}/clips/batch", status_code=HTTPStatus.CREATED, response_model=None)
    def add_clip_batch(video_id: UUID, collection_id: UUID, payload: AddClipBatchPayload, request: Request):
        try:
            items = add_clip_batch_use_case.execute(
                AddClipBatchCommand(
                    user_id=str(request.state.user_id),
                    video_id=str(video_id),
                    collection_id=str(collection_id),
                    clips=[
                        AddClipCommand(
                            user_id=str(request.state.user_id),
                            video_id=str(video_id),
                            collection_id=str(collection_id),
                            start_ms=clip.start_ms,
                            end_ms=clip.end_ms,
                            description=clip.description,
                        )
                        for clip in payload.clips
                    ],
                )
            )
            return {"items": [_item_to_dict(item) for item in items]}
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.delete("/{collection_id}/clips/{item_id}", status_code=HTTPStatus.NO_CONTENT, response_model=None)
    def delete_clip(video_id: UUID, collection_id: UUID, item_id: UUID, request: Request):
        try:
            delete_item_use_case.execute(
                DeleteClipCollectionItemCommand(
                    user_id=str(request.state.user_id),
                    video_id=str(video_id),
                    collection_id=str(collection_id),
                    item_id=str(item_id),
                )
            )
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.patch("/{collection_id}/clips/{item_id}", response_model=None)
    def update_clip_description(video_id: UUID, collection_id: UUID, item_id: UUID, payload: UpdateClipPayload, request: Request):
        try:
            item = update_clip_description_use_case.execute(
                UpdateClipDescriptionCommand(
                    user_id=str(request.state.user_id),
                    video_id=str(video_id),
                    collection_id=str(collection_id),
                    item_id=str(item_id),
                    description=payload.description,
                )
            )
            return {"item": _item_to_dict(item)}
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/{collection_id}/clips/{item_id}/export", response_model=None)
    def export_clip(video_id: UUID, collection_id: UUID, item_id: UUID, request: Request):
        try:
            download_url = export_clip_item_use_case.execute(
                ExportClipItemCommand(
                    user_id=str(request.state.user_id),
                    video_id=str(video_id),
                    collection_id=str(collection_id),
                    item_id=str(item_id),
                )
            )
            return {"download_url": download_url}
        except ClipCollectionError as exc:
            return JSONResponse(status_code=clip_collection_error_http_status(exc.code), content=exc.to_envelope())

    return router
