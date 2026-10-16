"""Threshold calibration (spec section 12) for the dense grounding score.

    uv run python eval/calibrate.py [--kb kb1_retail]

1. Ingests the KB with the real models and records, for every question, the best dense cosine
   among the top-4 retrieved chunks (= the pipeline's ``top_score``) and whether the gold
   evidence is in the top 4.
2. SCORE_THRESHOLD = the highest threshold whose false fallback on answerable questions is
   <= 5 % (this maximises correct fallback on unanswerable ones).
3. CONF_HIGH / CONF_MID = the lowest scores above which >= 95 % / >= 85 % of questions are
   answerable AND correctly retrieved (bucket precision).
Writes config/thresholds.<embed model>.json (loaded by rag-api) and a report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, datetime

from harness import ROOT, session  # type: ignore[import-not-found]
from retrieval_eval import DOCS, norm  # type: ignore[import-not-found]

from app.retrieval.retriever import RetrievalSettings

MAX_FALSE_FALLBACK = 0.05
HIGH_PRECISION = 0.95
MID_PRECISION = 0.85


def sweep(rows: list[dict]) -> dict:  # type: ignore[type-arg]
    ans = [r for r in rows if r["type"] == "answerable"]
    una = [r for r in rows if r["type"] == "unanswerable"]
    grid = [i / 1000 for i in range(0, 1001)]

    def false_fb(t: float) -> float:
        return float(sum(r["top_score"] < t for r in ans)) / len(ans)

    def correct_fb(t: float) -> float:
        return float(sum(r["top_score"] < t for r in una)) / len(una)

    threshold = max(t for t in grid if false_fb(t) <= MAX_FALSE_FALLBACK)

    def precision_above(t: float) -> float | None:
        above = [r for r in rows if r["top_score"] >= t]
        if len(above) < 5:
            return None
        good = sum(r["type"] == "answerable" and r["found@4"] for r in above)
        return round(float(good) / len(above), 4)

    def lowest_with(p: float) -> float:
        for t in grid:
            if t < threshold:
                continue
            prec = precision_above(t)
            if prec is not None and prec >= p:
                return t
        return 1.0

    mid = lowest_with(MID_PRECISION)
    high = max(lowest_with(HIGH_PRECISION), mid)
    return {
        "score_threshold": threshold,
        "conf_mid": mid,
        "conf_high": high,
        "metrics": {
            "false_fallback_answerable": round(false_fb(threshold), 4),
            "correct_fallback_unanswerable": round(correct_fb(threshold), 4),
            "precision_at_or_above_mid": precision_above(mid),
            "precision_at_or_above_high": precision_above(high),
            "share_answerable_high": round(sum(r["top_score"] >= high for r in ans) / len(ans), 4),
        },
    }


async def collect(kb: str) -> tuple[list[dict], str, str]:  # type: ignore[type-arg]
    folder = ROOT / "eval/datasets" / kb
    questions = [json.loads(line) for line in (folder / "questions.jsonl").read_text().splitlines()]
    rows = []
    async with session() as s:
        await s.upload([folder / d for d in DOCS])
        await s.wait_ready()
        settings = RetrievalSettings(top_k=4)
        await s.resources.retriever.retrieve(s.scope, "warm up", replace(settings, top_k=1))
        for q in questions:
            res = await s.resources.retriever.retrieve(
                s.scope, q["question"], settings, score_threshold=0.0
            )
            found = bool(q["evidence"]) and any(
                norm(q["evidence"]) in norm(c.text) for c in res.candidates
            )
            rows.append(
                {
                    "id": q["id"],
                    "type": q["type"],
                    "top_score": res.top_score or 0.0,
                    "found@4": found,
                }
            )
        return rows, s.resources.settings.embed_model, s.resources.settings.embed_model_revision


async def main(args: argparse.Namespace) -> int:
    t = time.monotonic()
    rows, model, revision = await collect(args.kb)
    result = sweep(rows)
    name = model.rsplit("/", 1)[-1]
    out = {
        "embed_model": model,
        "embed_model_revision": revision,
        "dataset": args.kb,
        "questions": {
            "answerable": sum(r["type"] == "answerable" for r in rows),
            "unanswerable": sum(r["type"] == "unanswerable" for r in rows),
        },
        "calibrated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "preliminary (KB #1 only); full calibration in Phase 6",
        **result,
    }
    cfg = ROOT / "config" / f"thresholds.{name}.json"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text(json.dumps(out, indent=2) + "\n")
    (ROOT / "eval/reports" / f"calibration-{args.kb}-{name}.json").write_text(
        json.dumps(rows, indent=2) + "\n"
    )

    ans = sorted(r["top_score"] for r in rows if r["type"] == "answerable")
    una = sorted(r["top_score"] for r in rows if r["type"] == "unanswerable")
    report = [
        f"# Threshold calibration — {args.kb}, {model}@{revision[:8]}",
        "",
        f"{out['status']}. {len(ans)} answerable, {len(una)} unanswerable questions; {time.monotonic() - t:.0f} s.",
        "",
        "| Value | Calibrated | Placeholder |",
        "|---|---|---|",
        f"| SCORE_THRESHOLD | **{result['score_threshold']:.3f}** | 0.45 |",
        f"| CONF_MID | **{result['conf_mid']:.3f}** | 0.55 |",
        f"| CONF_HIGH | **{result['conf_high']:.3f}** | 0.70 |",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| False fallback on answerable | {result['metrics']['false_fallback_answerable']:.3f} | ≤ 0.05 |",
        f"| Correct fallback on unanswerable | {result['metrics']['correct_fallback_unanswerable']:.3f} | ≥ 0.90 |",
        f"| Precision at/above CONF_MID | {result['metrics']['precision_at_or_above_mid']} | ≥ {MID_PRECISION} |",
        f"| Precision at/above CONF_HIGH | {result['metrics']['precision_at_or_above_high']} | ≥ {HIGH_PRECISION} |",
        f"| Answerable questions bucketed high | {result['metrics']['share_answerable_high']:.3f} | — |",
        "",
        "Top-score distribution (dense cosine of the best of 4 chunks):",
        "",
        "| Set | min | p10 | median | p90 | max |",
        "|---|---|---|---|---|---|",
    ]

    def at(v: list[float], p: float) -> float:
        return v[min(len(v) - 1, int(p * (len(v) - 1)))]

    for label, v in (("answerable", ans), ("unanswerable", una)):
        report.append(
            f"| {label} | {v[0]:.3f} | {at(v, 0.1):.3f} | {at(v, 0.5):.3f} | {at(v, 0.9):.3f} | {v[-1]:.3f} |"
        )
    text = "\n".join(report) + "\n"
    (ROOT / "eval/reports" / f"calibration-{args.kb}-{name}.md").write_text(text)
    print(text)
    print(f"wrote {cfg}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--kb", default="kb1_retail")
    raise SystemExit(asyncio.run(main(p.parse_args())))
