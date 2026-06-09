"""Build the merged HTML5 payload from an Epub model.

The merged HTML is the translation payload sent to DeepL.
Structure mirrors tech-spec §4.3.

NCX nav block is flattened into a single <ol> with data-ncx-depth to
preserve hierarchy information without requiring DeepL to handle nesting.
"""

from __future__ import annotations

import html

from epub_translation_prepare.epub._safe_parser import parse_xml_recover
from epub_translation_prepare.epub.model import Epub, NavPoint
from epub_translation_prepare.epub.xhtml import count_ruby_elements
from epub_translation_prepare.logging_setup import get_logger

_log = get_logger("merge.builder")

# XHTML namespace for title extraction
_XHTML_NS = "http://www.w3.org/1999/xhtml"


def build(epub: Epub) -> str:
    """Produce the merged HTML5 string from the Epub model.

    Returns a complete HTML5 document as a string.
    """
    meta = epub.metadata
    source_lang = meta.language or "und"
    title = html.escape(meta.titles[0] if meta.titles else "")
    description = html.escape(meta.descriptions[0] if meta.descriptions else "")

    parts: list[str] = []
    parts.append("<!DOCTYPE html>\n")
    parts.append(f'<html lang="{html.escape(source_lang)}">\n')
    parts.append("<head>\n")
    parts.append('<meta charset="utf-8">\n')
    parts.append(f"<title>{title}</title>\n")
    if meta.descriptions:
        parts.append(f'<meta name="description" content="{description}">\n')
    parts.append("</head>\n")
    parts.append("<body>\n")

    # OPF metadata block
    parts.append('<header data-source="opf-metadata">\n')
    if meta.titles:
        parts.append(f'<h1 data-dc="title">{html.escape(meta.titles[0])}</h1>\n')
        for i, extra_title in enumerate(meta.titles[1:], start=1):
            parts.append(
                f'<h2 data-dc="title" data-dc-index="{i}">'
                f"{html.escape(extra_title)}</h2>\n"
            )
    for desc in meta.descriptions:
        parts.append(f'<p data-dc="description">{html.escape(desc)}</p>\n')
    for subj in meta.subjects:
        parts.append(f'<span data-dc="subject">{html.escape(subj)}</span>\n')
    parts.append("</header>\n")

    # NCX nav block
    if epub.ncx is not None:
        parts.append('<nav data-source="ncx">\n')
        doc_title = html.escape(epub.ncx.doc_title)
        parts.append(f'<h2 data-ncx="doctitle">{doc_title}</h2>\n')
        parts.append("<ol>\n")
        _flatten_nav_map(epub.ncx.nav_map, parts, depth=0)
        parts.append("</ol>\n")
        parts.append("</nav>\n")

    # XHTML spine sections
    for idx, spine_ref in enumerate(epub.spine.items):
        item = epub.manifest.get(spine_ref.idref)
        if item is None:
            continue
        href = item.href
        xhtml_file = epub.xhtmls.get(href)
        if xhtml_file is None:
            continue

        # Extract per-file title for translator context
        xhtml_title = _extract_xhtml_title(xhtml_file.raw_bytes)

        parts.append(
            f'<section data-source-href="{html.escape(href)}" '
            f'data-spine-idx="{idx}">\n'
        )
        parts.append('<header data-section-meta="true">\n')
        if xhtml_title:
            parts.append(
                f'<h1 data-xhtml-title="true">{html.escape(xhtml_title)}</h1>\n'
            )
        parts.append("</header>\n")
        parts.append(xhtml_file.body_html)
        parts.append("\n</section>\n")

    parts.append("</body>\n")
    parts.append("</html>\n")

    return "".join(parts)


def _flatten_nav_map(
    nav_points: list[NavPoint],
    parts: list[str],
    depth: int,
) -> None:
    """Recursively flatten navPoints into <li> entries with data-ncx-depth."""
    for np in nav_points:
        parts.append(
            f'<li data-ncx-id="{html.escape(np.nav_id)}" '
            f'data-ncx-playorder="{np.play_order}" '
            f'data-ncx-src="{html.escape(np.src)}" '
            f'data-ncx-depth="{depth}">'
            f"{html.escape(np.label)}"
            f"</li>\n"
        )
        if np.children:
            _flatten_nav_map(np.children, parts, depth + 1)


def _extract_xhtml_title(xhtml_bytes: bytes) -> str:
    """Extract the <title> text from an XHTML file's <head>."""
    try:
        tree = parse_xml_recover(xhtml_bytes)
        _XHTML = f"{{{_XHTML_NS}}}"

        # Try namespaced first
        title_el = tree.find(f"{_XHTML}head/{_XHTML}title")
        if title_el is None:
            title_el = tree.find(".//title")
        if title_el is not None and title_el.text:
            return title_el.text.strip()
    except Exception:
        pass
    return ""


def count_ruby(epub: Epub) -> int:
    """Return total number of <ruby> elements across all spine XHTML files."""
    total = 0
    for xhtml_file in epub.xhtmls.values():
        total += count_ruby_elements(xhtml_file.raw_bytes)
    return total
