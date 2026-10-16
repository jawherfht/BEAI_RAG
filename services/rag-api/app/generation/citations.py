"""Citation parsing and text variants (spec section 6, step 9).

- ``[n]`` markers (also ``[1, 2]`` and ``[1][2]``) map to the numbered CONTEXT passages.
- ``display_text``: the answer for the chat/test panel (markers removed; the "see Section 4"
  wording the model writes stays).
- ``spoken_text``: the same without markers, markdown or URLs (for TTS).
- ``SpokenStream`` removes markers from streamed tokens incrementally.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from app.retrieval.retriever import RetrievedChunk

_MARKER = re.compile(r"\s*\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_URL = re.compile(r"(?:https?://|www\.)\S*[^\s.,;:!?)\]]")  # keeps trailing punctuation
_TAIL = re.compile(r"\s*(?:\[[\d,\s]*)?$")  # whitespace and/or an unfinished "[1,"
_MARKDOWN = re.compile(r"[*_`#>|]+")
_SPACES = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?؟。])")


@dataclass(frozen=True, slots=True)
class Source:
    file_name: str | None
    page: int | None
    section: str | None
    url: str | None
    snippet: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "page": self.page,
            "section": self.section,
            "url": self.url,
            "snippet": self.snippet,
            "score": round(self.score, 4),
        }


@dataclass(frozen=True, slots=True)
class ParsedAnswer:
    display_text: str
    spoken_text: str
    sources: list[Source]
    cited: list[int]  # 1-based passage numbers in order of first citation


def cited_numbers(text: str, n_passages: int) -> list[int]:
    seen: list[int] = []
    for match in _MARKER.finditer(text):
        for part in match.group(1).split(","):
            n = int(part)
            if 1 <= n <= n_passages and n not in seen:
                seen.append(n)
    return seen


def strip_markers(text: str) -> str:
    text = _MARKER.sub("", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACES.sub(" ", text).strip()


def to_spoken(text: str) -> str:
    text = strip_markers(text)
    text = _URL.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACES.sub(" ", text).strip()


def to_source(chunk: RetrievedChunk) -> Source:
    return Source(
        file_name=chunk.file_name or chunk.title,
        page=chunk.page,
        section=chunk.section,
        url=chunk.url,
        snippet=chunk.snippet,
        score=chunk.score,
    )


def parse_answer(raw: str, passages: list[RetrievedChunk]) -> ParsedAnswer:
    cited = cited_numbers(raw, len(passages))
    return ParsedAnswer(
        display_text=strip_markers(raw),
        spoken_text=to_spoken(raw),
        sources=[to_source(passages[n - 1]) for n in cited],
        cited=cited,
    )


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def is_fallback_answer(answer: str, fallback_message: str, threshold: float = 0.8) -> bool:
    """True if the model replied with the fallback sentence (rule 2)."""
    a, f = _norm(strip_markers(answer)), _norm(fallback_message)
    if not a or not f:
        return False
    if f in a and len(a) <= len(f) * 1.5:
        return True
    return difflib.SequenceMatcher(None, a, f).ratio() >= threshold


class SpokenStream:
    """Incrementally removes ``[n]`` markers from streamed tokens (for live TTS).

    Trailing whitespace and an unfinished ``[...`` are held back until the next token shows
    whether a marker follows, so " [1]" disappears completely, including its space.
    """

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, token: str) -> str:
        text = _MARKER.sub("", self._pending + token)
        tail = _TAIL.search(text)
        cut = tail.start() if tail else len(text)
        self._pending = text[cut:]
        return text[:cut]

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        stripped = rest.strip()
        if stripped.startswith("[") and re.fullmatch(r"\[[\d,\s]*", stripped):
            return ""
        return rest
