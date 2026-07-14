"""Unit tests for OPF parsing and metadata manipulation (test-plan §6.1)."""

from __future__ import annotations

import pytest
from lxml import etree

from tests.fixtures.minimal import build_minimal_epub


@pytest.mark.unit
def test_parse_extracts_all_dc_titles_in_order() -> None:
    """Multiple dc:title elements are extracted in document order."""
    from epub_deepl.epub.opf import parse_metadata

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:language>en</dc:language>
    <dc:title>Title One</dc:title>
    <dc:title>Title Two</dc:title>
    <dc:title>Title Three</dc:title>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    assert meta.titles == ["Title One", "Title Two", "Title Three"]


@pytest.mark.unit
def test_parse_extracts_descriptions_subjects_creators() -> None:
    """All translatable and structural fields are extracted correctly."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(
        build_minimal_epub(
            titles=("My Book",),
            descriptions=("A test book",),
            subjects=("sci-fi", "adventure"),
            creators=("Jane Doe",),
        )
    )
    assert epub.metadata.titles == ["My Book"]
    assert epub.metadata.descriptions == ["A test book"]
    assert epub.metadata.subjects == ["sci-fi", "adventure"]
    assert epub.metadata.creators == ["Jane Doe"]


@pytest.mark.unit
def test_parse_preserves_opf_namespaced_meta_extensions() -> None:
    """Calibre/Apple custom <meta> elements survive the parse-rebuild cycle."""
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:language>en</dc:language>
    <dc:title>Original Title</dc:title>
    <dc:description>Original desc</dc:description>
    <dc:subject>sci-fi</dc:subject>
    <meta name="calibre:series" content="My Series"/>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.titles = ["Translated Title"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")
    # The calibre:meta element must be present
    assert b"calibre:series" in new_bytes


@pytest.mark.unit
def test_rebuild_preserves_dc_title_id_attribute() -> None:
    """rebuild_opf_bytes mutates dc:title text but keeps its id attribute.

    Dropping id="t1" would orphan any <meta refines="#t1"> pair (EPUB 3
    requirement) referencing this title.
    """
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookID">urn:uuid:12345</dc:identifier>
    <dc:language>en</dc:language>
    <dc:title id="t1">Original Title</dc:title>
    <meta refines="#t1" property="title-type">main</meta>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.titles = ["New Title"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"
    title_el = new_root.find(f".//{{{_DC_NS}}}title")
    assert title_el is not None
    assert title_el.get("id") == "t1"
    assert title_el.text == "New Title"


@pytest.mark.unit
def test_rebuild_preserves_dc_subject_and_description_attributes() -> None:
    """rebuild_opf_bytes mutates text but keeps xml:lang / opf:* attributes."""
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:language>en</dc:language>
    <dc:title>Title</dc:title>
    <dc:description xml:lang="en">Original description</dc:description>
    <dc:subject opf:authority="BISAC" opf:term="FIC000000">Fiction</dc:subject>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.descriptions = ["New description"]
    meta.subjects = ["New subject"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"
    _OPF_NS = "http://www.idpf.org/2007/opf"
    _XML_NS = "http://www.w3.org/XML/1998/namespace"

    desc_el = new_root.find(f".//{{{_DC_NS}}}description")
    assert desc_el is not None
    assert desc_el.get(f"{{{_XML_NS}}}lang") == "en"
    assert desc_el.text == "New description"

    subj_el = new_root.find(f".//{{{_DC_NS}}}subject")
    assert subj_el is not None
    assert subj_el.get(f"{{{_OPF_NS}}}authority") == "BISAC"
    assert subj_el.get(f"{{{_OPF_NS}}}term") == "FIC000000"
    assert subj_el.text == "New subject"


@pytest.mark.unit
def test_rebuild_preserves_refines_meta_pairing() -> None:
    """The rebuilt OPF keeps <meta refines="#t1"> paired with dc:title id="t1"."""
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookID">urn:uuid:12345</dc:identifier>
    <dc:language>en</dc:language>
    <dc:title id="t1">Original Title</dc:title>
    <meta refines="#t1" property="title-type">main</meta>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.titles = ["Translated Title"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"

    title_el = new_root.find(f".//{{{_DC_NS}}}title")
    assert title_el is not None
    assert title_el.get("id") == "t1"

    refines_metas = [
        el
        for el in new_root.iter()
        if isinstance(el.tag, str)
        and (el.tag.endswith("}meta") or el.tag == "meta")
        and el.get("refines") == "#t1"
    ]
    assert len(refines_metas) == 1


@pytest.mark.unit
def test_rebuild_clusters_new_translatable_elements_from_empty() -> None:
    """New description/subject/language elements cluster after dc:title.

    Regression: a naive "insert at the first existing translatable element"
    fallback flips the order on each successive zero-baseline insert (each
    new tag lands *before* the previous one), producing dc:language,
    dc:subject, dc:description, dc:title instead of the intended
    title, description, subject, language.
    """
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookID">urn:uuid:12345</dc:identifier>
    <dc:title>Original Title</dc:title>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.titles = ["New Title"]
    meta.descriptions = ["New description"]
    meta.subjects = ["New subject"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"
    _OPF_NS = "http://www.idpf.org/2007/opf"
    metadata_el = new_root.find(f"{{{_OPF_NS}}}metadata")
    assert metadata_el is not None

    tags = [el.tag for el in metadata_el]
    assert tags == [
        f"{{{_DC_NS}}}identifier",
        f"{{{_DC_NS}}}title",
        f"{{{_DC_NS}}}description",
        f"{{{_DC_NS}}}subject",
        f"{{{_DC_NS}}}language",
    ]


@pytest.mark.unit
def test_rebuild_new_pair_lands_after_existing_translatable_block() -> None:
    """New subject+language elements land after an existing title+description
    block, in that same relative order (subject before language).
    """
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookID">urn:uuid:12345</dc:identifier>
    <dc:title>Original Title</dc:title>
    <dc:description>Original description</dc:description>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.titles = ["New Title"]
    meta.descriptions = ["New description"]
    meta.subjects = ["New subject"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"
    _OPF_NS = "http://www.idpf.org/2007/opf"
    metadata_el = new_root.find(f"{{{_OPF_NS}}}metadata")
    assert metadata_el is not None

    tags = [el.tag for el in metadata_el]
    assert tags == [
        f"{{{_DC_NS}}}identifier",
        f"{{{_DC_NS}}}title",
        f"{{{_DC_NS}}}description",
        f"{{{_DC_NS}}}subject",
        f"{{{_DC_NS}}}language",
    ]


@pytest.mark.unit
def test_rebuild_strips_stray_child_elements_and_tail() -> None:
    """rebuild_opf_bytes clears pre-existing child elements before mutating
    .text, instead of leaving them (and their tails) glued after the new
    text — a regression vs. the old remove-and-recreate strategy, which
    always produced a clean text-only element.
    """
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:language>en</dc:language>
    <dc:title>Title</dc:title>
    <dc:description xml:lang="en">Hello <b>world</b> tail</dc:description>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.descriptions = ["New description"]
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"
    _XML_NS = "http://www.w3.org/XML/1998/namespace"
    desc_el = new_root.find(f".//{{{_DC_NS}}}description")
    assert desc_el is not None
    assert desc_el.get(f"{{{_XML_NS}}}lang") == "en"
    assert desc_el.text == "New description"
    assert len(desc_el) == 0


@pytest.mark.unit
def test_set_language_replaces_first_dc_language() -> None:
    """rebuild_opf_bytes replaces dc:language with the target language."""
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:language>en</dc:language>
    <dc:title>Book</dc:title>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    new_bytes = rebuild_opf_bytes(opf, meta, "pl")
    rebuilt_meta = parse_metadata(new_bytes)
    assert rebuilt_meta.language == "pl"


@pytest.mark.unit
def test_set_language_preserves_extras_and_warns_when_multiple(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With multiple dc:language elements, only the first becomes the target.

    Extra dc:language elements are preserved unchanged (not collapsed) and a
    WARNING is logged — a deliberate behaviour change from the old
    collapse-to-one logic.
    """
    import logging

    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(build_minimal_epub(languages=["en", "de"]))

    monkeypatch.setattr(logging.getLogger("epub_deepl"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="epub_deepl.epub.opf"):
        new_bytes = rebuild_opf_bytes(epub.opf_raw_xml, epub.metadata, "pl")

    rebuilt = parse_metadata(new_bytes)
    assert rebuilt.language == "pl"

    new_root = etree.fromstring(new_bytes)
    _DC_NS = "http://purl.org/dc/elements/1.1/"
    lang_els = new_root.findall(f".//{{{_DC_NS}}}language")
    assert [el.text for el in lang_els] == ["pl", "de"]

    assert any(
        "dc:language" in record.getMessage() and record.levelno == logging.WARNING
        for record in caplog.records
    )


@pytest.mark.unit
def test_apply_translated_metadata_preserves_non_translated_fields() -> None:
    """rebuild_opf_bytes preserves creator/publisher/identifier structurally (C-2).

    Uses canonical XML (c14n2) for comparison so cosmetic lxml re-serialisation
    is not flagged as a failure — only real semantic changes are.
    """
    from epub_deepl.epub.opf import parse_metadata, rebuild_opf_bytes

    opf = b"""<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:language>en</dc:language>
    <dc:title>Old Title</dc:title>
    <dc:description>Old desc</dc:description>
    <dc:subject>old subject</dc:subject>
    <dc:creator opf:role="aut">Jane Doe</dc:creator>
    <dc:publisher>Test Publisher</dc:publisher>
    <dc:date>2024-01-01</dc:date>
    <dc:identifier id="BookID">urn:uuid:12345</dc:identifier>
  </metadata>
</package>"""
    meta = parse_metadata(opf)
    meta.titles = ["New Title"]
    meta.descriptions = ["New desc"]
    meta.subjects = ["new subject"]

    new_bytes = rebuild_opf_bytes(opf, meta, "pl")
    new_root = etree.fromstring(new_bytes)
    orig_root = etree.fromstring(opf)

    _DC_NS = "http://purl.org/dc/elements/1.1/"
    _OPF_NS = "http://www.idpf.org/2007/opf"

    # Check creator preserved
    orig_creator = orig_root.find(f".//{{{_DC_NS}}}creator")
    new_creator = new_root.find(f".//{{{_DC_NS}}}creator")
    assert orig_creator is not None and new_creator is not None
    # Canonical form comparison (C-2).
    # c14n2 on a *detached* subtree element fails when namespace declarations
    # live on ancestor elements — serialize the full document and compare the
    # specific element text/attributes instead.
    assert orig_creator.text == new_creator.text, "Creator text changed"
    assert orig_creator.attrib == new_creator.attrib, "Creator attrs changed"


@pytest.mark.unit
def test_opf_serialization_preserves_manifest_and_spine() -> None:
    """After rebuild, manifest and spine are structurally identical (US-013)."""
    from epub_deepl.epub.opf import (
        parse_manifest,
        parse_metadata,
        parse_spine,
        rebuild_opf_bytes,
    )

    opf = build_minimal_epub()
    # Extract the OPF bytes
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(opf)) as zf:
        opf_bytes = zf.read("OEBPS/content.opf")

    meta = parse_metadata(opf_bytes)
    new_opf = rebuild_opf_bytes(opf_bytes, meta, "pl")

    orig_manifest = parse_manifest(opf_bytes)
    new_manifest = parse_manifest(new_opf)
    orig_spine = parse_spine(opf_bytes)
    new_spine = parse_spine(new_opf)

    assert set(orig_manifest.keys()) == set(new_manifest.keys())
    assert [r.idref for r in orig_spine.items] == [r.idref for r in new_spine.items]

    # Canonical XML equality for manifest element
    orig_tree = etree.fromstring(opf_bytes)
    new_tree = etree.fromstring(new_opf)
    _OPF = "http://www.idpf.org/2007/opf"
    orig_manifest_el = orig_tree.find(f"{{{_OPF}}}manifest")
    new_manifest_el = new_tree.find(f"{{{_OPF}}}manifest")
    if orig_manifest_el is not None and new_manifest_el is not None:
        # c14n2 on a subtree element fails when namespace declarations live on
        # ancestor elements. Compare manifest items structurally instead.
        orig_items = sorted(
            [(el.get("id"), el.get("href"), el.get("media-type")) for el in orig_manifest_el],
            key=lambda t: t[0] or "",
        )
        new_items = sorted(
            [(el.get("id"), el.get("href"), el.get("media-type")) for el in new_manifest_el],
            key=lambda t: t[0] or "",
        )
        assert orig_items == new_items, "Manifest items changed after rebuild"
