from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from src.application.clip_collections.ports import ClipExporterPort
from src.infrastructure.storage import R2Storage


class FFmpegClipExporter(ClipExporterPort):
    def __init__(
        self,
        *,
        storage: R2Storage,
        ffmpeg_binary: str = "ffmpeg",
        download_url_ttl_seconds: int = 3600,
        source_url_ttl_seconds: int = 3600,
        timeout_seconds: int = 120,
    ) -> None:
        self._storage = storage
        self._ffmpeg_binary = ffmpeg_binary
        self._download_url_ttl_seconds = download_url_ttl_seconds
        self._source_url_ttl_seconds = source_url_ttl_seconds
        self._timeout_seconds = timeout_seconds

    def export_exists(self, *, export_key: str) -> bool:
        return self._storage.object_exists(export_key)

    def export_clip(self, *, source_key: str, export_key: str, start_ms: int, end_ms: int) -> None:
        source_url = self._storage.generate_presigned_url(source_key, expires_in=self._source_url_ttl_seconds)
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "clip.mp4"
            subprocess.run(
                [
                    self._ffmpeg_binary,
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    _format_ffmpeg_seconds(start_ms),
                    "-i",
                    source_url,
                    "-t",
                    _format_ffmpeg_seconds(end_ms - start_ms),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                text=True,
            )
            with output_path.open("rb") as exported_file:
                self._storage.upload_file(exported_file, export_key, "video/mp4")

    def generate_download_url(self, *, export_key: str, expires_in: int | None = None) -> str:
        effective_ttl = self._download_url_ttl_seconds if expires_in is None else expires_in
        return self._storage.generate_download_url(export_key, expires_in=effective_ttl)


def _format_ffmpeg_seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"
