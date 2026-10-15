"""Per-document language detection with lingua (Apache-2.0), low-accuracy mode for speed."""

from __future__ import annotations

import threading
from typing import Any

_detector: Any = None
_lock = threading.Lock()


def _get() -> Any:
    global _detector
    with _lock:
        if _detector is None:
            from lingua import LanguageDetectorBuilder

            _detector = (
                LanguageDetectorBuilder.from_all_languages().with_low_accuracy_mode().build()
            )
        return _detector


def detect_language(text: str) -> str | None:
    """ISO 639-1 code (e.g. "en", "fr", "ar") or None if unknown."""
    sample = text[:4000].strip()
    if len(sample) < 20:
        return None
    lang = _get().detect_language_of(sample)
    if lang is None:
        return None
    return str(lang.iso_code_639_1.name).lower()
