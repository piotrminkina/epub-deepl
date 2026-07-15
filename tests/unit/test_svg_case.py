"""Unit tests for SVG / MathML attribute-case restoration (US-022, FR-6).

``restore_svg_attribute_case`` undoes the unconditional attribute-name
lowercasing performed by lxml's HTML parser, but only inside ``<svg>`` /
``<math>`` subtrees — plain HTML attributes are correctly lowercase and
must never be touched.

The assertions pin the *contract* (representative spec-mandated names,
subtree scoping, idempotence, the real HTML-parser round-trip), not the
full internal mapping table, so they survive a reimplementation that
derives the names from a different source.
"""

from __future__ import annotations

import pytest
from lxml import etree

from epub_deepl.epub._safe_parser import parse_html_document
from epub_deepl.epub._svg_case import restore_svg_attribute_case


@pytest.mark.unit
def test_renames_lowercased_attrs_on_svg_root() -> None:
    tree = etree.fromstring('<svg viewbox="0 0 10 10" preserveaspectratio="xMidYMid meet"/>')

    restore_svg_attribute_case(tree)

    assert tree.get("viewBox") == "0 0 10 10"
    assert tree.get("preserveAspectRatio") == "xMidYMid meet"
    assert "viewbox" not in tree.attrib
    assert "preserveaspectratio" not in tree.attrib


@pytest.mark.unit
def test_renames_attrs_on_svg_descendants() -> None:
    """The rename applies to the whole subtree, not just the <svg> root."""
    tree = etree.fromstring(
        '<svg><defs><animate attributename="offset" repeatcount="2"/></defs></svg>'
    )

    restore_svg_attribute_case(tree)

    animate = tree.find(".//animate")
    assert animate is not None
    assert animate.get("attributeName") == "offset"
    assert animate.get("repeatCount") == "2"


@pytest.mark.unit
def test_math_subtree_is_in_scope() -> None:
    """<math> is a scoping root just like <svg>."""
    tree = etree.fromstring('<math><mrow attributename="x"/></math>')

    restore_svg_attribute_case(tree)

    mrow = tree.find(".//mrow")
    assert mrow is not None
    assert mrow.get("attributeName") == "x"


@pytest.mark.unit
def test_namespaced_svg_element_is_in_scope() -> None:
    """Scoping matches on local name, so a namespaced <svg> counts."""
    tree = etree.fromstring('<svg xmlns="http://www.w3.org/2000/svg" viewbox="0 0 4 4"/>')

    restore_svg_attribute_case(tree)

    assert tree.get("viewBox") == "0 0 4 4"


@pytest.mark.unit
def test_plain_html_attributes_outside_svg_untouched() -> None:
    """A name colliding with the SVG enumeration on a plain HTML element
    (outside any <svg>/<math> subtree) must stay lowercase."""
    tree = etree.fromstring('<div viewbox="0 0 1 1"><p preserveaspectratio="x">t</p></div>')

    restore_svg_attribute_case(tree)

    assert tree.get("viewbox") == "0 0 1 1"
    assert "viewBox" not in tree.attrib
    p = tree.find(".//p")
    assert p is not None
    assert p.get("preserveaspectratio") == "x"


@pytest.mark.unit
def test_non_case_sensitive_attrs_inside_svg_untouched() -> None:
    tree = etree.fromstring('<svg width="10" class="figure" data-x="1"/>')

    restore_svg_attribute_case(tree)

    assert dict(tree.attrib) == {"width": "10", "class": "figure", "data-x": "1"}


@pytest.mark.unit
def test_correct_case_input_is_unchanged_and_idempotent() -> None:
    tree = etree.fromstring('<svg viewBox="0 0 10 10"/>')

    restore_svg_attribute_case(tree)
    restore_svg_attribute_case(tree)

    assert dict(tree.attrib) == {"viewBox": "0 0 10 10"}


@pytest.mark.unit
def test_html_parser_lowercasing_is_undone_end_to_end() -> None:
    """The production pipeline pairing: parse with the (lowercasing) HTML
    parser used for translated content, then restore attribute case."""
    html = (
        '<html><body><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        'preserveAspectRatio="xMidYMid meet"><rect width="100" height="100"/></svg>'
        "</body></html>"
    )
    tree = parse_html_document(html.encode("utf-8"))
    svg = tree.find(".//svg")
    assert svg is not None
    # Premise guard: the HTML parser really does lowercase. If a future
    # lxml/libxml2 stops doing so, this test documents that the module
    # became a no-op rather than silently passing.
    assert "viewbox" in svg.attrib

    restore_svg_attribute_case(tree)

    assert svg.get("viewBox") == "0 0 100 100"
    assert svg.get("preserveAspectRatio") == "xMidYMid meet"
