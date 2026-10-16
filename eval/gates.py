"""Offline grounding-gate replay and threshold calibration over eval/runs rows.

A gate decides, before the LLM is called, that the knowledge base cannot answer. End to end:
    fallback = gate(signal) OR the LLM's own fallback reply [OR the answer cites nothing]
Rows come from eval/run_eval.py, where every question reached the LLM with the gate off, so
any gate can be replayed without new LLM calls.

Signals:  dense  = best dense cosine of the top 4 (spec 6, step 5)
          rerank = best Qwen3-Reranker P(yes) of the top 4 ("top-4 check")
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

Row = dict[str, Any]
MAX_FALSE_FALLBACK = 0.05
GRID = [i / 1000 for i in range(0, 1001)]


def is_answerable(row: Row) -> bool:
    return row["type"] in {"answerable", "tricky"}


def dense(row: Row) -> float:
    return max(row["dense4"], default=0.0)


def rerank(row: Row) -> float:
    return max(row["rerank4"], default=0.0)


SIGNALS: dict[str, Callable[[Row], float]] = {"dense": dense, "rerank": rerank}


def llm_fallback(row: Row, *, no_citation: bool) -> bool:
    return bool(row["llm_fallback"]) or (no_citation and not row["sources"])


@dataclass(frozen=True)
class Gate:
    """fallback if dense < t_dense or rerank < t_rerank (None = signal unused)."""

    t_dense: float | None = None
    t_rerank: float | None = None
    no_citation: bool = False

    def gated(self, row: Row) -> bool:
        return (self.t_dense is not None and dense(row) < self.t_dense) or (
            self.t_rerank is not None and rerank(row) < self.t_rerank
        )

    def fallback(self, row: Row) -> bool:
        return self.gated(row) or llm_fallback(row, no_citation=self.no_citation)

    @property
    def name(self) -> str:
        parts = []
        if self.t_dense is not None:
            parts.append(f"dense<{self.t_dense:.3f}")
        if self.t_rerank is not None:
            parts.append(f"rerank<{self.t_rerank:.3f}")
        base = " or ".join(parts) or "LLM only"
        return base + (" (+no citation)" if self.no_citation else "")


@dataclass(frozen=True)
class Rates:
    correct_fallback: float  # unanswerable questions that fell back
    false_fallback: float  # answerable (+ tricky) questions that fell back
    llm_calls_saved: float  # share of all questions stopped before the LLM
    n_unanswerable: int
    n_answerable: int


def rates(gate: Gate, rows: Sequence[Row]) -> Rates:
    ans = [r for r in rows if is_answerable(r)]
    una = [r for r in rows if not is_answerable(r)]
    return Rates(
        correct_fallback=sum(gate.fallback(r) for r in una) / max(1, len(una)),
        false_fallback=sum(gate.fallback(r) for r in ans) / max(1, len(ans)),
        llm_calls_saved=sum(gate.gated(r) for r in rows) / max(1, len(rows)),
        n_unanswerable=len(una),
        n_answerable=len(ans),
    )


def _better(a: Rates, b: Rates | None) -> bool:
    if b is None:
        return True
    return (a.correct_fallback, -a.false_fallback, a.llm_calls_saved) > (
        b.correct_fallback,
        -b.false_fallback,
        b.llm_calls_saved,
    )


def _plateau_mid(values: list[float]) -> float:
    """Middle of the best thresholds: the same score on the calibration set, more margin."""
    return values[len(values) // 2]


def calibrate_single(signal: str, rows: Sequence[Row], *, no_citation: bool) -> Gate:
    best: Rates | None = None
    ties: list[float] = []
    for t in GRID:
        gate = Gate(**{f"t_{signal}": t}, no_citation=no_citation)
        r = rates(gate, rows)
        if r.false_fallback > MAX_FALSE_FALLBACK:
            continue
        key = (r.correct_fallback, -r.false_fallback)
        if best is None or key > (best.correct_fallback, -best.false_fallback):
            best, ties = r, [t]
        elif key == (best.correct_fallback, -best.false_fallback):
            ties.append(t)
    t = _plateau_mid(ties) if ties else 0.0
    return Gate(**{f"t_{signal}": t}, no_citation=no_citation)


def calibrate_combined(rows: Sequence[Row], *, no_citation: bool, step: int = 10) -> Gate:
    coarse = GRID[::step]
    best: tuple[Rates, Gate] | None = None
    for td in coarse:
        for tr in coarse:
            gate = Gate(td, tr, no_citation)
            r = rates(gate, rows)
            if r.false_fallback <= MAX_FALSE_FALLBACK and _better(r, best[0] if best else None):
                best = (r, gate)
    return best[1] if best else Gate(0.0, 0.0, no_citation)


def calibrate(strategy: str, rows: Sequence[Row], *, no_citation: bool) -> Gate:
    if strategy == "llm":
        return Gate(no_citation=no_citation)
    if strategy == "combined":
        return calibrate_combined(rows, no_citation=no_citation)
    return calibrate_single(strategy, rows, no_citation=no_citation)


STRATEGIES = ("llm", "dense", "rerank", "combined")


def confidence_cuts(
    signal: str, rows: Sequence[Row], gate: Gate, high: float = 0.95, mid: float = 0.85
) -> tuple[float, float]:
    """CONF_MID / CONF_HIGH: lowest signal values above which >= mid / >= high of the answers
    that pass the gate are answerable AND cite the gold source (bucket precision)."""
    fn = SIGNALS[signal]
    passed = [r for r in rows if not gate.fallback(r)]
    floor = getattr(gate, f"t_{signal}") or 0.0

    def precision(t: float) -> float | None:
        above = [r for r in passed if fn(r) >= t]
        if len(above) < 10:
            return None
        return sum(is_answerable(r) and bool(r["citation_ok"]) for r in above) / len(above)

    def lowest(p: float) -> float:
        for t in GRID:
            if t >= floor and (prec := precision(t)) is not None and prec >= p:
                return t
        return 1.0

    m = lowest(mid)
    return m, max(m, lowest(high))


def leave_one_out(
    data: dict[str, list[Row]], strategy: str, *, no_citation: bool
) -> dict[str, tuple[Gate, Rates]]:
    """Calibrate on all KBs but one, measure on the held-out KB."""
    out: dict[str, tuple[Gate, Rates]] = {}
    for held in data:
        train = [r for kb, rows in data.items() if kb != held for r in rows]
        gate = calibrate(strategy, train, no_citation=no_citation)
        out[held] = (gate, rates(gate, data[held]))
    return out


def loo_score(loo: dict[str, tuple[Gate, Rates]]) -> tuple[float, float]:
    """(mean held-out correct fallback, worst held-out false fallback)."""
    mean = sum(r.correct_fallback for _, r in loo.values()) / max(1, len(loo))
    worst = max((r.false_fallback for _, r in loo.values()), default=0.0)
    return mean, worst
