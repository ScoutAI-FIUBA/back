from __future__ import annotations

BASKETBALL_POSITIONS: dict[str, str] = {
    "PG": "Base",
    "SG": "Escolta",
    "SF": "Alero",
    "PF": "Ala-Pívot",
    "C": "Pívot",
}

VALID_POSITION_CODES = frozenset(BASKETBALL_POSITIONS)


def is_valid_position(code: str) -> bool:
    return code in VALID_POSITION_CODES
