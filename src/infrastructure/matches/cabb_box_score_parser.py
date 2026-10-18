from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from src.application.matches.excel_import import BoxScoreFileError, BoxScoreParserPort
from src.domain.matches.box_score import (
    BoxScoreLine,
    BoxScorePlayer,
    BoxScoreTeam,
    ParsedBoxScore,
    Shooting,
)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 200

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Column header row of the CABB export. Matching it exactly is what lets us read
# fixed positions below; any other layout is rejected instead of misread.
_HEADERS = [
    "num.", "nombre", "min", "pts", "a/i", "%", "a/i", "%", "a/i", "%",
    "def", "of", "tot.", "ast", "rec", "per", "tc", "tr", "fc", "fr", "val", "+/-",
]
_COLUMNS = "ABCDEFGHIJKLMNOPQRSTUV"


def _column_of(reference: str) -> str:
    return re.match(r"[A-Z]+", reference).group(0)  # type: ignore[union-attr]


def _row_of(reference: str) -> int:
    return int(re.search(r"\d+", reference).group(0))  # type: ignore[union-attr]


def _int(value: str | None) -> int:
    if value is None or value.strip() == "":
        return 0
    try:
        return int(float(value.strip().replace(",", ".")))
    except ValueError:
        raise BoxScoreFileError(f"Expected a number but found {value!r}") from None


def _shooting(value: str | None) -> Shooting:
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", value or "0/0")
    if match is None:
        raise BoxScoreFileError(f"Expected made/attempted but found {value!r}")
    made, attempted = int(match.group(1)), int(match.group(2))
    if made > attempted:
        raise BoxScoreFileError(f"Made shots exceed attempts in {value!r}")
    return Shooting(made=made, attempted=attempted)


def _minutes(value: str | None) -> int:
    match = re.fullmatch(r"\s*(\d+):(\d{2})\s*", value or "0:00")
    if match is None:
        raise BoxScoreFileError(f"Expected minutes as mm:ss but found {value!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def _line(cells: dict[str, str]) -> BoxScoreLine:
    c = lambda i: cells.get(_COLUMNS[i])  # noqa: E731
    return BoxScoreLine(
        minutes_seconds=_minutes(c(2)),
        points=_int(c(3)),
        two_point=_shooting(c(4)),
        three_point=_shooting(c(6)),
        free_throw=_shooting(c(8)),
        rebounds_defensive=_int(c(10)),
        rebounds_offensive=_int(c(11)),
        rebounds_total=_int(c(12)),
        assists=_int(c(13)),
        steals=_int(c(14)),
        turnovers=_int(c(15)),
        blocks=_int(c(16)),
        blocks_received=_int(c(17)),
        fouls=_int(c(18)),
        fouls_drawn=_int(c(19)),
        valuation=_int(c(20)),
        plus_minus=_int(c(21)),
    )


def _title_parts(title: str) -> tuple[str | None, str | None, str | None]:
    text = re.sub(r"^\s*Estad[ií]sticas\s*-\s*", "", title, flags=re.IGNORECASE)
    parts = re.split(r"\s+vs\.?\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None, None, None
    away, _, competition = parts[1].partition(" - ")
    return parts[0].strip() or None, away.strip() or None, competition.strip() or None


class CabbBoxScoreParser(BoxScoreParserPort):
    """Reads the Excel box score exported by the Argentine basketball confederation."""

    def parse(self, data: bytes) -> ParsedBoxScore:
        if len(data) > MAX_FILE_BYTES:
            raise BoxScoreFileError("The file is too large", too_large=True)
        rows = self._read_xlsx_rows(data) if data[:2] == b"PK" else self._read_csv_rows(data)
        title = next(
            (
                text
                for cells in rows.values()
                for text in cells.values()
                if re.match(r"\s*Estad[ií]sticas\s*-", text, flags=re.IGNORECASE)
            ),
            None,
        )
        home_hint, away_hint, competition = _title_parts(title) if title else (None, None, None)

        header_rows = [
            number
            for number, cells in sorted(rows.items())
            if cells.get("A", "").strip().lower() == "num."
        ]
        if not header_rows:
            raise BoxScoreFileError("This does not look like a federation box score (no player table found)")

        teams: list[BoxScoreTeam] = []
        for position, header_row in enumerate(header_rows):
            header = [rows[header_row].get(column, "").strip().lower() for column in _COLUMNS]
            if header != _HEADERS:
                raise BoxScoreFileError("Unsupported box score layout: the column headers are not the expected ones")
            next_header = header_rows[position + 1] if position + 1 < len(header_rows) else None
            teams.append(self._read_team(rows, header_row, next_header))
        if len(teams) != 2:
            raise BoxScoreFileError(f"Expected two team tables but found {len(teams)}")
        return ParsedBoxScore(
            title=title,
            home_name_hint=home_hint,
            away_name_hint=away_hint,
            competition=competition,
            teams=teams,
        )

    def _read_team(self, rows: dict[int, dict[str, str]], header_row: int, next_header: int | None) -> BoxScoreTeam:
        name = None
        for number in range(header_row - 1, 0, -1):
            text = rows.get(number, {}).get("A", "").strip()
            if text and text.upper() != "TOTALES":
                name = text
                break
        if not name:
            raise BoxScoreFileError("A team table has no team name above it")

        players: list[BoxScorePlayer] = []
        totals: BoxScoreLine | None = None
        last = next_header if next_header is not None else max(rows) + 1
        for number in range(header_row + 1, last):
            cells = rows.get(number)
            if not cells:
                continue
            if cells.get("B", "").strip().upper() == "TOTALES":
                totals = _line(cells)
                break
            jersey = cells.get("A", "").strip()
            player_name = cells.get("B", "").strip()
            if not player_name:
                continue
            players.append(
                BoxScorePlayer(
                    jersey_number=jersey if re.fullmatch(r"\d{1,2}", jersey) else None,
                    name=player_name[:200],
                    line=_line(cells),
                )
            )
        if not players:
            raise BoxScoreFileError(f"The table for {name!r} has no players")
        return BoxScoreTeam(name=name, players=players, totals=totals)

    @staticmethod
    def _read_csv_rows(data: bytes) -> dict[int, dict[str, str]]:
        """Reads the same sheet exported as CSV: row N, column K is cell (K, N)."""

        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise BoxScoreFileError("The file encoding is not supported")
        if "\x00" in text:
            raise BoxScoreFileError("The file is not a valid .xlsx workbook or CSV")
        sample = text[:4096]
        delimiter = max((";", ",", "\t"), key=sample.count)
        if sample.count(delimiter) == 0:
            raise BoxScoreFileError("The file is not a valid .xlsx workbook or CSV")
        rows: dict[int, dict[str, str]] = {}
        for number, record in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
            for index, value in enumerate(record[: len(_COLUMNS)]):
                if value.strip() != "":
                    rows.setdefault(number, {})[_COLUMNS[index]] = value
        return rows

    def _read_xlsx_rows(self, data: bytes) -> dict[int, dict[str, str]]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise BoxScoreFileError("The file is not a valid .xlsx workbook") from None
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS or sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
            raise BoxScoreFileError("The workbook is too large to import", too_large=True)
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise BoxScoreFileError("The file is not a valid .xlsx workbook")
        try:
            shared = self._shared_strings(archive, names)
            sheet_path = self._first_sheet_path(archive)
            root = ET.fromstring(archive.read(sheet_path))
        except (ET.ParseError, KeyError):
            raise BoxScoreFileError("The workbook could not be read") from None

        rows: dict[int, dict[str, str]] = {}
        for cell in root.iter("{%s}c" % _NS["m"]):
            reference = cell.get("r")
            if not reference:
                continue
            value = cell.find("m:v", _NS)
            if value is not None and value.text is not None:
                text = shared[int(value.text)] if cell.get("t") == "s" else value.text
            else:
                inline = cell.find("m:is", _NS)
                text = "".join(t.text or "" for t in inline.iter("{%s}t" % _NS["m"])) if inline is not None else ""
            if text != "":
                rows.setdefault(_row_of(reference), {})[_column_of(reference)] = text
        return rows

    @staticmethod
    def _shared_strings(archive: zipfile.ZipFile, names: set[str]) -> list[str]:
        if "xl/sharedStrings.xml" not in names:
            return []
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        return ["".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])) for si in root.findall("m:si", _NS)]

    @staticmethod
    def _first_sheet_path(archive: zipfile.ZipFile) -> str:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.find("m:sheets", _NS)
        if sheets is None or len(sheets) == 0:
            raise KeyError("sheets")
        relationship_id = sheets[0].get("{%s}id" % _REL_NS)
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for relationship in relationships:
            if relationship.get("Id") == relationship_id:
                target = relationship.get("Target", "").lstrip("/")
                return target if target.startswith("xl/") else f"xl/{target}"
        raise KeyError(relationship_id)
