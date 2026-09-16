FORBIDDEN_TEAM_ACCESS = "FORBIDDEN_TEAM_ACCESS"
VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
CLIP_COLLECTION_NOT_FOUND = "CLIP_COLLECTION_NOT_FOUND"
CLIP_COLLECTION_ITEM_NOT_FOUND = "CLIP_COLLECTION_ITEM_NOT_FOUND"
INVALID_CLIP_RANGE = "INVALID_CLIP_RANGE"
CLIP_EXPORT_FAILED = "CLIP_EXPORT_FAILED"


class ClipCollectionError(Exception):
    def __init__(self, *, code: str, message: str, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)

    def to_envelope(self) -> dict[str, object]:
        error: dict[str, object] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


def clip_collection_error_http_status(code: str) -> int:
    if code == FORBIDDEN_TEAM_ACCESS:
        return 403
    if code in (VIDEO_NOT_FOUND, CLIP_COLLECTION_NOT_FOUND, CLIP_COLLECTION_ITEM_NOT_FOUND):
        return 404
    if code == CLIP_EXPORT_FAILED:
        return 502
    return 400
