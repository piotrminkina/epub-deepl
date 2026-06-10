"""XHTML body extraction and replacement.

Each source XHTML file is stored as raw bytes for round-trip fidelity.
Body content is extracted as an HTML5 string for merging into the
translation payload, then replaced with translated content on restore.
"""

from __future__ import annotations

from lxml import etree

from epub_deepl_prepare.epub._safe_parser import (
    parse_html_document,
    parse_xml_recover,
)
from epub_deepl_prepare.epub._svg_case import restore_svg_attribute_case

_MATHML_NS = "http://www.w3.org/1998/Math/MathML"


def extract_body_html(xhtml_bytes: bytes) -> str:
    """Extract the inner HTML of <body> from an XHTML file.

    Returns the serialised inner content of <body> as an HTML5 string.
    MathML elements receive translate="no" before extraction.
    """
    # Use recover parser: real-world EPUBs sometimes have minor XML issues
    try:
        tree = parse_xml_recover(xhtml_bytes)
    except etree.XMLSyntaxError:
        # Last resort: parse as HTML
        html_tree = parse_html_document(xhtml_bytes)
        body = html_tree.find(".//body")
        if body is None:
            return ""
        return _inner_html(body)

    # Find body — handle both namespaced and non-namespaced
    body = _find_body(tree)
    if body is None:
        return ""

    # Mark MathML elements as translate="no" (US-011)
    _mark_mathml(body)

    return _inner_html(body)


def _find_body(root: etree._Element) -> etree._Element | None:
    """Find <body> in an lxml element tree, handling XHTML namespaces."""
    # Try common XHTML namespace
    _XHTML_NS = "http://www.w3.org/1999/xhtml"
    body = root.find(f"{{{_XHTML_NS}}}body")
    if body is not None:
        return body
    body = root.find(".//body")
    if body is not None:
        return body
    # root itself might be html — look for body as direct child
    for child in root:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag.endswith("body") or tag == "body":
            return child
    return None


def _mark_mathml(element: etree._Element) -> None:
    """Add translate="no" to every MathML element recursively."""
    for el in element.iter():
        tag = el.tag
        if isinstance(tag, str) and tag.startswith(f"{{{_MATHML_NS}}}"):
            el.set("translate", "no")


def _inner_html(element: etree._Element) -> str:
    """Return the inner content of an element as a serialised HTML string.

    Includes all children and their text; excludes the element's own tags.
    """
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        parts.append(etree.tostring(child, method="html", encoding="unicode", with_tail=True))
    return "".join(parts)


def replace_body_content(original_xhtml_bytes: bytes, new_body_html: str) -> bytes:
    """Replace the <body> content of an XHTML file with new HTML.

    Preserves:
    - Original DOCTYPE
    - Root element (html) and its attributes
    - Head element and all its children
    - Body element and its attributes (class, id, etc.)
    - XML declaration

    Returns serialised XHTML bytes.
    """
    try:
        tree = parse_xml_recover(original_xhtml_bytes)
    except etree.XMLSyntaxError:
        # Fall back to HTML parsing for badly-formed XHTML
        tree = parse_html_document(original_xhtml_bytes)

    body = _find_body(tree)
    if body is None:
        # No body — return original unchanged
        return original_xhtml_bytes

    # Clear existing body children and text
    body.text = None
    for child in list(body):
        body.remove(child)

    # Parse the new body content as an HTML fragment. The HTML parser is
    # used (not XML) because translated content may contain HTML5 named
    # entities (`&copy;`, `&times;`) and unclosed void elements that the
    # XML parser rejects. Then `_restore_svg_attribute_case` re-applies
    # SVG / MathML camelCase attribute names — see restore.parser.
    if new_body_html.strip():
        wrapper_html = f"<div>{new_body_html}</div>"
        wrapper_bytes = wrapper_html.encode("utf-8")
        html_wrapper = parse_html_document(wrapper_bytes)
        restore_svg_attribute_case(html_wrapper)
        div = html_wrapper.find(".//div")
        if div is None:
            div = html_wrapper

        if div is not None:
            body.text = div.text
            for child in list(div):
                body.append(child)

    # Re-serialise as XML (XHTML 1.1 style) to preserve declarations
    result = etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        method="xml",
        pretty_print=False,
    )
    return result


def count_ruby_elements(xhtml_bytes: bytes) -> int:
    """Return the number of <ruby> elements in an XHTML file."""
    try:
        tree = parse_xml_recover(xhtml_bytes)
    except etree.XMLSyntaxError:
        try:
            tree = parse_html_document(xhtml_bytes)
        except Exception:
            return 0

    count = 0
    for el in tree.iter():
        tag = el.tag
        if isinstance(tag, str) and (tag == "ruby" or tag.endswith("}ruby")):
            count += 1
    return count
