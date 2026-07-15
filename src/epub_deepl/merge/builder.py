"""Build the merged HTML5 payload from an Epub model.

The merged HTML is the translation payload sent to DeepL.
Structure mirrors tech-spec §4.3.

NCX nav block is flattened into a single <ol> with data-ncx-depth to
preserve hierarchy information without requiring DeepL to handle nesting.

`build()` extracts a `_PayloadPlan` from the Epub model, then renders it
into one document. `build_split()` packs the same plan's `_PayloadSection`s
across multiple payload documents when the single-document render exceeds
DeepL's per-document character limit — see docs/adr/0006 (auto-split).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from epub_deepl.epub._safe_parser import parse_xml_recover
from epub_deepl.epub.model import Epub, NavPoint
from epub_deepl.epub.nav import extract_nav_body_html
from epub_deepl.epub.xhtml import count_ruby_elements
from epub_deepl.errors import InternalError, OversizedSection
from epub_deepl.logging_setup import get_logger

_log = get_logger("merge.builder")

# XHTML namespace for title extraction
_XHTML_NS = "http://www.w3.org/1999/xhtml"

#: DeepL's document-translation limit is 1,000,000 chars; 900k leaves a
#: ~10% margin. See docs/adr/0006.
DEFAULT_MAX_CHARS = 900_000

#: Fixed budgetary allowance for the `data-part="N" data-parts-total="M"`
#: attribute text added to `<body>` once a document is split into more than
#: one part. Budgeting uses the *unmarked* envelope length (see
#: `_build_plan`'s `envelope_open`) plus this reserve, rather than the
#: actual marked length, because the marked length depends on the final
#: part count — which packing itself is still computing. 64 chars is
#: comfortably above the ~50 chars the marker text occupies even at
#: four-digit part counts.
_PART_MARKER_RESERVE = 64


@dataclass(frozen=True)
class _PayloadSection:
    """One fully-rendered `<section>` block, including its own open/close tags.

    Pre-rendering the whole section (rather than storing raw body HTML) lets
    a future packing step measure `len(html)` directly when distributing
    sections across multiple payload documents.
    """

    href: str
    html: str


@dataclass(frozen=True)
class _PayloadPlan:
    """Everything needed to render one or more translation-payload documents.

    `envelope_open`/`envelope_close` wrap every payload document.
    `preamble` (OPF metadata header + NCX nav block) belongs to the first
    document only. `sections` is the full ordered list — the non-spine
    EPUB 3 nav doc (if any) first, then spine sections in spine order —
    ready to be packed across one or more documents.

    `envelope_open` is always the unmarked (`part=None`) rendering — the
    one `_render_single` uses for the single-document case. `build_split`
    re-renders a marked envelope per part from `source_lang`/`title`/
    `description`/`has_description` instead of reusing `envelope_open`.
    """

    envelope_open: str
    preamble: str
    sections: list[_PayloadSection]
    envelope_close: str
    source_lang: str
    title: str
    description: str
    has_description: bool


def build(epub: Epub) -> str:
    """Produce the merged HTML5 string from the Epub model.

    Returns a complete HTML5 document as a string.
    """
    return _render_single(_build_plan(epub))


def _render_single(plan: _PayloadPlan) -> str:
    """Render `plan` into one complete HTML5 document holding every section."""
    parts = [plan.envelope_open, plan.preamble]
    parts.extend(section.html for section in plan.sections)
    parts.append(plan.envelope_close)
    return "".join(parts)


def build_split(epub: Epub, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split epub's translation payload across one or more documents.

    Packs whole `<section>` elements in spine order — never inside a
    section — so each returned document stays within `max_chars`
    characters. Returns a single-element list, byte-identical to
    `build(epub)`, when `max_chars <= 0`, the single-document render
    already fits, or there are no sections to pack (nothing to split).

    Raises:
        OversizedSection: one section alone exceeds the budget of a fresh
            part; raise --max-chars or split that chapter in the source.
        InternalError: a packed part still exceeds max_chars (packing bug).
    """
    plan = _build_plan(epub)
    single = _render_single(plan)
    if max_chars <= 0 or not plan.sections or len(single) <= max_chars:
        return [single]

    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    groups = _pack_sections(
        plan.sections,
        max_chars=max_chars,
        envelope_len=envelope_len,
        preamble_len=len(plan.preamble),
    )
    total = len(groups)

    rendered = [
        _render_part(plan, group, index=index, total=total)
        for index, group in enumerate(groups, start=1)
    ]

    for index, part_html in enumerate(rendered, start=1):
        if len(part_html) > max_chars:
            raise InternalError(
                f"packed part {index}/{total} is {len(part_html):,} chars, "
                f"which exceeds --max-chars {max_chars:,} (packing bug — "
                f"the {_PART_MARKER_RESERVE}-char marker reserve was insufficient)"
            )

    return rendered


def _pack_sections(
    sections: list[_PayloadSection],
    *,
    max_chars: int,
    envelope_len: int,
    preamble_len: int,
) -> list[list[_PayloadSection]]:
    """Greedily pack sections into budget-respecting groups, spine order preserved."""

    def budget(part_number: int) -> int:
        remaining = max_chars - envelope_len - _PART_MARKER_RESERVE
        if part_number == 1:
            remaining -= preamble_len
        return remaining

    groups: list[list[_PayloadSection]] = []
    current: list[_PayloadSection] = []
    current_len = 0

    for section in sections:
        part_number = len(groups) + 1
        sec_len = len(section.html)
        if current and current_len + sec_len > budget(part_number):
            groups.append(current)
            current = []
            current_len = 0
            part_number = len(groups) + 1

        fresh_part_budget = budget(part_number)
        if sec_len > fresh_part_budget:
            raise OversizedSection(
                f"section {section.href!r} is {sec_len:,} chars, exceeding the "
                f"per-part budget of {fresh_part_budget:,} chars at "
                f"--max-chars {max_chars:,}; raise --max-chars or split this "
                f"chapter in the source EPUB"
            )
        current.append(section)
        current_len += sec_len

    if current:
        groups.append(current)
    return groups


def _render_part(
    plan: _PayloadPlan,
    group: list[_PayloadSection],
    *,
    index: int,
    total: int,
) -> str:
    """Render one part of a split payload: envelope + (preamble if part 1) + sections."""
    part_marker = (index, total) if total >= 2 else None
    parts = [
        _body_open(
            plan.source_lang, plan.title, plan.description, plan.has_description, part_marker
        )
    ]
    if index == 1:
        parts.append(plan.preamble)
    parts.extend(section.html for section in group)
    parts.append(plan.envelope_close)
    return "".join(parts)


def _build_plan(epub: Epub) -> _PayloadPlan:
    """Extract everything `_render_single` needs from `epub` into a `_PayloadPlan`."""
    meta = epub.metadata
    source_lang = meta.language or "und"
    title = meta.titles[0] if meta.titles else ""
    has_description = bool(meta.descriptions)
    description = meta.descriptions[0] if meta.descriptions else ""

    return _PayloadPlan(
        envelope_open=_body_open(source_lang, title, description, has_description, part=None),
        preamble=_build_preamble(epub),
        sections=_build_sections(epub),
        envelope_close="</body>\n</html>\n",
        source_lang=source_lang,
        title=title,
        description=description,
        has_description=has_description,
    )


def _body_open(
    source_lang: str,
    title: str,
    description: str,
    has_description: bool,
    part: tuple[int, int] | None,
) -> str:
    """Render the `<!DOCTYPE html>`…`<body>` opening block for one payload document.

    `part` (`(index, total)`, 1-based) is reserved for a future multi-part
    split: when given, it stamps `data-part`/`data-parts-total` onto `<body>`.
    Today, `part` is always `None`, which reproduces the historical unmarked
    `<body>\\n`.
    """
    parts = [
        "<!DOCTYPE html>\n",
        f'<html lang="{html.escape(source_lang)}">\n',
        "<head>\n",
        '<meta charset="utf-8">\n',
        f"<title>{html.escape(title)}</title>\n",
    ]
    if has_description:
        parts.append(f'<meta name="description" content="{html.escape(description)}">\n')
    parts.append("</head>\n")
    if part is None:
        parts.append("<body>\n")
    else:
        index, total = part
        parts.append(f'<body data-part="{index}" data-parts-total="{total}">\n')
    return "".join(parts)


def _build_preamble(epub: Epub) -> str:
    """Render the OPF metadata header + NCX nav block (first-document-only)."""
    meta = epub.metadata
    parts: list[str] = []

    # OPF metadata block — the <header> shell is always emitted, even when
    # every dc:* list below is empty.
    parts.append('<header data-source="opf-metadata">\n')
    if meta.titles:
        parts.append(f'<h1 data-dc="title">{html.escape(meta.titles[0])}</h1>\n')
        for i, extra_title in enumerate(meta.titles[1:], start=1):
            parts.append(
                f'<h2 data-dc="title" data-dc-index="{i}">{html.escape(extra_title)}</h2>\n'
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

    return "".join(parts)


def _build_sections(epub: Epub) -> list[_PayloadSection]:
    """Return the ordered `_PayloadSection` list: non-spine nav doc first, then spine."""
    sections: list[_PayloadSection] = []

    # EPUB 3 nav document — non-spine only. An in-spine nav doc is annotated
    # in place inside the spine loop below instead (it already gets a
    # <section data-source-href="…" data-spine-idx="…"> there); emitting it
    # here too would send it to DeepL twice.
    if epub.nav_doc is not None and not epub.nav_doc.in_spine:
        sections.append(_render_nav_doc_section(epub.nav_doc.href, epub.nav_doc.raw_bytes))

    # XHTML spine sections
    for idx, spine_ref in enumerate(epub.spine.items):
        item = epub.manifest.get(spine_ref.idref)
        if item is None:
            continue
        href = item.href
        xhtml_file = epub.xhtmls.get(href)
        if xhtml_file is None:
            continue

        # An in-spine nav doc gets the same data-nav-doc marker and page-list
        # translate="no" treatment as its non-spine counterpart above, but
        # stays inline in spine order instead of a separate section — it is
        # restored via the same generic spine mechanism as any other chapter.
        is_in_spine_nav_doc = (
            epub.nav_doc is not None and epub.nav_doc.in_spine and epub.nav_doc.href == href
        )
        section_body = (
            extract_nav_body_html(xhtml_file.raw_bytes)
            if is_in_spine_nav_doc
            else xhtml_file.body_html
        )
        sections.append(
            _render_spine_section(
                href=href,
                idx=idx,
                is_nav_doc=is_in_spine_nav_doc,
                title=_extract_xhtml_title(xhtml_file.raw_bytes),
                body_html=section_body,
            )
        )

    return sections


def _render_nav_doc_section(href: str, raw_bytes: bytes) -> _PayloadSection:
    """Render the non-spine EPUB 3 nav document's own `<section>` block."""
    nav_title = _extract_xhtml_title(raw_bytes)
    parts = [f'<section data-source-href="{html.escape(href)}" data-nav-doc="true">\n']
    parts.append('<header data-section-meta="true">\n')
    if nav_title:
        parts.append(f'<h1 data-xhtml-title="true">{html.escape(nav_title)}</h1>\n')
    parts.append("</header>\n")
    parts.append(extract_nav_body_html(raw_bytes))
    parts.append("\n</section>\n")
    return _PayloadSection(href=href, html="".join(parts))


def _render_spine_section(
    *, href: str, idx: int, is_nav_doc: bool, title: str, body_html: str
) -> _PayloadSection:
    """Render one spine item's `<section>` block."""
    nav_doc_attr = ' data-nav-doc="true"' if is_nav_doc else ""
    parts = [
        f'<section data-source-href="{html.escape(href)}" data-spine-idx="{idx}"{nav_doc_attr}>\n',
        '<header data-section-meta="true">\n',
    ]
    if title:
        parts.append(f'<h1 data-xhtml-title="true">{html.escape(title)}</h1>\n')
    parts.append("</header>\n")
    parts.append(body_html)
    parts.append("\n</section>\n")
    return _PayloadSection(href=href, html="".join(parts))


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
