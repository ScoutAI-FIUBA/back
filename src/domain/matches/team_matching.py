from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable

# Words that say nothing about which team it is; federations and rosters spell them differently.
_FILLER_WORDS = frozenset({"club", "c", "cd", "ca", "csd", "sc", "ac", "de", "del", "la", "el", "los", "las", "y", "and", "the", "fc", "bc"})

NAME_MATCH_THRESHOLD = 0.6
ROSTER_MATCH_THRESHOLD = 0.5


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()


def name_tokens(name: str) -> list[str]:
    """Lowercase words without accents or punctuation ("Bos. Celtics" -> bos, celtics)."""

    words = (re.sub(r"[^a-z0-9]", "", word) for word in _fold(name).split())
    tokens = [word for word in words if word]
    meaningful = [word for word in tokens if word not in _FILLER_WORDS]
    return meaningful or tokens


def _is_abbreviation(short: str, full: str) -> bool:
    """bos -> boston, brk -> brooklyn: same first letter and the rest in order."""

    if len(short) < 3 or short[0] != full[0]:
        return False
    remaining = iter(full)
    return all(letter in remaining for letter in short)


def _tokens_alike(left: str, right: str) -> bool:
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if _is_abbreviation(shorter, longer):
        return True
    return len(shorter) >= 4 and SequenceMatcher(None, left, right).ratio() >= 0.85  # small typo


def name_similarity(left: str, right: str) -> float:
    """0..1. How well two team names describe the same team, tolerant of abbreviations."""

    a, b = name_tokens(left), name_tokens(right)
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    unused = list(longer)
    matched = 0
    for token in shorter:
        for candidate in unused:
            if _tokens_alike(token, candidate):
                unused.remove(candidate)
                matched += 1
                break
    return matched / len(shorter)


def surname_matches(file_name: str, last_name: str) -> bool:
    """File names read "SURNAME, GIVEN NAMES"; the roster keeps the surname separately."""

    file_surname = "".join(name_tokens(file_name.split(",")[0]))
    roster_surname = "".join(name_tokens(last_name))
    if not file_surname or not roster_surname:
        return False
    if file_surname in roster_surname or roster_surname in file_surname:
        return True
    return SequenceMatcher(None, file_surname, roster_surname).ratio() >= 0.85


def roster_similarity(file_players: Iterable[tuple[str | None, str]], roster: Iterable[tuple[str | None, str]]) -> float | None:
    """Share of players that appear in both the file and the roster (same jersey number and surname).

    Both arguments are (jersey_number, surname-or-name) pairs. ``None`` means there is no
    evidence either way (an empty roster or no jersey numbers), which is not the same as 0.
    """

    file_list = [(number, name) for number, name in file_players if number]
    roster_list = [(number, name) for number, name in roster if number]
    if not file_list or not roster_list:
        return None
    unused = list(roster_list)
    matched = 0
    for number, name in file_list:
        for entry in unused:
            if entry[0] == number and surname_matches(name, entry[1]):
                unused.remove(entry)
                matched += 1
                break
    return matched / min(len(file_list), len(roster_list))


def same_team(name_score: float, roster_score: float | None) -> bool:
    return name_score >= NAME_MATCH_THRESHOLD or (roster_score is not None and roster_score >= ROSTER_MATCH_THRESHOLD)
