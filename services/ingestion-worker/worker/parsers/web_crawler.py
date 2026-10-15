"""Polite website crawler (spec sections 5 and 9).

- robots.txt respected (user-agent ``BEAI-KB-Crawler``); same host only; breadth-first up to
  ``crawl_depth`` (max 3) and ``max_pages`` (max 500); at most 1 request/second per host.
- SSRF protection: every request (including each redirect hop) must resolve only to public
  IP addresses; redirects are followed manually and only within the allowed host.
- Main content extracted with Trafilatura (Markdown, tables kept). For web pages the
  citation "page" is the URL; the page title is the first heading of each page.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from worker.parsers.base import Element, ElementKind, ParsedDocument, ParseError

USER_AGENT = "BEAI-KB-Crawler/1.0 (+https://beai.studio/crawler)"
ROBOTS_AGENT = "BEAI-KB-Crawler"
MAX_DEPTH = 3
MAX_PAGES = 500
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|ico|css|js|zip|gz|mp4|mp3|avi|mov|docx?|xlsx?|pptx?)$", re.I
)

Resolver = Callable[[str], Awaitable[list[str]]]


class BlockedURLError(ParseError):
    """URL not allowed (private address, other host, bad scheme)."""


async def _default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class Fetched:
    url: str
    status: int
    content_type: str
    text: str


@dataclass
class CrawledPage:
    url: str
    title: str | None
    markdown: str


class WebCrawler:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        min_interval_s: float = 1.0,
        timeout_s: float = 15.0,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout_s, headers={"User-Agent": USER_AGENT}, follow_redirects=False
        )
        self._resolver = resolver or _default_resolver
        self._min_interval = min_interval_s
        self._last_request: dict[str, float] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def crawl(
        self, start_url: str, crawl_depth: int = 1, max_pages: int = 50
    ) -> ParsedDocument:
        depth = max(0, min(crawl_depth, MAX_DEPTH))
        limit = max(1, min(max_pages, MAX_PAGES))
        start = _normalise(start_url)
        host = urlsplit(start).hostname or ""
        await self._check_url(start, host)
        robots = await self._robots(start)

        pages: list[CrawledPage] = []
        seen = {start}
        frontier = [start]
        for level in range(depth + 1):
            next_frontier: list[str] = []
            for url in frontier:
                if len(pages) >= limit:
                    break
                if not robots.can_fetch(ROBOTS_AGENT, url):
                    continue
                fetched = await self._fetch_html(url, host)
                if fetched is None:
                    continue
                final_url, html = fetched
                page = extract_page(final_url, html)
                if page is not None:
                    pages.append(page)
                if level < depth:
                    for link in extract_links(final_url, html, host):
                        if link not in seen:
                            seen.add(link)
                            next_frontier.append(link)
            frontier = next_frontier
            if not frontier or len(pages) >= limit:
                break
        if not pages:
            raise ParseError("No readable pages found at this URL")
        return pages_to_document(pages)

    async def _check_url(self, url: str, allowed_host: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise BlockedURLError("Only http and https URLs can be crawled")
        if not parts.hostname or parts.hostname != allowed_host:
            raise BlockedURLError("URL leaves the allowed domain")
        try:
            addresses = await self._resolver(parts.hostname)
        except OSError as exc:
            raise ParseError(f"Could not resolve {parts.hostname}") from exc
        if not addresses or not all(is_public_ip(a) for a in addresses):
            raise BlockedURLError("URL resolves to a private or reserved address")

    async def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        now = time.monotonic()
        if last is not None and now - last < self._min_interval:
            await asyncio.sleep(self._min_interval - (now - last))
        self._last_request[host] = time.monotonic()

    async def _get(self, url: str, allowed_host: str) -> Fetched | None:
        for _ in range(MAX_REDIRECTS + 1):
            await self._check_url(url, allowed_host)
            await self._throttle(allowed_host)
            async with self._client.stream("GET", url) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    url = _normalise(urljoin(url, location))
                    if urlsplit(url).hostname != allowed_host:
                        return None  # redirects only within the allowed domain
                    continue
                body = bytearray()
                async for part in resp.aiter_bytes():
                    body.extend(part)
                    if len(body) > MAX_PAGE_BYTES:
                        return None
                encoding = resp.charset_encoding or "utf-8"
                return Fetched(
                    url=url,
                    status=resp.status_code,
                    content_type=resp.headers.get("content-type", ""),
                    text=bytes(body).decode(encoding, errors="replace"),
                )
        return None

    async def _fetch_html(self, url: str, host: str) -> tuple[str, str] | None:
        try:
            got = await self._get(url, host)
        except httpx.HTTPError:
            return None
        if got is None or got.status != 200 or "html" not in got.content_type:
            return None
        return got.url, got.text

    async def _robots(self, start: str) -> RobotFileParser:
        parts = urlsplit(start)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            got = await self._get(robots_url, parts.hostname or "")
        except httpx.HTTPError:
            got = None
        if got is None or got.status >= 400:
            parser.parse([])  # no robots.txt -> everything allowed
        else:
            parser.parse(got.text.splitlines())
        return parser


def _normalise(url: str) -> str:
    url, _ = urldefrag(url.strip())
    parts = urlsplit(url)
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.lower()}://{host}{port}{path}{query}"


def extract_links(base_url: str, html: str, allowed_host: str) -> list[str]:
    import lxml.html

    try:
        tree = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return []
    links: list[str] = []
    for href in tree.xpath("//a/@href"):
        url = _normalise(urljoin(base_url, str(href)))
        parts = urlsplit(url)
        if (
            parts.scheme in {"http", "https"}
            and parts.hostname == allowed_host
            and not SKIP_EXTENSIONS.search(parts.path)
        ):
            links.append(url)
    return list(dict.fromkeys(links))


def extract_page(url: str, html: str) -> CrawledPage | None:
    import trafilatura

    markdown = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_images=False,
        favor_precision=True,
    )
    if not markdown or not markdown.strip():
        return None
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = meta.title if meta is not None and meta.title else None
    return CrawledPage(url=url, title=title, markdown=markdown)


def markdown_to_elements(markdown: str, url: str, title: str | None) -> list[Element]:
    elements = [Element(ElementKind.HEADING, title or url, level=1, url=url, title=title or url)]
    table: list[str] = []

    def flush_table() -> None:
        if table:
            elements.append(
                Element(ElementKind.TABLE, "\n".join(table), url=url, title=title or url)
            )
            table.clear()

    for block in re.split(r"\n\s*\n", markdown):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.lstrip().startswith("|") for ln in lines):
            table.extend(lines)
            continue
        flush_table()
        heading = re.match(r"^(#{1,6})\s+(.*)$", lines[0])
        if heading and len(lines) == 1:
            level = len(heading.group(1)) + 1  # page title is level 1
            elements.append(
                Element(ElementKind.HEADING, heading.group(2), level=level, url=url, title=title)
            )
        else:
            elements.append(
                Element(ElementKind.PARAGRAPH, "\n".join(lines), url=url, title=title or url)
            )
    flush_table()
    return elements


def pages_to_document(pages: list[CrawledPage]) -> ParsedDocument:
    elements: list[Element] = []
    digest = hashlib.sha256()
    for page in sorted(pages, key=lambda p: p.url):
        digest.update(page.url.encode() + b"\0" + page.markdown.encode() + b"\0")
    for page in pages:
        elements.extend(markdown_to_elements(page.markdown, page.url, page.title))
    return ParsedDocument(
        elements=elements,
        title=pages[0].title,
        pages=len(pages),
        content_hash=digest.hexdigest(),
        meta={"urls": [p.url for p in pages]},
    )
