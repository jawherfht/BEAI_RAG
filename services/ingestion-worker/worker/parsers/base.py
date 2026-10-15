"""Parsed-document model shared by all parsers (files, web pages, business info)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ElementKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"  # Markdown, kept whole


@dataclass(slots=True)
class Element:
    kind: ElementKind
    text: str
    page: int | None = None
    level: int = 1  # heading depth (1 = top level)
    url: str | None = None  # web pages: the page URL ("page" of a web citation)
    title: str | None = None  # web pages: the page title


@dataclass(slots=True)
class ParsedDocument:
    elements: list[Element]
    title: str | None = None
    pages: int | None = None
    language: str | None = None
    content_hash: str | None = None  # web sources: hash of the extracted text (re-crawl)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "pages": self.pages,
            "language": self.language,
            "content_hash": self.content_hash,
            "meta": self.meta,
            "elements": [
                {
                    "kind": e.kind.value,
                    "text": e.text,
                    "page": e.page,
                    "level": e.level,
                    "url": e.url,
                    "title": e.title,
                }
                for e in self.elements
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ParsedDocument:
        return cls(
            elements=[
                Element(
                    kind=ElementKind(e["kind"]),
                    text=e["text"],
                    page=e.get("page"),
                    level=e.get("level", 1),
                    url=e.get("url"),
                    title=e.get("title"),
                )
                for e in data["elements"]
            ],
            title=data.get("title"),
            pages=data.get("pages"),
            language=data.get("language"),
            content_hash=data.get("content_hash"),
            meta=data.get("meta") or {},
        )

    def plain_text(self, limit: int | None = None) -> str:
        out: list[str] = []
        size = 0
        for e in self.elements:
            out.append(e.text)
            size += len(e.text)
            if limit is not None and size >= limit:
                break
        text = "\n".join(out)
        return text[:limit] if limit is not None else text


class ParseError(Exception):
    """A document that cannot be parsed. Permanent: not retried."""
