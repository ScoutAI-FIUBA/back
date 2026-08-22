MATCH_NOT_FOUND = "MATCH_NOT_FOUND"
TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
PLAYER_NOT_FOUND = "PLAYER_NOT_FOUND"
INVALID_MATCH_TEAMS = "INVALID_MATCH_TEAMS"
INVALID_WINNER_TEAM = "INVALID_WINNER_TEAM"


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
    if code in (INVALID_MATCH_TEAMS, INVALID_WINNER_TEAM):
        return 422
    return 400
