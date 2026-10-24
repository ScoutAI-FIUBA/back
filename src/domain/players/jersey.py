from __future__ import annotations


def normalize_jersey_number(value: str) -> str:
    """Compares jersey numbers by value: "07" and "7" are the same number.

    "0" and "00" stay distinct (both exist in basketball), so only numbers with a non-zero
    digit lose their leading zeros.
    """

    text = value.strip()
    if text.isdigit() and text.strip("0"):
        return text.lstrip("0")
    return text
