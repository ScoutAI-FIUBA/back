from __future__ import annotations

from abc import ABC, abstractmethod


class ArtifactNotFoundError(Exception):
    """The processing service did not write the requested file."""


class ArtifactReadError(Exception):
    """The file exists but could not be read or parsed."""


class ArtifactReaderPort(ABC):
    """Reads the files the processing service wrote for one job.

    Only ever used for the small structured outputs the statistics are derived
    from. The large per-frame track dump is deliberately never read here — it can
    reach a hundred megabytes for a full game, which no web request should touch.
    """

    @abstractmethod
    def read_json(self, *, results_key: str, filename: str) -> dict | None:
        """Parsed JSON document, or None when the file is absent."""

    @abstractmethod
    def read_jsonl(self, *, results_key: str, filename: str, max_lines: int) -> list[dict]:
        """Parsed JSON-lines records, stopping after `max_lines`.

        Bounded on purpose: an unbounded read of a long game would exhaust the
        memory of a small web instance.
        """
