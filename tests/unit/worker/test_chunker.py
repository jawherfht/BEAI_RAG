"""Spec section 13: no mid-sentence cuts, page numbers kept, tables whole."""

import itertools

import pytest

from beai_rag_core.embedding.tokenizer import WhitespaceTokenCounter
from worker.chunking.chunker import Chunker
from worker.chunking.sentences import split_sentences
from worker.parsers.base import Element, ElementKind, ParsedDocument

TOK = WhitespaceTokenCounter()
H, P, T = ElementKind.HEADING, ElementKind.PARAGRAPH, ElementKind.TABLE


def sentences(n: int, words: int = 8, prefix: str = "s") -> str:
    return " ".join(
        " ".join(f"{prefix}{i}w{j}" for j in range(words - 1)) + f" end{i}." for i in range(n)
    )


def doc(*elements: Element) -> ParsedDocument:
    return ParsedDocument(elements=list(elements), pages=3)


def test_small_paragraphs_packed_with_section_and_pages() -> None:
    d = doc(
        Element(H, "Returns policy", page=1, level=1),
        Element(H, "Section 4 – Returns", page=2, level=2),
        Element(P, "30 days, unworn, with receipt.", page=2),
        Element(P, "Refunds go to the original card.", page=2),
    )
    chunks = Chunker(TOK, chunk_size=200, chunk_overlap=20).chunk(d)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.section == "Returns policy > Section 4 – Returns"
    assert (c.page, c.page_end) == (2, 2)
    assert "30 days, unworn, with receipt." in c.text


def test_sections_are_not_mixed() -> None:
    d = doc(
        Element(H, "A", page=1),
        Element(P, "Alpha text.", page=1),
        Element(H, "B", page=1),
        Element(P, "Beta text.", page=1),
    )
    chunks = Chunker(TOK, 200, 0).chunk(d)
    assert [(c.section, c.text) for c in chunks] == [("A", "Alpha text."), ("B", "Beta text.")]


def test_heading_levels_reset_path() -> None:
    d = doc(
        Element(H, "Top", level=1),
        Element(H, "Sub", level=2),
        Element(P, "x."),
        Element(H, "Other top", level=1),
        Element(P, "y."),
    )
    assert [c.section for c in Chunker(TOK, 200, 0).chunk(d)] == ["Top > Sub", "Other top"]


@pytest.mark.parametrize(("size", "overlap"), [(40, 0), (40, 10), (60, 12), (100, 25)])
def test_never_cuts_mid_sentence(size: int, overlap: int) -> None:
    text = sentences(40)
    all_sentences = set(split_sentences(text))
    chunks = Chunker(TOK, size, overlap).chunk(doc(Element(P, text, page=1)))
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= size
        for piece in c.text.split("\n\n"):
            assert piece in all_sentences, f"cut sentence: {piece!r}"


def test_overlap_repeats_trailing_sentences() -> None:
    chunks = Chunker(TOK, 40, 10).chunk(doc(Element(P, sentences(20), page=1)))
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.text.split("\n\n")[0] == prev.text.split("\n\n")[-1]


def test_no_overlap_when_zero() -> None:
    chunks = Chunker(TOK, 40, 0).chunk(doc(Element(P, sentences(20), page=1)))
    joined = [s for c in chunks for s in c.text.split("\n\n")]
    assert len(joined) == len(set(joined)) == 20


def test_page_span_recorded() -> None:
    d = doc(
        Element(P, "First page sentence.", page=1),
        Element(P, "Second page sentence.", page=2),
    )
    (c,) = Chunker(TOK, 200, 0).chunk(d)
    assert (c.page, c.page_end) == (1, 2)


def _table(rows: int) -> str:
    lines = ["| code | description |", "|---|---|"]
    lines += [f"| R{i} | item number {i} with some words |" for i in range(rows)]
    return "\n".join(lines)


def test_table_kept_whole_up_to_twice_chunk_size() -> None:
    table = _table(7)  # 76 tokens, chunk size 40 -> still whole (<= 2x)
    assert 40 < TOK.count(table) <= 80
    chunks = Chunker(TOK, 40, 10).chunk(
        doc(Element(P, "Before.", page=1), Element(T, table, page=1), Element(P, "After.", page=1))
    )
    assert any(c.text == table for c in chunks)


def test_huge_table_split_by_rows_with_header() -> None:
    table = _table(60)
    chunks = Chunker(TOK, 50, 10).chunk(doc(Element(T, table, page=3)))
    assert len(chunks) > 1
    rows_seen = []
    for c in chunks:
        lines = c.text.splitlines()
        assert lines[:2] == ["| code | description |", "|---|---|"]
        rows_seen += lines[2:]
        assert c.page == 3
    assert rows_seen == table.splitlines()[2:]


def test_runon_sentence_is_the_only_token_cut() -> None:
    runon = " ".join(f"w{i}" for i in range(300))  # no punctuation at all
    chunks = Chunker(TOK, 50, 0).chunk(doc(Element(P, runon, page=1)))
    assert all(c.token_count <= 100 for c in chunks)
    assert " ".join(c.text for c in chunks) == runon


def test_web_pages_never_share_a_chunk() -> None:
    d = doc(
        Element(H, "Page A", level=1, url="https://x.test/a", title="Page A"),
        Element(P, "About A.", url="https://x.test/a", title="Page A"),
        Element(H, "Page B", level=1, url="https://x.test/b", title="Page B"),
        Element(P, "About B.", url="https://x.test/b", title="Page B"),
    )
    chunks = Chunker(TOK, 200, 0).chunk(d)
    assert [(c.url, c.section, c.title) for c in chunks] == [
        ("https://x.test/a", "Page A", "Page A"),
        ("https://x.test/b", "Page B", "Page B"),
    ]


def test_chunk_indexes_are_sequential() -> None:
    chunks = Chunker(TOK, 30, 5).chunk(doc(Element(P, sentences(30), page=1)))
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_invalid_settings_rejected() -> None:
    with pytest.raises(ValueError):
        Chunker(TOK, 100, 100)
