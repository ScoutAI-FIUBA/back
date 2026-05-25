from __future__ import annotations

import io
import os
import unittest
from unittest.mock import MagicMock, patch

from src.infrastructure.storage import (
    MULTIPART_PART_SIZE_BYTES,
    MULTIPART_THRESHOLD_BYTES,
    R2Settings,
    R2Storage,
    StorageNotConfiguredError,
)


class TestR2Settings(unittest.TestCase):
    def test_from_env_returns_none_when_any_required_var_is_missing(self) -> None:
        env = {
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(R2Settings.from_env())

    def test_from_env_returns_none_when_any_required_var_is_blank(self) -> None:
        env = {
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "   ",
            "R2_BUCKET_NAME": "bucket",
            "R2_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(R2Settings.from_env())

    def test_from_env_strips_whitespace_from_values(self) -> None:
        env = {
            "R2_ACCESS_KEY_ID": "  key-id  ",
            "R2_SECRET_ACCESS_KEY": " secret ",
            "R2_BUCKET_NAME": " my-bucket ",
            "R2_ENDPOINT_URL": " https://acct.r2.cloudflarestorage.com ",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = R2Settings.from_env()

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings.access_key_id, "key-id")
        self.assertEqual(settings.secret_access_key, "secret")
        self.assertEqual(settings.bucket_name, "my-bucket")
        self.assertEqual(settings.endpoint_url, "https://acct.r2.cloudflarestorage.com")


class TestR2Storage(unittest.TestCase):
    def test_is_configured_false_without_settings(self) -> None:
        with patch.object(R2Settings, "from_env", return_value=None):
            storage = R2Storage()
        self.assertFalse(storage.is_configured)

    def test_require_client_raises_when_not_configured(self) -> None:
        with patch.object(R2Settings, "from_env", return_value=None):
            storage = R2Storage(settings=None)
        with self.assertRaises(StorageNotConfiguredError):
            storage._require_client()

    def test_require_client_builds_client_lazily_when_configured(self) -> None:
        settings = R2Settings(
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            endpoint_url="https://example.r2.cloudflarestorage.com",
        )
        storage = R2Storage(settings=settings)
        self.assertIsNone(storage._client)

        with patch("src.infrastructure.storage._build_client") as build_client:
            build_client.return_value = object()
            client, returned_settings = storage._require_client()

        build_client.assert_called_once_with(settings)
        self.assertIs(client, build_client.return_value)
        self.assertEqual(returned_settings, settings)
        self.assertIs(storage._client, client)


class TestR2StorageUpload(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = R2Settings(
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            endpoint_url="https://example.r2.cloudflarestorage.com",
        )
        self.storage = R2Storage(settings=self.settings)
        self.client = MagicMock()
        self.storage._client = self.client

    def test_upload_video_uses_simple_upload_when_size_below_threshold(self) -> None:
        data = b"small-video"
        file = io.BytesIO(data)

        key = self.storage.upload_video(
            file, "videos/small.mp4", "video/mp4", size=len(data)
        )

        self.client.upload_fileobj.assert_called_once()
        self.client.create_multipart_upload.assert_not_called()
        self.assertEqual(key, "videos/small.mp4")

    def test_upload_video_uses_multipart_when_size_above_threshold(self) -> None:
        part_size = 5
        threshold = 10
        payload = b"a" * 12

        self.client.create_multipart_upload.return_value = {"UploadId": "upload-1"}
        self.client.upload_part.side_effect = [
            {"ETag": "etag-1"},
            {"ETag": "etag-2"},
            {"ETag": "etag-3"},
        ]

        with (
            patch(
                "src.infrastructure.storage.MULTIPART_THRESHOLD_BYTES", threshold
            ),
            patch(
                "src.infrastructure.storage.MULTIPART_PART_SIZE_BYTES", part_size
            ),
        ):
            key = self.storage.upload_video(
                io.BytesIO(payload),
                "videos/large.mp4",
                "video/mp4",
                size=len(payload),
            )

        self.client.upload_fileobj.assert_not_called()
        self.client.create_multipart_upload.assert_called_once_with(
            Bucket="bucket",
            Key="videos/large.mp4",
            ContentType="video/mp4",
        )
        self.assertEqual(self.client.upload_part.call_count, 3)
        self.client.complete_multipart_upload.assert_called_once_with(
            Bucket="bucket",
            Key="videos/large.mp4",
            UploadId="upload-1",
            MultipartUpload={
                "Parts": [
                    {"PartNumber": 1, "ETag": "etag-1"},
                    {"PartNumber": 2, "ETag": "etag-2"},
                    {"PartNumber": 3, "ETag": "etag-3"},
                ]
            },
        )
        self.client.abort_multipart_upload.assert_not_called()
        self.assertEqual(key, "videos/large.mp4")

    def test_upload_video_multipart_aborts_on_failure(self) -> None:
        threshold = 1
        part_size = 1
        payload = b"ab"

        self.client.create_multipart_upload.return_value = {"UploadId": "upload-2"}
        self.client.upload_part.side_effect = [
            {"ETag": "etag-1"},
            RuntimeError("network error"),
        ]

        with (
            patch(
                "src.infrastructure.storage.MULTIPART_THRESHOLD_BYTES", threshold
            ),
            patch(
                "src.infrastructure.storage.MULTIPART_PART_SIZE_BYTES", part_size
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.storage.upload_video(
                    io.BytesIO(payload),
                    "videos/fail.mp4",
                    size=len(payload),
                )

        self.client.abort_multipart_upload.assert_called_once_with(
            Bucket="bucket",
            Key="videos/fail.mp4",
            UploadId="upload-2",
        )
        self.client.complete_multipart_upload.assert_not_called()

    def test_upload_video_multipart_preserves_original_error_when_abort_fails(
        self,
    ) -> None:
        threshold = 1
        part_size = 1
        payload = b"ab"

        self.client.create_multipart_upload.return_value = {"UploadId": "upload-4"}
        self.client.upload_part.side_effect = RuntimeError("network error")
        self.client.abort_multipart_upload.side_effect = RuntimeError("abort failed")

        with (
            patch(
                "src.infrastructure.storage.MULTIPART_THRESHOLD_BYTES", threshold
            ),
            patch(
                "src.infrastructure.storage.MULTIPART_PART_SIZE_BYTES", part_size
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.storage.upload_video(
                    io.BytesIO(payload),
                    "videos/fail-abort.mp4",
                    size=len(payload),
                )

        self.assertEqual(str(ctx.exception), "network error")

    def test_upload_video_infers_size_from_seekable_stream(self) -> None:
        data = b"tiny"
        file = io.BytesIO(data)

        key = self.storage.upload_video(file, "videos/inferred.mp4")

        self.client.upload_fileobj.assert_called_once()
        self.assertEqual(key, "videos/inferred.mp4")

    def test_upload_video_chooses_multipart_from_seekable_large_stream(self) -> None:
        threshold = 4
        part_size = 2
        payload = b"123456"

        self.client.create_multipart_upload.return_value = {"UploadId": "upload-3"}
        self.client.upload_part.side_effect = [
            {"ETag": "e1"},
            {"ETag": "e2"},
            {"ETag": "e3"},
        ]

        with (
            patch(
                "src.infrastructure.storage.MULTIPART_THRESHOLD_BYTES", threshold
            ),
            patch(
                "src.infrastructure.storage.MULTIPART_PART_SIZE_BYTES", part_size
            ),
        ):
            key = self.storage.upload_video(
                io.BytesIO(payload), "videos/seek-large.mp4"
            )

        self.client.create_multipart_upload.assert_called_once()
        self.assertEqual(self.client.upload_part.call_count, 3)
        self.assertEqual(key, "videos/seek-large.mp4")

    def test_module_defaults_use_100mb_threshold_and_64mb_parts(self) -> None:
        self.assertEqual(MULTIPART_THRESHOLD_BYTES, 100 * 1024 * 1024)
        self.assertEqual(MULTIPART_PART_SIZE_BYTES, 64 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
