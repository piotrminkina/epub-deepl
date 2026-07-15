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

from epub_deepl.epub._safe_parser import parse_html_document
from epub_deepl.epub._svg_case import restore_svg_attribute_case
from epub_deepl.errors import TranslatedHtmlMismatch, UserError
from epub_deepl.logging_setup import get_logger

_log = get_logger("restore.parser")


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
    #: Advisory ``<body data-part="N" data-parts-total="M">`` markers from a
    #: split payload (see ``merge/builder.py:build_split``). ``None`` when
    #: absent or unparseable as an int — never a hard failure, since the
    #: real completeness gate is ``validate_translated_html``'s section-vs-
    #: spine set equality, not these markers.
    part_index: int | None = None
    parts_total: int | None = None


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

    # --- Part markers (advisory; <body data-part="N" data-parts-total="M">) ---
    body_el = tree.find(".//body")
    if body_el is not None:
        doc.part_index = _parse_marker_int(body_el, "data-part")
        doc.parts_total = _parse_marker_int(body_el, "data-parts-total")

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


def _parse_marker_int(el: etree._Element, attr: str) -> int | None:
    """Tolerant int parse of a `<body>` marker attribute; absent/garbage → None."""
    raw = el.get(attr)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return None


def merge_translated_docs(docs: list[tuple[str, TranslatedDoc]]) -> TranslatedDoc:
    """Merge `(path, TranslatedDoc)` pairs from a split payload's parts.

    A single doc passes through unchanged and silent — this is the common
    case when the payload was not split. With multiple docs:

    - Sections are unioned across parts; the same ``data-source-href``
      appearing in two parts raises ``TranslatedHtmlMismatch`` naming the
      href and both file paths, since we cannot tell which copy is
      authoritative.
    - The metadata trio (titles/descriptions/subjects) and the NCX block
      (``ncx_doctitle`` + ``nav_labels``) normally live in part 1 only:
      whichever doc is first (in the given order) to carry non-empty
      content for a given field wins wholesale; any other doc with
      non-empty content for that same field is logged as an extra carrier
      (WARN), not merged in.
    - ``html_lang``: the first non-``None`` value wins; a later doc
      disagreeing is WARNed ("pass --lang" to override explicitly).
    - Part markers (``part_index``/``parts_total``) are advisory only:
      disagreeing totals, a total that doesn't match the number of files
      given, or gaps in the part-index sequence are all WARNed, never
      raised. The real completeness gate is the section-vs-spine set
      equality check in ``validator.validate_translated_html``.

    Raises:
        TranslatedHtmlMismatch: the same section href appears in more than
            one part.
    """
    if len(docs) == 1:
        # A lone file can still carry a data-parts-total that disagrees
        # with "1 file given" -- the single most likely real user mistake
        # (forgetting a part). The check itself is silent when no markers
        # are present at all, so this costs nothing in the common case.
        _check_part_markers(docs)
        return docs[0][1]

    merged = TranslatedDoc()
    section_sources: dict[str, str] = {}  # href → path, for the mismatch message
    titles_carrier: str | None = None
    descriptions_carrier: str | None = None
    subjects_carrier: str | None = None
    ncx_carrier: str | None = None
    lang_carrier: str | None = None

    for path, doc in docs:
        for href, body in doc.sections.items():
            if href in section_sources:
                raise TranslatedHtmlMismatch(
                    f"Section {href!r} appears in more than one translated part: "
                    f"{section_sources[href]!r} and {path!r}"
                )
            section_sources[href] = path
            merged.sections[href] = body

        if doc.titles:
            if titles_carrier is None:
                merged.titles = doc.titles
                titles_carrier = path
            else:
                _log.warning(
                    "titles also present in %r (already carried by %r); ignoring the extra copy",
                    path,
                    titles_carrier,
                )
        if doc.descriptions:
            if descriptions_carrier is None:
                merged.descriptions = doc.descriptions
                descriptions_carrier = path
            else:
                _log.warning(
                    "descriptions also present in %r (already carried by %r); "
                    "ignoring the extra copy",
                    path,
                    descriptions_carrier,
                )
        if doc.subjects:
            if subjects_carrier is None:
                merged.subjects = doc.subjects
                subjects_carrier = path
            else:
                _log.warning(
                    "subjects also present in %r (already carried by %r); ignoring the extra copy",
                    path,
                    subjects_carrier,
                )
        if doc.ncx_doctitle or doc.nav_labels:
            if ncx_carrier is None:
                merged.ncx_doctitle = doc.ncx_doctitle
                merged.nav_labels = doc.nav_labels
                ncx_carrier = path
            else:
                _log.warning(
                    "NCX nav block also present in %r (already carried by %r); "
                    "ignoring the extra copy",
                    path,
                    ncx_carrier,
                )
        if doc.html_lang is not None:
            if lang_carrier is None:
                merged.html_lang = doc.html_lang
                lang_carrier = path
            elif doc.html_lang != merged.html_lang:
                _log.warning(
                    "conflicting <html lang> across parts: %r (from %r) vs %r (from %r); "
                    "pass --lang explicitly to override",
                    merged.html_lang,
                    lang_carrier,
                    doc.html_lang,
                    path,
                )

    _check_part_markers(docs)
    return merged


def _check_part_markers(docs: list[tuple[str, TranslatedDoc]]) -> None:
    """Advisory sanity check on part_index/parts_total markers; WARN only, never raise."""
    present = [(path, doc.part_index, doc.parts_total) for path, doc in docs]
    present = [m for m in present if m[1] is not None or m[2] is not None]
    if not present:
        return  # markers absent from every part — silent, nothing to check

    totals = {total for _, _, total in present if total is not None}
    if len(totals) > 1:
        _log.warning("data-parts-total disagrees across files: %s", sorted(totals))
    elif totals:
        (total,) = totals
        if total != len(docs):
            _log.warning(
                "data-parts-total=%d but %d file(s) were given to restore", total, len(docs)
            )

    indices = sorted(idx for _, idx, _ in present if idx is not None)
    if indices and indices != list(range(1, len(indices) + 1)):
        _log.warning("data-part indices are not a contiguous 1..N sequence: %s", indices)


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
