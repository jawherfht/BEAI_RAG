"""Business info form -> a one-page document named "Business info" (spec section 4.1)."""

from __future__ import annotations

from typing import Any

from worker.parsers.base import Element, ElementKind, ParsedDocument

BUSINESS_INFO_FILE_NAME = "Business info"

_FIELDS = (
    ("company_name", "Company name"),
    ("hours", "Opening hours"),
    ("address", "Address"),
    ("contact", "Contact"),
)


def render_business_info(form: dict[str, Any]) -> ParsedDocument:
    elements = [Element(ElementKind.HEADING, BUSINESS_INFO_FILE_NAME, page=1, level=1)]
    for key, label in _FIELDS:
        value = str(form.get(key) or "").strip()
        if value:
            elements.append(Element(ElementKind.PARAGRAPH, f"{label}: {value}", page=1))
    faq = [f for f in form.get("faq") or [] if f.get("question") and f.get("answer")]
    if faq:
        elements.append(Element(ElementKind.HEADING, "FAQ", page=1, level=2))
        for item in faq:
            elements.append(
                Element(
                    ElementKind.PARAGRAPH,
                    f"Q: {item['question'].strip()}\nA: {item['answer'].strip()}",
                    page=1,
                )
            )
    return ParsedDocument(elements=elements, title=BUSINESS_INFO_FILE_NAME, pages=1)
