"""Core data model for epub-deepl-prepare.

Plain dataclasses — no lxml types in model layer (keeps model serialisation-agnostic).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ManifestItem:
    """One <item> in the OPF <manifest>."""

    item_id: str  # OPF <item id="...">
    href: str  # OPF <item href="..."> relative to OPF directory
    media_type: str  # e.g. application/xhtml+xml
    properties: str | None = None  # EPUB 3 only; preserved but unused in MVP


@dataclass
class SpineRef:
    """One <itemref> in the OPF <spine>."""

    idref: str  # references ManifestItem.item_id
    linear: bool = True  # spine linear="yes" is the default


@dataclass
class Spine:
    """OPF <spine> element."""

    items: list[SpineRef]
    toc_idref: str | None  # spine toc="..." attribute; references NCX item


@dataclass
class OpfMetadata:
    """Translatable and structural metadata from the OPF <metadata> element.

    Fields split into:
      - translatable: titles, descriptions, subjects, language
      - structural (preserved but not translated): creators, publishers, dates,
        identifiers, rights
      - extra_raw_xml: complete <metadata>…</metadata> bytes from the original
        OPF; used as the base for restoration so we never lose custom <meta>
        or publisher extension elements.
    """

    titles: list[str]
    descriptions: list[str]
    subjects: list[str]
    language: str  # "und" if missing (US-019 / I-1)
    creators: list[str]
    publishers: list[str]
    dates: list[str]
    identifiers: list[str]
    rights: list[str]
    extra_raw_xml: bytes  # complete <metadata>…</metadata> serialised bytes


@dataclass
class NavPoint:
    """One <navPoint> in the NCX <navMap> (recursive)."""

    nav_id: str
    play_order: int
    label: str
    src: str  # path#fragment relative to NCX directory
    children: list[NavPoint] = field(default_factory=list)


@dataclass
class Ncx:
    """Parsed NCX file."""

    doc_title: str
    nav_map: list[NavPoint]  # top-level entries only; children nested inside
    raw_xml: bytes  # original bytes — used as template for NCX restoration
    ncx_href_in_zip: str  # full ZIP path to the NCX file, e.g. "OEBPS/toc.ncx"


@dataclass
class XhtmlFile:
    """One XHTML content file from the OPF spine."""

    href: str  # path relative to OPF directory (key in Epub.xhtmls)
    raw_bytes: bytes  # original bytes (full file — head + body)
    body_html: str  # extracted <body> inner HTML as a serialised string


@dataclass
class Epub:
    """Complete in-memory representation of a parsed EPUB 2.0 archive."""

    opf_path: str  # full ZIP path, e.g. "OEBPS/content.opf"
    opf_dir: str  # dirname of opf_path, e.g. "OEBPS"
    manifest: dict[str, ManifestItem]  # keyed by item_id
    spine: Spine
    metadata: OpfMetadata
    ncx: Ncx | None
    xhtmls: dict[str, XhtmlFile]  # keyed by href (OPF-relative)
    other_files: dict[str, bytes]  # zip_path → bytes (CSS, images, fonts, …)
    # Preserve original bytes of key structural files for restoration
    opf_raw_xml: bytes  # original OPF bytes (template for writer)
    container_xml_bytes: bytes  # META-INF/container.xml verbatim
