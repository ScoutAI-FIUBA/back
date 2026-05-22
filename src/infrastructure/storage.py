"""Cloudflare R2 storage adapter.

R2 is S3-compatible, so boto3 works out of the box pointing at the R2 endpoint.
The client is initialized lazily so the application can boot without storage
credentials configured (useful for first deploys / environments without R2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import BinaryIO

import boto3
from botocore.client import Config


class StorageNotConfiguredError(RuntimeError):
    """Raised when storage operations are invoked without R2 credentials."""


@dataclass(frozen=True)
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    endpoint_url: str

    @classmethod
    def from_env(cls) -> "R2Settings | None":
        required = {
            "R2_ACCOUNT_ID": os.getenv("R2_ACCOUNT_ID"),
            "R2_ACCESS_KEY_ID": os.getenv("R2_ACCESS_KEY_ID"),
            "R2_SECRET_ACCESS_KEY": os.getenv("R2_SECRET_ACCESS_KEY"),
            "R2_BUCKET_NAME": os.getenv("R2_BUCKET_NAME"),
            "R2_ENDPOINT_URL": os.getenv("R2_ENDPOINT_URL"),
        }
        if any(value is None or value.strip() == "" for value in required.values()):
            return None
        return cls(
            account_id=required["R2_ACCOUNT_ID"],
            access_key_id=required["R2_ACCESS_KEY_ID"],
            secret_access_key=required["R2_SECRET_ACCESS_KEY"],
            bucket_name=required["R2_BUCKET_NAME"],
            endpoint_url=required["R2_ENDPOINT_URL"],
        )


def _build_client(settings: R2Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


class R2Storage:
    """Thin wrapper over boto3 S3 client targeting Cloudflare R2."""

    def __init__(self, settings: R2Settings | None = None) -> None:
        self._settings = settings or R2Settings.from_env()
        self._client = _build_client(self._settings) if self._settings else None

    @property
    def is_configured(self) -> bool:
        return self._client is not None and self._settings is not None

    def _require_client(self):
        if self._client is None or self._settings is None:
            raise StorageNotConfiguredError(
                "R2 storage is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME and R2_ENDPOINT_URL."
            )
        return self._client, self._settings

    def upload_video(self, file: BinaryIO, key: str, content_type: str | None = None) -> str:
        """Upload a video file to R2. Returns the object key on success."""
        client, settings = self._require_client()
        extra_args = {"ContentType": content_type} if content_type else {}
        client.upload_fileobj(file, settings.bucket_name, key, ExtraArgs=extra_args)
        return key

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a time-limited URL to read the object."""
        client, settings = self._require_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete_video(self, key: str) -> None:
        client, settings = self._require_client()
        client.delete_object(Bucket=settings.bucket_name, Key=key)
