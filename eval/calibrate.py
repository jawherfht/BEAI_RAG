"""Threshold calibration (spec section 12) from the Phase 6 runs of the three KBs.

    uv run python eval/calibrate.py [--tag c512] [--signal auto|dense|rerank]

Reads eval/runs/<kb>.<tag>.jsonl (written by eval/run_eval.py; no re-ingestion) and, on all
three KBs pooled:
- SCORE_THRESHOLD / RERANK_SCORE_THRESHOLD: maximise correct fallback on unanswerable questions,
  end to end (gate OR the LLM's own fallback), with false fallback on answerable <= 5 %;
- CONF_MID / CONF_HIGH (and the RERANK_ ones): lowest scores above which >= 85 % / >= 95 % of
  the answers passing the gate are answerable and cite the gold source;
- GROUNDING_SIGNAL: with --signal auto, the signal with the best leave-one-KB-out correct
  fallback whose held-out false fallback stays <= 5 % on every KB.
Writes config/thresholds.<embed model>.json, which rag-api loads at startup.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from gates import (  # type: ignore[import-not-found]
    MAX_FALSE_FALLBACK,
    calibrate,
    confidence_cuts,
    leave_one_out,
    loo_score,
    rates,
)
from harness import ROOT  # type: ignore[import-not-found]
from report import KBS, load  # type: ignore[import-not-found]

from app.config import Settings


def main(args: argparse.Namespace) -> int:
    data = {kb: rows for kb in KBS if (rows := load(kb, args.tag))}
    if len(data) < 2:
        raise SystemExit("need runs for at least two KBs (eval/run_eval.py)")
    pooled = [r for rows in data.values() for r in rows]

    values: dict[str, float] = {}
    metrics: dict[str, object] = {}
    loo: dict[str, tuple[float, float]] = {}
    for signal in ("dense", "rerank"):
        gate = calibrate(signal, pooled, no_citation=False)
        threshold = getattr(gate, f"t_{signal}")
        mid, high = confidence_cuts(signal, pooled, gate)
        prefix = "" if signal == "dense" else "rerank_"
        values |= {f"{prefix}score_threshold": threshold, f"{prefix}conf_mid": mid, f"{prefix}conf_high": high}  # fmt: skip
        r = rates(gate, pooled)
        loo[signal] = loo_score(leave_one_out(data, signal, no_citation=False))
        metrics[signal] = {
            "correct_fallback_unanswerable": round(r.correct_fallback, 4),
            "false_fallback_answerable": round(r.false_fallback, 4),
            "llm_calls_saved": round(r.llm_calls_saved, 4),
            "leave_one_kb_out_correct_fallback": round(loo[signal][0], 4),
            "leave_one_kb_out_worst_false_fallback": round(loo[signal][1], 4),
        }

    signal = args.signal
    if signal == "auto":
        ok = [s for s in loo if loo[s][1] <= MAX_FALSE_FALLBACK + 1e-9] or list(loo)
        signal = max(ok, key=lambda s: loo[s][0])

    settings = Settings()
    name = settings.embed_model.rsplit("/", 1)[-1]
    out = {
        "embed_model": settings.embed_model,
        "embed_model_revision": settings.embed_model_revision,
        "rerank_model": settings.rerank_model,
        "datasets": {kb: len(rows) for kb, rows in data.items()},
        "calibrated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": f"Phase 6, {len(data)} KBs pooled (eval/reports/phase6-eval.md)",
        "grounding_signal": signal,
        **{k: round(v, 3) for k, v in values.items()},
        "metrics": metrics,
    }
    cfg: Path = ROOT / "config" / f"thresholds.{name}.json"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print(f"wrote {cfg}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="c512")
    p.add_argument("--signal", choices=["auto", "dense", "rerank"], default="auto")
    raise SystemExit(main(p.parse_args()))
