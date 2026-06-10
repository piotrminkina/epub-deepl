"""Synthetic minimal EPUB factory for tests.

Produces a valid EPUB 2.0 ZIP entirely in memory, parameterised by
declarative arguments. Used as the foundation of all unit and
synth-integration tests.
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

_OPF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="BookID">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
{metadata_elements}  </metadata>
  <manifest>
{manifest_items}  </manifest>
  <spine toc="ncx">
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

_NAV_POINT_TEMPLATE = """\
    <navPoint id="{nav_id}" playOrder="{play_order}">
      <navLabel><text>{label}</text></navLabel>
      <content src="{src}"/>
{children}    </navPoint>
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
    """Specification for a navPoint in the NCX."""

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
    identifiers: tuple[str, ...] = ("urn:uuid:test-12345",),
    rights: tuple[str, ...] = (),
    xhtmls: list[XhtmlSpec] | None = None,
    nav_map: list[NavPointSpec] | None = None,
    extra_files: dict[str, bytes] | None = None,
    include_css: bool = True,
    include_drm: bool = False,
    extra_opf_meta: str = "",
    languages: list[str] | None = None,  # override language with multiple entries
) -> bytes:
    """Return raw EPUB 2.0 bytes with the given structure.

    Args:
        xhtmls: list of XhtmlSpec; defaults to 3 chapters with headings
        nav_map: list of NavPointSpec; defaults to 3 navPoints for the 3 chapters
        extra_files: additional zip entries (CSS, images, etc.)
        include_css: include a minimal stylesheet.css
        include_drm: add META-INF/encryption.xml (for DRM rejection tests)
        extra_opf_meta: extra XML to append inside <metadata>
        languages: if given, overrides `language` with multiple dc:language elements

    Returns:
        Raw bytes of the EPUB ZIP archive.
    """
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
    for t in titles:
        meta_lines.append(f"    <dc:title>{_escape(t)}</dc:title>")
    for d in descriptions:
        meta_lines.append(f"    <dc:description>{_escape(d)}</dc:description>")
    for s in subjects:
        meta_lines.append(f"    <dc:subject>{_escape(s)}</dc:subject>")
    for c in creators:
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

    # Build spine
    spine_lines: list[str] = []
    for i in range(len(xhtmls)):
        spine_lines.append(f'    <itemref idref="chapter{i + 1}"/>')

    opf_content = _OPF_TEMPLATE.format(
        metadata_elements="\n".join(meta_lines) + "\n",
        manifest_items="\n".join(manifest_lines) + "\n",
        spine_items="\n".join(spine_lines) + "\n",
    )

    # Build NCX
    nav_points_xml = _render_nav_points(nav_map, counter=[1])
    ncx_content = _NCX_TEMPLATE.format(
        doc_title=_escape(titles[0] if titles else ""),
        nav_points=nav_points_xml,
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
        zf.writestr("OEBPS/toc.ncx", ncx_content.encode("utf-8"))

        if include_css:
            zf.writestr(
                "OEBPS/stylesheet.css",
                b"body { font-family: serif; }\n",
            )

        for xhtml in xhtmls:
            content = _XHTML_TEMPLATE.format(
                lang=xhtml.lang,
                title=_escape(xhtml.title),
                body=xhtml.body_html,
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


def _escape(s: str) -> str:
    """XML escape a string."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
