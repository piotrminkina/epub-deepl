"""Unit tests for EPUB 2.x/3.x version gating and nav-document discovery (reader.py)."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from epub_deepl.errors import MissingNavDoc, NotAnEpub
from tests.fixtures.minimal import build_minimal_epub


def _epub_bytes_without_file(epub_bytes: bytes, remove_name: str) -> bytes:
    """Return EPUB bytes with one file removed."""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            if info.filename == remove_name:
                continue
            # Preserve mimetype ZipInfo for STORED flag
            if info.filename == "mimetype":
                zinfo = zipfile.ZipInfo("mimetype")
                zinfo.compress_type = zipfile.ZIP_STORED
                zinfo.flag_bits = 0
                zinfo.extra = b""
                dst.writestr(zinfo, src.read("mimetype"))
            else:
                dst.writestr(info, src.read(info.filename))
    return buf.getvalue()


def _epub_bytes_with_opf_version(
    epub_bytes: bytes,
    new_version: str | None,
    opf_path: str = "OEBPS/content.opf",
) -> bytes:
    """Return EPUB bytes with the OPF `<package version="...">` attribute rewritten.

    `new_version=None` removes the version attribute entirely (for testing the
    absent-version rejection path). The substitution is anchored to `<package`
    specifically so it never touches the `version="1.0"` in the leading XML
    declaration (`<?xml version="1.0" ...?>`).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            if info.filename == opf_path:
                content = src.read(opf_path).decode("utf-8")
                if new_version is None:
                    content = re.sub(
                        r'<package\s+version="[^"]*"\s*', "<package ", content, count=1
                    )
                else:
                    content = re.sub(
                        r'(<package\s+)version="[^"]*"',
                        rf'\1version="{new_version}"',
                        content,
                        count=1,
                    )
                dst.writestr(info, content.encode("utf-8"))
            elif info.filename == "mimetype":
                zinfo = zipfile.ZipInfo("mimetype")
                zinfo.compress_type = zipfile.ZIP_STORED
                zinfo.flag_bits = 0
                zinfo.extra = b""
                dst.writestr(zinfo, src.read("mimetype"))
            else:
                dst.writestr(info, src.read(info.filename))
    return buf.getvalue()


@pytest.mark.unit
def test_reader_accepts_epub_2_0() -> None:
    """EPUB 2.0 is accepted; nav_doc stays None (no nav discovery below major 3)."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(build_minimal_epub(epub_version="2.0"))
    assert epub.epub_version == "2.0"
    assert epub.major_version == 2
    assert epub.nav_doc is None


@pytest.mark.unit
def test_reader_accepts_epub_2_x_non_dot_zero_variant() -> None:
    """Any 2.x version string is accepted, not just the literal "2.0"."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_with_opf_version(build_minimal_epub(epub_version="2.0"), "2.1")
    epub = read_epub_bytes(epub_bytes)
    assert epub.epub_version == "2.1"
    assert epub.major_version == 2


@pytest.mark.unit
def test_reader_accepts_epub_3_0_with_nav_doc() -> None:
    """EPUB 3.0 is accepted and its nav document is discovered and parsed."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(build_minimal_epub(epub_version="3.0"))
    assert epub.epub_version == "3.0"
    assert epub.major_version == 3
    assert epub.nav_doc is not None
    assert epub.nav_doc.href == "nav.xhtml"
    assert epub.nav_doc.has_toc_nav is True
    assert epub.nav_doc.in_spine is False
    assert len(epub.nav_doc.toc_entries) == 3


@pytest.mark.unit
def test_reader_nav_doc_in_spine_detected() -> None:
    """A nav doc referenced by an itemref in the spine has in_spine=True."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(build_minimal_epub(epub_version="3.0", nav_in_spine=True))
    assert epub.nav_doc is not None
    assert epub.nav_doc.in_spine is True


@pytest.mark.unit
def test_reader_nav_doc_not_in_spine_by_default() -> None:
    """A nav doc not referenced by any itemref has in_spine=False (the fixture default)."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(build_minimal_epub(epub_version="3.0", nav_in_spine=False))
    assert epub.nav_doc is not None
    assert epub.nav_doc.in_spine is False


@pytest.mark.unit
def test_reader_rejects_version_1_0() -> None:
    """OPF version "1.0" is rejected (only 2.x/3.x are supported)."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_with_opf_version(build_minimal_epub(), "1.0")
    with pytest.raises(NotAnEpub, match="Unsupported EPUB version"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_reader_rejects_version_4_0() -> None:
    """OPF version "4.0" is rejected (only 2.x/3.x are supported)."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_with_opf_version(build_minimal_epub(), "4.0")
    with pytest.raises(NotAnEpub, match="Unsupported EPUB version"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_reader_rejects_absent_version_attribute() -> None:
    """OPF <package> without a version attribute at all is rejected."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_with_opf_version(build_minimal_epub(), None)
    with pytest.raises(NotAnEpub, match="Unsupported EPUB version"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_reader_epub2_skips_nav_discovery_even_if_nav_item_present() -> None:
    """Nav discovery is gated on major_version >= 3: an EPUB 2.0 with a manifest
    nav item (and a nav.xhtml file present) must still leave nav_doc as None.
    """
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = build_minimal_epub(epub_version="2.0", include_nav_doc=True)
    epub = read_epub_bytes(epub_bytes)
    assert epub.major_version == 2
    assert epub.nav_doc is None


@pytest.mark.unit
def test_reader_epub3_without_nav_item_leaves_nav_doc_none() -> None:
    """An EPUB 3.0 with no manifest item declaring properties="nav" is not an error
    at the reader layer — nav_doc simply stays None (the validator layer is what
    raises MissingNavDoc for this case).
    """
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = build_minimal_epub(epub_version="3.0", include_nav_doc=False)
    epub = read_epub_bytes(epub_bytes)
    assert epub.major_version == 3
    assert epub.nav_doc is None


@pytest.mark.unit
def test_reader_rejects_missing_nav_doc_file() -> None:
    """A manifest nav item whose ZIP entry is missing must raise MissingNavDoc."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_without_file(build_minimal_epub(epub_version="3.0"), "OEBPS/nav.xhtml")
    with pytest.raises(MissingNavDoc, match="Nav document"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_reader_nav_doc_excluded_from_other_files() -> None:
    """The nav document's ZIP path must not leak into Epub.other_files."""
    from epub_deepl.epub.reader import read_epub_bytes

    epub = read_epub_bytes(build_minimal_epub(epub_version="3.0"))
    assert "OEBPS/nav.xhtml" not in epub.other_files
