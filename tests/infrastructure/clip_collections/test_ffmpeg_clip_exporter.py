from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from src.infrastructure.clip_collections.ffmpeg_clip_exporter import FFmpegClipExporter


class TestFFmpegClipExporter(unittest.TestCase):
    def test_export_exists_delegates_to_storage(self) -> None:
        storage = MagicMock()
        storage.object_exists.return_value = True

        exporter = FFmpegClipExporter(storage=storage)

        self.assertTrue(exporter.export_exists(export_key="exports/item-1.mp4"))
        storage.object_exists.assert_called_once_with("exports/item-1.mp4")

    def test_export_clip_reencodes_exact_range_and_uploads_mp4(self) -> None:
        storage = MagicMock()
        storage.generate_presigned_url.return_value = "https://source.local/video.mp4"

        exporter = FFmpegClipExporter(storage=storage, ffmpeg_binary="ffmpeg-test", timeout_seconds=30)

        def _run(command, check, capture_output, timeout, text):
            self.assertEqual(command[0], "ffmpeg-test")
            self.assertIn("0.500", command)
            self.assertIn("2.000", command)
            output_path = Path(command[-1])
            output_path.write_bytes(b"mp4-data")
            self.assertTrue(check)
            self.assertTrue(capture_output)
            self.assertEqual(timeout, 30)
            self.assertTrue(text)
            return MagicMock()

        with patch("src.infrastructure.clip_collections.ffmpeg_clip_exporter.subprocess.run", side_effect=_run) as run_mock:
            exporter.export_clip(source_key="videos/source.mp4", export_key="exports/item-1.mp4", start_ms=500, end_ms=2500)

        storage.generate_presigned_url.assert_called_once_with("videos/source.mp4", expires_in=3600)
        storage.upload_file.assert_called_once()
        self.assertEqual(storage.upload_file.call_args.args[1:], ("exports/item-1.mp4", "video/mp4"))
        run_mock.assert_called_once()

    def test_generate_download_url_uses_configured_default_ttl(self) -> None:
        storage = MagicMock()
        storage.generate_download_url.return_value = "https://download.local/file.mp4"

        exporter = FFmpegClipExporter(storage=storage, download_url_ttl_seconds=123)

        self.assertEqual(exporter.generate_download_url(export_key="exports/item-1.mp4"), "https://download.local/file.mp4")
        storage.generate_download_url.assert_called_once_with("exports/item-1.mp4", expires_in=123)

    def test_generate_download_url_allows_explicit_ttl_override(self) -> None:
        storage = MagicMock()
        storage.generate_download_url.return_value = "https://download.local/file.mp4"

        exporter = FFmpegClipExporter(storage=storage, download_url_ttl_seconds=123)

        self.assertEqual(
            exporter.generate_download_url(export_key="exports/item-1.mp4", expires_in=999),
            "https://download.local/file.mp4",
        )
        storage.generate_download_url.assert_called_once_with("exports/item-1.mp4", expires_in=999)
