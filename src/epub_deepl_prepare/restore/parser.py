"""Parse translated HTML5 into a TranslatedDoc.

The translated HTML was produced by builder.py, passed through DeepL, and
returned. DeepL may have:
  - Preserved all data-* attributes (happy path)
  - Reordered attributes (still fine — we use attribute-value queries)
  - Collapsed whitespace in some elements
  - Re-encoded entities

I-17 mitigation: we pass the bytes through lxml's HTML parser which handles
re-encoding and non-UTF-8 gracefully.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from lxml import etree

from epub_deepl_prepare.epub._safe_parser import parse_html_document
from epub_deepl_prepare.epub._svg_case import restore_svg_attribute_case
from epub_deepl_prepare.errors import UserError


@dataclass
class TranslatedDoc:
    """Extracted content from a translated HTML5 document."""

    titles: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    ncx_doctitle: str = ""
    nav_labels: dict[str, str] = field(default_factory=dict)  # data-ncx-id → label
    sections: dict[str, str] = field(default_factory=dict)  # data-source-href → body HTML
    #: Raw ``<html lang="...">`` value, trimmed. ``None`` if the root
    #: element has no ``lang`` attribute or the value is empty after
    #: whitespace trim. Used by ``cli`` to auto-detect the target
    #: language without an explicit ``--lang`` flag.
    html_lang: str | None = None


def parse_translated_html(html_path: str) -> TranslatedDoc:
    """Parse a translated HTML file from disk."""
    try:
        data = pathlib.Path(html_path).read_bytes()
    except OSError as exc:
        raise UserError(f"Cannot read translated HTML: {exc}") from exc
    return parse_translated_html_bytes(data)


def parse_translated_html_bytes(data: bytes) -> TranslatedDoc:
    """Parse translated HTML from bytes.

    Uses the HTML parser (it tolerates HTML5-isms — named entities,
    unclosed void elements, missing namespace declarations — that the
    XML parser rejects), then runs a focused post-parse pass to restore
    SVG / MathML attribute case (``viewBox`` etc.) which the HTML parser
    lowercases per HTML4 semantics. Without that pass, epubcheck rejects
    EPUBs containing embedded SVG cover pages.
    """
    try:
        tree = parse_html_document(data)
    except Exception as exc:
        raise UserError(f"Translated HTML malformed: {exc}") from exc
    restore_svg_attribute_case(tree)

    doc = TranslatedDoc()

    # Extract <html lang="..."> (root attribute). EPUB Packages §5.6.3
    # mandates trimming leading/trailing whitespace before processing
    # language tag values; we apply the same rule here. Empty after
    # trim → leave as None so the CLI knows auto-detect failed and can
    # require --lang explicitly.
    raw_lang = tree.get("lang") or tree.get("{http://www.w3.org/XML/1998/namespace}lang")
    if raw_lang:
        trimmed = raw_lang.strip()
        if trimmed:
            doc.html_lang = trimmed

    # --- OPF metadata block ---
    meta_header = tree.find(".//header[@data-source='opf-metadata']")
    if meta_header is not None:
        for el in meta_header.iter():
            dc_attr = el.get("data-dc")
            if dc_attr == "title":
                text = _text_content(el)
                if text:
                    doc.titles.append(text)
            elif dc_attr == "description":
                text = _text_content(el)
                if text:
                    doc.descriptions.append(text)
            elif dc_attr == "subject":
                text = _text_content(el)
                if text:
                    doc.subjects.append(text)

    # --- NCX nav block ---
    ncx_nav = tree.find(".//nav[@data-source='ncx']")
    if ncx_nav is not None:
        # docTitle
        doctitle_el = ncx_nav.find(".//*[@data-ncx='doctitle']")
        if doctitle_el is not None:
            doc.ncx_doctitle = _text_content(doctitle_el)

        # nav labels
        for li in ncx_nav.iter("li"):
            nav_id = li.get("data-ncx-id")
            if nav_id:
                doc.nav_labels[nav_id] = _text_content(li)

    # --- Spine sections ---
    for section in tree.iter("section"):
        href = section.get("data-source-href")
        if href:
            # Extract the body content (everything except the section-meta header)
            body_html = _extract_section_body(section)
            doc.sections[href] = body_html

    return doc


def _text_content(el: etree._Element) -> str:
    """Return all text content of an element, whitespace-normalised."""
    text = "".join(str(t) for t in el.itertext())
    return " ".join(text.split())


def _extract_section_body(section: etree._Element) -> str:
    """Extract translatable body content from a <section data-source-href>.

    Excludes the <header data-section-meta="true"> wrapper (which contains
    the per-chapter title injected by builder for translator context) and
    returns the remaining inner HTML.
    """
    parts: list[str] = []
    for child in section:
        # Skip the injected section-meta header
        if child.get("data-section-meta") == "true":
            continue
        parts.append(etree.tostring(child, method="html", encoding="unicode", with_tail=True))
    # Also include text before first child if present
    if section.text and section.text.strip():
        parts.insert(0, section.text)
    return "".join(parts)
