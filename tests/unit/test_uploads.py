"""Upload safety: sniffing, extension agreement, size limit, zip bomb, macros."""

import io
import zipfile

import pytest

from app.domain.errors import PayloadTooLargeError, UnsupportedMediaTypeError
from app.uploads import DOCX, HTML, MD, PDF, PPTX, TXT, UploadLimits, check_file

LIMITS = UploadLimits(
    max_bytes=1024 * 1024, max_zip_uncompressed_bytes=5 * 1024 * 1024, max_zip_entries=50
)


def ooxml(kind: str, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml" if kind == "docx" else "ppt/presentation.xml", "<x/>")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "mime"),
    [
        ("returns-policy.pdf", b"%PDF-1.7\n...", PDF),
        ("doc.docx", ooxml("docx"), DOCX),
        ("deck.pptx", ooxml("pptx"), PPTX),
        ("notes.txt", "Plain text, accents é".encode(), TXT),
        ("readme.md", b"# Title\n\nBody", MD),
        ("page.html", b"<!DOCTYPE html><html><body>Hi</body></html>", HTML),
        ("fragment.htm", b"<p>only a fragment</p>", HTML),
        ("bom.txt", "﻿with bom".encode(), TXT),
        ("utf16.txt", "hello".encode("utf-16"), TXT),
    ],
)
def test_accepted(name: str, data: bytes, mime: str) -> None:
    checked = check_file(name, data, LIMITS)
    assert checked.mime_type == mime
    assert len(checked.sha256) == 64


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("image.png", b"\x89PNG\r\n\x1a\n"),
        ("fake.pdf", b"not a pdf at all"),
        ("fake.docx", b"%PDF-1.4 pretending"),
        ("binary.txt", b"\x00\x01\x02\xff" * 10),
        ("deck.docx", ooxml("pptx")),
        ("noext", b"text"),
        ("empty.txt", b""),
    ],
)
def test_rejected(name: str, data: bytes) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        check_file(name, data, LIMITS)


def test_too_large() -> None:
    with pytest.raises(PayloadTooLargeError):
        check_file("big.txt", b"a" * (LIMITS.max_bytes + 1), LIMITS)


def test_macros_refused() -> None:
    with pytest.raises(UnsupportedMediaTypeError, match="macros"):
        check_file("m.docx", ooxml("docx", {"word/vbaProject.bin": b"x"}), LIMITS)


def test_zip_bomb_refused() -> None:
    bomb = ooxml("docx", {"word/media/huge.bin": b"\0" * (6 * 1024 * 1024)})
    assert len(bomb) < LIMITS.max_bytes  # compresses tiny
    with pytest.raises(UnsupportedMediaTypeError, match="zip bomb"):
        check_file("bomb.docx", bomb, LIMITS)


def test_too_many_entries_refused() -> None:
    many = ooxml("docx", {f"word/p{i}.xml": b"x" for i in range(60)})
    with pytest.raises(UnsupportedMediaTypeError, match="zip bomb"):
        check_file("many.docx", many, LIMITS)
