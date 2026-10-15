"""Optional contextual chunk prefixes (CONTEXTUAL_CHUNKS=true), generated offline by the LLM.

One short sentence situating each chunk in its document is stored as ``context_prefix`` and
embedded as ``context_prefix + "\\n" + text``; users only ever see ``text``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import httpx

logger = logging.getLogger(__name__)

PROMPT = (
    '<document title="{title}">\n{document}\n</document>\n'
    "Here is a passage from this document:\n<passage>\n{chunk}\n</passage>\n"
    "Write ONE short sentence, in the language of the document, that situates this passage "
    "within the document to improve search retrieval. Reply with the sentence only."
)


class Contextualiser:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        disable_thinking: bool = True,
        concurrency: int = 4,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=60,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._model = model
        self._disable_thinking = disable_thinking
        self._sem = asyncio.Semaphore(concurrency)

    async def close(self) -> None:
        await self._client.aclose()

    async def prefixes(self, title: str, document: str, chunks: Sequence[str]) -> list[str]:
        doc_excerpt = document[:6000]
        return list(await asyncio.gather(*(self._one(title, doc_excerpt, c) for c in chunks)))

    async def _one(self, title: str, document: str, chunk: str) -> str:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT.format(title=title, document=document, chunk=chunk),
                }
            ],
            "temperature": 0.0,
            "max_tokens": 60,
        }
        if self._disable_thinking:
            # vLLM/Qwen3 switch; exact flag is verified per model (docs/decisions/0001-models.md).
            body["chat_template_kwargs"] = {"enable_thinking": False}
        async with self._sem:
            try:
                resp = await self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                text = str(resp.json()["choices"][0]["message"]["content"]).strip()
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                logger.warning("contextual prefix failed; continuing without it", exc_info=True)
                return ""
        return text.splitlines()[0][:300] if text else ""
