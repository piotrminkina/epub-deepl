"""Synthetic minimal EPUB factory for tests.

Produces a valid EPUB ZIP entirely in memory, parameterised by declarative
arguments. Defaults to EPUB 2.0 + NCX (the foundation of all unit and
synth-integration tests); `epub_version="3.0"` switches to EPUB 3.x
templates with an optional nav document (`nav.xhtml`).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import Any

_XHTML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
    "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
  <title>{title}</title>
</head>
<body>
{body}
</body>
</html>
"""

# EPUB 3 content documents: no http-equiv meta (epubcheck flags it as obsolete;
# the XML declaration above already asserts the UTF-8 encoding). The polyglot
# HTML5 doctype is spec-mandated for EPUB 3 content documents (epubcheck
# HTM-004 flags the legacy XHTML 1.1 DOCTYPE as "irregular" under EPUB 3
# rules, even though it's normal for EPUB 2 OPS documents).
_XHTML_TEMPLATE_EPUB3 = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head>
  <title>{title}</title>
</head>
<body>
{body}
</body>
</html>
"""

_OPF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<package version="{version}" xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="BookID">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
{metadata_elements}  </metadata>
  <manifest>
{manifest_items}  </manifest>
  <spine{spine_toc_attr}>
{spine_items}  </spine>
</package>
"""

# EPUB 3 requires a dcterms:modified meta (epubcheck-mandatory); dcterms is a
# pre-declared prefix in the EPUB 3 package vocabulary, no prefix= needed.
_OPF_TEMPLATE_EPUB3 = """\
<?xml version="1.0" encoding="UTF-8"?>
<package version="{version}" xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="BookID">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
{metadata_elements}    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
{manifest_items}  </manifest>
  <spine{spine_toc_attr}>
{spine_items}  </spine>
</package>
"""

_NCX_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
    "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:test-uuid"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{doc_title}</text></docTitle>
  <navMap>
{nav_points}  </navMap>
</ncx>
"""

# EPUB 3: NCX kept only for EPUB 2 reading-system backward compatibility, so
# its legacy DOCTYPE/DTD reference is dropped (epubcheck-clean without it).
# dtb:uid is a placeholder (not a literal, unlike EPUB 2's) — epubcheck's
# NCX-001 rule requires it to match the OPF's dc:identifier exactly.
_NCX_TEMPLATE_EPUB3 = """\
<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{dtb_uid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{doc_title}</text></docTitle>
  <navMap>
{nav_points}  </navMap>
</ncx>
"""

_NAV_POINT_TEMPLATE = """\
    <navPoint id="{nav_id}" playOrder="{play_order}">
      <navLabel><text>{label}</text></navLabel>
      <content src="{src}"/>
{children}    </navPoint>
"""

# EPUB 3 nav document (nav.xhtml). xmlns:epub is required for the epub:type
# attributes on <nav>. {extra_navs} holds the optional landmarks/page-list navs.
_NAV_DOC_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}">
<head>
  <title>{title}</title>
</head>
<body>
<nav epub:type="toc" id="toc">
<h1>{toc_heading}</h1>
<ol>
{toc_items}</ol>
</nav>
{extra_navs}</body>
</html>
"""

_LANDMARKS_NAV_TEMPLATE = """\
<nav epub:type="landmarks" hidden="">
<ol>
<li><a epub:type="bodymatter" href="{first_href}">Start of Content</a></li>
</ol>
</nav>
"""

_PAGE_LIST_NAV_TEMPLATE = """\
<nav epub:type="page-list" hidden="">
<ol>
{page_list_items}</ol>
</nav>
"""

_CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


@dataclass
class XhtmlSpec:
    """Specification for a single XHTML file in the test EPUB."""

    href: str  # relative to OEBPS, e.g. "ch01.xhtml"
    title: str = "Chapter"
    body_html: str = "<p>Content</p>"
    lang: str = "en"


@dataclass
class NavPointSpec:
    """Specification for a navPoint in the NCX (and, for EPUB 3, the nav doc toc)."""

    label: str
    src: str  # e.g. "ch01.xhtml#heading-id"
    nav_id: str = ""  # auto-generated if empty
    play_order: int = 0  # auto-assigned if 0
    children: list[NavPointSpec] = field(default_factory=list)


def build_minimal_epub(
    titles: tuple[str, ...] = ("Test Book",),
    descriptions: tuple[str, ...] = ("Test description",),
    subjects: tuple[str, ...] = ("test", "fiction"),
    language: str = "en",
    creators: tuple[str, ...] = ("Anonymous",),
    publishers: tuple[str, ...] = ("Test Publisher",),
    dates: tuple[str, ...] = ("2024-01-01",),
    identifiers: tuple[str, ...] | None = None,
    rights: tuple[str, ...] = (),
    xhtmls: list[XhtmlSpec] | None = None,
    nav_map: list[NavPointSpec] | None = None,
    extra_files: dict[str, bytes] | None = None,
    include_css: bool = True,
    include_drm: bool = False,
    extra_opf_meta: str = "",
    languages: list[str] | None = None,  # override language with multiple entries
    epub_version: str = "2.0",
    include_ncx: bool = True,
    include_nav_doc: bool | None = None,
    nav_in_spine: bool = False,
    nav_landmarks: bool = False,
    nav_page_list: bool = False,
    title_id: str = "",
) -> bytes:
    """Return raw EPUB bytes with the given structure.

    Args:
        xhtmls: list of XhtmlSpec; defaults to 3 chapters with headings
        nav_map: list of NavPointSpec; defaults to 3 navPoints for the 3 chapters
        identifiers: dc:identifier values; None (default) resolves to
            "urn:uuid:test-12345" for EPUB 2 (kept byte-identical to prior
            fixture output) or a syntactically valid UUID for EPUB 3 (epubcheck
            OPF-085 flags "test-12345" as an invalid UUID under EPUB 3 rules).
            The EPUB 3 NCX's dtb:uid is always kept in sync with identifiers[0]
            (epubcheck NCX-001).
        extra_files: additional zip entries (CSS, images, etc.)
        include_css: include a minimal stylesheet.css
        include_drm: add META-INF/encryption.xml (for DRM rejection tests)
        extra_opf_meta: extra XML to append inside <metadata>
        languages: if given, overrides `language` with multiple dc:language elements
        epub_version: OPF <package version="..."> value; "2.0" (default) selects the
            EPUB 2 + NCX templates, "3.x" selects the EPUB 3 templates (dcterms:modified
            meta, no http-equiv, NCX without its legacy DOCTYPE, nav doc support)
        include_ncx: include toc.ncx in the manifest/spine/ZIP
        include_nav_doc: include nav.xhtml; None (default) auto-resolves to whether
            epub_version's major version is >= 3
        nav_in_spine: also reference the nav doc as an ordinary spine itemref
            (default: non-spine, matching the common real-world layout)
        nav_landmarks: add a hidden epub:type="landmarks" nav to nav.xhtml
        nav_page_list: add a hidden epub:type="page-list" nav to nav.xhtml, with one
            entry per chapter targeting a matching <span id="page_N"/> appended to
            that chapter's body
        title_id: id attribute on the first dc:title only — combine with
            extra_opf_meta to test a <meta refines="#{title_id}"> pairing

    Returns:
        Raw bytes of the EPUB ZIP archive.
    """
    major_version = int(epub_version[0]) if epub_version else 0
    is_epub3 = major_version >= 3
    nav_doc_enabled = include_nav_doc if include_nav_doc is not None else is_epub3

    if identifiers is None:
        identifiers = (
            ("urn:uuid:00000000-0000-4000-8000-000000000001",)
            if is_epub3
            else ("urn:uuid:test-12345",)
        )

    if xhtmls is None:
        xhtmls = [
            XhtmlSpec(
                href="ch01.xhtml",
                title="Chapter 1",
                body_html='<h1 id="ch1-heading">Chapter One Heading</h1><p>Chapter 1 content.</p>',
            ),
            XhtmlSpec(
                href="ch02.xhtml",
                title="Chapter 2",
                body_html='<h1 id="ch2-heading">Chapter Two Heading</h1><p>Chapter 2 content.</p>',
            ),
            XhtmlSpec(
                href="ch03.xhtml",
                title="Chapter 3",
                body_html=(
                    '<h1 id="ch3-heading">Chapter Three Heading</h1><p>Chapter 3 content.</p>'
                ),
            ),
        ]

    if nav_map is None:
        nav_map = (
            [
                NavPointSpec(
                    label="Chapter One",
                    src=f"{xhtmls[0].href}#ch1-heading",
                    nav_id="navPoint-1",
                    play_order=1,
                ),
                NavPointSpec(
                    label="Chapter Two",
                    src=f"{xhtmls[1].href}#ch2-heading",
                    nav_id="navPoint-2",
                    play_order=2,
                ),
                NavPointSpec(
                    label="Chapter Three",
                    src=f"{xhtmls[2].href}#ch3-heading",
                    nav_id="navPoint-3",
                    play_order=3,
                ),
            ]
            if len(xhtmls) >= 3
            else [
                NavPointSpec(
                    label=x.title,
                    src=x.href,
                    nav_id=f"navPoint-{i + 1}",
                    play_order=i + 1,
                )
                for i, x in enumerate(xhtmls)
            ]
        )

    # Build OPF metadata XML
    meta_lines: list[str] = []
    lang_list = languages if languages is not None else [language]
    for lang_val in lang_list:
        meta_lines.append(f"    <dc:language>{lang_val}</dc:language>")
    for i, t in enumerate(titles):
        if i == 0 and title_id:
            meta_lines.append(f'    <dc:title id="{title_id}">{_escape(t)}</dc:title>')
        else:
            meta_lines.append(f"    <dc:title>{_escape(t)}</dc:title>")
    for d in descriptions:
        meta_lines.append(f"    <dc:description>{_escape(d)}</dc:description>")
    for s in subjects:
        meta_lines.append(f"    <dc:subject>{_escape(s)}</dc:subject>")
    for c in creators:
        # opf:role is EPUB 2 OPF vocabulary; EPUB 3's stricter DC-element
        # attribute allowlist (dir/id/xml:lang only) rejects it as RSC-005.
        if is_epub3:
            meta_lines.append(f"    <dc:creator>{_escape(c)}</dc:creator>")
        else:
            meta_lines.append(f'    <dc:creator opf:role="aut">{_escape(c)}</dc:creator>')
    for p in publishers:
        meta_lines.append(f"    <dc:publisher>{_escape(p)}</dc:publisher>")
    for dt in dates:
        meta_lines.append(f"    <dc:date>{_escape(dt)}</dc:date>")
    for ident in identifiers:
        meta_lines.append(f'    <dc:identifier id="BookID">{_escape(ident)}</dc:identifier>')
    for r in rights:
        meta_lines.append(f"    <dc:rights>{_escape(r)}</dc:rights>")
    if extra_opf_meta:
        meta_lines.append(f"    {extra_opf_meta}")

    # Build manifest
    manifest_lines: list[str] = []
    if include_ncx:
        manifest_lines.append(
            '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        )
    if include_css:
        manifest_lines.append('    <item id="css" href="stylesheet.css" media-type="text/css"/>')
    for i, xhtml in enumerate(xhtmls):
        manifest_lines.append(
            f'    <item id="chapter{i + 1}" href="{xhtml.href}" '
            f'media-type="application/xhtml+xml"/>'
        )
    if nav_doc_enabled:
        manifest_lines.append(
            '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
            'properties="nav"/>'
        )

    # Build spine
    spine_lines: list[str] = []
    for i in range(len(xhtmls)):
        spine_lines.append(f'    <itemref idref="chapter{i + 1}"/>')
    if nav_doc_enabled and nav_in_spine:
        spine_lines.append('    <itemref idref="nav"/>')

    spine_toc_attr = ' toc="ncx"' if include_ncx else ""
    opf_template = _OPF_TEMPLATE_EPUB3 if is_epub3 else _OPF_TEMPLATE
    opf_content = opf_template.format(
        version=epub_version,
        metadata_elements="\n".join(meta_lines) + "\n",
        manifest_items="\n".join(manifest_lines) + "\n",
        spine_toc_attr=spine_toc_attr,
        spine_items="\n".join(spine_lines) + "\n",
    )

    # Build NCX (optional)
    ncx_content = None
    if include_ncx:
        nav_points_xml = _render_nav_points(nav_map, counter=[1])
        ncx_template = _NCX_TEMPLATE_EPUB3 if is_epub3 else _NCX_TEMPLATE
        ncx_content = ncx_template.format(
            doc_title=_escape(titles[0] if titles else ""),
            nav_points=nav_points_xml,
            dtb_uid=identifiers[0] if identifiers else "urn:uuid:test-uuid",
        )

    # Build nav doc (optional, EPUB 3 only in practice)
    nav_doc_content = None
    if nav_doc_enabled:
        extra_navs = ""
        if nav_landmarks:
            extra_navs += _LANDMARKS_NAV_TEMPLATE.format(first_href=xhtmls[0].href)
        if nav_page_list:
            extra_navs += _PAGE_LIST_NAV_TEMPLATE.format(
                page_list_items=_render_page_list_items(xhtmls)
            )
        nav_doc_content = _NAV_DOC_TEMPLATE.format(
            lang=language,
            title=_escape(titles[0] if titles else "Navigation"),
            toc_heading="Contents",
            toc_items=_render_nav_ol(nav_map),
            extra_navs=extra_navs,
        )

    # Build ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # mimetype first, STORED, flag_bits=0, no extra
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        info.flag_bits = 0
        info.extra = b""
        zf.writestr(info, b"application/epub+zip")

        zf.writestr(
            zipfile.ZipInfo("META-INF/container.xml"),
            _CONTAINER_XML.encode("utf-8"),
        )
        zf.writestr("OEBPS/content.opf", opf_content.encode("utf-8"))
        if ncx_content is not None:
            zf.writestr("OEBPS/toc.ncx", ncx_content.encode("utf-8"))
        if nav_doc_content is not None:
            zf.writestr("OEBPS/nav.xhtml", nav_doc_content.encode("utf-8"))

        if include_css:
            zf.writestr(
                "OEBPS/stylesheet.css",
                b"body { font-family: serif; }\n",
            )

        xhtml_template = _XHTML_TEMPLATE_EPUB3 if is_epub3 else _XHTML_TEMPLATE
        for i, xhtml in enumerate(xhtmls):
            body = xhtml.body_html
            if nav_page_list:
                body = f'{body}\n<span id="page_{i + 1}"/>'
            content = xhtml_template.format(
                lang=xhtml.lang,
                title=_escape(xhtml.title),
                body=body,
            )
            zf.writestr(f"OEBPS/{xhtml.href}", content.encode("utf-8"))

        if include_drm:
            zf.writestr(
                "META-INF/encryption.xml",
                b'<?xml version="1.0"?><encryption xmlns="..."></encryption>',
            )

        if extra_files:
            for path, data in extra_files.items():
                zf.writestr(path, data)

    return buf.getvalue()


def _render_nav_points(points: list[NavPointSpec], counter: list[int]) -> str:
    """Recursively render navPoint XML."""
    parts: list[str] = []
    for p in points:
        nav_id = p.nav_id or f"navPoint-{counter[0]}"
        play_order = p.play_order if p.play_order else counter[0]
        counter[0] += 1
        children_xml = _render_nav_points(p.children, counter) if p.children else ""
        parts.append(
            _NAV_POINT_TEMPLATE.format(
                nav_id=nav_id,
                play_order=play_order,
                label=_escape(p.label),
                src=p.src,
                children=children_xml,
            )
        )
    return "".join(parts)


def _render_nav_ol(points: list[NavPointSpec]) -> str:
    """Recursively render nav doc <ol><li><a>...</a></li></ol> XML."""
    parts: list[str] = []
    for p in points:
        if p.children:
            children_xml = f"<ol>\n{_render_nav_ol(p.children)}</ol>\n"
            parts.append(f'<li><a href="{p.src}">{_escape(p.label)}</a>\n{children_xml}</li>\n')
        else:
            parts.append(f'<li><a href="{p.src}">{_escape(p.label)}</a></li>\n')
    return "".join(parts)


def _render_page_list_items(xhtmls: list[XhtmlSpec]) -> str:
    """Render page-list <li> entries, one per chapter, targeting <span id="page_N"/>."""
    parts: list[str] = []
    for i, xhtml in enumerate(xhtmls):
        page_num = i + 1
        parts.append(f'<li><a href="{xhtml.href}#page_{page_num}">{page_num}</a></li>\n')
    return "".join(parts)


def _escape(s: str) -> str:
    """XML escape a string."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
