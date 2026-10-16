"""Text normalisation for matching gold evidence phrases against retrieved chunks."""

from __future__ import annotations

import re
import unicodedata

# Arabic diacritics (harakat) and tatweel; PDF/DOCX extraction may keep or drop them.
_ARABIC_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_DASHES = str.maketrans({"–": "-", "—": "-", "’": "'", " ": " ", " ": " "})


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).casefold()
    text = _ARABIC_MARKS.sub("", text)
    return " ".join(text.split())


def contains(haystack: str, needle: str) -> bool:
    return norm(needle) in norm(haystack)
