from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.infrastructure.video.ffmpeg_thumbnail_generator import FFmpegThumbnailGenerator


class TestFFmpegThumbnailGenerator(unittest.TestCase):
    def _storage(self) -> MagicMock:
        storage = MagicMock()
        storage.generate_presigned_url.return_value = "https://source.local/video.mp4"
        return storage

    def test_generate_extracts_single_frame_and_uploads_jpeg(self) -> None:
        storage = self._storage()
        generator = FFmpegThumbnailGenerator(
            storage=storage,
            ffmpeg_binary="ffmpeg-test",
            width=640,
            qscale=3,
            timeout_seconds=15,
        )

        def _run(command, check, capture_output, timeout, text):
            self.assertEqual(command[0], "ffmpeg-test")
            self.assertEqual(command[command.index("-ss") + 1], "2")
            self.assertEqual(command[command.index("-frames:v") + 1], "1")
            self.assertEqual(command[command.index("-vf") + 1], "scale=640:-2")
            self.assertEqual(command[command.index("-q:v") + 1], "3")
            Path(command[-1]).write_bytes(b"jpeg-data")
            self.assertTrue(check)
            self.assertTrue(capture_output)
            self.assertEqual(timeout, 15)
            self.assertTrue(text)
            return MagicMock()

        with patch("src.infrastructure.video.ffmpeg_thumbnail_generator.subprocess.run", side_effect=_run) as run_mock:
            generator.generate(source_key="videos/source.mp4", thumbnail_key="thumbnails/t1/v1.jpg")

        storage.generate_presigned_url.assert_called_once_with("videos/source.mp4")
        storage.upload_file.assert_called_once()
        self.assertEqual(storage.upload_file.call_args.args[1:], ("thumbnails/t1/v1.jpg", "image/jpeg"))
        run_mock.assert_called_once()

    def test_generate_falls_back_to_frame_zero_when_seek_yields_no_frame(self) -> None:
        storage = self._storage()
        generator = FFmpegThumbnailGenerator(storage=storage)
        seeks: list[str] = []

        def _run(command, check, capture_output, timeout, text):
            del check, capture_output, timeout, text
            seeks.append(command[command.index("-ss") + 1])
            if len(seeks) == 2:
                Path(command[-1]).write_bytes(b"jpeg-data")
            return MagicMock()

        with patch("src.infrastructure.video.ffmpeg_thumbnail_generator.subprocess.run", side_effect=_run):
            generator.generate(source_key="videos/source.mp4", thumbnail_key="thumbnails/t1/v1.jpg")

        self.assertEqual(seeks, ["2", "0"])
        storage.upload_file.assert_called_once()

    def test_generate_propagates_ffmpeg_failure(self) -> None:
        storage = self._storage()
        generator = FFmpegThumbnailGenerator(storage=storage)

        with patch(
            "src.infrastructure.video.ffmpeg_thumbnail_generator.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                generator.generate(source_key="videos/source.mp4", thumbnail_key="thumbnails/t1/v1.jpg")

        storage.upload_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
