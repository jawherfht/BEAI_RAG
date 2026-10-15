"""Token counting with the embedding model's tokenizer (chunk sizes are in tokens)."""

from __future__ import annotations

import re
import threading
from typing import Any

_WS = re.compile(r"\S+")


class HFTokenCounter:
    """Loads ``tokenizer.json`` of a Hugging Face model with the ``tokenizers`` library."""

    def __init__(self, model: str, revision: str = "main") -> None:
        self._model = model
        self._revision = revision
        self._tok: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._tok is None:
                from tokenizers import Tokenizer

                self._tok = Tokenizer.from_pretrained(self._model, revision=self._revision)
            return self._tok

    def count(self, text: str) -> int:
        return len(self._load().encode(text, add_special_tokens=False).ids)

    def split_to_budget(self, text: str, budget: int) -> list[str]:
        enc = self._load().encode(text, add_special_tokens=False)
        if len(enc.ids) <= budget:
            return [text]
        pieces: list[str] = []
        for i in range(0, len(enc.ids), budget):
            start = enc.offsets[i][0]
            end = enc.offsets[min(i + budget, len(enc.ids)) - 1][1]
            pieces.append(text[start:end].strip())
        return [p for p in pieces if p]


class WhitespaceTokenCounter:
    """Approximate counter (one token per whitespace-separated word). Tests and tooling only."""

    def count(self, text: str) -> int:
        return len(_WS.findall(text))

    def split_to_budget(self, text: str, budget: int) -> list[str]:
        words = _WS.findall(text)
        return [" ".join(words[i : i + budget]) for i in range(0, len(words), budget)] or [""]
