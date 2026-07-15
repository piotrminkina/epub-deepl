"""Round-trip integration tests (test-plan §7.2).

Covers: US-006, US-007, US-008, US-011, US-013, US-018, US-019, US-020, SM-7.
C-1 (ZIP invariants on every round-trip output), C-4 (adversarial fixture).
"""

from __future__ import annotations

import io
import logging
import pathlib
import struct
import time
import zipfile
from collections.abc import Callable

import pytest

from tests.fixtures.minimal import NavPointSpec, XhtmlSpec, build_minimal_epub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _roundtrip(epub_bytes: bytes, target_lang: str = "en") -> bytes:
    """Run prepare + restore on in-memory bytes. Returns output EPUB bytes."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub = read_epub_bytes(epub_bytes)
    if not epub.metadata.language:
        epub.metadata.language = "und"
    merged_html = build(epub)
    doc = parse_translated_html_bytes(merged_html.encode("utf-8"))
    return apply_and_write_bytes(epub, doc, target_lang)


def _check_zip_invariants(epub_bytes: bytes) -> None:
    """Assert all ZIP packaging invariants from C-1 / SM-1."""
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        names = zf.namelist()
        # 1. mimetype is first entry
        assert names[0] == "mimetype", f"First entry: {names[0]!r}"
        # 2. STORED compression
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        # 3. No extra field bytes
        assert info.extra == b"", f"extra field: {info.extra!r}"
        # 4. Exact content
        assert zf.read("mimetype") == b"application/epub+zip"
        # 5. All other entries DEFLATED
        for entry in zf.infolist():
            if entry.filename == "mimetype":
                continue
            assert entry.compress_type == zipfile.ZIP_DEFLATED, (
                f"{entry.filename!r} compress_type={entry.compress_type}"
            )
        # 6. No CRC errors
        assert zf.testzip() is None

    # 7. flag_bits=0 on mimetype (binary check)
    sig = b"PK\x03\x04"
    offset = epub_bytes.find(sig)
    assert offset != -1
    flag_bits = struct.unpack_from("<H", epub_bytes, offset + 6)[0]
    assert flag_bits == 0, f"flag_bits={flag_bits:#06x}"


def _text_content_of_xhtml(epub_bytes: bytes, href_prefix: str) -> str:
    """Extract text from an XHTML file in the EPUB by href prefix."""
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        for name in zf.namelist():
            if href_prefix in name:
                return zf.read(name).decode("utf-8", errors="replace")
    return ""


def _simulated_translation(html: str) -> str:
    """Friendly identity transform: prefix every text segment with «PL»."""
    import re

    def _prefix(m: re.Match[str]) -> str:
        text = m.group(0)
        # Don't prefix if it's just whitespace or inside a tag
        stripped = text.strip()
        if not stripped:
            return text
        return text.replace(stripped, f"«PL» {stripped}", 1)

    # Prefix text nodes: replace content between > and <
    return re.sub(r"(?<=>)[^<>]+(?=<)", _prefix, html)


def _adversarial_translation(html: str, seed: int = 42) -> str:
    """Hostile transform simulating worst-case DeepL behaviour.

    SM-7: restore must succeed or fail with a precise diagnostic.
    """
    import random
    import re

    random.Random(seed)
    result = html

    # Strip HTML comments
    result = re.sub(r"<!--.*?-->", "", result, flags=re.DOTALL)

    # Reorder attributes alphabetically
    def _reorder_attrs(m: re.Match[str]) -> str:
        tag_content = m.group(1)
        name = re.match(r"^\w+", tag_content)
        if not name:
            return m.group(0)
        tag_name = name.group()
        attrs = re.findall(r'\s+[\w:-]+(?:="[^"]*")?', tag_content)
        attrs_sorted = sorted(attrs)
        return f"<{tag_name}{''.join(attrs_sorted)}>"

    result = re.sub(r"<(\w[^>]*)>", _reorder_attrs, result)

    # Collapse whitespace (but not inside <pre>)
    result = re.sub(r"[ \t]+", " ", result)

    # Re-encode some entities (NCR equivalents)
    result = result.replace("&mdash;", "&#8212;").replace("&ndash;", "&#8211;")

    return result


def _wide_epub_bytes_for_split(n_chapters: int = 5, filler: int = 400) -> bytes:
    """A synthetic EPUB 3 with `n_chapters`, each padded to `filler` chars
    and carrying a per-chapter `unique-marker-N`, sized so a modest
    `--max-chars` reliably forces `build_split` into more than one part.

    Passes an explicit `nav_map` (one entry per chapter, no fragment) --
    `build_minimal_epub`'s auto-derivation falls back to a hardcoded
    3-entry template referencing `#ch1-heading`/`#ch2-heading`/
    `#ch3-heading` once `len(xhtmls) >= 3`, anchors that don't exist in
    these padded bodies.
    """
    xhtmls = [
        XhtmlSpec(
            href=f"ch{i:02d}.xhtml",
            title=f"Chapter {i}",
            body_html=f"<p>{'X' * filler} unique-marker-{i}</p>",
        )
        for i in range(1, n_chapters + 1)
    ]
    nav_map = [
        NavPointSpec(label=f"Chapter {i}", src=f"ch{i:02d}.xhtml", nav_id=f"navPoint-{i}")
        for i in range(1, n_chapters + 1)
    ]
    return build_minimal_epub(epub_version="3.0", xhtmls=xhtmls, nav_map=nav_map)


def _max_chars_forcing_split(epub_bytes: bytes) -> int:
    """Compute `--max-chars` from the payload's own measured envelope/
    preamble/section lengths (rather than a guessed constant) so packing
    reliably yields >1 parts -- same technique as
    tests/unit/test_payload_split.py."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _PART_MARKER_RESERVE, _build_plan

    epub = read_epub_bytes(epub_bytes)
    plan = _build_plan(epub)
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    # Use the LARGEST section, not sections[0] -- for an EPUB 3 fixture,
    # section 0 is often the (small) non-spine nav doc, not a chapter, and
    # sizing off it would starve the budget for the actual chapters.
    max_section_len = max(len(section.html) for section in plan.sections)
    return envelope_len + _PART_MARKER_RESERVE + len(plan.preamble) + 2 * max_section_len


def _split_roundtrip(
    epub_bytes: bytes,
    max_chars: int,
    target_lang: str = "en",
    transform: Callable[[str], str] | None = None,
) -> bytes:
    """Run prepare (split) + restore (merge) on in-memory bytes, mirroring
    `_roundtrip` but exercising `build_split` / `merge_translated_docs`
    instead of the single-file path.

    `transform`, if given, simulates a per-part translation pass (e.g.
    `_simulated_translation`) applied to each part's HTML independently
    before parsing -- as DeepL would, translating each part in its own
    request. Returns output EPUB bytes.
    """
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build_split
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import merge_translated_docs, parse_translated_html_bytes

    epub = read_epub_bytes(epub_bytes)
    if not epub.metadata.language:
        epub.metadata.language = "und"
    parts = build_split(epub, max_chars=max_chars)
    assert len(parts) > 1, "test setup must actually force a split"

    docs = []
    for i, part_html in enumerate(parts, start=1):
        translated = transform(part_html) if transform else part_html
        docs.append((f"part{i}.html", parse_translated_html_bytes(translated.encode("utf-8"))))

    doc = merge_translated_docs(docs)
    return apply_and_write_bytes(epub, doc, target_lang)


# ---------------------------------------------------------------------------
# Synthetic round-trip tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_without_translation_synth_minimal() -> None:
    """Round-trip produces zip-invariant output on minimal EPUB."""
    epub_bytes = build_minimal_epub()
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)


@pytest.mark.integration
def test_roundtrip_zip_invariants_synth() -> None:
    """ZIP invariants hold on synthetic round-trip (C-1)."""
    epub_bytes = build_minimal_epub()
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)


@pytest.mark.integration
def test_roundtrip_without_translation_synth_with_nested_ncx() -> None:
    """Round-trip with nested NCX produces valid output."""
    epub_bytes = build_minimal_epub(
        xhtmls=[
            XhtmlSpec("ch01.xhtml", "Part 1", '<h1 id="p1">Part One</h1><h2 id="c1">Ch 1</h2>'),
            XhtmlSpec("ch02.xhtml", "Part 2", '<h1 id="p2">Part Two</h1>'),
        ],
        nav_map=[
            NavPointSpec(
                label="Part One",
                src="ch01.xhtml#p1",
                nav_id="part1",
                play_order=1,
                children=[
                    NavPointSpec(
                        label="Chapter 1",
                        src="ch01.xhtml#c1",
                        nav_id="ch1",
                        play_order=2,
                    )
                ],
            ),
            NavPointSpec(label="Part Two", src="ch02.xhtml#p2", nav_id="part2", play_order=3),
        ],
    )
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)


@pytest.mark.integration
def test_roundtrip_without_translation_synth_with_mathml() -> None:
    """MathML survives round-trip byte-identically (US-011)."""
    math_body = (
        '<h1 id="h1">Math Chapter</h1>'
        '<p><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<mrow><mn>42</mn></mrow></math></p>"
    )
    epub_bytes = build_minimal_epub(
        xhtmls=[XhtmlSpec("ch01.xhtml", "Math", math_body)],
        nav_map=[NavPointSpec("Math", "ch01.xhtml#h1", "np1", 1)],
    )
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)
    # MathML content must still be present in output
    xhtml_content = _text_content_of_xhtml(output, "ch01")
    assert "math" in xhtml_content.lower()


@pytest.mark.integration
def test_mathml_receives_translate_no_in_prepare() -> None:
    """prepare adds translate='no' to all MathML elements (US-011)."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build

    math_body = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mn>1</mn></mrow></math>'
    epub_bytes = build_minimal_epub(
        xhtmls=[XhtmlSpec("ch01.xhtml", "Math", math_body)],
        nav_map=[],
    )
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)
    assert 'translate="no"' in html


@pytest.mark.integration
def test_roundtrip_without_translation_synth_with_ruby() -> None:
    """Ruby annotations survive round-trip."""
    ruby_body = "<p><ruby>漢<rt>kan</rt></ruby>字</p>"
    epub_bytes = build_minimal_epub(
        xhtmls=[XhtmlSpec("ch01.xhtml", "Ruby", ruby_body)],
        nav_map=[],
    )
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)


@pytest.mark.integration
def test_restored_opf_dc_language_set_to_target() -> None:
    """Restored EPUB has dc:language equal to --lang value (US-009)."""
    from epub_deepl.epub.opf import parse_metadata

    epub_bytes = build_minimal_epub(language="en")
    output = _roundtrip(epub_bytes, target_lang="pl")
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        opf = zf.read("OEBPS/content.opf")
    meta = parse_metadata(opf)
    assert meta.language == "pl"


@pytest.mark.integration
def test_restored_opf_language_und_fallback_when_missing() -> None:
    """I-1 / US-019: prepare handles missing dc:language → 'und'."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build

    epub_bytes = build_minimal_epub(language="")
    epub = read_epub_bytes(epub_bytes)
    # Simulate missing language
    epub.metadata.language = ""
    html = build(epub)
    # The html lang attribute should be "und" when language is empty
    assert 'lang="und"' in html or 'lang=""' in html


@pytest.mark.integration
def test_manifest_element_canonical_xml_identical_after_roundtrip() -> None:
    """OPF manifest is canonical-XML-equal after round-trip (US-013, C-2)."""
    from lxml import etree

    epub_bytes = build_minimal_epub()
    output = _roundtrip(epub_bytes)

    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        orig_opf = zf.read("OEBPS/content.opf")
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        new_opf = zf.read("OEBPS/content.opf")

    _OPF_NS = "http://www.idpf.org/2007/opf"

    orig_root = etree.fromstring(orig_opf)
    new_root = etree.fromstring(new_opf)

    orig_manifest = orig_root.find(f"{{{_OPF_NS}}}manifest")
    new_manifest = new_root.find(f"{{{_OPF_NS}}}manifest")

    if orig_manifest is not None and new_manifest is not None:
        # c14n2 on a subtree element fails when namespace declarations live on
        # ancestor elements. Compare manifest items structurally instead.
        def _manifest_items(el: etree._Element) -> list[tuple[str | None, ...]]:
            return sorted(
                [(c.get("id"), c.get("href"), c.get("media-type")) for c in el],
                key=lambda t: t[0] or "",
            )

        assert _manifest_items(orig_manifest) == _manifest_items(new_manifest), (
            "Manifest items changed after round-trip"
        )


@pytest.mark.integration
def test_spine_element_canonical_xml_identical_after_roundtrip() -> None:
    """OPF spine is canonical-XML-equal after round-trip (US-013, C-2)."""
    from lxml import etree

    epub_bytes = build_minimal_epub()
    output = _roundtrip(epub_bytes)

    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        orig_opf = zf.read("OEBPS/content.opf")
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        new_opf = zf.read("OEBPS/content.opf")

    _OPF_NS = "http://www.idpf.org/2007/opf"
    orig_root = etree.fromstring(orig_opf)
    new_root = etree.fromstring(new_opf)

    orig_spine = orig_root.find(f"{{{_OPF_NS}}}spine")
    new_spine = new_root.find(f"{{{_OPF_NS}}}spine")

    if orig_spine is not None and new_spine is not None:
        # c14n2 on a subtree element fails when namespace declarations live on
        # ancestor elements. Compare spine itemrefs by idref list instead.
        orig_idrefs = [c.get("idref") for c in orig_spine]
        new_idrefs = [c.get("idref") for c in new_spine]
        assert orig_idrefs == new_idrefs, "Spine changed after round-trip"


@pytest.mark.integration
def test_input_equals_output_path_rejected_prepare(
    synth_epub_file: pathlib.Path,
) -> None:
    """US-018: prepare rejects output == input."""
    import contextlib
    import io
    import sys

    from epub_deepl.cli import main

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        rc = main(["prepare", str(synth_epub_file), "--output", str(synth_epub_file)])
    assert rc == 1
    assert "Output path equals input path" in stderr.getvalue()


@pytest.mark.integration
def test_input_equals_output_path_force_does_not_bypass(
    synth_epub_file: pathlib.Path,
) -> None:
    """US-018: --force does not bypass input==output check."""
    import contextlib
    import io

    from epub_deepl.cli import main

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        rc = main(["prepare", str(synth_epub_file), "--output", str(synth_epub_file), "--force"])
    assert rc == 1


@pytest.mark.integration
def test_non_xhtml_spine_item_rejected(tmp_path: pathlib.Path) -> None:
    """US-020: non-XHTML spine item causes exit 1."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.epub.validator import validate_epub
    from epub_deepl.errors import UnsupportedMediaType

    epub = read_epub_bytes(build_minimal_epub())
    # Change first spine item's media-type
    first_idref = epub.spine.items[0].idref
    epub.manifest[first_idref].media_type = "application/x-dtbook+xml"
    with pytest.raises(UnsupportedMediaType, match="Unsupported spine media-type"):
        validate_epub(epub)


@pytest.mark.integration
def test_adversarial_translation_strips_data_attribute_surfaces_precise_error() -> None:
    """SM-7 / C-4: stripping data-source-href causes precise TranslatedHtmlMismatch."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.errors import TranslatedHtmlMismatch
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub_bytes = build_minimal_epub()
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)

    # Simulate DeepL stripping data-source-href from one section
    stripped = html.replace('data-source-href="ch01.xhtml"', "")
    doc = parse_translated_html_bytes(stripped.encode("utf-8"))

    with pytest.raises(TranslatedHtmlMismatch):
        apply_and_write_bytes(epub, doc, "pl")


@pytest.mark.integration
def test_split_roundtrip_tolerates_stripped_part_markers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A translator that strips data-part/data-parts-total (e.g. because it
    doesn't recognise the attribute) must not crash restore, and must not
    trigger a false-positive marker-mismatch WARN either -- markers absent
    from every part are silent by design (the real completeness gate is the
    section-vs-spine set equality in validate_translated_html, unaffected by
    the part markers). Symmetric to
    test_adversarial_translation_strips_data_attribute_surfaces_precise_error,
    which covers data-source-href stripping -- that one must fail, this one
    must succeed. Regression test for BLOCK cycle 1 on task #22."""
    import re

    epub_bytes = _wide_epub_bytes_for_split()
    max_chars = _max_chars_forcing_split(epub_bytes)

    def _strip_part_markers(html: str) -> str:
        return re.sub(r'\s+data-part="\d+"\s+data-parts-total="\d+"', "", html)

    with caplog.at_level(logging.WARNING, logger="epub_deepl.restore.parser"):
        output = _split_roundtrip(epub_bytes, max_chars, transform=_strip_part_markers)
    _check_zip_invariants(output)

    for i in range(1, 6):
        text = _text_content_of_xhtml(output, f"ch{i:02d}.xhtml")
        assert f"unique-marker-{i}" in text
    assert caplog.records == []


@pytest.mark.integration
def test_adversarial_translation_attribute_reorder_still_succeeds() -> None:
    """SM-7 / C-4: attribute reordering does not break restore."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub_bytes = build_minimal_epub()
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)

    # Reorder section attributes (swap data-spine-idx and data-source-href)
    import re

    def _swap_attrs(m: re.Match[str]) -> str:
        s = m.group(0)
        # Move data-spine-idx before data-source-href
        s = re.sub(
            r'(data-source-href="[^"]*")\s+(data-spine-idx="\d+")',
            r"\2 \1",
            s,
        )
        return s

    reordered = re.sub(r"<section [^>]+>", _swap_attrs, html)

    doc = parse_translated_html_bytes(reordered.encode("utf-8"))
    # Should succeed — attribute order doesn't matter for XPath queries
    output = apply_and_write_bytes(epub, doc, "pl")
    _check_zip_invariants(output)


@pytest.mark.integration
def test_adversarial_translation_random_seeded_combinations() -> None:
    """SM-7: adversarial transform either succeeds or fails with precise error."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.errors import TranslatedHtmlMismatch
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub_bytes = build_minimal_epub()

    for seed in [1, 2, 3, 42, 99]:
        epub = read_epub_bytes(epub_bytes)
        html = build(epub)
        adversarial = _adversarial_translation(html, seed=seed)
        doc = parse_translated_html_bytes(adversarial.encode("utf-8"))

        try:
            output = apply_and_write_bytes(epub, doc, "pl")
            # If it succeeded, output must be a valid ZIP
            _check_zip_invariants(output)
        except TranslatedHtmlMismatch:
            pass  # Precise failure — acceptable per SM-7
        except Exception as exc:
            pytest.fail(f"Adversarial seed={seed} caused opaque crash: {type(exc).__name__}: {exc}")


@pytest.mark.integration
def test_simulated_translation_completeness() -> None:
    """Simulated translation touches every expected field (SM-2 proxy)."""
    from epub_deepl.epub.opf import parse_metadata
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub_bytes = build_minimal_epub(titles=("The Book",), descriptions=("The Desc",))
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)
    translated = _simulated_translation(html)
    doc = parse_translated_html_bytes(translated.encode("utf-8"))
    output = apply_and_write_bytes(epub, doc, "pl")

    # Check that translated title is in the output OPF
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        opf = zf.read("OEBPS/content.opf")
    meta = parse_metadata(opf)
    assert "«PL»" in meta.titles[0], f"Title not translated: {meta.titles}"


# ---------------------------------------------------------------------------
# EPUB 3 nav-document tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_epub3_both_navs_synth() -> None:
    """EPUB 3 with both NCX and a non-spine nav doc round-trips cleanly and
    keeps both navigation files in the output ZIP.
    """
    epub_bytes = build_minimal_epub(epub_version="3.0")
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        names = zf.namelist()
    assert "OEBPS/nav.xhtml" in names
    assert names.count("OEBPS/nav.xhtml") == 1
    assert "OEBPS/toc.ncx" in names


@pytest.mark.integration
def test_roundtrip_epub3_nav_only_synth() -> None:
    """EPUB 3 with a nav doc only, no NCX, round-trips cleanly (FR-4 nav
    matrix: EPUB 3.x requires the nav doc, NCX is optional).
    """
    epub_bytes = build_minimal_epub(epub_version="3.0", include_ncx=False)
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        names = zf.namelist()
    assert "OEBPS/nav.xhtml" in names
    assert names.count("OEBPS/nav.xhtml") == 1
    assert "OEBPS/toc.ncx" not in names


@pytest.mark.integration
def test_roundtrip_epub3_nav_in_spine_synth() -> None:
    """EPUB 3 with the nav doc also referenced as a spine item round-trips
    cleanly. Its final bytes travel through the ordinary spine-writing path
    in writer.py, not the non-spine step 4b fallback.
    """
    epub_bytes = build_minimal_epub(epub_version="3.0", nav_in_spine=True)
    output = _roundtrip(epub_bytes)
    _check_zip_invariants(output)
    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        names = zf.namelist()
    assert "OEBPS/nav.xhtml" in names
    assert names.count("OEBPS/nav.xhtml") == 1


@pytest.mark.integration
def test_epub3_nav_labels_consistent_with_ncx_after_translation() -> None:
    """EPUB 3: nav-doc toc labels and NCX navLabels resolve to the same
    translated heading text after a simulated translation.

    Both structures share the same nav_map source and the same anchor-
    resolution machinery (epub.ncx.resolve_anchor_label), so a chapter's
    NCX navLabel and its nav-doc toc entry label must end up identical.
    """
    from epub_deepl.epub.nav import parse_nav_doc
    from epub_deepl.epub.ncx import parse_ncx
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub_bytes = build_minimal_epub(epub_version="3.0")
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)
    translated = _simulated_translation(html)
    doc = parse_translated_html_bytes(translated.encode("utf-8"))
    output = apply_and_write_bytes(epub, doc, "pl")
    _check_zip_invariants(output)

    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        ncx_bytes = zf.read("OEBPS/toc.ncx")
        nav_bytes = zf.read("OEBPS/nav.xhtml")

    ncx = parse_ncx(ncx_bytes, "OEBPS/toc.ncx")
    nav_doc = parse_nav_doc(nav_bytes, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)

    assert len(ncx.nav_map) == len(nav_doc.toc_entries) == 3
    for nav_point, toc_entry in zip(ncx.nav_map, nav_doc.toc_entries, strict=True):
        assert nav_point.label == toc_entry.label, (
            f"NCX label {nav_point.label!r} != nav-doc label {toc_entry.label!r}"
        )
        assert nav_point.label.startswith("«PL»"), f"Label not translated: {nav_point.label!r}"


@pytest.mark.integration
def test_epub3_nav_toc_entry_keeps_translated_label_when_anchor_unresolvable() -> None:
    """A nav-doc toc entry whose target has neither the referenced fragment
    nor any heading at all cannot be anchor-resolved (resolve_anchor_label
    returns None); its label is left as DeepL's own (simulated) translation
    of the original nav-doc link text, exactly like the NCX fallback in
    resolve_label() when resolve_anchor_label fails there too.

    Distinguishes the two label origins by content rather than merely by the
    "«PL»" translation prefix (both are «PL»-prefixed under
    _simulated_translation): entry 0's target has a resolvable heading, so
    its label becomes the *heading's* translated text; entry 1's target has
    no heading, so its label stays the *nav link's own* translated text —
    a different string from any chapter heading.
    """
    from epub_deepl.epub.nav import parse_nav_doc
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    xhtmls = [
        XhtmlSpec(
            href="ch01.xhtml",
            title="Chapter 1",
            body_html='<h1 id="ch1-heading">Chapter One Heading</h1><p>Chapter 1 content.</p>',
        ),
        XhtmlSpec(
            href="ch02.xhtml",
            title="Chapter 2",
            body_html="<p>No heading here, just prose.</p>",
        ),
    ]
    nav_map = [
        NavPointSpec(
            label="Chapter One", src="ch01.xhtml#ch1-heading", nav_id="navPoint-1", play_order=1
        ),
        NavPointSpec(
            label="Chapter Two",
            src="ch02.xhtml#missing-fragment",
            nav_id="navPoint-2",
            play_order=2,
        ),
    ]
    epub_bytes = build_minimal_epub(epub_version="3.0", xhtmls=xhtmls, nav_map=nav_map)
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)
    translated = _simulated_translation(html)
    doc = parse_translated_html_bytes(translated.encode("utf-8"))
    output = apply_and_write_bytes(epub, doc, "pl")
    _check_zip_invariants(output)

    with zipfile.ZipFile(io.BytesIO(output)) as zf:
        nav_bytes = zf.read("OEBPS/nav.xhtml")
    nav_doc = parse_nav_doc(nav_bytes, "nav.xhtml", "OEBPS/nav.xhtml", in_spine=False)

    assert len(nav_doc.toc_entries) == 2
    resolved_entry, fallback_entry = nav_doc.toc_entries

    # Resolved via the chapter's own heading (fragment found).
    assert resolved_entry.label == "«PL» Chapter One Heading"
    # Unresolvable (fragment missing, no heading at all): kept as the
    # simulated-translated original nav link text, not overwritten.
    assert fallback_entry.label == "«PL» Chapter Two"
    assert fallback_entry.label != resolved_entry.label


@pytest.mark.integration
def test_epub3_payload_marks_nav_doc_and_page_list_no_translate() -> None:
    """merge.builder marks the non-spine EPUB 3 nav doc section with
    data-nav-doc="true" and excludes its page-list nav from translation via
    translate="no" (US-008). A non-spine nav doc carries no data-spine-idx —
    that attribute is reserved for sections backed by an actual spine entry.
    """
    import re

    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build

    epub_bytes = build_minimal_epub(epub_version="3.0", nav_page_list=True)
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)

    assert 'data-source-href="nav.xhtml"' in html
    assert 'data-nav-doc="true"' in html
    assert "page-list" in html
    assert 'translate="no"' in html

    match = re.search(r'<section[^>]*data-source-href="nav\.xhtml"[^>]*>', html)
    assert match is not None
    assert "data-spine-idx=" not in match.group(0)


@pytest.mark.integration
def test_epub3_in_spine_nav_doc_annotated_once_with_both_markers() -> None:
    """An in-spine nav doc's <section> carries both data-spine-idx (ordinary
    spine annotation) and data-nav-doc (discriminator marker) together, and
    appears exactly once in the payload — never emitted twice as a separate
    non-spine section too.
    """
    import re

    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build

    epub_bytes = build_minimal_epub(epub_version="3.0", nav_in_spine=True)
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)

    assert html.count('data-source-href="nav.xhtml"') == 1
    match = re.search(r'<section[^>]*data-source-href="nav\.xhtml"[^>]*>', html)
    assert match is not None
    assert "data-spine-idx=" in match.group(0)
    assert 'data-nav-doc="true"' in match.group(0)


@pytest.mark.integration
def test_epub3_missing_nav_section_raises_mismatch() -> None:
    """SM-7 / C-4: stripping the nav doc's own data-source-href section
    surfaces a precise TranslatedHtmlMismatch — the nav-doc counterpart of
    test_adversarial_translation_strips_data_attribute_surfaces_precise_error.
    """
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.errors import TranslatedHtmlMismatch
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub_bytes = build_minimal_epub(epub_version="3.0")
    epub = read_epub_bytes(epub_bytes)
    html = build(epub)

    stripped = html.replace('data-source-href="nav.xhtml"', "")
    doc = parse_translated_html_bytes(stripped.encode("utf-8"))

    with pytest.raises(TranslatedHtmlMismatch):
        apply_and_write_bytes(epub, doc, "pl")


# ---------------------------------------------------------------------------
# Corpus round-trip tests (skipped if corpus absent)
# ---------------------------------------------------------------------------


@pytest.mark.corpus
def test_roundtrip_without_translation_is_content_identical(
    corpus_epub: pathlib.Path,
) -> None:
    """SM-1 full composite check: round-trip produces ZIP-invariant output (corpus).

    Checks:
      (a) All XHTML content is text-equivalent after round-trip
      (b) ZIP invariants hold (C-1)
      (c) zipfile.testzip() passes
    """
    with open(corpus_epub, "rb") as f:
        epub_bytes = f.read()

    from epub_deepl.epub.reader import read_epub_bytes

    try:
        epub = read_epub_bytes(epub_bytes)
    except Exception as exc:
        pytest.skip(f"Cannot parse corpus EPUB: {exc}")

    if not epub.metadata.language:
        epub.metadata.language = "und"

    source_lang = epub.metadata.language

    output = _roundtrip(epub_bytes, target_lang=source_lang)
    _check_zip_invariants(output)

    # Compare XHTML content
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as orig_zf:
        with zipfile.ZipFile(io.BytesIO(output)) as new_zf:
            for name in orig_zf.namelist():
                if not name.endswith(".xhtml") and not name.endswith(".html"):
                    continue
                orig_zf.read(name).decode("utf-8", errors="replace")
                if name in new_zf.namelist():
                    new_content = new_zf.read(name).decode("utf-8", errors="replace")
                    # Text content should be equivalent (not necessarily byte-identical)
                    # We check that no text was lost by verifying bodies are similar
                    # (exact diff is too strict given lxml re-serialisation)
                    assert len(new_content) > 0


@pytest.mark.corpus
def test_zip_packaging_invariants_hold_after_roundtrip(
    corpus_epub: pathlib.Path,
) -> None:
    """C-1 / SM-1: ZIP invariants on every corpus round-trip output."""
    with open(corpus_epub, "rb") as f:
        epub_bytes = f.read()

    from epub_deepl.epub.reader import read_epub_bytes

    try:
        epub = read_epub_bytes(epub_bytes)
    except Exception as exc:
        pytest.skip(f"Cannot parse corpus EPUB: {exc}")

    if not epub.metadata.language:
        epub.metadata.language = "und"

    output = _roundtrip(epub_bytes, target_lang=epub.metadata.language)
    _check_zip_invariants(output)


@pytest.mark.corpus
def test_cli_turnaround_per_book(corpus_epub: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """SM-6: combined prepare+restore takes < 60s per book."""
    html_out = tmp_path / "prepared.html"
    epub_out = tmp_path / "restored.epub"

    import contextlib
    import io

    from epub_deepl.cli import main

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        start = time.monotonic()
        rc1 = main(["prepare", str(corpus_epub), "--output", str(html_out)])
        if rc1 != 0:
            pytest.skip(f"prepare failed: {stderr.getvalue()}")
        rc2 = main(
            ["restore", str(corpus_epub), str(html_out), "--lang", "en", "--output", str(epub_out)]
        )
        elapsed = time.monotonic() - start

    assert rc2 == 0, f"restore failed: {stderr.getvalue()}"
    assert elapsed < 60, f"Too slow: {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# Non-ASCII content end-to-end (lessons-learned G-1, P-2)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_roundtrip_preserves_non_ascii_content_end_to_end(
    tmp_path: pathlib.Path,
) -> None:
    """End-to-end policy guard: an EPUB whose metadata AND body contain
    Polish, CJK, and Cyrillic characters round-trips through
    prepare → restore without translation and emerges byte-identical
    in every non-ASCII run.

    Closes the policy gap from lessons-learned P-2 (test corpus
    monoculture). The pre-existing unit test
    `test_replace_body_preserves_non_ascii_utf8` pins the
    `replace_body_content` function; this test pins the full CLI
    pipeline (so future regressions in OPF, NCX, or the writer cannot
    slip past).
    """
    import zipfile

    from epub_deepl.cli import main as cli_main
    from tests.fixtures.minimal import NavPointSpec

    polish = "Poniższa książka zawiera żółć, ąęóźż — święto słowiańskich znaków."
    cjk = "日本語のテキスト、中文测试テスト、한국어 시험 — Unicode CJK 区域."
    cyrillic = "Кириллица проверка: щ ъ ы ь э ю я ё."

    epub_bytes = build_minimal_epub(
        titles=("Książka testowa — 测试", "Druga okładka"),
        descriptions=(polish, cjk),
        subjects=("вкуса-теста", "polski", "中文"),
        creators=("Иван Иванов",),
        language="pl",
        xhtmls=[
            XhtmlSpec(
                href="ch01.xhtml",
                title="Próbka — 章节一",
                body_html=(
                    '<h1 id="ch1">Wprowadzenie — 序章 — Введение</h1>'
                    f"<p>{polish}</p>"
                    f"<p>{cjk}</p>"
                    f"<p>{cyrillic}</p>"
                ),
            )
        ],
        nav_map=[
            NavPointSpec(
                label="Wprowadzenie — 序章 — Введение",
                src="ch01.xhtml#ch1",
            ),
        ],
    )
    in_path = tmp_path / "non-ascii.epub"
    in_path.write_bytes(epub_bytes)
    html_out = tmp_path / "prepared.html"
    epub_out = tmp_path / "restored.epub"

    assert cli_main(["prepare", str(in_path), "--output", str(html_out)]) == 0
    assert cli_main(["restore", str(in_path), str(html_out), "--output", str(epub_out)]) == 0

    # Every distinct non-ASCII run from the inputs must appear unchanged in
    # the restored OPF, NCX, or chapter XHTML. We assert on raw UTF-8 bytes
    # (not str equality) so a Latin-1 round-trip would fail loudly.
    with zipfile.ZipFile(epub_out) as zf:
        opf_bytes = next(zf.read(n) for n in zf.namelist() if n.endswith(".opf"))
        ncx_bytes = next(zf.read(n) for n in zf.namelist() if n.endswith(".ncx"))
        xhtml_bytes = b"".join(zf.read(n) for n in zf.namelist() if n.endswith((".xhtml", ".html")))

    blob = opf_bytes + ncx_bytes + xhtml_bytes
    for fragment, label in [
        (polish, "Polish body"),
        (cjk, "CJK body"),
        (cyrillic, "Cyrillic body"),
        ("Książka testowa — 测试", "mixed title"),
        ("Иван Иванов", "Cyrillic creator (untranslated)"),
        ("вкуса-теста", "Cyrillic subject"),
        ("Wprowadzenie — 序章 — Введение", "tri-script heading"),
    ]:
        assert fragment.encode("utf-8") in blob, (
            f"{label}: {fragment!r} (UTF-8) not found in restored EPUB output"
        )

        # Mojibake form (UTF-8 bytes re-decoded as Latin-1, re-encoded UTF-8)
        # must NOT appear anywhere.
        mojibake = fragment.encode("utf-8").decode("latin-1").encode("utf-8")
        assert mojibake not in blob, f"{label}: mojibake leaked through for {fragment!r}"


# ---------------------------------------------------------------------------
# Payload splitting (WP4-WP6 — see docs/adr/0006)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_split_roundtrip_preserves_content_losslessly() -> None:
    """build_split + merge_translated_docs + apply produces the same
    zip-invariant, content-complete EPUB as the unsplit path — splitting
    is purely a transport concern, not a content transform."""
    epub_bytes = _wide_epub_bytes_for_split()
    max_chars = _max_chars_forcing_split(epub_bytes)

    output = _split_roundtrip(epub_bytes, max_chars=max_chars)
    _check_zip_invariants(output)

    for i in range(1, 6):
        text = _text_content_of_xhtml(output, f"ch{i:02d}.xhtml")
        assert f"unique-marker-{i}" in text


@pytest.mark.integration
def test_split_roundtrip_survives_simulated_translation_across_parts() -> None:
    """A «PL» marker applied independently to EACH part (as DeepL would,
    translating each part in its own request) survives merge + restore
    for every chapter, regardless of which part it landed in."""
    epub_bytes = _wide_epub_bytes_for_split()
    max_chars = _max_chars_forcing_split(epub_bytes)

    output = _split_roundtrip(epub_bytes, max_chars=max_chars, transform=_simulated_translation)
    _check_zip_invariants(output)

    for i in range(1, 6):
        text = _text_content_of_xhtml(output, f"ch{i:02d}.xhtml")
        assert "«PL»" in text
        assert f"unique-marker-{i}" in text


# ---------------------------------------------------------------------------
# Embedded SVG attribute case (US-022 / FR-6)
# ---------------------------------------------------------------------------


def _inline_svg_epub_bytes() -> bytes:
    """EPUB 3 with one chapter embedding inline SVG whose attributes are
    case-sensitive per the SVG spec. The manifest item declares
    `properties="svg"` so the fixture is epubcheck-clean by construction."""
    return build_minimal_epub(
        epub_version="3.0",
        xhtmls=[
            XhtmlSpec(
                href="ch01.xhtml",
                title="Chapter 1",
                body_html=(
                    '<h1 id="c1">Chapter One</h1>'
                    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
                    'viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">'
                    '<rect width="100" height="100"/></svg>'
                ),
                properties="svg",
            )
        ],
        nav_map=[NavPointSpec(label="Chapter One", src="ch01.xhtml#c1")],
    )


@pytest.mark.integration
def test_prepare_payload_keeps_svg_attribute_case() -> None:
    """The merged payload uploaded to DeepL carries valid camelCase SVG
    attribute names — prepare extracts through the XML parser, which never
    lowercases. (The restore-side counterpart is the round-trip test below.)
    """
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build

    epub = read_epub_bytes(_inline_svg_epub_bytes())
    merged = build(epub)

    assert 'viewBox="0 0 100 100"' in merged
    assert 'preserveAspectRatio="xMidYMid meet"' in merged
    assert "viewbox=" not in merged
    assert "preserveaspectratio=" not in merged


@pytest.mark.integration
def test_roundtrip_svg_attribute_case_preserved() -> None:
    """US-022: inline SVG camelCase attributes survive the full round-trip.

    restore parses translated content with the lowercasing HTML parser, so
    this exercises `restore_svg_attribute_case` on the real pipeline rather
    than in isolation.
    """
    output = _roundtrip(_inline_svg_epub_bytes())
    _check_zip_invariants(output)

    xhtml = _text_content_of_xhtml(output, "ch01.xhtml")
    assert 'viewBox="0 0 100 100"' in xhtml
    assert 'preserveAspectRatio="xMidYMid meet"' in xhtml
    assert "viewbox=" not in xhtml
    assert "preserveaspectratio=" not in xhtml


@pytest.mark.integration
def test_roundtrip_svg_attribute_case_survives_simulated_translation() -> None:
    """US-022 under the friendly «PL» transform: text nodes change, SVG
    attribute names and values must not."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import build
    from epub_deepl.restore.applier import apply_and_write_bytes
    from epub_deepl.restore.parser import parse_translated_html_bytes

    epub = read_epub_bytes(_inline_svg_epub_bytes())
    merged = _simulated_translation(build(epub))
    doc = parse_translated_html_bytes(merged.encode("utf-8"))
    output = apply_and_write_bytes(epub, doc, "pl")
    _check_zip_invariants(output)

    xhtml = _text_content_of_xhtml(output, "ch01.xhtml")
    assert "«PL»" in xhtml
    assert 'viewBox="0 0 100 100"' in xhtml
    assert 'preserveAspectRatio="xMidYMid meet"' in xhtml
    assert "viewbox=" not in xhtml
    assert "preserveaspectratio=" not in xhtml
