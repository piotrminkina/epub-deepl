"""NCX parsing and serialisation.

Strategy for C-2 (byte-level preservation):
  NCX is restored by parsing the original raw_xml bytes, then replacing only
  <docTitle><text> and each <navLabel><text> in-place, preserving all other
  structure (navMap nesting, playOrder, content src, dtb:meta elements).
  Structural equality is tested via c14n2, not byte equality.
"""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urljoin

from lxml import etree

from epub_translation_prepare.epub._safe_parser import parse_html_document, parse_xml
from epub_translation_prepare.epub.model import Epub, NavPoint, Ncx
from epub_translation_prepare.errors import InternalError, MissingNcx

_NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
_NCX = f"{{{_NCX_NS}}}"


def _ncx(tag: str) -> str:
    return f"{_NCX}{tag}"


def _text_of(el: etree._Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _parse_nav_points(parent: etree._Element) -> list[NavPoint]:
    """Recursively parse <navPoint> elements under parent."""
    points: list[NavPoint] = []
    for child in parent:
        if child.tag not in (_ncx("navPoint"), "navPoint"):
            continue
        nav_id = child.get("id", "")
        play_order_str = child.get("playOrder", "0")
        try:
            play_order = int(play_order_str)
        except ValueError:
            play_order = 0

        label_el = child.find(_ncx("navLabel"))
        if label_el is None:
            label_el = child.find("navLabel")
        text_el = label_el.find(_ncx("text")) if label_el is not None else None
        if text_el is None and label_el is not None:
            text_el = label_el.find("text")
        label = _text_of(text_el)

        content_el = child.find(_ncx("content"))
        if content_el is None:
            content_el = child.find("content")
        src = content_el.get("src", "") if content_el is not None else ""

        children = _parse_nav_points(child)
        points.append(
            NavPoint(
                nav_id=nav_id,
                play_order=play_order,
                label=label,
                src=src,
                children=children,
            )
        )
    return points


def parse_ncx(ncx_bytes: bytes, ncx_href_in_zip: str) -> Ncx:
    """Parse raw NCX bytes into a Ncx model object."""
    try:
        tree = parse_xml(ncx_bytes)
    except etree.XMLSyntaxError as exc:
        raise MissingNcx(f"NCX malformed: {exc}") from exc

    # doc_title
    doc_title_el = tree.find(f".//{_ncx('docTitle')}/{_ncx('text')}")
    if doc_title_el is None:
        doc_title_el = tree.find(".//docTitle/text")
    doc_title = _text_of(doc_title_el)

    # navMap
    nav_map_el = tree.find(_ncx("navMap"))
    if nav_map_el is None:
        nav_map_el = tree.find("navMap")

    nav_map: list[NavPoint] = []
    if nav_map_el is not None:
        nav_map = _parse_nav_points(nav_map_el)

    return Ncx(
        doc_title=doc_title,
        nav_map=nav_map,
        raw_xml=ncx_bytes,
        ncx_href_in_zip=ncx_href_in_zip,
    )


def rebuild_ncx_bytes(
    ncx: Ncx,
    new_doc_title: str,
    new_labels: dict[str, str],  # nav_id → new label text
) -> bytes:
    """Return updated NCX bytes with docTitle and navLabel texts replaced.

    Only <text> element content is touched; all structural elements, attributes,
    dtb:meta, content src attrs, etc. are preserved via in-place lxml mutation.
    """
    try:
        tree = parse_xml(ncx.raw_xml)
    except etree.XMLSyntaxError as exc:
        raise InternalError(f"NCX raw_xml could not be re-parsed: {exc}") from exc

    # Update docTitle text
    doc_title_text_el = tree.find(f".//{_ncx('docTitle')}/{_ncx('text')}")
    if doc_title_text_el is None:
        doc_title_text_el = tree.find(".//docTitle/text")
    if doc_title_text_el is not None:
        doc_title_text_el.text = new_doc_title

    # Update each navLabel text
    for nav_point_el in tree.iter(_ncx("navPoint")):
        nav_id = nav_point_el.get("id", "")
        if nav_id in new_labels:
            label_el = nav_point_el.find(_ncx("navLabel"))
            if label_el is None:
                label_el = nav_point_el.find("navLabel")
            if label_el is not None:
                text_el = label_el.find(_ncx("text"))
                if text_el is None:
                    text_el = label_el.find("text")
                if text_el is not None:
                    text_el.text = new_labels[nav_id]

    # Also handle navPoints without namespace
    for nav_point_el in tree.iter("navPoint"):
        nav_id = nav_point_el.get("id", "")
        if nav_id in new_labels:
            label_el = nav_point_el.find("navLabel")
            if label_el is not None:
                text_el = label_el.find("text")
                if text_el is not None:
                    text_el.text = new_labels[nav_id]

    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    )


def xpath_literal(s: str) -> str:
    """Quote a string for safe embedding into an XPath 1.0 expression.

    XPath 1.0 has no escape syntax inside string literals, so any string
    containing both ' and " must be expressed via concat().
    Closes the injection / lookup-failure gap from C-3 / I-9 in devils-advocate.
    """
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    # Both quotes present: use XPath concat()
    parts = s.split("'")
    joined = ", \"'\", ".join(f"'{p}'" for p in parts)
    return f"concat({joined})"


def normalize_whitespace(s: str) -> str:
    """Collapse runs of whitespace to single spaces and strip ends."""
    return " ".join(s.split())


def _text_content(el: etree._Element) -> str:
    """Return all text content under element, concatenated."""
    return "".join(str(t) for t in el.itertext())


def _first_heading(tree: etree._Element) -> etree._Element | None:
    """Return the first h1, h2, or h3 in document order."""
    for tag in ("h1", "h2", "h3"):
        nodes = tree.xpath(f"//{tag}")
        if nodes:
            first = nodes[0]  # type: ignore[index]
            if isinstance(first, etree._Element):
                return first
    return None


def resolve_label(
    nav_point: NavPoint,
    ncx_href_in_zip: str,
    opf_dir: str,
    epub: Epub,
    flat_labels: dict[str, str],
) -> str:
    """Compute the <navLabel> text for a navPoint from the translated XHTML.

    C-3 fix: uses urllib.parse.urljoin + posixpath for URL-style resolution,
    anchored at the NCX file's own directory, NOT the OPF directory.

    Args:
        nav_point: the NavPoint whose label needs computing
        ncx_href_in_zip: full ZIP path to the NCX, e.g. "OEBPS/toc.ncx"
        opf_dir: OPF directory in ZIP, e.g. "OEBPS"
        epub: the full EPUB model (xhtmls keyed by OPF-relative href)
        flat_labels: fallback dict of nav_id → translated label text from merged HTML

    Returns:
        Whitespace-normalised text for the navLabel.
    """
    src = nav_point.src
    fragment: str | None
    if "#" in src:
        parts_split = src.split("#", 1)
        path_part, fragment = parts_split[0], parts_split[1] or None
    else:
        path_part, fragment = src, None

    # Resolve relative to NCX file's own directory (C-3 fix)
    ncx_dir_url = posixpath.dirname(ncx_href_in_zip) + "/"
    target_zip_path = unquote(urljoin(ncx_dir_url, path_part))

    # Security: reject paths escaping the OPF root
    opf_root = opf_dir.rstrip("/") + "/"
    if not target_zip_path.startswith(opf_root) and target_zip_path != opf_dir:
        raise InternalError(f"NCX src escapes OPF root: {target_zip_path!r}")

    # Re-express relative to OPF directory for xhtmls map lookup.
    # When opf_dir is "" (OPF at ZIP root) use "/" as the posixpath base so
    # that relpath("/titlepage.xhtml", "/") == "titlepage.xhtml" instead of
    # posixpath.relpath("/titlepage.xhtml", "") which uses cwd as the base and
    # produces a relative path full of "../" components.
    relpath_base = opf_dir if opf_dir else "/"
    target_href = posixpath.relpath(target_zip_path, relpath_base)

    xhtml = epub.xhtmls.get(target_href)
    if xhtml is None:
        raise InternalError(f"NCX points to non-manifest file: {target_href!r}")

    # Parse the (already-updated) XHTML bytes
    try:
        tree = parse_html_document(xhtml.raw_bytes)
    except Exception:
        return flat_labels.get(nav_point.nav_id, nav_point.label)

    if fragment:
        nodes = tree.xpath(f"//*[@id={xpath_literal(fragment)}]")
        if not nodes:
            # Fragment missing in translated XHTML — try heading fallback
            heading = _first_heading(tree)
            if heading is not None:
                return normalize_whitespace(_text_content(heading))
            return flat_labels.get(nav_point.nav_id, nav_point.label)
        assert isinstance(nodes[0], etree._Element)
        target_el: etree._Element = nodes[0]
    else:
        target_el_or_none = _first_heading(tree)
        if target_el_or_none is None:
            return flat_labels.get(nav_point.nav_id, nav_point.label)
        target_el = target_el_or_none

    return normalize_whitespace(_text_content(target_el))
