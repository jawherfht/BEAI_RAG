"""Crawler politeness and SSRF protection, with a mocked HTTP layer and resolver."""

import httpx
import pytest

from worker.parsers.base import ElementKind, ParseError
from worker.parsers.web_crawler import BlockedURLError, WebCrawler, is_public_ip

PUBLIC = "93.184.216.34"


def page(title: str, body: str, links: list[str] = ()) -> str:  # type: ignore[assignment]
    anchors = "".join(f'<a href="{href}">link</a> ' for href in links)
    paragraphs = "".join(
        f"<p>{body} sentence number {i} with enough words to keep.</p>" for i in range(5)
    )
    return (
        f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>"
        f"{paragraphs}</article>{anchors}</body></html>"
    )


def make_crawler(
    routes: dict[str, httpx.Response], dns: dict[str, list[str]] | None = None
) -> tuple[WebCrawler, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        assert request.headers["user-agent"].startswith("BEAI-KB-Crawler")
        return routes.get(url, httpx.Response(404))

    async def resolver(host: str) -> list[str]:
        return (dns or {}).get(host, [PUBLIC])

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"User-Agent": "BEAI-KB-Crawler/1.0"}
    )
    return WebCrawler(client=client, resolver=resolver, min_interval_s=0), requested


def html(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "text/html; charset=utf-8"})


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("93.184.216.34", True),
        ("10.0.0.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("192.168.1.1", False),
        ("::1", False),
        ("::ffff:10.0.0.1", False),
        ("2606:4700::1111", True),
    ],
)
def test_is_public_ip(ip: str, public: bool) -> None:
    assert is_public_ip(ip) is public


async def test_crawls_same_host_within_depth_and_respects_robots() -> None:
    routes = {
        "https://shop.test/robots.txt": httpx.Response(
            200, text="User-agent: *\nDisallow: /private\n"
        ),
        "https://shop.test/": html(
            page("Home", "Welcome", ["/returns", "/private/x", "https://other.test/", "/img.png"])
        ),
        "https://shop.test/returns": html(
            page("Returns", "Thirty days unworn with receipt", ["/deeper"])
        ),
        "https://shop.test/deeper": html(page("Deeper", "Too deep")),
    }
    crawler, requested = make_crawler(routes)
    doc = await crawler.crawl("https://shop.test/", crawl_depth=1, max_pages=50)
    assert doc.meta["urls"] == ["https://shop.test/", "https://shop.test/returns"]
    assert "https://shop.test/private/x" not in requested
    assert not any("other.test" in u for u in requested)
    assert "https://shop.test/deeper" not in requested  # depth 1
    assert doc.pages == 2 and doc.content_hash
    headings = [e for e in doc.elements if e.kind is ElementKind.HEADING and e.level == 1]
    assert [(h.text, h.url) for h in headings] == [
        ("Home", "https://shop.test/"),
        ("Returns", "https://shop.test/returns"),
    ]


async def test_max_pages() -> None:
    links = [f"/p{i}" for i in range(10)]
    routes = {"https://shop.test/": html(page("Home", "Welcome", links))}
    routes |= {f"https://shop.test/p{i}": html(page(f"P{i}", f"Body {i}")) for i in range(10)}
    crawler, _ = make_crawler(routes)
    doc = await crawler.crawl("https://shop.test/", crawl_depth=2, max_pages=3)
    assert doc.pages == 3


async def test_private_address_blocked() -> None:
    crawler, requested = make_crawler({}, dns={"intranet.test": ["10.1.2.3"]})
    with pytest.raises(BlockedURLError):
        await crawler.crawl("http://intranet.test/")
    assert requested == []


async def test_redirect_to_other_host_not_followed() -> None:
    routes = {"https://shop.test/": httpx.Response(302, headers={"location": "https://evil.test/"})}
    crawler, requested = make_crawler(routes)
    with pytest.raises(ParseError):
        await crawler.crawl("https://shop.test/")
    assert not any("evil.test" in u for u in requested)


async def test_redirect_within_host_followed_but_rechecked() -> None:
    routes = {
        "https://shop.test/": httpx.Response(301, headers={"location": "/home"}),
        "https://shop.test/home": html(page("Home", "Hello there")),
    }
    crawler, _ = make_crawler(routes)
    doc = await crawler.crawl("https://shop.test/", crawl_depth=0)
    assert doc.meta["urls"] == ["https://shop.test/home"]


async def test_non_http_scheme_blocked() -> None:
    crawler, _ = make_crawler({})
    with pytest.raises(BlockedURLError):
        await crawler.crawl("file:///etc/passwd")
