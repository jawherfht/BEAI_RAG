"""Structure-aware chunker (spec section 5, step 3).

- Sizes are in tokens of the embedding model's tokenizer (``TokenCounter``).
- Splits on structure first: a chunk never spans two sections (heading paths) or two web
  pages; within a section, whole paragraphs are packed; a paragraph larger than the chunk
  size is split into sentences. A chunk never ends mid-sentence.
- A table is kept whole unless it alone exceeds 2 x chunk_size; then it is split by rows and
  every part repeats the header row.
- A single sentence longer than 2 x chunk_size is the only case that is cut by tokens.
- Overlap: the next chunk starts with trailing whole sentences of the previous chunk, up to
  ``chunk_overlap`` tokens (never with table rows).
- Every chunk keeps ``page`` (first page), ``page_end`` (last page) and ``section``.
"""

from __future__ import annotations

from dataclasses import dataclass

from beai_rag_core.embedding.base import TokenCounter
from worker.chunking.sentences import split_sentences
from worker.parsers.base import Element, ElementKind, ParsedDocument

SECTION_SEPARATOR = " > "


@dataclass(slots=True)
class Chunk:
    index: int
    text: str
    section: str | None
    page: int | None
    page_end: int | None
    url: str | None
    title: str | None
    token_count: int


@dataclass(slots=True)
class _Piece:
    text: str
    tokens: int
    page: int | None
    is_table: bool = False


@dataclass(slots=True)
class _Group:
    section: str | None
    url: str | None
    title: str | None
    elements: list[Element]


class Chunker:
    def __init__(self, counter: TokenCounter, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("invalid chunk_size / chunk_overlap")
        self._counter = counter
        self._size = chunk_size
        self._overlap = chunk_overlap

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        for group in _group_by_section(doc.elements):
            for text, tokens, page, page_end in self._pack(self._pieces(group.elements)):
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        text=text,
                        section=group.section,
                        page=page,
                        page_end=page_end,
                        url=group.url,
                        title=group.title,
                        token_count=tokens,
                    )
                )
        return chunks

    # ---- pieces: paragraphs, sentences or table parts --------------------------------

    def _pieces(self, elements: list[Element]) -> list[_Piece]:
        pieces: list[_Piece] = []
        for el in elements:
            text = el.text.strip()
            if not text:
                continue
            tokens = self._counter.count(text)
            if el.kind is ElementKind.TABLE:
                if tokens <= 2 * self._size:
                    pieces.append(_Piece(text, tokens, el.page, is_table=True))
                else:
                    pieces.extend(self._split_table(text, el.page))
            elif tokens <= self._size:
                pieces.append(_Piece(text, tokens, el.page))
            else:
                for sentence in split_sentences(text):
                    pieces.extend(self._sentence_pieces(sentence, el.page))
        return pieces

    def _sentence_pieces(self, sentence: str, page: int | None) -> list[_Piece]:
        tokens = self._counter.count(sentence)
        if tokens <= 2 * self._size:
            return [_Piece(sentence, tokens, page)]
        # Pathological run-on "sentence": the only case cut by tokens.
        return [
            _Piece(part, self._counter.count(part), page)
            for part in self._counter.split_to_budget(sentence, self._size)
        ]

    def _split_table(self, table: str, page: int | None) -> list[_Piece]:
        lines = table.splitlines()
        header = (
            lines[:2]
            if len(lines) > 2 and set(lines[1].replace("|", "").strip()) <= set("-: ")
            else lines[:1]
        )
        rows = lines[len(header) :]
        parts: list[_Piece] = []
        current: list[str] = []
        header_tokens = self._counter.count("\n".join(header))
        budget = max(self._size - header_tokens, 1)
        used = 0
        for row in rows:
            row_tokens = self._counter.count(row)
            if current and used + row_tokens > budget:
                text = "\n".join(header + current)
                parts.append(_Piece(text, self._counter.count(text), page, is_table=True))
                current, used = [], 0
            current.append(row)
            used += row_tokens
        if current:
            text = "\n".join(header + current)
            parts.append(_Piece(text, self._counter.count(text), page, is_table=True))
        return parts

    # ---- packing ---------------------------------------------------------------------

    def _pack(self, pieces: list[_Piece]) -> list[tuple[str, int, int | None, int | None]]:
        out: list[tuple[str, int, int | None, int | None]] = []
        current: list[_Piece] = []
        used = 0
        for piece in pieces:
            if current and used + piece.tokens > self._size:
                out.append(_emit(current, used))
                current = self._overlap_from(current)
                used = sum(p.tokens for p in current)
                if current and used + piece.tokens > self._size:
                    current, used = [], 0
            current.append(piece)
            used += piece.tokens
        if current:
            out.append(_emit(current, used))
        return out

    def _overlap_from(self, previous: list[_Piece]) -> list[_Piece]:
        if self._overlap == 0 or previous[-1].is_table:
            return []
        last = previous[-1]
        carried: list[_Piece] = []
        used = 0
        for sentence in reversed(split_sentences(last.text)):
            tokens = self._counter.count(sentence)
            if used + tokens > self._overlap:
                break
            carried.insert(0, _Piece(sentence, tokens, last.page))
            used += tokens
        for p in carried:
            p.is_table = False
        return carried


def _emit(pieces: list[_Piece], tokens: int) -> tuple[str, int, int | None, int | None]:
    pages = [p.page for p in pieces if p.page is not None]
    text = "\n\n".join(p.text for p in pieces)
    return text, tokens, (min(pages) if pages else None), (max(pages) if pages else None)


def _group_by_section(elements: list[Element]) -> list[_Group]:
    groups: list[_Group] = []
    path: list[tuple[int, str]] = []
    current: _Group | None = None
    for el in elements:
        if el.kind is ElementKind.HEADING:
            level = max(el.level, 1)
            path = [(lvl, txt) for lvl, txt in path if lvl < level]
            path.append((level, el.text.strip()))
            current = None
            continue
        # Web pages start with their title as a level-1 heading (see web_crawler), so the
        # path resets per page; ``el.title`` is the fallback for pages without headings.
        section = SECTION_SEPARATOR.join(t for _, t in path) or el.title
        if current is None or current.section != section or current.url != el.url:
            current = _Group(section=section, url=el.url, title=el.title, elements=[])
            groups.append(current)
        current.elements.append(el)
    return groups
