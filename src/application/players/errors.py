PLAYER_NOT_FOUND = "PLAYER_NOT_FOUND"


class PlayerError(Exception):
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


def player_error_http_status(code: str) -> int:
    if code == PLAYER_NOT_FOUND:
        return 404
    return 400
