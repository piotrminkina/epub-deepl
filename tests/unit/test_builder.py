"""Identity tests for the payload-plan refactor (`merge/builder.py`).

`build()` was split into `_build_plan` (data extraction) + `_render_single`
(rendering) so a future work package can pack `_PayloadSection`s across
multiple payload documents without touching extraction logic — see
docs/adr/0006 (auto-split). These tests pin the internal contract the split
must uphold: `build(epub)` stays byte-identical to the pre-refactor output,
the OPF metadata header shell is unconditional, the non-spine EPUB 3 nav
doc leads `sections` while an in-spine one stays inline (never duplicated),
`data-spine-idx` survives skipped manifest/xhtml entries, and `_body_open`'s
new `part` parameter is a no-op until a caller actually passes one.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest

from tests.fixtures.minimal import build_minimal_epub

# Golden sha256 of build() output for the bundled corpus books, captured
# against the pre-refactor implementation. Any change to these hashes means
# build() output changed for real-world EPUBs — update only after reviewing
# the diff (e.g. via `cmp` against the previous golden HTML).
_GOLDEN_SHA256 = {
    "alice-pg11.epub": "2caaed250e845f893c7729988254b170e357fde8ff112c8b174004e930354790",
    "alice-pg11-epub3.epub": "6c676a05bf0e01cb5f04a2c9b6ceb4eca010ae12ba779dfffca6a8b77a92b670",
}


@pytest.mark.unit
def test_build_equals_render_single_of_plan(synth_epub_bytes: bytes) -> None:
    """`build(epub)` is exactly `_render_single(_build_plan(epub))` — the
    composition the refactor introduced, not just an equivalent rewrite."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan, _render_single, build

    epub = read_epub_bytes(synth_epub_bytes)
    assert build(epub) == _render_single(_build_plan(epub))


@pytest.mark.unit
def test_build_equals_render_single_of_plan_epub3(synth_epub3_bytes: bytes) -> None:
    """Same composition contract holds for an EPUB 3 book (NCX + nav doc)."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan, _render_single, build

    epub = read_epub_bytes(synth_epub3_bytes)
    assert build(epub) == _render_single(_build_plan(epub))


@pytest.mark.unit
def test_metadata_header_shell_emitted_even_when_empty() -> None:
    """The <header data-source="opf-metadata"> shell is unconditional — only
    its interior h1/p/span content is conditional per dc:* field."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub_bytes = build_minimal_epub(titles=(), descriptions=(), subjects=())
    epub = read_epub_bytes(epub_bytes)
    plan = _build_plan(epub)

    assert '<header data-source="opf-metadata">\n</header>\n' in plan.preamble
    assert "data-dc=" not in plan.preamble


@pytest.mark.unit
def test_metadata_header_content_order_when_present() -> None:
    """title(s), then description(s), then subject(s) — inside the shell."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub_bytes = build_minimal_epub(
        titles=("Main Title", "Alt Title"),
        descriptions=("A description.",),
        subjects=("fiction",),
    )
    epub = read_epub_bytes(epub_bytes)
    preamble = _build_plan(epub).preamble

    title_pos = preamble.index('data-dc="title"')
    alt_title_pos = preamble.index('data-dc-index="1"')
    desc_pos = preamble.index('data-dc="description"')
    subj_pos = preamble.index('data-dc="subject"')
    assert title_pos < alt_title_pos < desc_pos < subj_pos


@pytest.mark.unit
def test_preamble_omits_ncx_block_when_no_ncx() -> None:
    """`<nav data-source="ncx">` is only emitted when `epub.ncx` is present."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub_bytes = build_minimal_epub(epub_version="3.0", include_ncx=False)
    epub = read_epub_bytes(epub_bytes)
    assert epub.ncx is None

    preamble = _build_plan(epub).preamble
    assert 'data-source="ncx"' not in preamble
    assert 'data-source="opf-metadata"' in preamble


@pytest.mark.unit
def test_body_open_none_part_has_no_markers() -> None:
    """`_body_open(..., part=None)` reproduces the historical unmarked <body>."""
    from epub_deepl.merge.builder import _body_open

    opening = _body_open("en", "Title", "A description.", True, part=None)

    assert opening.endswith("<body>\n")
    assert "data-part" not in opening
    assert "data-parts-total" not in opening


@pytest.mark.unit
def test_body_open_with_part_stamps_markers() -> None:
    """`part=(index, total)` is reserved for the multi-part split (WP2): when
    given, it stamps data-part/data-parts-total onto <body>."""
    from epub_deepl.merge.builder import _body_open

    opening = _body_open("en", "Title", "", False, part=(1, 2))

    assert '<body data-part="1" data-parts-total="2">\n' in opening
    assert opening.endswith('<body data-part="1" data-parts-total="2">\n')


@pytest.mark.unit
def test_body_open_omits_description_meta_when_absent() -> None:
    """`has_description=False` must suppress the <meta name="description">
    tag entirely, not just leave its content empty."""
    from epub_deepl.merge.builder import _body_open

    opening = _body_open("en", "Title", "unused", False, part=None)
    assert "description" not in opening


@pytest.mark.unit
def test_plan_envelope_open_matches_body_open_with_part_none() -> None:
    """`_build_plan` always derives `envelope_open` via `_body_open(..., part=None)`
    today — no caller yet passes a real part."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _body_open, _build_plan

    epub_bytes = build_minimal_epub(titles=("T",), descriptions=("D",))
    epub = read_epub_bytes(epub_bytes)
    plan = _build_plan(epub)

    expected = _body_open(
        epub.metadata.language or "und",
        epub.metadata.titles[0],
        epub.metadata.descriptions[0],
        True,
        part=None,
    )
    assert plan.envelope_open == expected


@pytest.mark.unit
def test_plan_envelope_close_is_unmarked_closing_tags() -> None:
    """`envelope_close` is the plain, unmarked closing sequence."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub = read_epub_bytes(build_minimal_epub())
    assert _build_plan(epub).envelope_close == "</body>\n</html>\n"


@pytest.mark.unit
def test_sections_spine_order_matches_spine_when_no_nav_doc(synth_epub_bytes: bytes) -> None:
    """EPUB 2 (no nav doc): sections follow spine order exactly."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub = read_epub_bytes(synth_epub_bytes)
    hrefs = [s.href for s in _build_plan(epub).sections]
    assert hrefs == ["ch01.xhtml", "ch02.xhtml", "ch03.xhtml"]


@pytest.mark.unit
def test_non_spine_nav_doc_leads_sections() -> None:
    """A non-spine EPUB 3 nav doc is the first entry in `sections`, ahead of
    every spine chapter — never duplicated into the spine loop."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub_bytes = build_minimal_epub(epub_version="3.0", nav_in_spine=False)
    epub = read_epub_bytes(epub_bytes)
    assert epub.nav_doc is not None and not epub.nav_doc.in_spine

    sections = _build_plan(epub).sections
    hrefs = [s.href for s in sections]
    assert hrefs == ["nav.xhtml", "ch01.xhtml", "ch02.xhtml", "ch03.xhtml"]
    assert sum('data-nav-doc="true"' in s.html for s in sections) == 1
    assert "data-spine-idx" not in sections[0].html


@pytest.mark.unit
def test_in_spine_nav_doc_stays_inline_not_duplicated() -> None:
    """An in-spine EPUB 3 nav doc is annotated in place (same as any other
    spine chapter) and is not additionally prepended as its own section."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _build_plan

    epub_bytes = build_minimal_epub(epub_version="3.0", nav_in_spine=True)
    epub = read_epub_bytes(epub_bytes)
    assert epub.nav_doc is not None and epub.nav_doc.in_spine

    sections = _build_plan(epub).sections
    hrefs = [s.href for s in sections]
    assert hrefs == ["ch01.xhtml", "ch02.xhtml", "ch03.xhtml", "nav.xhtml"]
    assert sum('data-nav-doc="true"' in s.html for s in sections) == 1
    expected_attrs = 'data-source-href="nav.xhtml" data-spine-idx="3" data-nav-doc="true"'
    assert expected_attrs in sections[-1].html


@pytest.mark.unit
def test_spine_idx_survives_skipped_manifest_and_xhtml_gaps() -> None:
    """`data-spine-idx` must reflect the position in the FULL spine list
    (`enumerate(epub.spine.items)`), not a counter over emitted sections —
    a spine ref with no matching manifest item, or a manifest item with no
    matching XHTML file, must not shift the idx of later entries."""
    from epub_deepl.epub.model import (
        Epub,
        ManifestItem,
        OpfMetadata,
        Spine,
        SpineRef,
        XhtmlFile,
    )
    from epub_deepl.merge.builder import _build_sections

    metadata = OpfMetadata(
        titles=["T"],
        descriptions=[],
        subjects=[],
        language="en",
        creators=[],
        publishers=[],
        dates=[],
        identifiers=[],
        rights=[],
        extra_raw_xml=b"",
    )
    manifest = {
        "a": ManifestItem(item_id="a", href="a.xhtml", media_type="application/xhtml+xml"),
        # "b" has no manifest entry at all — spine_ref idref="b" resolves to
        # None and is skipped.
        "c": ManifestItem(item_id="c", href="c.xhtml", media_type="application/xhtml+xml"),
        # "d" resolves to a manifest item, but its XHTML file is missing from
        # epub.xhtmls — also skipped.
        "d": ManifestItem(item_id="d", href="d.xhtml", media_type="application/xhtml+xml"),
    }
    spine = Spine(
        items=[
            SpineRef(idref="a"),
            SpineRef(idref="b"),
            SpineRef(idref="c"),
            SpineRef(idref="d"),
        ],
        toc_idref=None,
    )
    epub = Epub(
        opf_path="OEBPS/content.opf",
        opf_dir="OEBPS",
        manifest=manifest,
        spine=spine,
        metadata=metadata,
        ncx=None,
        xhtmls={
            "a.xhtml": XhtmlFile(href="a.xhtml", raw_bytes=b"", body_html="<p>A</p>"),
            "c.xhtml": XhtmlFile(href="c.xhtml", raw_bytes=b"", body_html="<p>C</p>"),
        },
        other_files={},
        opf_raw_xml=b"",
        container_xml_bytes=b"",
    )

    sections = _build_sections(epub)

    assert [s.href for s in sections] == ["a.xhtml", "c.xhtml"]
    assert 'data-spine-idx="0"' in sections[0].html  # "a" is spine position 0
    assert 'data-spine-idx="2"' in sections[1].html  # "b" (position 1) skipped


@pytest.mark.corpus
def test_corpus_build_output_is_byte_stable(corpus_epub: pathlib.Path) -> None:
    """Regression gate: `build()` output for the bundled real-world corpus
    books must not change unless the change is deliberate. Guards the WP1
    refactor (and any future edit to merge/builder.py) against silently
    altering the DeepL payload for real EPUBs — the synthetic fixtures above
    exercise specific branches, but real books exercise all of them at once.
    """
    from epub_deepl.epub.reader import read_epub
    from epub_deepl.merge.builder import build

    epub = read_epub(str(corpus_epub))
    payload = build(epub)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    expected = _GOLDEN_SHA256.get(corpus_epub.name)
    if expected is None:
        pytest.skip(
            f"No golden sha256 recorded for {corpus_epub.name} "
            f"(actual sha256={digest}); add it to _GOLDEN_SHA256 once reviewed."
        )
    assert digest == expected, (
        f"{corpus_epub.name}: build() output changed "
        f"(sha256 {digest} != golden {expected}). "
        "If intentional, update _GOLDEN_SHA256 after reviewing the diff."
    )
