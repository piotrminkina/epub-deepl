"""Centralised safe lxml parser factory.

ALL parser constructions in this codebase MUST use functions from this module.
No other module may call lxml.etree.XMLParser() or lxml.html.HTMLParser()
directly — this is enforced by tests/unit/test_safe_parser.py which greps
source files for bare parser instantiation.

Security rationale (from tech-spec §10):
  - resolve_entities=False: blocks XXE and billion-laughs entity expansion
  - load_dtd=False: blocks DTD retrieval DoS
  - no_network=True: blocks any URL fetch triggered by parser
  - huge_tree=False: limits tree depth to prevent stack-overflow attacks
  - recover=False for XML: strict parsing; malformed input raises ParseError
"""

from lxml import etree, html


def xml_parser() -> etree.XMLParser:
    """Return a safe XMLParser for OPF, NCX, and XHTML source files."""
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=False,
        recover=False,
    )


def xml_parser_recover() -> etree.XMLParser:
    """Return a safe XMLParser with recover=True for lenient XHTML parsing."""
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=False,
        recover=True,
    )


def html_parser() -> html.HtmlMixin:
    """Return a safe HTMLParser for translated HTML5 documents.

    lxml.html.HTMLParser accepts only a subset of the kwargs that XMLParser does —
    in particular it does NOT accept resolve_entities, no_network, or load_dtd.
    HTML5 parsers use a tag-soup algorithm that never loads external entities or
    DTDs, so these security flags are redundant; huge_tree is the only relevant
    guard to keep.
    """
    return html.HTMLParser(huge_tree=False)  # type: ignore[return-value]


def parse_xml(data: bytes) -> etree._Element:
    """Parse bytes as XML with safe parser; raise etree.XMLSyntaxError on failure."""
    return etree.fromstring(data, parser=xml_parser())


def parse_xml_recover(data: bytes) -> etree._Element:
    """Parse bytes as XML with safe lenient parser (for XHTML content)."""
    return etree.fromstring(data, parser=xml_parser_recover())


def parse_html_document(data: bytes) -> html.HtmlElement:
    """Parse bytes as HTML5 document with safe HTMLParser."""
    return html.document_fromstring(data, parser=html_parser())  # type: ignore[arg-type]
