FORBIDDEN_TEAM_ACCESS = "FORBIDDEN_TEAM_ACCESS"
TEAM_NOT_FOUND = "TEAM_NOT_FOUND"
VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
VIDEO_NOT_READY = "VIDEO_NOT_READY"
JOB_NOT_FOUND = "JOB_NOT_FOUND"
JOB_ALREADY_ACTIVE = "JOB_ALREADY_ACTIVE"
PROCESSING_SERVICE_UNAVAILABLE = "PROCESSING_SERVICE_UNAVAILABLE"
INVALID_JOB_STATUS = "INVALID_JOB_STATUS"
JOB_NOT_FINISHED = "JOB_NOT_FINISHED"
RESULTS_NOT_AVAILABLE = "RESULTS_NOT_AVAILABLE"
STORAGE_NOT_CONFIGURED = "STORAGE_NOT_CONFIGURED"


class JobError(Exception):
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


def job_error_http_status(code: str) -> int:
    if code == FORBIDDEN_TEAM_ACCESS:
        return 403
    if code in (TEAM_NOT_FOUND, VIDEO_NOT_FOUND, JOB_NOT_FOUND, RESULTS_NOT_AVAILABLE):
        return 404
    # A video already being processed is a conflict, not a client mistake. The
    # caller should poll the existing job rather than start a second one.
    if code in (VIDEO_NOT_READY, JOB_ALREADY_ACTIVE, JOB_NOT_FINISHED):
        return 409
    if code == INVALID_JOB_STATUS:
        return 422
    # The processing service is a third party from this app's point of view.
    if code == PROCESSING_SERVICE_UNAVAILABLE:
        return 502
    # A deployment problem on our side, not the caller's fault.
    if code == STORAGE_NOT_CONFIGURED:
        return 503
    return 400
