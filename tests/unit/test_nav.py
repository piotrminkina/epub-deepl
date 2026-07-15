"""Unit tests for EPUB 3 nav document parsing and serialisation (test-plan §6.x)."""

from __future__ import annotations

import logging

import pytest

from epub_deepl.epub.model import Epub

_FLAT_NAV = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<h1>Contents</h1>
<ol>
<li><a href="ch01.xhtml#h1">Chapter 1</a></li>
<li><a href="ch02.xhtml#h2">Chapter 2</a></li>
</ol>
</nav>
</body>
</html>"""

_NESTED_NAV = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<h1>Contents</h1>
<ol>
<li><a href="part1.xhtml">Part One</a>
<ol>
<li><a href="ch01.xhtml#h1">Chapter 1</a>
<ol>
<li><a href="ch01.xhtml#sec1">Section 1</a></li>
</ol>
</li>
</ol>
</li>
</ol>
</nav>
</body>
</html>"""

_NAV_ROLE_FALLBACK = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Nav</title></head>
<body>
<nav role="doc-toc">
<ol>
<li><a href="ch01.xhtml">Chapter 1</a></li>
</ol>
</nav>
</body>
</html>"""

_NAV_OL_HEURISTIC_FALLBACK = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Nav</title></head>
<body>
<nav>
<ol>
<li><a href="ch01.xhtml">Chapter 1</a></li>
</ol>
</nav>
</body>
</html>"""

_NAV_NO_TOC = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Nav</title></head>
<body>
<p>No nav elements here at all.</p>
</body>
</html>"""

_NAV_WITH_LANDMARKS_AND_PAGELIST = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<h1>Contents</h1>
<ol>
<li><a href="ch01.xhtml">Chapter 1</a></li>
</ol>
</nav>
<nav epub:type="landmarks" hidden="">
<ol>
<li><a epub:type="bodymatter" href="ch01.xhtml">Start of Content</a></li>
</ol>
</nav>
<nav epub:type="page-list" hidden="">
<ol>
<li><a href="ch01.xhtml#page_1">1</a></li>
</ol>
</nav>
</body>
</html>"""

_NAV_PAGELIST_ROLE_FALLBACK = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<ol><li><a href="ch01.xhtml">Chapter 1</a></li></ol>
</nav>
<nav role="doc-pagelist" hidden="">
<ol><li><a href="ch01.xhtml#page_1">1</a></li></ol>
</nav>
</body>
</html>"""

_NAV_PAGELIST_AUTHOR_TRANSLATE_YES = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<ol><li><a href="ch01.xhtml">Chapter 1</a></li></ol>
</nav>
<nav epub:type="page-list" translate="yes">
<ol><li><a href="ch01.xhtml#page_1">1</a></li></ol>
</nav>
</body>
</html>"""

# A bare divider <li> (no <a>/<span> child) between two link <li>s — legal in
# an EPUB 3 toc, but contributes no NavDocEntry (see _parse_li / _li_yields_entry).
_NAV_WITH_DIVIDER_LI = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<h1>Contents</h1>
<ol>
<li><a href="ch01.xhtml#h1">Chapter 1</a></li>
<li>Part Two</li>
<li><a href="ch02.xhtml#h2">Chapter 2</a></li>
</ol>
</nav>
</body>
</html>"""

# A divider <li> inside a nested <ol>, alongside one genuine link <li>.
_NAV_NESTED_WITH_DIVIDER = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Nav</title></head>
<body>
<nav epub:type="toc" id="toc">
<h1>Contents</h1>
<ol>
<li><a href="part1.xhtml">Part One</a>
<ol>
<li>Subtitle</li>
<li><a href="ch01.xhtml#h1">Chapter 1</a></li>
</ol>
</li>
</ol>
</nav>
</body>
</html>"""


@pytest.mark.unit
def test_parse_flat_toc() -> None:
    """parse_nav_doc parses a flat toc <ol> into two NavDocEntry."""
    from epub_deepl.epub.nav import parse_nav_doc

    nav_doc = parse_nav_doc(_FLAT_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    assert nav_doc.has_toc_nav is True
    assert nav_doc.href == "nav.xhtml"
    assert nav_doc.href_in_zip == "OEBPS/nav.xhtml"
    assert nav_doc.in_spine is False
    assert len(nav_doc.toc_entries) == 2
    assert nav_doc.toc_entries[0].entry_id == "navdoc-toc-1"
    assert nav_doc.toc_entries[0].label == "Chapter 1"
    assert nav_doc.toc_entries[0].href == "ch01.xhtml#h1"
    assert nav_doc.toc_entries[1].entry_id == "navdoc-toc-2"
    assert nav_doc.toc_entries[1].label == "Chapter 2"


@pytest.mark.unit
def test_parse_nested_toc_preorder_ids() -> None:
    """Nested <ol> entries get pre-order ids: parent id lower than any child."""
    from epub_deepl.epub.nav import parse_nav_doc

    nav_doc = parse_nav_doc(_NESTED_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    assert len(nav_doc.toc_entries) == 1
    part = nav_doc.toc_entries[0]
    assert part.entry_id == "navdoc-toc-1"
    assert part.label == "Part One"
    assert len(part.children) == 1
    ch = part.children[0]
    assert ch.entry_id == "navdoc-toc-2"
    assert ch.label == "Chapter 1"
    assert len(ch.children) == 1
    sec = ch.children[0]
    assert sec.entry_id == "navdoc-toc-3"
    assert sec.label == "Section 1"


@pytest.mark.unit
def test_parse_no_toc_nav_found() -> None:
    """When no <nav> element exists at all, has_toc_nav is False and entries empty."""
    from epub_deepl.epub.nav import parse_nav_doc

    nav_doc = parse_nav_doc(_NAV_NO_TOC, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    assert nav_doc.has_toc_nav is False
    assert nav_doc.toc_entries == []


@pytest.mark.unit
def test_parse_toc_via_role_fallback() -> None:
    """A <nav role="doc-toc"> is found even without an epub:type=toc token."""
    from epub_deepl.epub.nav import parse_nav_doc

    nav_doc = parse_nav_doc(_NAV_ROLE_FALLBACK, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    assert nav_doc.has_toc_nav is True
    assert len(nav_doc.toc_entries) == 1
    assert nav_doc.toc_entries[0].label == "Chapter 1"


@pytest.mark.unit
def test_parse_toc_via_ol_heuristic_fallback() -> None:
    """A bare <nav><ol>...</ol></nav> is found as a last resort."""
    from epub_deepl.epub.nav import parse_nav_doc

    nav_doc = parse_nav_doc(
        _NAV_OL_HEURISTIC_FALLBACK, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False
    )
    assert nav_doc.has_toc_nav is True
    assert len(nav_doc.toc_entries) == 1


@pytest.mark.unit
def test_parse_in_spine_flag_passthrough() -> None:
    """in_spine is stored on the returned NavDoc unchanged."""
    from epub_deepl.epub.nav import parse_nav_doc

    nav_doc = parse_nav_doc(_FLAT_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=True)
    assert nav_doc.in_spine is True


@pytest.mark.unit
def test_parse_malformed_raises_missing_nav_doc() -> None:
    """Unparseable bytes raise MissingNavDoc, not a bare lxml exception."""
    from epub_deepl.epub.nav import parse_nav_doc
    from epub_deepl.errors import MissingNavDoc

    with pytest.raises(MissingNavDoc):
        parse_nav_doc(b"", "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)


@pytest.mark.unit
def test_extract_nav_body_html_contains_toc_content() -> None:
    """extract_nav_body_html returns the <body> inner HTML, not the whole document."""
    from epub_deepl.epub.nav import extract_nav_body_html

    body_html = extract_nav_body_html(_FLAT_NAV)
    assert "Chapter 1" in body_html
    assert "Chapter 2" in body_html
    assert "<html" not in body_html
    assert "<head" not in body_html


@pytest.mark.unit
def test_extract_nav_body_html_marks_page_list_no_translate() -> None:
    """Only the page-list <nav> gets translate="no"; toc and landmarks do not."""
    from epub_deepl.epub.nav import extract_nav_body_html

    body_html = extract_nav_body_html(_NAV_WITH_LANDMARKS_AND_PAGELIST)
    assert 'epub:type="page-list" hidden="" translate="no"' in body_html
    assert 'epub:type="toc" id="toc"' in body_html
    assert 'translate="no"' not in body_html.split('epub:type="toc"')[1].split("</nav>")[0]


@pytest.mark.unit
def test_extract_nav_body_html_marks_page_list_via_role_fallback() -> None:
    """role="doc-pagelist" is honoured even without an epub:type token."""
    from epub_deepl.epub.nav import extract_nav_body_html

    body_html = extract_nav_body_html(_NAV_PAGELIST_ROLE_FALLBACK)
    assert 'role="doc-pagelist" hidden="" translate="no"' in body_html


@pytest.mark.unit
def test_extract_nav_body_html_no_body_returns_empty_string() -> None:
    """A document with no <body> element returns an empty string."""
    from epub_deepl.epub.nav import extract_nav_body_html

    assert extract_nav_body_html(b"<html><head></head></html>") == ""


@pytest.mark.unit
def test_rebuild_replaces_body_and_applies_labels() -> None:
    """rebuild_nav_doc_bytes installs the translated body then overwrites toc texts."""
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_FLAT_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    translated_body = (
        '<nav epub:type="toc" id="toc"><h1>Table des matieres</h1><ol>'
        '<li><a href="ch01.xhtml#h1">Chapitre 1</a></li>'
        '<li><a href="ch02.xhtml#h2">Chapitre 2</a></li>'
        "</ol></nav>"
    )
    new_labels = {"navdoc-toc-1": "New Label One", "navdoc-toc-2": "New Label Two"}

    new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, new_labels)

    assert b"New Label One" in new_bytes
    assert b"New Label Two" in new_bytes
    assert b"Chapitre 1" not in new_bytes
    assert b"Chapitre 2" not in new_bytes
    # Head + doctype-equivalent structure preserved from the original raw_bytes.
    assert b"<title>Nav</title>" in new_bytes


@pytest.mark.unit
def test_rebuild_preserves_nested_structure_and_labels() -> None:
    """Nested <ol> entries are matched and overwritten at every depth."""
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_NESTED_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    translated_body = (
        '<nav epub:type="toc" id="toc"><ol>'
        '<li><a href="part1.xhtml">Teil Eins</a><ol>'
        '<li><a href="ch01.xhtml#h1">Kapitel Eins</a><ol>'
        '<li><a href="ch01.xhtml#sec1">Abschnitt Eins</a></li>'
        "</ol></li></ol></li></ol></nav>"
    )
    new_labels = {
        "navdoc-toc-1": "Part I",
        "navdoc-toc-2": "Chapter I",
        "navdoc-toc-3": "Section I",
    }

    new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, new_labels)

    assert b"Part I<" in new_bytes
    assert b"Chapter I<" in new_bytes
    assert b"Section I<" in new_bytes


@pytest.mark.unit
def test_rebuild_structure_guard_falls_back_on_shape_mismatch(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A translated toc with fewer <li> than the original triggers the structure guard.

    The translated body is kept as-is (labels are NOT overwritten) and a
    WARNING is logged — better than a partial or misapplied label overwrite.
    """
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_FLAT_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    # DeepL merged/dropped a list item: only one <li> instead of two.
    translated_body = (
        '<nav epub:type="toc" id="toc"><ol>'
        '<li><a href="ch01.xhtml#h1">Chapitre Unique</a></li>'
        "</ol></nav>"
    )
    new_labels = {"navdoc-toc-1": "Should Not Apply", "navdoc-toc-2": "Should Not Apply Either"}

    monkeypatch.setattr(logging.getLogger("epub_deepl"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="epub_deepl.epub.nav"):
        new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, new_labels)

    assert b"Chapitre Unique" in new_bytes
    assert b"Should Not Apply" not in new_bytes
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.unit
def test_rebuild_divider_li_does_not_trip_structure_guard(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare divider <li> between two link <li>s must not count against the
    structure guard: the translated shape is identical once dividers are
    excluded from both sides, so labels ARE applied and no WARNING is logged.
    """
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_NAV_WITH_DIVIDER_LI, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    translated_body = (
        '<nav epub:type="toc" id="toc"><ol>'
        '<li><a href="ch01.xhtml#h1">Chapitre Un</a></li>'
        "<li>Deuxieme Partie</li>"
        '<li><a href="ch02.xhtml#h2">Chapitre Deux</a></li>'
        "</ol></nav>"
    )
    new_labels = {"navdoc-toc-1": "First Chapter", "navdoc-toc-2": "Second Chapter"}

    monkeypatch.setattr(logging.getLogger("epub_deepl"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="epub_deepl.epub.nav"):
        new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, new_labels)

    assert b"First Chapter" in new_bytes
    assert b"Second Chapter" in new_bytes
    # The divider itself carries no id, so it passes through untouched.
    assert b"Deuxieme Partie" in new_bytes
    assert not any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.unit
def test_rebuild_divider_li_in_nested_ol_does_not_trip_structure_guard(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A divider <li> nested inside a child <ol> is likewise excluded from the
    nested-level structure guard, so the genuine nested entry still gets its
    label applied with no WARNING.
    """
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(
        _NAV_NESTED_WITH_DIVIDER, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False
    )
    translated_body = (
        '<nav epub:type="toc" id="toc"><ol>'
        '<li><a href="part1.xhtml">Teil Eins</a><ol>'
        "<li>Untertitel</li>"
        '<li><a href="ch01.xhtml#h1">Kapitel Eins</a></li>'
        "</ol></li></ol></nav>"
    )
    new_labels = {"navdoc-toc-1": "Part I", "navdoc-toc-2": "Chapter I"}

    monkeypatch.setattr(logging.getLogger("epub_deepl"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="epub_deepl.epub.nav"):
        new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, new_labels)

    assert b"Part I<" in new_bytes
    assert b"Chapter I<" in new_bytes
    assert b"Untertitel" in new_bytes
    assert not any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.unit
def test_rebuild_genuine_mismatch_still_trips_guard_despite_divider(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Divider-filtering must not paper over a real shape mismatch: merging
    two chapters into one link <li> (while the divider is still present)
    still trips the guard, falls back untouched, and logs a WARNING.
    """
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_NAV_WITH_DIVIDER_LI, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    # DeepL merged the two chapters into one <li>; the divider survives.
    translated_body = (
        '<nav epub:type="toc" id="toc"><ol>'
        '<li><a href="ch01.xhtml#h1">Merged Chapter</a></li>'
        "<li>Part Two</li>"
        "</ol></nav>"
    )
    new_labels = {"navdoc-toc-1": "Should Not Apply", "navdoc-toc-2": "Should Not Apply Either"}

    monkeypatch.setattr(logging.getLogger("epub_deepl"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="epub_deepl.epub.nav"):
        new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, new_labels)

    assert b"Merged Chapter" in new_bytes
    assert b"Should Not Apply" not in new_bytes
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.unit
def test_rebuild_no_toc_nav_only_replaces_body() -> None:
    """When has_toc_nav is False, new_labels are ignored and body is just replaced."""
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_NAV_NO_TOC, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    assert nav_doc.has_toc_nav is False

    new_bytes = rebuild_nav_doc_bytes(nav_doc, "<p>Translated paragraph.</p>", {"x": "y"})
    assert b"Translated paragraph." in new_bytes


@pytest.mark.unit
def test_rebuild_empty_new_labels_skips_tree_walk() -> None:
    """An empty new_labels dict short-circuits the structure-guard walk entirely."""
    from epub_deepl.epub.nav import parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(_FLAT_NAV, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)
    # Deliberately shape-mismatched translated body: would trip the guard if
    # new_labels were non-empty, but the early-return means it never gets there.
    translated_body = (
        '<nav epub:type="toc" id="toc"><ol><li><a href="x">Only One</a></li></ol></nav>'
    )

    new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, {})
    assert b"Only One" in new_bytes


@pytest.mark.unit
def test_rebuild_strips_injected_page_list_translate_marker() -> None:
    """The translate="no" marker extract_nav_body_html injects for DeepL is
    payload-only and must not survive into the restored nav document.
    """
    from epub_deepl.epub.nav import extract_nav_body_html, parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(
        _NAV_WITH_LANDMARKS_AND_PAGELIST, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False
    )
    # Simulate an unmodified round-trip through DeepL: translate="no" content
    # passes through untouched, so the "translated" body still carries the
    # injected marker exactly as extract_nav_body_html produced it.
    translated_body = extract_nav_body_html(_NAV_WITH_LANDMARKS_AND_PAGELIST)
    assert 'translate="no"' in translated_body  # sanity: marker really is there

    new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, {})

    assert b'translate="no"' not in new_bytes


@pytest.mark.unit
def test_rebuild_preserves_author_supplied_page_list_translate_attr() -> None:
    """An author-supplied translate attribute on the original page-list nav
    survives rebuild unchanged, even though extract_nav_body_html always
    overwrites it to "no" for the DeepL payload.
    """
    from epub_deepl.epub.nav import extract_nav_body_html, parse_nav_doc, rebuild_nav_doc_bytes

    nav_doc = parse_nav_doc(
        _NAV_PAGELIST_AUTHOR_TRANSLATE_YES, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False
    )
    translated_body = extract_nav_body_html(_NAV_PAGELIST_AUTHOR_TRANSLATE_YES)
    assert 'translate="no"' in translated_body  # extraction always forces "no"

    new_bytes = rebuild_nav_doc_bytes(nav_doc, translated_body, {})

    assert b'translate="yes"' in new_bytes
    assert b'translate="no"' not in new_bytes


def _make_epub_with_xhtmls(
    xhtml_map: dict[str, str],  # href -> body HTML
    opf_dir: str = "OEBPS",
) -> Epub:
    """Build a minimal EPUB 3 Epub model with given XHTML content.

    Mirrors `test_anchor_resolution.py`'s helper of the same name.
    """
    from epub_deepl.epub.model import ManifestItem, OpfMetadata, Spine, SpineRef, XhtmlFile

    xhtml_template = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head>'
        "<body>{body}</body></html>"
    )

    xhtmls = {}
    manifest = {}
    spine_items = []
    for i, (href, body) in enumerate(xhtml_map.items()):
        raw = xhtml_template.format(body=body).encode("utf-8")
        xhtmls[href] = XhtmlFile(href=href, raw_bytes=raw, body_html=body)
        manifest[f"item{i}"] = ManifestItem(
            item_id=f"item{i}", href=href, media_type="application/xhtml+xml"
        )
        spine_items.append(SpineRef(idref=f"item{i}"))

    return Epub(
        opf_path=f"{opf_dir}/content.opf",
        opf_dir=opf_dir,
        manifest=manifest,
        spine=Spine(items=spine_items, toc_idref=None),
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
        ncx=None,
        xhtmls=xhtmls,
        other_files={},
        opf_raw_xml=b"<package/>",
        container_xml_bytes=b"<container/>",
        epub_version="3.0",
        major_version=3,
    )


@pytest.mark.unit
def test_resolve_nav_labels_flat_entries_resolve_from_headings() -> None:
    """Each toc entry's label is resolved from its target heading, not its parsed link text."""
    from epub_deepl.epub.model import NavDoc, NavDocEntry
    from epub_deepl.epub.nav import resolve_nav_labels

    epub = _make_epub_with_xhtmls(
        {
            "ch01.xhtml": '<h1 id="ch1-heading">Chapter One Title</h1>',
            "ch02.xhtml": '<h1 id="ch2-heading">Chapter Two Title</h1>',
        }
    )
    nav_doc = NavDoc(
        href="nav.xhtml",
        href_in_zip="OEBPS/nav.xhtml",
        raw_bytes=b"<html/>",
        has_toc_nav=True,
        toc_entries=[
            NavDocEntry(entry_id="navdoc-toc-1", label="Old One", href="ch01.xhtml#ch1-heading"),
            NavDocEntry(entry_id="navdoc-toc-2", label="Old Two", href="ch02.xhtml#ch2-heading"),
        ],
    )

    labels = resolve_nav_labels(nav_doc, epub)

    assert labels == {
        "navdoc-toc-1": "Chapter One Title",
        "navdoc-toc-2": "Chapter Two Title",
    }


@pytest.mark.unit
def test_resolve_nav_labels_without_fragment_uses_first_heading() -> None:
    """An href with no fragment resolves to the target's first heading."""
    from epub_deepl.epub.model import NavDoc, NavDocEntry
    from epub_deepl.epub.nav import resolve_nav_labels

    epub = _make_epub_with_xhtmls({"ch01.xhtml": "<h1>First Heading</h1><p>Para</p>"})
    nav_doc = NavDoc(
        href="nav.xhtml",
        href_in_zip="OEBPS/nav.xhtml",
        raw_bytes=b"<html/>",
        has_toc_nav=True,
        toc_entries=[NavDocEntry(entry_id="navdoc-toc-1", label="Old", href="ch01.xhtml")],
    )

    labels = resolve_nav_labels(nav_doc, epub)

    assert labels == {"navdoc-toc-1": "First Heading"}


@pytest.mark.unit
def test_resolve_nav_labels_nested_entries_all_resolved() -> None:
    """Nested (child) toc entries are resolved too, not just top-level ones."""
    from epub_deepl.epub.model import NavDoc, NavDocEntry
    from epub_deepl.epub.nav import resolve_nav_labels

    epub = _make_epub_with_xhtmls(
        {
            "part1.xhtml": '<h1 id="part1-heading">Part One</h1>',
            "ch01.xhtml": '<h1 id="ch1-heading">Chapter One</h1>',
        }
    )
    nav_doc = NavDoc(
        href="nav.xhtml",
        href_in_zip="OEBPS/nav.xhtml",
        raw_bytes=b"<html/>",
        has_toc_nav=True,
        toc_entries=[
            NavDocEntry(
                entry_id="navdoc-toc-1",
                label="Old Part",
                href="part1.xhtml#part1-heading",
                children=[
                    NavDocEntry(
                        entry_id="navdoc-toc-2",
                        label="Old Chapter",
                        href="ch01.xhtml#ch1-heading",
                    ),
                ],
            ),
        ],
    )

    labels = resolve_nav_labels(nav_doc, epub)

    assert labels == {
        "navdoc-toc-1": "Part One",
        "navdoc-toc-2": "Chapter One",
    }


@pytest.mark.unit
def test_resolve_nav_labels_skips_entries_without_href() -> None:
    """An entry with an empty href (e.g. a heading-only <span>) is omitted entirely."""
    from epub_deepl.epub.model import NavDoc, NavDocEntry
    from epub_deepl.epub.nav import resolve_nav_labels

    epub = _make_epub_with_xhtmls({"ch01.xhtml": '<h1 id="ch1-heading">Chapter One</h1>'})
    nav_doc = NavDoc(
        href="nav.xhtml",
        href_in_zip="OEBPS/nav.xhtml",
        raw_bytes=b"<html/>",
        has_toc_nav=True,
        toc_entries=[
            NavDocEntry(entry_id="navdoc-toc-1", label="Heading-only span", href=""),
            NavDocEntry(entry_id="navdoc-toc-2", label="Old", href="ch01.xhtml#ch1-heading"),
        ],
    )

    labels = resolve_nav_labels(nav_doc, epub)

    assert labels == {"navdoc-toc-2": "Chapter One"}


@pytest.mark.unit
def test_resolve_nav_labels_unresolvable_entry_omitted() -> None:
    """A fragment missing from the target with no heading fallback omits the entry."""
    from epub_deepl.epub.model import NavDoc, NavDocEntry
    from epub_deepl.epub.nav import resolve_nav_labels

    epub = _make_epub_with_xhtmls({"ch01.xhtml": "<p>No headings, no matching id here.</p>"})
    nav_doc = NavDoc(
        href="nav.xhtml",
        href_in_zip="OEBPS/nav.xhtml",
        raw_bytes=b"<html/>",
        has_toc_nav=True,
        toc_entries=[
            NavDocEntry(entry_id="navdoc-toc-1", label="Old", href="ch01.xhtml#missing"),
        ],
    )

    labels = resolve_nav_labels(nav_doc, epub)

    assert labels == {}


@pytest.mark.unit
def test_resolve_nav_labels_hostile_href_omitted_not_fatal(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root-escaping or external href is omitted with a WARNING, never fatal.

    Mirrors the per-navPoint fallback in restore.applier._resolve_all_labels:
    one hostile entry must not abort the whole restore.
    """
    from epub_deepl.epub.model import NavDoc, NavDocEntry
    from epub_deepl.epub.nav import resolve_nav_labels

    epub = _make_epub_with_xhtmls({"ch01.xhtml": '<h1 id="ch1-heading">Chapter One</h1>'})
    nav_doc = NavDoc(
        href="nav.xhtml",
        href_in_zip="OEBPS/nav.xhtml",
        raw_bytes=b"<html/>",
        has_toc_nav=True,
        toc_entries=[
            NavDocEntry(entry_id="navdoc-toc-1", label="Escape", href="../../evil.xhtml"),
            NavDocEntry(entry_id="navdoc-toc-2", label="External", href="https://example.com/x"),
            NavDocEntry(entry_id="navdoc-toc-3", label="Old", href="ch01.xhtml#ch1-heading"),
        ],
    )

    monkeypatch.setattr(logging.getLogger("epub_deepl"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="epub_deepl.epub.nav"):
        labels = resolve_nav_labels(nav_doc, epub)

    assert labels == {"navdoc-toc-3": "Chapter One"}
    assert sum(record.levelno == logging.WARNING for record in caplog.records) >= 1
