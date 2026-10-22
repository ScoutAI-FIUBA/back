MATCH_NOT_FOUND = "MATCH_NOT_FOUND"
TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
PLAYER_NOT_FOUND = "PLAYER_NOT_FOUND"
INVALID_MATCH_TEAMS = "INVALID_MATCH_TEAMS"
INVALID_WINNER_TEAM = "INVALID_WINNER_TEAM"
INVALID_STATS_FILE = "INVALID_STATS_FILE"
STATS_FILE_TOO_LARGE = "STATS_FILE_TOO_LARGE"
TEAM_MISMATCH = "TEAM_MISMATCH"


class MatchError(Exception):
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


def match_error_http_status(code: str) -> int:
    if code in (MATCH_NOT_FOUND, TEAM_NOT_FOUND, PLAYER_NOT_FOUND):
        return 404
    if code in (INVALID_MATCH_TEAMS, INVALID_WINNER_TEAM, INVALID_STATS_FILE, TEAM_MISMATCH):
        return 422
    if code == STATS_FILE_TOO_LARGE:
        return 413
    return 400
