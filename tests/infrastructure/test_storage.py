from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.infrastructure.storage import R2Settings, R2Storage, StorageNotConfiguredError


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


if __name__ == "__main__":
    unittest.main()
