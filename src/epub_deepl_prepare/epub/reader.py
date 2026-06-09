"""EPUB ZIP reader: parse archive into Epub model.

Security: all XML parsing goes through epub._safe_parser (XXE, billion-laughs,
network access all blocked).
"""

from __future__ import annotations

import io
import posixpath
import zipfile

from lxml import etree

from epub_deepl_prepare.epub import opf as opf_module
from epub_deepl_prepare.epub._safe_parser import parse_xml
from epub_deepl_prepare.epub.model import Epub, XhtmlFile
from epub_deepl_prepare.epub.ncx import parse_ncx
from epub_deepl_prepare.epub.xhtml import extract_body_html
from epub_deepl_prepare.errors import DrmDetected, MissingNcx, NotAnEpub

# Max uncompressed EPUB size (500 MB) — zip-bomb guard (tech-spec §10)
_MAX_EPUB_SIZE_BYTES = 500 * 1024 * 1024


def read_epub(epub_path: str) -> Epub:
    """Parse an EPUB file at epub_path into an Epub model.

    Raises:
        NotAnEpub: for any structural invalidity
        DrmDetected: if META-INF/encryption.xml is present
        MissingNcx: if NCX is required but missing
    """
    try:
        zf = zipfile.ZipFile(epub_path, "r")
    except zipfile.BadZipFile as exc:
        raise NotAnEpub(f"Not a ZIP archive: {exc}") from exc
    except OSError as exc:
        raise NotAnEpub(f"Cannot open file: {exc}") from exc

    with zf:
        return _read_from_zipfile(zf)


def read_epub_bytes(epub_bytes: bytes) -> Epub:
    """Parse EPUB from in-memory bytes (used in tests)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(epub_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise NotAnEpub(f"Not a ZIP archive: {exc}") from exc

    with zf:
        return _read_from_zipfile(zf)


def _read_from_zipfile(zf: zipfile.ZipFile) -> Epub:
    names = set(zf.namelist())

    # Zip-bomb guard
    total_size = sum(info.file_size for info in zf.infolist())
    if total_size > _MAX_EPUB_SIZE_BYTES:
        raise NotAnEpub(
            f"EPUB exceeds size cap ({total_size} > {_MAX_EPUB_SIZE_BYTES} bytes)"
        )

    # DRM check (before any other processing)
    if "META-INF/encryption.xml" in names:
        raise DrmDetected("EPUB is encrypted (DRM detected)")

    # mimetype
    if "mimetype" not in names:
        raise NotAnEpub("Missing mimetype entry")
    mimetype_content = zf.read("mimetype").rstrip(b"\n").rstrip(b"\r\n")
    if mimetype_content != b"application/epub+zip":
        raise NotAnEpub(
            f"mimetype is not application/epub+zip (got {mimetype_content!r})"
        )

    # container.xml
    if "META-INF/container.xml" not in names:
        raise NotAnEpub("Missing META-INF/container.xml")
    container_bytes = zf.read("META-INF/container.xml")
    opf_path = opf_module.get_opf_path_from_container(container_bytes)

    if opf_path not in names:
        raise NotAnEpub(f"OPF referenced in container.xml not found in ZIP: {opf_path!r}")

    opf_raw = zf.read(opf_path)
    opf_dir = posixpath.dirname(opf_path)

    # Validate EPUB version
    _validate_epub_version(opf_raw)

    # Parse OPF sections
    metadata = opf_module.parse_metadata(opf_raw)
    manifest = opf_module.parse_manifest(opf_raw)
    spine = opf_module.parse_spine(opf_raw)

    # Locate NCX
    ncx_item_id = spine.toc_idref
    ncx_item = None
    if ncx_item_id and ncx_item_id in manifest:
        ncx_item = manifest[ncx_item_id]
    else:
        # Fallback: find by media-type
        for manifest_item in manifest.values():
            if manifest_item.media_type == "application/x-dtbncx+xml":
                ncx_item = manifest_item
                break

    ncx = None
    if ncx_item is not None:
        ncx_zip_path = _join_opf(opf_dir, ncx_item.href)
        if ncx_zip_path in names:
            ncx_bytes = zf.read(ncx_zip_path)
            ncx = parse_ncx(ncx_bytes, ncx_zip_path)
        else:
            raise MissingNcx(f"NCX file referenced in manifest not found in ZIP: {ncx_zip_path!r}")

    # Read all XHTML spine files
    xhtmls: dict[str, XhtmlFile] = {}
    for spine_ref in spine.items:
        item = manifest.get(spine_ref.idref)
        if item is None:
            continue  # Caught by validator
        zip_path = _join_opf(opf_dir, item.href)
        if zip_path not in names:
            continue  # Caught by validator
        raw_bytes = zf.read(zip_path)
        body_html = extract_body_html(raw_bytes)
        xhtmls[item.href] = XhtmlFile(
            href=item.href,
            raw_bytes=raw_bytes,
            body_html=body_html,
        )

    # All other files (CSS, images, fonts, non-spine XHTML)
    skip_paths = {
        "mimetype",
        "META-INF/container.xml",
        opf_path,
    }
    if ncx_item is not None:
        skip_paths.add(_join_opf(opf_dir, ncx_item.href))
    for href in xhtmls:
        skip_paths.add(_join_opf(opf_dir, href))

    other_files: dict[str, bytes] = {}
    for name in names:
        if name not in skip_paths and not name.endswith("/"):
            other_files[name] = zf.read(name)

    return Epub(
        opf_path=opf_path,
        opf_dir=opf_dir,
        manifest=manifest,
        spine=spine,
        metadata=metadata,
        ncx=ncx,
        xhtmls=xhtmls,
        other_files=other_files,
        opf_raw_xml=opf_raw,
        container_xml_bytes=container_bytes,
    )


def _validate_epub_version(opf_bytes: bytes) -> None:
    """Raise NotAnEpub if OPF root is not a <package> with version 2.x."""
    try:
        root = parse_xml(opf_bytes)
    except etree.XMLSyntaxError as exc:
        raise NotAnEpub(f"OPF malformed: {exc}") from exc

    local_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if local_tag != "package":
        raise NotAnEpub(f"OPF root element is <{local_tag}>, expected <package>")

    version = root.get("version", "")
    if not version.startswith("2"):
        raise NotAnEpub(
            f"Unsupported EPUB version {version!r} (only 2.x is supported)"
        )


def _join_opf(opf_dir: str, href: str) -> str:
    """Join OPF directory with a manifest href to produce a ZIP path."""
    if not opf_dir:
        return href
    return posixpath.join(opf_dir, href)
