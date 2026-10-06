from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from src.application.video.ports import ThumbnailGeneratorPort
from src.infrastructure.storage import R2Storage


class FFmpegThumbnailGenerator(ThumbnailGeneratorPort):
    """Extracts a single JPEG preview frame from a stored video.

    Mirrors ``FFmpegClipExporter``: presign the source object, run ffmpeg once
    inside a ``TemporaryDirectory`` and upload the JPEG through ``R2Storage``.
    Generation is best-effort; errors propagate to the caller, which swallows
    them so a thumbnail failure never fails the request.
    """

    def __init__(
        self,
        *,
        storage: R2Storage,
        ffmpeg_binary: str = "ffmpeg",
        seek_seconds: int = 2,
        width: int = 640,
        qscale: int = 3,
        timeout_seconds: int = 15,
    ) -> None:
        self._storage = storage
        self._ffmpeg_binary = ffmpeg_binary
        self._seek_seconds = seek_seconds
        self._width = width
        self._qscale = qscale
        self._timeout_seconds = timeout_seconds

    def generate(self, *, source_key: str, thumbnail_key: str) -> None:
        source_url = self._storage.generate_presigned_url(source_key)
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "frame.jpg"
            self._run_ffmpeg(source_url=source_url, output_path=output_path, seek_seconds=self._seek_seconds)
            if not _has_frame(output_path):
                # A seek past the source duration yields no frame; retry from frame 0.
                self._run_ffmpeg(source_url=source_url, output_path=output_path, seek_seconds=0)
            with output_path.open("rb") as frame_file:
                self._storage.upload_file(frame_file, thumbnail_key, "image/jpeg")

    def _run_ffmpeg(self, *, source_url: str, output_path: Path, seek_seconds: int) -> None:
        subprocess.run(
            [
                self._ffmpeg_binary,
                "-y",
                "-loglevel",
                "error",
                "-ss",
                str(seek_seconds),
                "-i",
                source_url,
                "-frames:v",
                "1",
                "-vf",
                f"scale={self._width}:-2",
                "-q:v",
                str(self._qscale),
                str(output_path),
            ],
            check=True,
            capture_output=True,
            timeout=self._timeout_seconds,
            text=True,
        )


def _has_frame(output_path: Path) -> bool:
    return output_path.exists() and output_path.stat().st_size > 0
