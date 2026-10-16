# Phase 4 acceptance run (2026-10-16)

Stack: harrier-oss-v1-0.6b via embed-server (CPU), calibrated thresholds, Qwen3.8-27B on Groq (dev). Command: `make phase4-check`.

```
LLM: qwen/qwen3.8-27b @ https://api.groq.com/openai/v1 (thinking switch: reasoning_effort)
thresholds: 0.553 / 0.553 / 0.599 (/home/user/BEAI_RAG/config/thresholds.harrier-oss-v1-0.6b.json)

POST /test "What's your return policy?" -> 200
{
  "answer": "You can return unworn items in their original packaging within 30 days, provided you have the receipt. Please note that final-sale items, gift cards, and personalised products cannot be returned.",
  "spoken_text": "You can return unworn items in their original packaging within 30 days, provided you have the receipt. Please note that final-sale items, gift cards, and personalised products cannot be returned.",
  "sources": [
    {
      "file_name": "returns-policy.pdf",
      "page": 2,
      "section": "Section 4 - Returns",
      "url": null,
      "snippet": "Returns are accepted within 30 days, unworn, with receipt. Items must be in their original packaging with all tags attached. Final-sale items, gift cards and personalised products cannot be returned.…",
      "score": 0.6148
    }
  ],
  "confidence": "high",
  "fallback": false,
  "latency_ms": {
    "embed": 926.8,
    "search": 19.5,
    "rerank": 0.0,
    "llm_ttft": 586.3,
    "llm_total": 671.0,
    "total": 1631.2
  },
  "cache_hit": false,
  "error": null
}

POST /test 'What is the capital of Australia?' -> {"answer": "I'm not sure about that. Would you like me to connect you with someone?", "spoken_text": "I'm not sure about that. Would you like me to connect you with someone?", "sources": [], "confidence": "low", "fallback": true, "latency_ms": {"embed": 590.3, "search": 14.2, "rerank": 0.0, "total": 613.9}, "cache_hit": false, "error": null}
  SSE 'How much does standard delivery cost?': conf=high fallback=False ttft=610.4 ms, rate-limit wait=0 ms, src=['returns-policy.pdf']
  SSE 'How long is a gift card valid?': conf=high fallback=False ttft=297.7 ms, rate-limit wait=0 ms, src=['store-faq.md']
  SSE 'When is a parcel treated as lost?': conf=high fallback=False ttft=292.8 ms, rate-limit wait=0 ms, src=['shipping-guide.pdf']
  SSE 'Can swimwear be returned?': conf=high fallback=False ttft=276.2 ms, rate-limit wait=0 ms, src=['returns-policy.pdf']
  SSE 'What do I need to make a warranty claim?': conf=medium fallback=False ttft=292.1 ms, rate-limit wait=0 ms, src=['warranty.txt']
  SSE 'Which carrier delivers parcels in France?': conf=high fallback=False ttft=250.3 ms, rate-limit wait=0 ms, src=['shipping-guide.pdf']
  SSE 'How should I wash a wool jumper?': conf=high fallback=False ttft=290.2 ms, rate-limit wait=0 ms, src=['product-care.docx']
  SSE 'Do Acme Plus members pay for standard shipping?': conf=high fallback=False ttft=281.3 ms, rate-limit wait=0 ms, src=['returns-policy.pdf']

LLM TTFT over 8 answers: p50 291 ms, p95 501 ms (rate-limit waits excluded; total waited 0.0 s)

Checks:
  [PASS] mentions 30 days
  [PASS] mentions unworn
  [PASS] mentions receipt
  [PASS] source returns-policy.pdf p.2
  [PASS] confidence high
  [PASS] not fallback
  [PASS] unanswerable -> fallback
  [PASS] unanswerable -> LLM not called

PHASE 4 ACCEPTANCE: PASS
```
