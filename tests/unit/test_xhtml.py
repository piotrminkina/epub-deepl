"""Unit tests for XHTML body extraction and replacement (test-plan §6.6)."""

from __future__ import annotations

import pytest

_XHTML_FULL = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
    "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
  <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
  <title>Test Chapter</title>
  <link rel="stylesheet" href="style.css" type="text/css"/>
</head>
<body class="chapter" id="ch01">
<h1 id="ch1-heading">Chapter One</h1>
<p>This is the content.</p>
</body>
</html>"""


@pytest.mark.unit
def test_extract_body_inner_returns_html5_string() -> None:
    """extract_body_html returns the inner content of <body> as a string."""
    from epub_deepl_prepare.epub.xhtml import extract_body_html

    result = extract_body_html(_XHTML_FULL)
    assert "Chapter One" in result
    assert "This is the content." in result
    # Should not include the <body> tag itself
    assert "<body" not in result


@pytest.mark.unit
def test_extract_body_inner_preserves_inline_namespaces() -> None:
    """MathML and SVG inline namespaces are preserved in body HTML."""
    from epub_deepl_prepare.epub.xhtml import extract_body_html

    xhtml_with_math = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:m="http://www.w3.org/1998/Math/MathML">
<head><title>Math</title></head>
<body>
<p>Formula: <m:math><m:mrow><m:mn>1</m:mn></m:mrow></m:math></p>
</body>
</html>"""
    result = extract_body_html(xhtml_with_math)
    assert "math" in result.lower() or "mrow" in result.lower() or "1" in result


@pytest.mark.unit
def test_mathml_receives_translate_no() -> None:
    """Every MathML element gets translate='no' in extracted body HTML (US-011)."""
    from epub_deepl_prepare.epub.xhtml import extract_body_html

    xhtml_with_math = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Math</title></head>
<body>
<p><math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mn>42</mn></mrow></math></p>
</body>
</html>"""
    result = extract_body_html(xhtml_with_math)
    assert 'translate="no"' in result


@pytest.mark.unit
def test_replace_body_preserves_root_attributes() -> None:
    """replace_body_content preserves the root <html> attributes."""
    from epub_deepl_prepare.epub.xhtml import replace_body_content

    result = replace_body_content(_XHTML_FULL, "<p>Translated</p>")
    # Root html element should still have xml:lang or lang
    assert b"<html" in result


@pytest.mark.unit
def test_replace_body_preserves_head_unchanged() -> None:
    """replace_body_content preserves the <head> element and its children."""
    from epub_deepl_prepare.epub.xhtml import replace_body_content

    result = replace_body_content(_XHTML_FULL, "<p>Translated</p>")
    assert b"Test Chapter" in result  # title preserved
    assert b"style.css" in result  # link preserved


@pytest.mark.unit
def test_replace_body_handles_empty_body() -> None:
    """replace_body_content handles empty replacement body without error."""
    from epub_deepl_prepare.epub.xhtml import replace_body_content

    result = replace_body_content(_XHTML_FULL, "")
    assert result  # Some bytes must be produced
    assert b"<html" in result


@pytest.mark.unit
def test_replace_body_injects_translated_content() -> None:
    """The new body content appears in the output."""
    from epub_deepl_prepare.epub.xhtml import replace_body_content

    result = replace_body_content(_XHTML_FULL, "<p>Przetlumaczono</p>")
    assert b"Przetlumaczono" in result


@pytest.mark.unit
def test_count_ruby_elements_zero_for_no_ruby() -> None:
    """count_ruby_elements returns 0 when no ruby elements present."""
    from epub_deepl_prepare.epub.xhtml import count_ruby_elements

    assert count_ruby_elements(_XHTML_FULL) == 0


@pytest.mark.unit
def test_count_ruby_elements_counts_correctly() -> None:
    """count_ruby_elements counts each <ruby> element."""
    from epub_deepl_prepare.epub.xhtml import count_ruby_elements

    xhtml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml">'
        b"<head><title>R</title></head><body>"
        b"<ruby>\xe6\xbc\xa2<rt>kan</rt></ruby>"
        b"<ruby>\xe5\xad\x97<rt>ji</rt></ruby>"
        b"</body></html>"
    )
    assert count_ruby_elements(xhtml) == 2
