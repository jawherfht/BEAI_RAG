"""Upload safety (spec sections 5 and 9): type sniffing, size limit, zip-bomb and macro checks.

The declared content type is never trusted: the type comes from the file's bytes, and the
file extension must agree with it. Nothing is executed; DOCX/PPTX with VBA projects are
refused outright.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from fastapi import UploadFile

from app.domain.errors import PayloadTooLargeError, UnsupportedMediaTypeError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TXT = "text/plain"
MD = "text/markdown"
HTML = "text/html"

EXTENSIONS: dict[str, str] = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".pptx": PPTX,
    ".txt": TXT,
    ".md": MD,
    ".markdown": MD,
    ".html": HTML,
    ".htm": HTML,
}
ACCEPTED = "PDF, DOCX, PPTX, TXT, MD, HTML"
TEXT_TYPES = frozenset({TXT, MD, HTML})


@dataclass(frozen=True, slots=True)
class CheckedFile:
    file_name: str
    mime_type: str
    data: bytes
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class UploadLimits:
    max_bytes: int
    max_zip_uncompressed_bytes: int
    max_zip_entries: int


async def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    buf = bytearray()
    while chunk := await upload.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise PayloadTooLargeError(
                f"{upload.filename or 'File'} is larger than {max_bytes // (1024 * 1024)} MB",
                details={"file_name": upload.filename, "max_bytes": max_bytes},
            )
    return bytes(buf)


def check_file(file_name: str, data: bytes, limits: UploadLimits) -> CheckedFile:
    if len(data) > limits.max_bytes:
        raise PayloadTooLargeError(
            f"{file_name} is larger than {limits.max_bytes // (1024 * 1024)} MB",
            details={"file_name": file_name, "max_bytes": limits.max_bytes},
        )
    if not data:
        raise UnsupportedMediaTypeError(f"{file_name} is empty", details={"file_name": file_name})
    ext = PurePath(file_name).suffix.lower()
    expected = EXTENSIONS.get(ext)
    if expected is None:
        raise _unsupported(file_name)
    sniffed = sniff(data, limits)
    # Text formats only need to be valid text; binary formats must match byte-for-byte.
    if sniffed != expected and not (expected in TEXT_TYPES and sniffed in TEXT_TYPES):
        raise UnsupportedMediaTypeError(
            f"{file_name}: the content does not match the {ext} extension",
            details={"file_name": file_name, "detected": sniffed},
        )
    return CheckedFile(file_name, expected, data, hashlib.sha256(data).hexdigest())


def sniff(data: bytes, limits: UploadLimits) -> str | None:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK\x03\x04"):
        return _sniff_ooxml(data, limits)
    text = _decode_text(data)
    if text is None:
        return None
    head = text[:1024].lstrip().lower()
    if head.startswith(("<!doctype html", "<html")) or "<body" in head:
        return HTML
    return TXT


def _sniff_ooxml(data: bytes, limits: UploadLimits) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > limits.max_zip_entries:
                raise UnsupportedMediaTypeError("Document has too many parts (possible zip bomb)")
            total = sum(i.file_size for i in infos)
            if total > limits.max_zip_uncompressed_bytes:
                raise UnsupportedMediaTypeError("Document expands too much (possible zip bomb)")
            names = {i.filename for i in infos}
    except zipfile.BadZipFile:
        return None
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise UnsupportedMediaTypeError("Documents with macros are not accepted")
    if "[Content_Types].xml" not in names:
        return None
    if "word/document.xml" in names:
        return DOCX
    if "ppt/presentation.xml" in names:
        return PPTX
    return None


def _decode_text(data: bytes) -> str | None:
    """UTF-8 (optionally with BOM) or BOM-marked UTF-16; anything else is treated as binary."""
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def _unsupported(file_name: str) -> UnsupportedMediaTypeError:
    return UnsupportedMediaTypeError(
        f"{file_name}: unsupported file type. Accepted: {ACCEPTED}",
        details={"file_name": file_name, "accepted": ACCEPTED},
    )
