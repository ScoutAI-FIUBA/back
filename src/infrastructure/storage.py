"""Cloudflare R2 storage adapter.

R2 is S3-compatible, so boto3 works out of the box pointing at the R2 endpoint.
The boto3 client is created on first use so the application can boot without
storage credentials configured (useful for first deploys / environments without R2).
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import BinaryIO

import boto3
from botocore.client import BaseClient, Config

# Files above this size use explicit S3 multipart upload to R2.
MULTIPART_THRESHOLD_BYTES = 100 * 1024 * 1024
# Part size for multipart uploads (S3 minimum per part is 5 MiB, except the last).
MULTIPART_PART_SIZE_BYTES = 64 * 1024 * 1024


class StorageNotConfiguredError(RuntimeError):
    """Raised when storage operations are invoked without R2 credentials."""


@dataclass(frozen=True)
class R2Settings:
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    endpoint_url: str

    @classmethod
    def from_env(cls) -> "R2Settings | None":
        required = {
            "R2_ACCESS_KEY_ID": os.getenv("R2_ACCESS_KEY_ID"),
            "R2_SECRET_ACCESS_KEY": os.getenv("R2_SECRET_ACCESS_KEY"),
            "R2_BUCKET_NAME": os.getenv("R2_BUCKET_NAME"),
            "R2_ENDPOINT_URL": os.getenv("R2_ENDPOINT_URL"),
        }
        if any(value is None or value.strip() == "" for value in required.values()):
            return None
        return cls(
            access_key_id=required["R2_ACCESS_KEY_ID"].strip(),
            secret_access_key=required["R2_SECRET_ACCESS_KEY"].strip(),
            bucket_name=required["R2_BUCKET_NAME"].strip(),
            endpoint_url=required["R2_ENDPOINT_URL"].strip(),
        )


def _build_client(settings: R2Settings) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _file_size(file: BinaryIO) -> int | None:
    """Return stream length when seekable; None if size cannot be determined."""
    tell = getattr(file, "tell", None)
    seek = getattr(file, "seek", None)
    if tell is None or seek is None:
        return None
    try:
        position = tell()
        seek(0, os.SEEK_END)
        size = tell()
        seek(position)
        return size
    except OSError:
        return None


def _rewind(file: BinaryIO) -> None:
    seek = getattr(file, "seek", None)
    if seek is None:
        return
    try:
        seek(0)
    except OSError:
        pass


class R2Storage:
    """Thin wrapper over boto3 S3 client targeting Cloudflare R2."""

    def __init__(self, settings: R2Settings | None = None) -> None:
        self._settings = settings or R2Settings.from_env()
        self._client: BaseClient | None = None

    @property
    def is_configured(self) -> bool:
        return self._settings is not None

    def _require_client(self) -> tuple[BaseClient, R2Settings]:
        if self._settings is None:
            raise StorageNotConfiguredError(
                "R2 storage is not configured. Set R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME and R2_ENDPOINT_URL."
            )
        if self._client is None:
            self._client = _build_client(self._settings)
        return self._client, self._settings

    def upload_video(
        self,
        file: BinaryIO,
        key: str,
        content_type: str | None = None,
        *,
        size: int | None = None,
    ) -> str:
        """Upload a video file to R2. Returns the object key on success.

        Uses a single PUT via upload_fileobj for smaller files. When ``size`` is
        known (or the stream is seekable) and exceeds MULTIPART_THRESHOLD_BYTES,
        uses explicit S3 multipart upload with MULTIPART_PART_SIZE_BYTES chunks.
        """
        effective_size = size if size is not None else _file_size(file)
        _rewind(file)
        if (
            effective_size is not None
            and effective_size > MULTIPART_THRESHOLD_BYTES
        ):
            return self._upload_multipart(file, key, content_type)
        return self._upload_simple(file, key, content_type)

    def _upload_simple(
        self, file: BinaryIO, key: str, content_type: str | None
    ) -> str:
        client, settings = self._require_client()
        extra_args = {"ContentType": content_type} if content_type else {}
        client.upload_fileobj(file, settings.bucket_name, key, ExtraArgs=extra_args)
        return key

    def _upload_multipart(
        self, file: BinaryIO, key: str, content_type: str | None
    ) -> str:
        client, settings = self._require_client()
        create_kwargs: dict[str, str] = {
            "Bucket": settings.bucket_name,
            "Key": key,
        }
        if content_type:
            create_kwargs["ContentType"] = content_type

        created = client.create_multipart_upload(**create_kwargs)
        upload_id = created["UploadId"]
        parts: list[dict[str, str | int]] = []
        part_number = 1

        try:
            while True:
                chunk = file.read(MULTIPART_PART_SIZE_BYTES)
                if not chunk:
                    break
                uploaded = client.upload_part(
                    Bucket=settings.bucket_name,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=chunk,
                )
                parts.append(
                    {"PartNumber": part_number, "ETag": uploaded["ETag"]}
                )
                part_number += 1

            if not parts:
                raise ValueError("Cannot upload an empty file to R2")

            client.complete_multipart_upload(
                Bucket=settings.bucket_name,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            with contextlib.suppress(Exception):
                client.abort_multipart_upload(
                    Bucket=settings.bucket_name,
                    Key=key,
                    UploadId=upload_id,
                )
            raise

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
