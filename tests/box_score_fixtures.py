"""Builds a synthetic federation box score (.xlsx / .csv) for tests. No real people."""
from __future__ import annotations

import csv
import io
import zipfile
from xml.sax.saxutils import escape

COLUMNS = "ABCDEFGHIJKLMNOPQRSTUV"
GROUP_ROW = {"E": "TC 2P", "G": "TC 3P", "I": "TL", "K": "Rebotes", "Q": "TAP", "S": "FAL"}
HEADERS = [
    "Num.", "Nombre", "MIN", "PTS", "A/I", "%", "A/I", "%", "A/I", "%",
    "DEF", "OF", "Tot.", "AST", "REC", "PER", "TC", "TR", "FC", "FR", "VAL", "+/-",
]


def player(number, name, minutes, pts, two, three, ft, reb=(0, 0), ast=0, rec=0, per=0):
    return [
        str(number), name, minutes, str(pts), two, "0", three, "0", ft, "0",
        str(reb[0]), str(reb[1]), str(sum(reb)), str(ast), str(rec), str(per), "0", "0", "1", "1", "5", "0",
    ]


def totals(minutes, pts, two, three, ft):
    return ["", "TOTALES", minutes, str(pts), two, "0", three, "0", ft, "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]


HOME_PLAYERS = [
    player(4, "ALFA, UNO", "30:00", 8, "2/4", "0/1", "4/5"),
    player(5, "BETA, DOS", "25:30", 5, "1/2", "1/3", "0/0"),
    player(6, "GAMMA, TRES", "00:00", 0, "0/0", "0/0", "0/0"),
]
AWAY_PLAYERS = [
    player(7, "DELTA, CUATRO", "35:00", 7, "2/3", "0/0", "3/4"),
    player(7, "EPSILON, CINCO", "10:00", 2, "1/1", "0/0", "0/0"),
]


def grid(*, home_points=13, away_points=9, title="Estadísticas - Club Alfa vs Club Beta - LIGA TEST - 2026", home_name="Club Alfa", away_name="Club Beta"):
    rows: list[list[str]] = [[] for _ in range(5)]
    rows.append([title])
    rows.extend([[] for _ in range(4)])
    rows.append(["TOTALES"])
    rows.append([])
    for name, players, pts in ((home_name, HOME_PLAYERS, home_points), (away_name, AWAY_PLAYERS, away_points)):
        rows.append([name])
        group = [""] * 22
        for column, label in GROUP_ROW.items():
            group[COLUMNS.index(column)] = label
        rows.append(group)
        rows.append(list(HEADERS))
        rows.append([])
        rows.extend(list(r) for r in players)
        rows.append(totals("200:00", pts, "0/0", "0/0", "0/0"))
        rows.append([])
    return rows


def as_csv(rows, *, delimiter=";", encoding="utf-8"):
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter).writerows(rows)
    return out.getvalue().encode(encoding)


def as_xlsx(rows) -> bytes:
    strings: list[str] = []

    def sid(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    sheet_rows = []
    for number, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{COLUMNS[i]}{number}" t="s"><v>{sid(v)}</v></c>' for i, v in enumerate(row) if v != ""
        )
        if cells:
            sheet_rows.append(f'<row r="{number}">{cells}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
    return buffer.getvalue()
