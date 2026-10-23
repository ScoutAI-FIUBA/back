"""Only a file that is really missing reads as absent; any other storage failure is an error."""

from __future__ import annotations

import io

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from src.application.stats.ports import ArtifactReadError
from src.infrastructure.stats.r2_artifact_reader import R2ArtifactReader
from src.infrastructure.storage import StorageNotConfiguredError


class _Storage:
    def __init__(self, error: Exception | None = None, body: bytes = b'{"a": 1}') -> None:
        self.error, self.body = error, body

    def _require_client(self):
        storage = self

        class _Client:
            def get_object(self, *, Bucket, Key):
                if storage.error is not None:
                    raise storage.error
                return {"Body": io.BytesIO(storage.body)}

        return _Client(), type("Settings", (), {"bucket_name": "bucket"})()


def _client_error(code: str, status: int = 400) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": status}},
                       "GetObject")


@pytest.mark.parametrize("code", ["NoSuchKey", "404", "NotFound"])
def test_a_missing_object_reads_as_absent(code) -> None:
    reader = R2ArtifactReader(storage=_Storage(_client_error(code, 404)))
    assert reader.read_json(results_key="r/", filename="numbers.json") is None
    assert reader.read_jsonl(results_key="r/", filename="positions.jsonl", max_lines=5) == []


@pytest.mark.parametrize("error", [
    _client_error("SlowDown", 503),
    _client_error("InternalError", 500),
    _client_error("AccessDenied", 403),
    _client_error("RequestTimeout", 400),
    ConnectTimeoutError(endpoint_url="https://r2"),
    ConnectionResetError("reset"),
    StorageNotConfiguredError("not configured"),
])
def test_any_other_failure_is_an_error_not_a_missing_file(error) -> None:
    reader = R2ArtifactReader(storage=_Storage(error))
    with pytest.raises(ArtifactReadError):
        reader.read_json(results_key="r/", filename="numbers.json")
    with pytest.raises(ArtifactReadError):
        reader.read_jsonl(results_key="r/", filename="positions.jsonl", max_lines=5)


def test_a_readable_object_still_reads() -> None:
    assert R2ArtifactReader(storage=_Storage()).read_json(results_key="r/", filename="x.json") == {"a": 1}
