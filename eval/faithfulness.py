# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["ragas==0.4.3", "langchain-community==0.4.1", "openai>=1.60,<3", "httpx>=0.27"]
# [tool.uv]
# exclude-newer = "2026-01-20T00:00:00Z"  # resolve as of the ragas 0.4.3 release (langchain API)
# ///
"""RAGAS faithfulness (spec section 12) on a stratified subset of the Phase 6 answers.

    uv run --script eval/faithfulness.py [--tag c512] [--n 100]

Standalone (PEP 723): RAGAS and its LangChain/instructor dependencies stay out of the
workspace lock and never reach a service image. Reads eval/runs/<kb>.<tag>.jsonl, picks ~n
answered questions (the LLM did not fall back) stratified by KB and question type, and scores
each with ragas.metrics.collections.Faithfulness: the answer is split into statements, each
checked against the passages the LLM saw (2 judge calls per answer). Judge = the dev LLM
(LLM_BASE_URL / LLM_MODEL, thinking off). The proxy adds the API key for api.groq.com, so the
client sends no Authorization header of its own. Results are appended to
eval/runs/faithfulness.<tag>.jsonl (resumable); the summary goes to stdout and the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI
from ragas.llms.base import llm_factory
from ragas.metrics.collections import Faithfulness

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval/runs"
KBS = ("kb1_retail", "kb2_saas_fr", "kb3_hr_ar")
_MARKER = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")


def env(key: str, default: str) -> str:
    """Environment first, then the repo's .env (no secrets are read from it)."""
    if key in os.environ:
        return os.environ[key]
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"')
    return default


def pick(tag: str, n: int, seed: int = 12) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for kb in KBS:
        path = RUNS / f"{kb}.{tag}.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        answered = [r for r in rows if not r["llm_fallback"] and not r.get("error")]
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in answered:
            by_type[r["type"]].append(r)
        per_kb = math.ceil(n / len(KBS))
        for items in by_type.values():
            k = max(1, round(per_kb * len(items) / max(1, len(answered))))
            out += rng.sample(items, min(k, len(items)))
    return out


async def strip_auth(request: httpx.Request) -> None:
    request.headers.pop("Authorization", None)  # the egress proxy injects the real key


async def main(args: argparse.Namespace) -> int:
    out = RUNS / f"faithfulness.{args.tag}.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["id"]] = row
    sample = pick(args.tag, args.n)
    todo = [r for r in sample if r["id"] not in done]
    print(f"faithfulness: {len(sample)} sampled, {len(todo)} to score")

    base_url = env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model = env("LLM_MODEL", "qwen/qwen3.8-27b")
    switch = env("LLM_THINKING_SWITCH", "reasoning_effort")
    extra: dict[str, Any] = {"temperature": 0.0, "max_tokens": 1500}
    if switch == "reasoning_effort":
        extra["reasoning_effort"] = "none"
    elif switch == "chat_template_kwargs":
        extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    http = httpx.AsyncClient(event_hooks={"request": [strip_auth]}, timeout=120)
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("LLM_API_KEY", "injected-by-proxy"),
        http_client=http if "LLM_API_KEY" not in os.environ else None,
        max_retries=10,  # 429: the SDK honours Retry-After
    )
    metric = Faithfulness(llm=llm_factory(model, client=client, **extra))

    with out.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(todo, 1):
            answer = _MARKER.sub("", r["answer"]).strip()
            try:
                result = await metric.ascore(
                    user_input=r["question"], response=answer, retrieved_contexts=r["contexts"]
                )
                score, error = float(result.value), None
            except Exception as exc:  # judge output that fails validation: record, go on
                score, error = float("nan"), f"{type(exc).__name__}: {str(exc)[:200]}"
            row = {"id": r["id"], "kb": r["kb"], "type": r["type"], "score": score, "error": error}
            done[r["id"]] = row
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if i % 10 == 0:
                print(f"  {i}/{len(todo)}", flush=True)

    scored = [done[r["id"]] for r in sample if r["id"] in done]
    valid = [x["score"] for x in scored if not math.isnan(x["score"])]
    summary = {
        "tag": args.tag,
        "judge": model,
        "sampled": len(sample),
        "scored": len(valid),
        "faithfulness_mean": sum(valid) / len(valid) if valid else None,
        "share_fully_faithful": sum(v >= 0.999 for v in valid) / len(valid) if valid else None,
        "by_kb": {
            kb: sum(v) / len(v)
            for kb in KBS
            if (v := [x["score"] for x in scored if x["kb"] == kb and not math.isnan(x["score"])])
        },
        "by_type": {
            t: sum(v) / len(v)
            for t in ("answerable", "tricky", "unanswerable")
            if (v := [x["score"] for x in scored if x["type"] == t and not math.isnan(x["score"])])
        },
        "lowest": sorted(
            ((x["score"], x["id"]) for x in scored if not math.isnan(x["score"])),
        )[:10],
    }
    (RUNS / f"faithfulness.{args.tag}.summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))
    await http.aclose()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="c512")
    p.add_argument("--n", type=int, default=100)
    raise SystemExit(asyncio.run(main(p.parse_args())))
