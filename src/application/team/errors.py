TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
TEAM_HAS_MATCHES = "TEAM_HAS_MATCHES"
TEAM_DELETE_CONFLICT = "TEAM_DELETE_CONFLICT"


class TeamError(Exception):
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


def team_error_http_status(code: str) -> int:
    if code == TEAM_NOT_FOUND:
        return 404
    if code in {TEAM_HAS_MATCHES, TEAM_DELETE_CONFLICT}:
        return 409
    return 400
