"""Phase 6 report (spec section 12) from the eval/runs rows of the three KBs.

    uv run python eval/report.py [--tag c512]

Gate thresholds are chosen by leave-one-KB-out: calibrated on two KBs, measured on the third,
so the reported rates are what a new customer's KB would see. Writes
eval/reports/phase6-eval.md and eval/reports/phase6-eval.json.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gates import (  # type: ignore[import-not-found]
    MAX_FALSE_FALLBACK,
    STRATEGIES,
    Gate,
    Row,
    calibrate,
    is_answerable,
    leave_one_out,
    loo_score,
    rates,
)
from harness import ROOT, percentile  # type: ignore[import-not-found]

KBS = ("kb1_retail", "kb2_saas_fr", "kb3_hr_ar")
LABEL = {
    "kb1_retail": "KB1 retail (EN)",
    "kb2_saas_fr": "KB2 SaaS (FR)",
    "kb3_hr_ar": "KB3 HR (AR)",
}
RUNS: Path = ROOT / "eval/runs"
REPORTS: Path = ROOT / "eval/reports"


def load(kb: str, tag: str) -> list[Row]:
    path = RUNS / f"{kb}.{tag}.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if not r.get("error")]


def retrieval(rows: Sequence[Row]) -> dict[str, float]:
    ans = [r for r in rows if is_answerable(r)]
    plain = [r for r in ans if r["type"] == "answerable"]
    tricky = [r for r in ans if r["type"] == "tricky"]
    n = max(1, len(ans))
    return {
        "recall@4": sum(r["rank"] is not None and r["rank"] <= 4 for r in ans) / n,
        "recall@4_answerable": sum(r["rank"] is not None and r["rank"] <= 4 for r in plain) / max(1, len(plain)),
        "tricky_all_evidence@4": sum(r["all_evidence@4"] for r in tricky) / max(1, len(tricky)),
        "gold_source@4": sum(r["gold_file@4"] for r in ans) / n,
        "mrr@10": sum(1 / r["rank"] for r in ans if r["rank"] is not None and r["rank"] <= 10) / n,
    }  # fmt: skip


def citation_accuracy(rows: Sequence[Row], gate: Gate) -> float:
    answered = [r for r in rows if is_answerable(r) and not gate.fallback(r)]
    return sum(bool(r["citation_ok"]) for r in answered) / max(1, len(answered))


def latency(rows: Sequence[Row]) -> dict[str, float]:
    ret = [r["lat"]["embed"] + r["lat"]["search"] for r in rows]
    rr4 = [r["lat"]["rerank4"] for r in rows if not r["lat"].get("rerank50")]
    ttft = [r["lat"]["llm_ttft"] for r in rows if r["lat"].get("llm_ttft")]
    return {
        "retrieval_p50": percentile(ret, 50),
        "retrieval_p95": percentile(ret, 95),
        "embed_p95": percentile([r["lat"]["embed"] for r in rows], 95),
        "search_p95": percentile([r["lat"]["search"] for r in rows], 95),
        "rerank4_p50": percentile(rr4, 50),
        "rerank4_p95": percentile(rr4, 95),
        "ttft_p50": percentile(ttft, 50),
        "ttft_p95": percentile(ttft, 95),
    }


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def main(args: argparse.Namespace) -> int:
    data = {kb: rows for kb in KBS if (rows := load(kb, args.tag))}
    if not data:
        raise SystemExit(f"no runs for tag {args.tag} in {RUNS}")
    pooled = [r for rows in data.values() for r in rows]
    md: list[str] = [
        "# Phase 6 evaluation",
        "",
        f"Runs: `eval/runs/*.{args.tag}.jsonl` · "
        + ", ".join(f"{LABEL[kb]}: {len(rows)} questions" for kb, rows in data.items()),
        "",
        "## Retrieval (gold evidence in the hybrid top k)",
        "",
        "| KB | Recall@4 | Recall@4 (plain answerable) | Tricky: all evidence in top 4 | Gold file+page in top 4 | MRR@10 |",
        "|---|---|---|---|---|---|",
    ]
    summary: dict[str, Any] = {"tag": args.tag, "retrieval": {}, "gates": {}, "latency": {}}
    for kb, rows in [*data.items(), ("all", pooled)]:
        m = retrieval(rows)
        summary["retrieval"][kb] = m
        md.append(
            f"| {LABEL.get(kb, 'All')} | {m['recall@4']:.3f} | {m['recall@4_answerable']:.3f} | "
            f"{m['tricky_all_evidence@4']:.3f} | {m['gold_source@4']:.3f} | {m['mrr@10']:.3f} |"
        )

    md += [
        "",
        "## Grounding gates, end to end (leave-one-KB-out)",
        "",
        "End-to-end fallback = gate before the LLM **or** the LLM's own fallback reply. Thresholds "
        f"are calibrated on two KBs (maximise correct fallback with false fallback ≤ {pct(MAX_FALSE_FALLBACK)}) "
        "and measured on the held-out KB. *+no citation*: an answer citing no passage also counts as a fallback.",
        "",
        "| Strategy | Held-out KB | Thresholds (from the other two) | Correct fallback (unanswerable) | False fallback (answerable+tricky) | LLM calls saved |",
        "|---|---|---|---|---|---|",
    ]
    best: tuple[float, str, bool] | None = None
    for strategy in STRATEGIES:
        for no_citation in (False, True):
            loo = leave_one_out(data, strategy, no_citation=no_citation)
            key = f"{strategy}{'+nocite' if no_citation else ''}"
            summary["gates"][key] = {kb: {"gate": g.name, **vars(r)} for kb, (g, r) in loo.items()}
            mean_correct, worst_false = loo_score(loo)
            for kb, (g, r) in loo.items():
                md.append(
                    f"| {key} | {LABEL[kb]} | `{g.name}` | {pct(r.correct_fallback)} | "
                    f"{pct(r.false_fallback)} | {pct(r.llm_calls_saved)} |"
                )
            md.append(
                f"| **{key}** | **mean** | | **{pct(mean_correct)}** | worst {pct(worst_false)} | |"
            )
            if worst_false <= MAX_FALSE_FALLBACK + 1e-9 and (
                best is None or mean_correct > best[0]
            ):
                best = (mean_correct, strategy, no_citation)

    md += ["", "## Chosen gate", ""]
    if best is None:
        md.append("No strategy kept false fallback ≤ 5 % on every held-out KB.")
        chosen = Gate()
    else:
        _, strategy, no_citation = best
        chosen = calibrate(strategy, pooled, no_citation=no_citation)
        pr = rates(chosen, pooled)
        summary["chosen"] = {
            "strategy": strategy,
            "no_citation": no_citation,
            "gate": chosen.name,
            **vars(pr),
        }
        md += [
            f"Best held-out mean: **{strategy}{' + no citation' if no_citation else ''}** "
            f"({pct(best[0])} correct fallback). Calibrated on all three KBs: `{chosen.name}` → "
            f"correct fallback {pct(pr.correct_fallback)}, false fallback {pct(pr.false_fallback)}, "
            f"{pct(pr.llm_calls_saved)} of questions stopped before the LLM.",
        ]

    md += [
        "",
        "## Quality and latency with the chosen gate",
        "",
        "| KB | Citation accuracy (file+page) | Correct fallback | False fallback | Retrieval p50 / p95 (embed+search, ms) | Re-rank top-4 p50 / p95 (ms, CPU) | LLM TTFT p50 / p95 (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for kb, rows in [*data.items(), ("all", pooled)]:
        lat = latency(rows)
        r = rates(chosen, rows)
        cit = citation_accuracy(rows, chosen)
        summary["latency"][kb] = lat
        summary.setdefault("citation_accuracy", {})[kb] = cit
        md.append(
            f"| {LABEL.get(kb, 'All')} | {cit:.3f} | {pct(r.correct_fallback)} | {pct(r.false_fallback)} | "
            f"{lat['retrieval_p50']:.0f} / {lat['retrieval_p95']:.0f} | {lat['rerank4_p50']:.0f} / {lat['rerank4_p95']:.0f} | "
            f"{lat['ttft_p50']:.0f} / {lat['ttft_p95']:.0f} |"
        )

    misses = [r for r in pooled if not is_answerable(r) and not chosen.fallback(r)]
    false_fb = [r for r in pooled if is_answerable(r) and chosen.fallback(r)]
    if misses:
        md += ["", "Unanswerable questions answered anyway (chosen gate):", ""]
        md += [f"- `{r['id']}` {r['question']} → dense {max(r['dense4']):.3f}, rerank {max(r['rerank4']):.3f}: “{r['answer'][:140]}”" for r in misses]  # fmt: skip
    if false_fb:
        md += ["", "Answerable questions that fell back (chosen gate):", ""]
        md += [f"- `{r['id']}` {r['question']} → dense {max(r['dense4']):.3f}, rerank {max(r['rerank4']):.3f}, LLM fallback {r['llm_fallback']}, rank {r['rank']}" for r in false_fb]  # fmt: skip

    text = "\n".join(md) + "\n"
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "phase6-eval.md").write_text(text, encoding="utf-8")
    (REPORTS / "phase6-eval.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print(text)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="c512")
    raise SystemExit(main(p.parse_args()))
