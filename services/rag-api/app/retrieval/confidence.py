"""Grounding threshold and confidence buckets (spec section 6, steps 5-6).

Confidence is a bucket (high / medium / low), never shown as a percentage. Thresholds are
calibrated per embedding model (and separately for re-ranker scores) on the eval set.
"""

from __future__ import annotations

from dataclasses import dataclass

from beai_rag_core.enums import Confidence


@dataclass(frozen=True, slots=True)
class Thresholds:
    score_threshold: float  # below -> fallback, the LLM is not called
    conf_mid: float
    conf_high: float

    def __post_init__(self) -> None:
        if not self.score_threshold <= self.conf_mid <= self.conf_high:
            raise ValueError("thresholds must satisfy score_threshold <= conf_mid <= conf_high")

    def is_grounded(self, top_score: float | None) -> bool:
        return top_score is not None and top_score >= self.score_threshold

    def bucket(self, top_score: float | None) -> Confidence:
        if top_score is None:
            return Confidence.LOW
        if top_score >= self.conf_high:
            return Confidence.HIGH
        if top_score >= self.conf_mid:
            return Confidence.MEDIUM
        return Confidence.LOW
