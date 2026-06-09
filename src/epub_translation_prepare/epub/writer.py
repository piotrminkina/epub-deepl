"""EPUB ZIP writer: serialise Epub model to a conformant EPUB ZIP.

Critical ZIP packaging invariants (tech-spec §7, C-1):
  1. mimetype MUST be first entry
  2. mimetype MUST use STORED compression
  3. mimetype MUST have flag_bits = 0 (no UTF-8 flag, no encryption bits)
  4. mimetype MUST have extra = b'' (no extra field bytes)
  5. All other entries MUST use DEFLATED compression
  6. mimetype content is exactly b'application/epub+zip' (20 bytes, no newline)
"""

from __future__ import annotations

import io
import pathlib
import posixpath
import zipfile

from epub_translation_prepare.epub.model import Epub, OpfMetadata
from epub_translation_prepare.epub.ncx import rebuild_ncx_bytes
from epub_translation_prepare.epub.opf import rebuild_opf_bytes


def write_epub(
    epub: Epub,
    output_path: str,
    updated_xhtml_bytes: dict[str, bytes],  # href → bytes
    new_metadata_titles: list[str],
    new_metadata_descriptions: list[str],
    new_metadata_subjects: list[str],
    target_language: str,
    new_ncx_labels: dict[str, str],  # nav_id → text
    new_doc_title: str,
) -> None:
    """Write a fully assembled EPUB ZIP to output_path.

    All structural content not explicitly updated is preserved byte-for-byte.
    """
    new_metadata = OpfMetadata(
        titles=new_metadata_titles,
        descriptions=new_metadata_descriptions,
        subjects=new_metadata_subjects,
        language=target_language,
        creators=epub.metadata.creators,
        publishers=epub.metadata.publishers,
        dates=epub.metadata.dates,
        identifiers=epub.metadata.identifiers,
        rights=epub.metadata.rights,
        extra_raw_xml=epub.metadata.extra_raw_xml,
    )

    new_opf_bytes = rebuild_opf_bytes(epub.opf_raw_xml, new_metadata, target_language)

    new_ncx_bytes: bytes | None = None
    if epub.ncx is not None:
        new_ncx_bytes = rebuild_ncx_bytes(epub.ncx, new_doc_title, new_ncx_labels)

    _write_zip(
        epub=epub,
        output_path=output_path,
        updated_xhtml_bytes=updated_xhtml_bytes,
        new_opf_bytes=new_opf_bytes,
        new_ncx_bytes=new_ncx_bytes,
    )


def write_epub_bytes(
    epub: Epub,
    updated_xhtml_bytes: dict[str, bytes],
    new_metadata_titles: list[str],
    new_metadata_descriptions: list[str],
    new_metadata_subjects: list[str],
    target_language: str,
    new_ncx_labels: dict[str, str],
    new_doc_title: str,
) -> bytes:
    """Like write_epub but returns bytes (for testing)."""
    new_metadata = OpfMetadata(
        titles=new_metadata_titles,
        descriptions=new_metadata_descriptions,
        subjects=new_metadata_subjects,
        language=target_language,
        creators=epub.metadata.creators,
        publishers=epub.metadata.publishers,
        dates=epub.metadata.dates,
        identifiers=epub.metadata.identifiers,
        rights=epub.metadata.rights,
        extra_raw_xml=epub.metadata.extra_raw_xml,
    )

    new_opf_bytes = rebuild_opf_bytes(epub.opf_raw_xml, new_metadata, target_language)

    new_ncx_bytes: bytes | None = None
    if epub.ncx is not None:
        new_ncx_bytes = rebuild_ncx_bytes(epub.ncx, new_doc_title, new_ncx_labels)

    buf = io.BytesIO()
    _write_zip_to_stream(
        epub=epub,
        stream=buf,
        updated_xhtml_bytes=updated_xhtml_bytes,
        new_opf_bytes=new_opf_bytes,
        new_ncx_bytes=new_ncx_bytes,
    )
    return buf.getvalue()


def _write_zip(
    epub: Epub,
    output_path: str,
    updated_xhtml_bytes: dict[str, bytes],
    new_opf_bytes: bytes,
    new_ncx_bytes: bytes | None,
) -> None:
    buf = io.BytesIO()
    _write_zip_to_stream(epub, buf, updated_xhtml_bytes, new_opf_bytes, new_ncx_bytes)
    pathlib.Path(output_path).write_bytes(buf.getvalue())


def _write_zip_to_stream(
    epub: Epub,
    stream: io.BytesIO,
    updated_xhtml_bytes: dict[str, bytes],
    new_opf_bytes: bytes,
    new_ncx_bytes: bytes | None,
) -> None:
    """Write the complete EPUB ZIP to a stream.

    Order of entries:
      1. mimetype (STORED, flag_bits=0, extra=b'')  ← MUST be first
      2. META-INF/container.xml
      3. OPF
      4. NCX (if present)
      5. All XHTML files (in spine order, then any non-spine XHTML)
      6. All other files (CSS, images, fonts, etc.)
    """
    with zipfile.ZipFile(stream, "w") as zf:
        # 1. mimetype — CRITICAL: must be first, STORED, flag_bits=0, no extra
        _write_mimetype(zf)

        # 2. META-INF/container.xml — byte-for-byte from input
        zf.writestr(
            _deflated_info("META-INF/container.xml"),
            epub.container_xml_bytes,
        )

        # 3. OPF — rebuilt with updated metadata
        zf.writestr(
            _deflated_info(epub.opf_path),
            new_opf_bytes,
        )

        # 4. NCX
        if epub.ncx is not None and new_ncx_bytes is not None:
            zf.writestr(
                _deflated_info(epub.ncx.ncx_href_in_zip),
                new_ncx_bytes,
            )

        # 5. XHTML files in spine order first
        written_zip_paths: set[str] = set()
        for spine_ref in epub.spine.items:
            item = epub.manifest.get(spine_ref.idref)
            if item is None:
                continue
            href = item.href
            zip_path = posixpath.join(epub.opf_dir, href) if epub.opf_dir else href
            if zip_path in written_zip_paths:
                continue
            content = updated_xhtml_bytes.get(href)
            if content is None:
                # Fallback to original bytes
                xhtml_file = epub.xhtmls.get(href)
                content = xhtml_file.raw_bytes if xhtml_file else b""
            zf.writestr(_deflated_info(zip_path), content)
            written_zip_paths.add(zip_path)

        # Any non-spine XHTML files (e.g. in manifest but not spine)
        for href, xhtml_file in epub.xhtmls.items():
            zip_path = posixpath.join(epub.opf_dir, href) if epub.opf_dir else href
            if zip_path not in written_zip_paths:
                content = updated_xhtml_bytes.get(href, xhtml_file.raw_bytes)
                zf.writestr(_deflated_info(zip_path), content)
                written_zip_paths.add(zip_path)

        # 6. Other files (CSS, images, fonts, META-INF extras) — byte-for-byte
        skip = {
            "mimetype",
            "META-INF/container.xml",
            epub.opf_path,
        }
        if epub.ncx is not None:
            skip.add(epub.ncx.ncx_href_in_zip)

        for zip_path, data in epub.other_files.items():
            if zip_path not in skip and zip_path not in written_zip_paths:
                zf.writestr(_deflated_info(zip_path), data)


def _write_mimetype(zf: zipfile.ZipFile) -> None:
    """Write the mimetype entry with all EPUB packaging invariants satisfied.

    tech-spec §7 and C-1 compliance:
    - STORED compression
    - flag_bits = 0 (no UTF-8 flag, no encryption)
    - extra = b'' (no extra field bytes)
    - Content exactly 20 bytes, no newline
    """
    info = zipfile.ZipInfo("mimetype")
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o644 << 16
    info.flag_bits = 0
    info.extra = b""
    zf.writestr(info, b"application/epub+zip")


def _deflated_info(zip_path: str) -> zipfile.ZipInfo:
    """Create a ZipInfo for a DEFLATED entry."""
    info = zipfile.ZipInfo(zip_path)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info
