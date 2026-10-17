"""Offline stand-in for an OpenAI-compatible LLM (local-mode smoke tests, no API key/quota).

Answers by quoting the first sentence of CONTEXT passage [1] with a [1] citation, or the
fallback sentence from the system prompt when there is no context. Streams SSE like the
real endpoints. Test-only: used by deploy/local/compose.test.yml, never in production.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FALLBACK = re.compile(r'reply exactly with: "([^"]+)"')
# "[1] (file, p.2, Section 4) passage text" up to the next block or the question.
PASSAGE = re.compile(r"^\[1\] \([^)]*\) (.+?)(?:\n\n\[2\]|\n\nQUESTION|\Z)", re.S | re.M)


def answer(messages: list[dict[str, str]]) -> str:
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    user = messages[-1]["content"] if messages else ""
    m = PASSAGE.search(user)
    if not m:
        fb = FALLBACK.search(system)
        return fb.group(1) if fb else "I don't know."
    first = re.split(r"(?<=[.!?])\s", " ".join(m.group(1).split()), maxsplit=1)[0]
    return f"{first} [1]"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet
        return

    def do_GET(self) -> None:
        body = json.dumps({"object": "list", "data": [{"id": "mock-llm", "object": "model"}]})
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self) -> None:
        req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
        text = answer(req.get("messages", []))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for word in re.findall(r"\S+\s*", text):
            chunk = {"choices": [{"delta": {"content": word}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        usage = {
            "choices": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": len(text) // 4},
        }
        self.wfile.write(f"data: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()  # noqa: S104
