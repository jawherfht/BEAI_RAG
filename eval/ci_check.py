"""CI eval subset (spec section 12): 30 questions, fail if a metric drops > 3 points from main.

    uv run python eval/ci_check.py [--tag c512-s10] [--update-baseline]

Run eval/run_eval.py --subset 10 for each KB first (10 stratified questions per KB = 30).
The metrics use the gate rag-api is configured with (config/thresholds.<model>.json), i.e. the
live behaviour, and are compared with eval/ci/baseline.json, which is refreshed on main with
--update-baseline whenever a change is meant to move the numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gates import Gate, Row, is_answerable, rates  # type: ignore[import-not-found]
from harness import ROOT  # type: ignore[import-not-found]
from report import KBS, citation_accuracy, load, retrieval  # type: ignore[import-not-found]

from app.config import Settings

BASELINE: Path = ROOT / "eval/ci/baseline.json"
MAX_DROP = 0.03
# Higher is better for all but false fallback.
LOWER_IS_BETTER = {"false_fallback"}


def live_gate(settings: Settings) -> Gate:
    if settings.grounding_signal == "rerank":
        return Gate(t_rerank=settings.rerank_score_threshold)
    return Gate(t_dense=settings.score_threshold)


def metrics(rows: list[Row], gate: Gate) -> dict[str, float]:
    r = rates(gate, rows)
    ret = retrieval(rows)
    return {
        "recall@4": round(ret["recall@4"], 4),
        "mrr@10": round(ret["mrr@10"], 4),
        "citation_accuracy": round(citation_accuracy(rows, gate), 4),
        "correct_fallback": round(r.correct_fallback, 4),
        "false_fallback": round(r.false_fallback, 4),
    }


def main(args: argparse.Namespace) -> int:
    rows = [r for kb in KBS for r in load(kb, args.tag)]
    if not rows:
        raise SystemExit(f"no rows for tag {args.tag}: run eval/run_eval.py --subset 10 first")
    gate = live_gate(Settings())
    current = metrics(rows, gate)
    n_ans = sum(is_answerable(r) for r in rows)
    print(f"{len(rows)} questions ({n_ans} answerable), gate `{gate.name}`")
    print(json.dumps(current, indent=2))
    if args.update_baseline or not BASELINE.exists():
        # First run (no baseline yet): record this run as the baseline. In CI it is printed
        # and uploaded as an artifact so it can be committed; the next run compares against it.
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(
            json.dumps({"tag": args.tag, "gate": gate.name, **current}, indent=2) + "\n"
        )
        print(f"wrote {BASELINE} (no comparison on this run):")
        print(BASELINE.read_text())
        return 0
    base = json.loads(BASELINE.read_text())
    failed = []
    for key, value in current.items():
        drop = (value - base[key]) if key in LOWER_IS_BETTER else (base[key] - value)
        status = "FAIL" if drop > MAX_DROP + 1e-9 else "ok"
        print(f"{status:4} {key:18} {base[key]:.3f} -> {value:.3f}")
        if status == "FAIL":
            failed.append(key)
    if failed:
        print(f"metrics dropped more than {MAX_DROP * 100:.0f} points: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="c512-s10")
    p.add_argument("--update-baseline", action="store_true")
    sys.exit(main(p.parse_args()))
