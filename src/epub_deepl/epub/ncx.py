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

from epub_deepl.epub._safe_parser import parse_html_document, parse_xml
from epub_deepl.epub.model import Epub, NavPoint, Ncx
from epub_deepl.errors import InternalError, MissingNcx

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
    joined = ', "\'", '.join(f"'{p}'" for p in parts)
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


def resolve_anchor_label(
    src: str,
    base_href_in_zip: str,
    opf_dir: str,
    epub: Epub,
) -> str | None:
    """Resolve a content anchor (NCX navPoint or nav-doc <a>) to a label.

    Shared by NCX label resolution (`resolve_label`) and the EPUB 3 nav
    document resolver (`epub.nav.resolve_nav_labels`) — both structures
    reference content the same way: a path, optionally with a "#fragment",
    relative to the referencing file's own directory.

    Path-normalization fix: resolution happens in *absolute* URL-path space
    (base directory prefixed with "/") rather than relative space. This
    matters when opf_dir is "" (OPF at ZIP root) and the NCX/nav doc lives in
    a subdirectory — resolving in relative space made `urljoin` produce a
    relative result that could never satisfy an absolute `opf_root` prefix
    check, causing every such entry to spuriously raise as an "escape".
    Working in absolute space and checking the joined result's leading "/"
    is both necessary and sufficient: `urljoin` already collapses ".."
    segments, and a genuine escape above the ZIP root is the one case where
    it drops the leading "/" instead of resolving further upward.

    Percent-decoding happens *before* `urljoin`, not after: `urljoin` only
    collapses literal ".."/"." segments per RFC 3986 dot-segment removal —
    a percent-encoded segment such as "%2e%2e" is opaque to it and rides
    through unresolved, only becoming a real ".." once decoded. Decoding
    afterward (the historical bug here) let an encoded ".." pass both the
    ZIP-root and OPF-root escape checks below, then decode into a genuine
    escape once nothing was left to catch it.

    An empty path component (a bare "#fragment" or a fully empty src) is
    resolved to `base_href_in_zip` itself, matching standard URL fragment
    semantics ("this same document") rather than the document's containing
    directory.

    Args:
        src: raw content src/href, e.g. "ch01.xhtml#heading-3"
        base_href_in_zip: full ZIP path of the referencing NCX or nav
            document, e.g. "OEBPS/toc.ncx"
        opf_dir: OPF directory in ZIP, e.g. "OEBPS" (may be "")
        epub: the full EPUB model (xhtmls keyed by OPF-relative href)

    Returns:
        Whitespace-normalised label text, or None if the fragment is absent
        from the target XHTML and no heading fallback is available (or the
        target could not be parsed) — callers fall back to their own label.

    Raises:
        InternalError: src resolves outside the ZIP root, or to a file that
            is not a spine XHTML entry known to `epub.xhtmls`.
    """
    fragment: str | None
    if "#" in src:
        path_part, _, frag = src.partition("#")
        fragment = frag or None
    else:
        path_part, fragment = src, None

    if path_part:
        base_dir = posixpath.dirname(base_href_in_zip)
        base_dir_url = f"/{base_dir}/" if base_dir else "/"
        joined = urljoin(base_dir_url, unquote(path_part))
        if not joined.startswith("/"):
            raise InternalError(f"Anchor src escapes ZIP root: {src!r}")
        # Second, independent pass: collapse any "." / ".." segments left
        # over from the join, and refuse to proceed if any ".." survives —
        # defense in depth for the containment check below, which is a raw
        # string-prefix test and must never see a path that could still
        # traverse via a residual dot-segment.
        normalized = posixpath.normpath(joined)
        if any(segment == ".." for segment in normalized.split("/")):
            raise InternalError(f"Anchor src escapes ZIP root: {src!r}")
        target_zip_path = normalized.lstrip("/")
    else:
        target_zip_path = base_href_in_zip

    opf_root = f"{opf_dir.rstrip('/')}/" if opf_dir else ""
    if opf_root and not target_zip_path.startswith(opf_root):
        raise InternalError(f"Anchor src escapes OPF root: {target_zip_path!r}")
    target_href = target_zip_path[len(opf_root) :] if opf_root else target_zip_path

    xhtml = epub.xhtmls.get(target_href)
    if xhtml is None:
        raise InternalError(f"Anchor points to non-manifest file: {target_href!r}")

    # Parse the (already-updated) XHTML bytes
    try:
        tree = parse_html_document(xhtml.raw_bytes)
    except Exception:
        return None

    if fragment:
        nodes = tree.xpath(f"//*[@id={xpath_literal(fragment)}]")
        if not nodes:
            # Fragment missing in translated XHTML — try heading fallback
            heading = _first_heading(tree)
            if heading is not None:
                return normalize_whitespace(_text_content(heading))
            return None
        assert isinstance(nodes[0], etree._Element)
        target_el: etree._Element = nodes[0]
    else:
        target_el_or_none = _first_heading(tree)
        if target_el_or_none is None:
            return None
        target_el = target_el_or_none

    return normalize_whitespace(_text_content(target_el))


def resolve_label(
    nav_point: NavPoint,
    ncx_href_in_zip: str,
    opf_dir: str,
    epub: Epub,
    flat_labels: dict[str, str],
) -> str:
    """Compute the <navLabel> text for a navPoint from the translated XHTML.

    Thin wrapper over `resolve_anchor_label`; falls back to the merged-HTML
    translated label whenever anchor resolution can't produce a better one.

    Args:
        nav_point: the NavPoint whose label needs computing
        ncx_href_in_zip: full ZIP path to the NCX, e.g. "OEBPS/toc.ncx"
        opf_dir: OPF directory in ZIP, e.g. "OEBPS"
        epub: the full EPUB model (xhtmls keyed by OPF-relative href)
        flat_labels: fallback dict of nav_id → translated label text from merged HTML

    Returns:
        Whitespace-normalised text for the navLabel.
    """
    result = resolve_anchor_label(nav_point.src, ncx_href_in_zip, opf_dir, epub)
    return result if result is not None else flat_labels.get(nav_point.nav_id, nav_point.label)
