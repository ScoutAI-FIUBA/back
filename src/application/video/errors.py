FORBIDDEN_TEAM_ACCESS = "FORBIDDEN_TEAM_ACCESS"
TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
VIDEO_NOT_READY = "VIDEO_NOT_READY"
UPLOAD_NOT_INITIALIZED = "UPLOAD_NOT_INITIALIZED"
VIDEO_STORAGE_KEY_CONFLICT = "VIDEO_STORAGE_KEY_CONFLICT"
PLAYER_TEAM_MISMATCH = "PLAYER_TEAM_MISMATCH"
STORAGE_DELETE_FAILED = "STORAGE_DELETE_FAILED"


class VideoError(Exception):
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


def video_error_http_status(code: str) -> int:
    if code == FORBIDDEN_TEAM_ACCESS:
        return 403
    if code in (TEAM_NOT_FOUND, VIDEO_NOT_FOUND):
        return 404
    if code in (VIDEO_NOT_READY, UPLOAD_NOT_INITIALIZED, VIDEO_STORAGE_KEY_CONFLICT):
        return 409
    if code == PLAYER_TEAM_MISMATCH:
        return 422
    if code == STORAGE_DELETE_FAILED:
        return 502
    return 400
