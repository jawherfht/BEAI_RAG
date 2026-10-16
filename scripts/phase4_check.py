"""Phase 4 acceptance check (spec section 15) with the real stack.

- POST /test {"question": "What's your return policy?"} -> answer equivalent to
  "30 days, unworn, with receipt — see Section 4.", source returns-policy.pdf p.2,
  confidence high.
- An unanswerable question returns the fallback WITHOUT calling the LLM.
- TTFT p50/p95 over several questions via /answer (SSE). The spec target (<= 500 ms p95) is
  for vLLM on the GPU pool; in dev the LLM is whatever LLM_BASE_URL points to.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from harness import percentile, session  # type: ignore[import-not-found]  # noqa: E402

KB1 = ROOT / "eval/datasets/kb1_retail"
DOCS = [
    "returns-policy.pdf",
    "shipping-guide.pdf",
    "product-care.docx",
    "store-faq.md",
    "warranty.txt",
]
WIREFRAME_Q = "What's your return policy?"
UNANSWERABLE_Q = "What is the capital of Australia?"
TTFT_QUESTIONS = [
    "How much does standard delivery cost?",
    "How long is a gift card valid?",
    "When is a parcel treated as lost?",
    "Can swimwear be returned?",
    "What do I need to make a warranty claim?",
    "Which carrier delivers parcels in France?",
    "How should I wash a wool jumper?",
    "Do Acme Plus members pay for standard shipping?",
]


class CountingLLM:
    """Wraps the real LLM client to count calls (proves "no LLM call" for the fallback)."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.calls = inner, 0

    def stream(self, messages: Any, **kw: Any) -> Any:
        self.calls += 1
        return self.inner.stream(messages, **kw)

    async def ping(self) -> None:
        await self.inner.ping()

    async def close(self) -> None:
        await self.inner.close()


async def sse_answer(s, question: str) -> dict:  # type: ignore[no-untyped-def, type-arg]
    done = {}
    async with s.client.stream(
        "POST", f"{s.base}/answer", headers=s.headers, json={"question": question}
    ) as r:
        r.raise_for_status()
        event = None
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "done":
                done = json.loads(line[6:])
    return done


async def main() -> int:
    ok = True
    async with session() as s:
        s.resources.llm = llm = CountingLLM(s.resources.llm)
        settings = s.resources.settings
        print(
            f"LLM: {settings.llm_model} @ {settings.llm_base_url} (thinking switch: {settings.llm_thinking_switch})"
        )
        print(
            f"thresholds: {settings.score_threshold} / {settings.conf_mid} / {settings.conf_high} ({settings.thresholds_source})"
        )
        await s.upload([KB1 / d for d in DOCS])
        await s.wait_ready()

        r = await s.client.post(f"{s.base}/test", headers=s.headers, json={"question": WIREFRAME_Q})
        body = r.json()
        print(f"\nPOST /test {WIREFRAME_Q!r} -> {r.status_code}")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        text = body.get("answer", "").lower()
        src = body.get("sources") or [{}]
        checks = {
            "mentions 30 days": "30" in text and "day" in text,
            "mentions unworn": "unworn" in text,
            "mentions receipt": "receipt" in text,
            "source returns-policy.pdf p.2": src[0].get("file_name") == "returns-policy.pdf"
            and src[0].get("page") == 2,
            "confidence high": body.get("confidence") == "high",
            "not fallback": body.get("fallback") is False,
        }

        before = llm.calls
        r = await s.client.post(
            f"{s.base}/test", headers=s.headers, json={"question": UNANSWERABLE_Q}
        )
        fb = r.json()
        print(f"\nPOST /test {UNANSWERABLE_Q!r} -> {json.dumps(fb, ensure_ascii=False)}")
        checks["unanswerable -> fallback"] = fb.get("fallback") is True and fb.get("sources") == []
        checks["unanswerable -> LLM not called"] = llm.calls == before

        ttft, waits = [], []
        for q in TTFT_QUESTIONS:
            done = await sse_answer(s, q)
            lat = done.get("latency_ms", {})
            if "llm_ttft" in lat:
                ttft.append(lat["llm_ttft"])
                waits.append(lat.get("llm_rate_limit_wait", 0.0))
            print(
                f"  SSE {q!r}: conf={done.get('confidence')} fallback={done.get('fallback')} "
                f"ttft={lat.get('llm_ttft')} ms, rate-limit wait={lat.get('llm_rate_limit_wait', 0)} ms, "
                f"src={[x.get('file_name') for x in done.get('sources', [])]}"
            )
        if ttft:
            print(
                f"\nLLM TTFT over {len(ttft)} answers: p50 {percentile(ttft, 50):.0f} ms, "
                f"p95 {percentile(ttft, 95):.0f} ms (rate-limit waits excluded; total waited {sum(waits) / 1000:.1f} s)"
            )

    print("\nChecks:")
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("\nPHASE 4 ACCEPTANCE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
