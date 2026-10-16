"""Phase 6 evaluation (spec section 12): collect per-question signals and answers for one KB.

    uv run python eval/run_eval.py --kb kb1_retail [--chunk 512] [--rerank] [--subset 60]

For a fresh tenant: ingest the KB with the real models, then for every question
1. retrieve the top 10 (no gate, no cache) -> rank of the gold evidence (recall@4, MRR@10),
   the best dense cosine of the top 4 and retrieval latency;
2. score the top 4 passages with the re-ranker (Qwen3-Reranker-0.6B, P(yes)) -> the candidate
   grounding signal ("top-4 check"); with --rerank the live path also re-ranks 50 candidates;
3. ask POST /test once with the grounding gate disabled (thresholds 0) -> the LLM's answer,
   whether the LLM itself fell back, its citations and TTFT.
Gate strategies are then replayed offline by eval/report.py: final fallback = gate(signal) OR
the LLM's own fallback. One LLM call per question keeps the run within Groq's free quota.

Rows are appended to eval/runs/<kb>.<tag>.jsonl as they complete; a rerun skips finished ids.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from harness import ROOT, Session, session  # type: ignore[import-not-found]
from text_match import contains, norm  # type: ignore[import-not-found]

from app.config import Settings
from app.retrieval.retriever import RetrievalSettings, RetrievedChunk

RUNS: Path = ROOT / "eval/runs"
FALLBACK_MESSAGES = {
    # The tenant's fallback message in the agent's language (as a French / Arabic agent would
    # configure it), so rule 2's "reply exactly with" needs no translation to be detected.
    "kb2_saas_fr": "Je ne suis pas sûr de pouvoir répondre à cela. Voulez-vous que je vous mette en relation avec un conseiller ?",
    "kb3_hr_ar": "لست متأكدا من الإجابة على ذلك. هل تريد أن أوصلك بأحد الموظفين؟",
}


def load_questions(kb: str) -> list[dict[str, Any]]:
    path = ROOT / "eval/datasets" / kb / "questions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def stratified(questions: list[dict[str, Any]], n: int, seed: int = 6) -> list[dict[str, Any]]:
    """n questions in the dataset's type proportions (100/30/20 -> 40/12/8 for n=60)."""
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in questions:
        by_type[q["type"]].append(q)
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for items in by_type.values():
        k = round(n * len(items) / len(questions))
        out += rng.sample(items, min(k, len(items)))
    return sorted(out, key=lambda q: str(q["id"]))


def evidence_rank(q: dict[str, Any], chunks: list[RetrievedChunk]) -> int | None:
    """Rank of the first chunk holding the (first) evidence phrase."""
    if not q["evidence"]:
        return None
    return next((i + 1 for i, c in enumerate(chunks) if contains(c.text, q["evidence"][0])), None)


def all_evidence_in(q: dict[str, Any], chunks: list[RetrievedChunk]) -> bool:
    text = " ".join(norm(c.text) for c in chunks)
    return bool(q["evidence"]) and all(norm(e) in text for e in q["evidence"])


def citation_ok(gold: list[dict[str, Any]], sources: list[dict[str, Any]]) -> bool | None:
    """True if a cited source matches a gold file (+ page when the gold has one)."""
    if not gold or not sources:
        return None
    return any(
        s.get("file_name") == g["file_name"] and (g["page"] is None or s.get("page") == g["page"])
        for s in sources
        for g in gold
    )


async def ask(s: Session, question: str, attempts: int = 4) -> dict[str, Any]:
    for attempt in range(attempts):
        r = await s.client.post(f"{s.base}/test", headers=s.headers, json={"question": question})
        r.raise_for_status()
        body: dict[str, Any] = r.json()
        if body.get("error") != "llm_unavailable":
            return body
        await asyncio.sleep(30 * (attempt + 1))  # quota window; the client already retried
    return body


def run_tag(chunk: int, rerank: bool, subset: int, label: str = "") -> str:
    tag = f"c{chunk}{'-rerank' if rerank else ''}{f'-s{subset}' if subset else ''}"
    return f"{tag}-{label}" if label else tag


def plan(args: argparse.Namespace) -> tuple[Path, list[dict[str, Any]], int, int]:
    """(output file, questions still to run, already done, total) — reruns resume."""
    questions = load_questions(args.kb)
    if args.subset:
        questions = stratified(questions, args.subset)
    tag = run_tag(args.chunk, args.rerank, args.subset, args.label)
    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"{args.kb}.{tag}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines()}
    return out, [q for q in questions if q["id"] not in done], len(done), len(questions)


async def run(args: argparse.Namespace, out: Path, todo: list[dict[str, Any]], n_done: int, n_total: int) -> None:  # fmt: skip
    kb = args.kb
    folder = ROOT / "eval/datasets" / kb

    # Gate off: every question reaches the LLM; gates are replayed offline.
    settings = Settings(score_threshold=0.0, conf_mid=0.0, conf_high=0.0, rerank_score_threshold=0.0, rerank_conf_mid=0.0, rerank_conf_high=0.0, rerank_timeout_s=600.0)  # fmt: skip
    async with session(settings=settings) as s:
        kb_settings: dict[str, Any] = {"chunk_size": args.chunk, "rerank_enabled": args.rerank}
        if kb in FALLBACK_MESSAGES:
            kb_settings["fallback_message"] = FALLBACK_MESSAGES[kb]
        await s.put_settings(**kb_settings)
        t = time.monotonic()
        docs = sorted(
            p for p in folder.iterdir() if p.suffix in {".pdf", ".docx", ".md", ".html", ".txt"}
        )
        await s.upload(docs)
        sources = await s.wait_ready()
        if any(x["status"] == "error" for x in sources):
            raise SystemExit(f"ingestion errors: {sources}")
        print(
            f"{kb}: ingested {len(docs)} docs, {sum(x['chunks'] or 0 for x in sources)} chunks in {time.monotonic() - t:.0f} s"
        )

        r = s.resources
        kb_version = int(
            (await s.client.get(f"{s.base}/knowledge-base", headers=s.headers)).json()["kb_version"]
        )
        assert r.reranker is not None, "the eval needs the re-ranker (RERANK_URL)"
        top10 = RetrievalSettings(top_k=10, rerank_enabled=args.rerank)
        await r.retriever.retrieve(
            s.scope, "warm up", replace(top10, top_k=1, rerank_enabled=False)
        )
        with out.open("a", encoding="utf-8") as fh:
            for i, q in enumerate(todo, 1):
                res = await r.retriever.retrieve(s.scope, q["question"], top10, score_threshold=0.0)
                ranked, top4 = res.candidates, res.candidates[:4]
                t_rr = time.perf_counter()
                if res.reranked:  # top 4 already carry their scores from the 50-candidate pass
                    rr = [c.rerank_score or 0.0 for c in top4]
                    # /test would re-rank the same 50 candidates again (~100 s on CPU): hand it
                    # this result through the retrieval cache instead.
                    primed = replace(res, chunks=top4, candidates=[], fallback=False)
                    await r.retrieval_cache.set(
                        s.scope, kb_version, q["question"], primed.to_dict()
                    )
                else:
                    rr = await r.reranker.rerank(q["question"], [c.text for c in top4])
                rerank4_ms = (time.perf_counter() - t_rr) * 1000
                body = await ask(s, q["question"])
                lat = body.get("latency_ms") or {}
                row = {
                    "id": q["id"],
                    "kb": kb,
                    "type": q["type"],
                    "question": q["question"],
                    "gold": q["gold"],
                    "rank": evidence_rank(q, ranked),
                    "all_evidence@4": all_evidence_in(q, top4),
                    "gold_file@4": any(
                        c.file_name == g["file_name"] and (g["page"] is None or c.page == g["page"])
                        for c in top4
                        for g in q["gold"]
                    ),
                    "dense4": [round(c.dense_score, 4) for c in top4],
                    "rerank4": [round(x, 4) for x in rr],
                    "rerank50_top": round(top4[0].rerank_score, 4)
                    if res.reranked and top4 and top4[0].rerank_score is not None
                    else None,
                    "contexts": [c.text for c in top4],
                    "answer": body["answer"],
                    "llm_fallback": body["fallback"],
                    "error": body.get("error"),
                    "sources": [
                        {"file_name": x.get("file_name"), "page": x.get("page")}
                        for x in body["sources"]
                    ],
                    "citation_ok": citation_ok(q["gold"], body["sources"]),
                    "lat": {
                        "embed": res.latency_ms.get("embed", 0.0),
                        "search": res.latency_ms.get("search", 0.0),
                        "rerank50": res.latency_ms.get("rerank", 0.0),
                        "rerank4": round(rerank4_ms, 1),
                        "llm_ttft": lat.get("llm_ttft"),
                        "llm_total": lat.get("llm_total"),
                        "rate_limit_wait": lat.get("llm_rate_limit_wait", 0.0),
                    },
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                if i % 10 == 0 or i == len(todo):
                    print(f"{kb}: {n_done + i}/{n_total}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--kb", required=True)
    p.add_argument("--chunk", type=int, default=512)
    p.add_argument("--rerank", action="store_true", help="re-rank 50 candidates on the live path")
    p.add_argument("--subset", type=int, default=0, help="stratified subset of n questions")
    p.add_argument("--label", default="", help="suffix for the run tag (e.g. a model name)")
    args = p.parse_args()
    out, todo, n_done, n_total = plan(args)
    if todo:
        asyncio.run(run(args, out, todo, n_done, n_total))
    print(f"{out.name}: {n_total} rows", file=sys.stderr)
