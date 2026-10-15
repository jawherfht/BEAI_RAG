"""Generate eval/datasets/kb1_retail/returns-policy.pdf (spec section 12, sample KB #1).

Page 2, Section 4 says "30 days, unworn, with receipt". Pure Python: writes a small,
valid PDF with a real text layer (Helvetica / Helvetica-Bold, WinAnsiEncoding).
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent / "kb1_retail" / "returns-policy.pdf"

# (font, size, text); "H" = Helvetica-Bold heading, "P" = Helvetica body text.
PAGES: list[list[tuple[str, int, str]]] = [
    [
        ("H", 20, "Acme Retail – Returns and Shipping Policy"),
        ("P", 11, "Effective 1 January 2026. This policy applies to all purchases made in our"),
        ("P", 11, "stores and on acme-retail.example."),
        ("H", 14, "Section 1 – About this policy"),
        ("P", 11, "This document explains how orders are shipped, how returns work and how"),
        ("P", 11, "refunds are paid. Store staff will help you with any question."),
        ("H", 14, "Section 2 – Orders"),
        ("P", 11, "Orders placed before 2 pm on a business day are prepared the same day."),
        ("P", 11, "You receive an order confirmation by email with your order number."),
        ("H", 14, "Section 3 – Shipping"),
        ("P", 11, "Standard shipping takes 3 to 5 business days and costs 4.90 EUR."),
        ("P", 11, "Shipping is free for orders above 50 EUR. Express delivery takes 1 day."),
    ],
    [
        ("H", 14, "Section 4 – Returns"),
        ("P", 11, "Returns are accepted within 30 days, unworn, with receipt."),
        ("P", 11, "Items must be unworn and in their original packaging with all tags attached."),
        ("P", 11, "Please bring or include your receipt or order confirmation."),
        ("P", 11, "Final-sale items and gift cards cannot be returned."),
        ("H", 14, "Section 5 – Refunds"),
        ("P", 11, "Refunds are paid to the original payment method within 5 business days"),
        ("P", 11, "after we receive the returned item. Return shipping is free in the EU."),
        ("H", 14, "Section 6 – Exchanges"),
        ("P", 11, "You can exchange an item for another size or colour within 30 days."),
    ],
]


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(lines: list[tuple[str, int, str]]) -> bytes:
    out = [b"BT"]
    y = 790
    for font, size, text in lines:
        y -= size + (14 if font == "H" else 6)
        name = b"/F2" if font == "H" else b"/F1"
        out.append(name + b" %d Tf 1 0 0 1 56 %d Tm (" % (size, y) + _escape(text) + b") Tj")
    out.append(b"ET")
    return b"\n".join(out)


def build() -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # placeholder, filled below
    pages = add(b"")
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    page_ids = []
    for lines in PAGES:
        stream = _content(lines)
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>" % (pages, content, f1, f2)
            )
        )
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    objects[pages - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    pdf += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(pdf)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
