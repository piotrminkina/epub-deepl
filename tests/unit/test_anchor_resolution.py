"""Unit tests for anchor resolution algorithm (C-3 / test-plan §6.3)."""

from __future__ import annotations

import pytest

from epub_deepl_prepare.epub.model import Epub, NavPoint
from epub_deepl_prepare.epub.ncx import normalize_whitespace, xpath_literal


def _make_epub_with_xhtmls(
    xhtml_map: dict[str, str],  # href -> body HTML
    opf_dir: str = "OEBPS",
) -> Epub:
    """Build a minimal Epub model with given XHTML content."""
    from epub_deepl_prepare.epub.model import (
        Epub,
        ManifestItem,
        NavPoint,
        Ncx,
        OpfMetadata,
        Spine,
        SpineRef,
        XhtmlFile,
    )

    _XHTML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head><body>{body}</body></html>"""

    xhtmls = {}
    manifest = {}
    spine_items = []
    for i, (href, body) in enumerate(xhtml_map.items()):
        raw = _XHTML_TEMPLATE.format(body=body).encode("utf-8")
        xhtmls[href] = XhtmlFile(href=href, raw_bytes=raw, body_html=body)
        manifest[f"item{i}"] = ManifestItem(
            item_id=f"item{i}", href=href, media_type="application/xhtml+xml"
        )
        spine_items.append(SpineRef(idref=f"item{i}"))

    return Epub(
        opf_path=f"{opf_dir}/content.opf",
        opf_dir=opf_dir,
        manifest=manifest,
        spine=Spine(items=spine_items, toc_idref="ncx"),
        metadata=OpfMetadata(
            titles=["T"],
            descriptions=[],
            subjects=[],
            language="en",
            creators=[],
            publishers=[],
            dates=[],
            identifiers=[],
            rights=[],
            extra_raw_xml=b"<metadata/>",
        ),
        ncx=Ncx(doc_title="T", nav_map=[], raw_xml=b"<ncx/>", ncx_href_in_zip=f"{opf_dir}/toc.ncx"),
        xhtmls=xhtmls,
        other_files={},
        opf_raw_xml=b"<package/>",
        container_xml_bytes=b"<container/>",
    )


@pytest.mark.unit
def test_resolve_label_with_fragment() -> None:
    """Anchor resolution finds element by id when src has fragment."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": '<h1 id="ch1-heading">Chapter One Title</h1><p>Content</p>',
        }
    )
    nav_point = NavPoint(
        nav_id="np1", play_order=1, label="Old Label", src="ch01.xhtml#ch1-heading"
    )
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={"np1": "Flat Fallback"},
    )
    assert label == "Chapter One Title"


@pytest.mark.unit
def test_resolve_label_with_fragment_resolves_to_correct_id() -> None:
    """Anchor resolution picks the element with the matching id, not any heading."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": (
                '<h1 id="wrong">Wrong Heading</h1><h2 id="correct">Correct Section</h2>'
            ),
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="Old", src="ch01.xhtml#correct")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    assert label == "Correct Section"


@pytest.mark.unit
def test_resolve_label_with_fragment_returns_normalized_whitespace() -> None:
    """Label is whitespace-normalised (SM-3)."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": '<h1 id="h1">  Chapter   One  </h1>',
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="Old", src="ch01.xhtml#h1")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    assert label == "Chapter One"


@pytest.mark.unit
def test_resolve_label_without_fragment_uses_first_heading() -> None:
    """When src has no fragment, first heading is used."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": "<h1>First Heading</h1><p>Para</p>",
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="Old", src="ch01.xhtml")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={"np1": "Flat"},
    )
    assert label == "First Heading"


@pytest.mark.unit
def test_resolve_label_h2_used_when_no_h1() -> None:
    """Falls through to h2 if no h1 exists."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": '<h2 id="sec">Section Title</h2><p>Para</p>',
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="Old", src="ch01.xhtml")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    assert label == "Section Title"


@pytest.mark.unit
def test_resolve_label_h3_used_when_no_h1_h2() -> None:
    """Falls through to h3 if no h1 or h2 exists."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": "<h3>Subsection</h3><p>Para</p>",
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="Old", src="ch01.xhtml")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    assert label == "Subsection"


@pytest.mark.unit
def test_resolve_label_no_heading_falls_back_to_flat_label() -> None:
    """When no heading exists, flat_labels fallback is used."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": "<p>Just a paragraph, no heading.</p>",
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="OrigLabel", src="ch01.xhtml")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={"np1": "Translated Label"},
    )
    assert label == "Translated Label"


@pytest.mark.unit
def test_resolve_label_missing_fragment_no_heading_falls_back_to_flat_label() -> None:
    """Fragment not found + no heading → flat_label fallback."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": "<p>Content without the expected anchor.</p>",
        }
    )
    nav_point = NavPoint(nav_id="np1", play_order=1, label="Orig", src="ch01.xhtml#missing-id")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={"np1": "Fallback"},
    )
    assert label == "Fallback"


@pytest.mark.unit
def test_resolve_label_id_collision_across_files_scoped_per_file() -> None:
    """Same id in two files resolves to the correct file's element (R-4 / C-3)."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": '<h1 id="intro">Chapter 1 Intro</h1>',
            "ch02.xhtml": '<h1 id="intro">Chapter 2 Intro</h1>',
        }
    )

    nav1 = NavPoint(nav_id="np1", play_order=1, label="Old1", src="ch01.xhtml#intro")
    nav2 = NavPoint(nav_id="np2", play_order=2, label="Old2", src="ch02.xhtml#intro")

    label1 = resolve_label(
        nav_point=nav1,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    label2 = resolve_label(
        nav_point=nav2,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    assert label1 == "Chapter 1 Intro"
    assert label2 == "Chapter 2 Intro"
    assert label1 != label2  # Scoped correctly — R-4 prevented


@pytest.mark.unit
def test_resolve_label_ncx_in_subdirectory() -> None:
    """C-3: NCX src is resolved relative to NCX directory, not OPF directory."""
    from epub_deepl_prepare.epub.ncx import resolve_label

    # Structure: OPF at OEBPS/content.opf, NCX at OEBPS/toc.ncx, XHTML at OEBPS/Text/ch01.xhtml
    epub = _make_epub_with_xhtmls({"Text/ch01.xhtml": '<h1 id="h1">Correct Title</h1>'})

    nav_point = NavPoint(nav_id="np1", play_order=1, label="Old", src="Text/ch01.xhtml#h1")
    label = resolve_label(
        nav_point=nav_point,
        ncx_href_in_zip="OEBPS/toc.ncx",
        opf_dir="OEBPS",
        epub=epub,
        flat_labels={},
    )
    assert label == "Correct Title"


@pytest.mark.unit
def test_xpath_literal_simple_string() -> None:
    """Simple strings are wrapped in single quotes."""
    assert xpath_literal("hello") == "'hello'"


@pytest.mark.unit
def test_xpath_literal_string_with_single_quote() -> None:
    """Strings with single quotes use double quotes."""
    assert xpath_literal("it's here") == '"it\'s here"'


@pytest.mark.unit
def test_xpath_literal_string_with_both_quotes() -> None:
    """Strings with both quote types use concat()."""
    result = xpath_literal('it\'s a "test"')
    assert result.startswith("concat(")
    # Verify it's valid XPath by checking structure
    assert "'" in result and '"' in result


@pytest.mark.unit
def test_normalize_whitespace() -> None:
    """normalize_whitespace collapses runs and strips ends."""
    assert normalize_whitespace("  hello   world  ") == "hello world"
    assert normalize_whitespace("a\n\tb  c") == "a b c"
    assert normalize_whitespace("") == ""
