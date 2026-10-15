"""File parsing with Docling (PDF, DOCX, PPTX, HTML, MD) plus a plain-text reader (TXT).

Docling gives structured items with page provenance: headings, paragraphs, list items and
tables (exported whole, as Markdown). PDFs use Docling's layout + table models and OCR for
scanned pages; DOCX/PPTX/HTML/MD use model-free backends. Model weights download from
Hugging Face on first use unless ``DOCLING_ARTIFACTS_PATH`` points to a pre-fetched copy.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from worker.parsers.base import Element, ElementKind, ParsedDocument, ParseError

SKIPPED_LABELS = frozenset({"page_header", "page_footer", "picture", "chart", "marker"})

MIME_TO_FORMAT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/html": "html",
    "text/markdown": "md",
    "text/plain": "txt",
}


class DoclingParser:
    def __init__(self, *, ocr: bool = True, artifacts_path: str | None = None) -> None:
        self._ocr = ocr
        self._artifacts_path = artifacts_path
        self._converter: Any = None
        self._lock = threading.Lock()

    def _get_converter(self) -> Any:
        with self._lock:
            if self._converter is None:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import DocumentConverter, PdfFormatOption

                options = PdfPipelineOptions(
                    do_ocr=self._ocr,
                    do_table_structure=True,
                    artifacts_path=self._artifacts_path,
                    enable_remote_services=False,
                )
                self._converter = DocumentConverter(
                    allowed_formats=[
                        InputFormat.PDF,
                        InputFormat.DOCX,
                        InputFormat.PPTX,
                        InputFormat.HTML,
                        InputFormat.MD,
                    ],
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
                )
            return self._converter

    def parse(self, path: Path, mime_type: str, *, max_pages: int | None = None) -> ParsedDocument:
        """Blocking; call from a worker thread."""
        fmt = MIME_TO_FORMAT.get(mime_type)
        if fmt is None:
            raise ParseError(f"Unsupported file type: {mime_type}")
        if fmt == "txt":
            return parse_plain_text(path.read_text(encoding="utf-8", errors="replace"))
        try:
            result = self._get_converter().convert(
                path, raises_on_error=True, max_num_pages=max_pages or 2**31
            )
        except Exception as exc:  # docling raises many exception types
            if is_infrastructure_error(exc):
                # e.g. model weights cannot be downloaded: not the document's fault -> retry.
                raise ModelUnavailableError(f"Parser models unavailable: {exc}") from exc
            raise ParseError(f"Could not read this document ({type(exc).__name__})") from exc
        return docling_to_parsed(result.document)


class ModelUnavailableError(RuntimeError):
    """Parser models could not be loaded (download/network). Transient: retried."""


_INFRA_MODULES = ("httpx", "httpcore", "requests", "urllib3", "huggingface_hub", "aiohttp")


def is_infrastructure_error(exc: BaseException) -> bool:
    """Network / model-hub failures anywhere in the exception chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        module = type(current).__module__ or ""
        if isinstance(current, ConnectionError | TimeoutError) or module.startswith(_INFRA_MODULES):
            return True
        current = current.__cause__ or current.__context__
    return False


def docling_to_parsed(doc: Any) -> ParsedDocument:
    from docling_core.types.doc.items.table.table import TableItem
    from docling_core.types.doc.items.text import ListItem, SectionHeaderItem, TextItem

    elements: list[Element] = []
    title: str | None = None
    for item, _depth in doc.iterate_items():
        label = str(getattr(item, "label", ""))
        label = label.rsplit(".", 1)[-1].lower()
        if label in SKIPPED_LABELS:
            continue
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        if isinstance(item, TableItem):
            md = item.export_to_markdown(doc=doc).strip()
            if md:
                elements.append(Element(ElementKind.TABLE, md, page))
        elif isinstance(item, SectionHeaderItem):
            elements.append(Element(ElementKind.HEADING, item.text, page, level=item.level + 1))
        elif isinstance(item, ListItem):
            marker = item.marker or "-"
            elements.append(Element(ElementKind.LIST_ITEM, f"{marker} {item.text}", page))
        elif isinstance(item, TextItem) and item.text.strip():
            if label == "title":
                title = title or item.text.strip()
                elements.append(Element(ElementKind.HEADING, item.text, page, level=1))
            else:
                elements.append(Element(ElementKind.PARAGRAPH, item.text, page))
    pages = len(doc.pages) if getattr(doc, "pages", None) else None
    return ParsedDocument(elements=_merge_list_items(elements), title=title, pages=pages)


def _merge_list_items(elements: list[Element]) -> list[Element]:
    """Consecutive list items on the same page become one paragraph-like block."""
    merged: list[Element] = []
    for el in elements:
        prev = merged[-1] if merged else None
        if (
            el.kind is ElementKind.LIST_ITEM
            and prev is not None
            and prev.kind is ElementKind.LIST_ITEM
            and prev.page == el.page
        ):
            prev.text = f"{prev.text}\n{el.text}"
        else:
            merged.append(el)
    return merged


def parse_plain_text(text: str) -> ParsedDocument:
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return ParsedDocument(
        elements=[Element(ElementKind.PARAGRAPH, p, page=1) for p in paragraphs if p], pages=1
    )
