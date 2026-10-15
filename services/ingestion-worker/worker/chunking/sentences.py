"""Multilingual sentence splitting (Latin, CJK and Arabic punctuation)."""

from __future__ import annotations

import re

_BOUNDARY = re.compile(r"(?<=[.!?。！？؟۔])[\"'”’)\]]*\s+|\n+")
_ABBREVIATIONS = frozenset(
    {
        "e.g.",
        "i.e.",
        "etc.",
        "mr.",
        "mrs.",
        "ms.",
        "dr.",
        "prof.",
        "no.",
        "vs.",
        "fig.",
        "p.",
        "pp.",
        "st.",
        "inc.",
        "ltd.",
        "co.",
        "art.",
        "sec.",
        "approx.",
        "ca.",
        "cf.",
        "env.",
    }
)


def split_sentences(text: str) -> list[str]:
    """Split on sentence-final punctuation followed by whitespace, or on newlines.

    Does not split after common abbreviations, single letters ("J. Smith") or numbers ("4. ").
    """
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        candidate = text[start : match.start()].strip()
        if not candidate:
            start = match.end()
            continue
        if match.group(0).strip("\"'”’)] \t") == "" and _is_false_boundary(candidate):
            continue
        sentences.append(text[start : match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_false_boundary(candidate: str) -> bool:
    last = candidate.rsplit(None, 1)[-1].lower()
    if last in _ABBREVIATIONS:
        return True
    core = last.rstrip(".")
    return (len(core) == 1 and core.isalpha()) or (core.isdigit() and last.endswith("."))
