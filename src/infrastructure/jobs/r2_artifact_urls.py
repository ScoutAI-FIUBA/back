"""Presigned download URLs for processing-job artifacts.

Signing only. This module never fetches an object — `generate_presigned_url`
builds a signed URL locally from the key and credentials, so it costs no network
call and works even for a key that does not exist yet.
"""

from __future__ import annotations

from src.application.jobs.ports import ArtifactUrlSignerPort, ArtifactUrlsUnavailableError


class R2ArtifactUrls(ArtifactUrlSignerPort):
    def __init__(self, *, storage) -> None:
        self._storage = storage

    def presign(self, *, key: str, expires_in: int) -> str:
        return self._storage.generate_presigned_url(key, expires_in=expires_in)


class UnavailableArtifactUrls(ArtifactUrlSignerPort):
    """Used when object storage is not configured, so the app still boots."""

    def presign(self, *, key: str, expires_in: int) -> str:
        raise ArtifactUrlsUnavailableError(
            "Object storage is not configured; cannot build a download URL."
        )
