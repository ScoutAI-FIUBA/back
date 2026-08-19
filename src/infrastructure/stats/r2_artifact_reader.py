"""Reads a job's analysis files from R2.

Only the small structured outputs are ever fetched — the shot list, team
assignments, jersey numbers, and projected positions. Reads are size-capped so a
malformed or unexpectedly large file cannot exhaust a small web instance.
"""

from __future__ import annotations

import json
import logging

from src.application.stats.ports import ArtifactReaderPort, ArtifactReadError

logger = logging.getLogger(__name__)

# Generous for a shot list or team assignment, far below anything that would
# threaten the process.
MAX_JSON_BYTES = 8_000_000
MAX_JSONL_BYTES = 32_000_000


class R2ArtifactReader(ArtifactReaderPort):
    def __init__(self, *, storage) -> None:
        self._storage = storage

    def _fetch(self, results_key: str, filename: str, limit: int) -> bytes | None:
        key = f"{results_key.rstrip('/')}/{filename}"
        try:
            client, settings = self._storage._require_client()
            response = client.get_object(Bucket=settings.bucket_name, Key=key)
            body = response["Body"].read(limit + 1)
        except Exception:
            # A missing file is ordinary — not every pipeline run writes every
            # artifact — so this is None rather than an error.
            logger.info("Artifact not readable: %s", key, exc_info=True)
            return None
        if len(body) > limit:
            raise ArtifactReadError(f"{filename} is larger than this service will read.")
        return body

    def read_json(self, *, results_key: str, filename: str) -> dict | None:
        body = self._fetch(results_key, filename, MAX_JSON_BYTES)
        if body is None:
            return None
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise ArtifactReadError(f"{filename} is not valid JSON.") from exc
        return parsed if isinstance(parsed, dict) else None

    def read_jsonl(self, *, results_key: str, filename: str, max_lines: int) -> list[dict]:
        body = self._fetch(results_key, filename, MAX_JSONL_BYTES)
        if body is None:
            return []
        rows: list[dict] = []
        for line in body.splitlines():
            if len(rows) >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # One malformed line should not discard an otherwise good file.
                continue
            if isinstance(record, dict):
                rows.append(record)
        return rows


class UnavailableArtifactReader(ArtifactReaderPort):
    """Used when object storage is not configured, so the app still boots."""

    def read_json(self, *, results_key: str, filename: str) -> dict | None:
        raise ArtifactReadError("Object storage is not configured.")

    def read_jsonl(self, *, results_key: str, filename: str, max_lines: int) -> list[dict]:
        raise ArtifactReadError("Object storage is not configured.")
