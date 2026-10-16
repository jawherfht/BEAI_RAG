"""Phase 3 retrieval evaluation on KB #1: recall@4, MRR@10, retrieval latency.

    uv run python eval/retrieval_eval.py [--rerank] [--no-hybrid] [--chunk 512]

Ingests KB #1 for a fresh tenant with the real models, then for every answerable question
retrieves the top 10 (no answer cache) and checks where the gold evidence first appears.
A question counts as found at rank r if the r-th chunk contains its evidence phrase.
Writes a Markdown report to eval/reports/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import unicodedata
from dataclasses import replace

from harness import ROOT, percentile, session  # type: ignore[import-not-found]

from app.retrieval.retriever import RetrievalSettings

KB1 = ROOT / "eval/datasets/kb1_retail"
DOCS = [
    "returns-policy.pdf",
    "shipping-guide.pdf",
    "product-care.docx",
    "store-faq.md",
    "warranty.txt",
]


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("–", "-").casefold()
    return " ".join(text.split())


async def main(args: argparse.Namespace) -> int:
    questions = [json.loads(line) for line in (KB1 / "questions.jsonl").read_text().splitlines()]
    questions = [q for q in questions if q["type"] == "answerable"]
    if args.limit:
        questions = questions[:: max(1, len(questions) // args.limit)][: args.limit]
    async with session() as s:
        await s.put_settings(
            chunk_size=args.chunk, hybrid_enabled=not args.no_hybrid, rerank_enabled=args.rerank
        )
        t = time.monotonic()
        await s.upload([KB1 / d for d in DOCS])
        sources = await s.wait_ready()
        ingest_s = time.monotonic() - t
        errors = [x for x in sources if x["status"] == "error"]
        if errors:
            print("ingestion errors:", errors)
            return 1
        chunks_total = sum(x["chunks"] or 0 for x in sources)

        retriever = s.resources.retriever
        settings = RetrievalSettings(
            top_k=10, hybrid_enabled=not args.no_hybrid, rerank_enabled=args.rerank
        )
        # Warm-up (first query loads lazy state), not measured.
        await retriever.retrieve(s.scope, "warm up", replace(settings, top_k=4))
        ranks: list[int | None] = []
        lat: dict[str, list[float]] = {
            "embed": [],
            "search": [],
            "rerank": [],
            "retrieval_total": [],
        }
        misses = []
        page_hits = 0
        for q in questions:
            result = await retriever.retrieve(s.scope, q["question"], settings, score_threshold=0.0)
            for k in lat:
                lat[k].append(result.latency_ms.get(k, 0.0))
            ev = norm(q["evidence"])
            rank = next(
                (i + 1 for i, c in enumerate(result.candidates) if ev in norm(c.text)), None
            )
            ranks.append(rank)
            if rank is not None and rank <= 4:
                c = result.candidates[rank - 1]
                gold = q["gold"]
                if c.file_name == gold["file_name"] and (
                    gold["page"] is None or c.page == gold["page"]
                ):
                    page_hits += 1
            else:
                top = result.candidates[0] if result.candidates else None
                misses.append(
                    (
                        q["id"],
                        q["question"],
                        rank,
                        top.file_name if top else None,
                        (top.text[:80] if top else ""),
                    )
                )

    n = len(questions)
    recall4 = sum(1 for r in ranks if r is not None and r <= 4) / n
    recall1 = sum(1 for r in ranks if r == 1) / n
    mrr10 = sum(1 / r for r in ranks if r is not None and r <= 10) / n
    mode = f"{'hybrid' if not args.no_hybrid else 'dense'}{'+rerank' if args.rerank else ''}, chunk {args.chunk}"
    if args.limit:
        mode += f", subset {n}"
    lines = [
        f"# Phase 3 retrieval — KB #1 ({mode})",
        "",
        f"Questions: {n} answerable · sources: {len(DOCS)} · chunks: {chunks_total} · ingest {ingest_s:.0f} s",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| Recall@4 (evidence in top 4) | **{recall4:.3f}** | ≥ 0.90 |",
        f"| Recall@1 | {recall1:.3f} | — |",
        f"| MRR@10 | **{mrr10:.3f}** | ≥ 0.75 |",
        f"| Citation file+page correct (of recall@4 hits) | {page_hits}/{sum(1 for r in ranks if r and r <= 4)} | — |",
        "",
        "Latency per query (ms), this machine:",
        "",
        "| Stage | p50 | p95 |",
        "|---|---|---|",
    ]
    for k, v in lat.items():
        lines.append(f"| {k} | {percentile(v, 50):.1f} | {percentile(v, 95):.1f} |")
    if misses:
        lines += ["", "Misses (evidence not in top 4):", ""]
        lines += [f'- `{i}` {q} → rank {r}; top-1 from {f}: "{t}…"' for i, q, r, f, t in misses]
    report = "\n".join(lines) + "\n"
    out = (
        ROOT
        / "eval/reports"
        / f"phase3-retrieval-{mode.replace(', ', '-').replace(' ', '').replace('+', '-')}.md"
    )
    out.write_text(report)
    print(report)
    print(f"wrote {out}")
    return 0 if recall4 >= 0.90 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rerank", action="store_true")
    p.add_argument("--no-hybrid", action="store_true")
    p.add_argument("--chunk", type=int, default=512)
    p.add_argument("--limit", type=int, default=0, help="evaluate an evenly spaced subset")
    raise SystemExit(asyncio.run(main(p.parse_args())))
