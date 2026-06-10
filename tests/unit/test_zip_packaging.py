"""Unit tests for ZIP packaging invariants (C-1 / test-plan §6.4).

These tests verify the binary-level properties that diff -r on unzipped
content cannot detect: STORED compression, flag_bits=0, no extra fields.
"""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from tests.fixtures.minimal import XhtmlSpec, build_minimal_epub


def _write_test_epub() -> bytes:
    """Write a round-trip EPUB and return its bytes."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.writer import write_epub_bytes
    from epub_deepl_prepare.merge.builder import build
    from epub_deepl_prepare.restore.applier import apply_and_write_bytes
    from epub_deepl_prepare.restore.parser import parse_translated_html_bytes

    source_epub = build_minimal_epub()
    epub = read_epub_bytes(source_epub)
    merged_html = build(epub)
    doc = parse_translated_html_bytes(merged_html.encode("utf-8"))
    return apply_and_write_bytes(epub, doc, "en")


@pytest.mark.unit
def test_mimetype_is_first_entry() -> None:
    """mimetype must be the first entry in the ZIP central directory."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        names = zf.namelist()
    assert names[0] == "mimetype", f"First entry is {names[0]!r}, expected 'mimetype'"


@pytest.mark.unit
def test_mimetype_is_stored_compression() -> None:
    """mimetype must use ZIP_STORED (no compression)."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        info = zf.getinfo("mimetype")
    assert info.compress_type == zipfile.ZIP_STORED, (
        f"mimetype compress_type={info.compress_type}, expected ZIP_STORED (0)"
    )


@pytest.mark.unit
def test_mimetype_has_no_extra_field() -> None:
    """mimetype must have no extra field bytes (C-1 / tech-spec §7)."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        info = zf.getinfo("mimetype")
    assert info.extra == b"", f"mimetype has extra field bytes: {info.extra!r}"


@pytest.mark.unit
def test_mimetype_byte_content_exact() -> None:
    """mimetype content must be exactly 20 bytes, no newline."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        content = zf.read("mimetype")
    assert content == b"application/epub+zip", (
        f"mimetype content is {content!r}, expected b'application/epub+zip'"
    )


@pytest.mark.unit
def test_mimetype_general_purpose_flag_zero() -> None:
    """mimetype local file header must have flag_bits=0 (C-1).

    This is the regression vector: Python's zipfile sets UTF-8 flag (bit 11)
    by default on STORED entries when using writestr() without explicit ZipInfo.
    We construct ZipInfo manually and force flag_bits=0.
    """
    epub_bytes = _write_test_epub()
    # Parse the local file header manually to check flag_bits
    # ZIP local file header signature: PK\x03\x04
    # Offset 6 = general purpose bit flag (2 bytes, little-endian)
    sig = b"PK\x03\x04"
    offset = epub_bytes.find(sig)
    assert offset != -1, "No local file header found in ZIP"
    flag_bits = struct.unpack_from("<H", epub_bytes, offset + 6)[0]
    assert flag_bits == 0, f"mimetype local file header flag_bits={flag_bits:#06x}, expected 0"


@pytest.mark.unit
def test_other_entries_are_deflated() -> None:
    """All entries except mimetype must use DEFLATED compression."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        for info in zf.infolist():
            if info.filename == "mimetype":
                continue
            assert info.compress_type == zipfile.ZIP_DEFLATED, (
                f"{info.filename!r} uses compress_type={info.compress_type}, "
                f"expected ZIP_DEFLATED (8)"
            )


@pytest.mark.unit
def test_zip_can_be_reopened_and_read_back() -> None:
    """The output ZIP must be readable after writing."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        names = set(zf.namelist())
    assert "mimetype" in names
    assert "META-INF/container.xml" in names
    assert "OEBPS/content.opf" in names


@pytest.mark.unit
def test_zip_testzip_returns_none() -> None:
    """zipfile.testzip() must return None (no CRC errors)."""
    epub_bytes = _write_test_epub()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        bad = zf.testzip()
    assert bad is None, f"CRC error in entry: {bad!r}"


@pytest.mark.unit
def test_mimetype_first_entry_offset_zero() -> None:
    """The mimetype entry's local header must begin at offset 0."""
    epub_bytes = _write_test_epub()
    # The first 4 bytes of a valid EPUB ZIP should be the PK\x03\x04 signature
    assert epub_bytes[:4] == b"PK\x03\x04"
    # Check the filename field in the local header (offset 26-27 = filename len)
    fname_len = struct.unpack_from("<H", epub_bytes, 26)[0]
    fname = epub_bytes[30 : 30 + fname_len]
    assert fname == b"mimetype", f"First entry filename is {fname!r}"
