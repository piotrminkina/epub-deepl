"""Unit tests for input validation (FR-4, test-plan §6.5)."""

from __future__ import annotations

import io
import pathlib
import zipfile

import pytest

from epub_deepl_prepare.errors import (
    BrokenManifest,
    BrokenSpine,
    DrmDetected,
    MissingNcx,
    NotAnEpub,
    OutputEqualsInput,
    OutputExists,
    TranslatedHtmlMismatch,
    UnsupportedMediaType,
)
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


def _epub_bytes_wrong_mimetype(epub_bytes: bytes) -> bytes:
    """Return EPUB bytes with wrong mimetype content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            if info.filename == "mimetype":
                zinfo = zipfile.ZipInfo("mimetype")
                zinfo.compress_type = zipfile.ZIP_STORED
                zinfo.flag_bits = 0
                zinfo.extra = b""
                dst.writestr(zinfo, b"application/not-epub")
            else:
                dst.writestr(info, src.read(info.filename))
    return buf.getvalue()


@pytest.mark.unit
def test_validate_accepts_minimal_synthetic_epub() -> None:
    """A well-formed minimal EPUB should pass validation."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_epub

    epub = read_epub_bytes(build_minimal_epub())
    validate_epub(epub)  # Should not raise


@pytest.mark.unit
def test_validate_rejects_non_zip_file(tmp_path: pathlib.Path) -> None:
    """A non-ZIP file must be rejected."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes

    with pytest.raises(NotAnEpub, match="Not a ZIP"):
        read_epub_bytes(b"not a zip file at all")


@pytest.mark.unit
def test_validate_rejects_missing_mimetype() -> None:
    """ZIP without mimetype entry must be rejected."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_without_file(build_minimal_epub(), "mimetype")
    with pytest.raises(NotAnEpub, match="mimetype"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_validate_rejects_wrong_mimetype_content() -> None:
    """ZIP with wrong mimetype content must be rejected."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_wrong_mimetype(build_minimal_epub())
    with pytest.raises(NotAnEpub, match="mimetype"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_validate_rejects_missing_container_xml() -> None:
    """ZIP without META-INF/container.xml must be rejected."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes

    epub_bytes = _epub_bytes_without_file(build_minimal_epub(), "META-INF/container.xml")
    with pytest.raises(NotAnEpub, match="container"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_validate_rejects_drm_protected_epub() -> None:
    """EPUB with META-INF/encryption.xml must raise DrmDetected."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes

    epub_bytes = build_minimal_epub(include_drm=True)
    with pytest.raises(DrmDetected, match="DRM"):
        read_epub_bytes(epub_bytes)


@pytest.mark.unit
def test_validate_rejects_manifest_with_missing_file() -> None:
    """EPUB whose manifest references a missing file must raise BrokenManifest."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_epub

    # Remove ch03.xhtml but keep it in the manifest
    epub_bytes = _epub_bytes_without_file(build_minimal_epub(), "OEBPS/ch03.xhtml")
    epub = read_epub_bytes(epub_bytes)
    with pytest.raises(BrokenManifest, match="Missing"):
        validate_epub(epub)


@pytest.mark.unit
def test_validate_lists_all_missing_files_in_error() -> None:
    """BrokenManifest message must list the missing file hrefs."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_epub

    epub_bytes = _epub_bytes_without_file(build_minimal_epub(), "OEBPS/ch02.xhtml")
    epub = read_epub_bytes(epub_bytes)
    with pytest.raises(BrokenManifest) as exc_info:
        validate_epub(epub)
    assert "ch02.xhtml" in str(exc_info.value)


@pytest.mark.unit
def test_validate_rejects_spine_with_unresolved_idref() -> None:
    """Spine with unresolved idref must raise BrokenSpine."""
    from epub_deepl_prepare.epub.model import SpineRef
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_epub

    epub = read_epub_bytes(build_minimal_epub())
    epub.spine.items.append(SpineRef(idref="nonexistent-id"))
    with pytest.raises(BrokenSpine, match="nonexistent-id"):
        validate_epub(epub)


@pytest.mark.unit
def test_validate_rejects_missing_ncx() -> None:
    """EPUB without NCX must raise MissingNcx."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_epub

    epub = read_epub_bytes(build_minimal_epub())
    epub.ncx = None
    with pytest.raises(MissingNcx):
        validate_epub(epub)


@pytest.mark.unit
def test_validate_rejects_non_xhtml_spine_item() -> None:
    """Spine item with non-XHTML media-type must raise UnsupportedMediaType (US-020)."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_epub

    epub = read_epub_bytes(build_minimal_epub())
    # Corrupt the media-type of the first spine item
    first_idref = epub.spine.items[0].idref
    epub.manifest[first_idref].media_type = "text/html"
    with pytest.raises(UnsupportedMediaType, match="Unsupported spine media-type"):
        validate_epub(epub)


@pytest.mark.unit
def test_validate_translated_html_missing_sections() -> None:
    """Translated HTML missing sections raises TranslatedHtmlMismatch."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_translated_html

    epub = read_epub_bytes(build_minimal_epub())
    # Provide only 1 of 3 sections
    sections = {"ch01.xhtml": "<p>translated</p>"}
    with pytest.raises(TranslatedHtmlMismatch, match="Missing sections"):
        validate_translated_html(epub, sections)


@pytest.mark.unit
def test_validate_translated_html_unknown_sections() -> None:
    """Translated HTML with extra unknown sections raises TranslatedHtmlMismatch."""
    from epub_deepl_prepare.epub.reader import read_epub_bytes
    from epub_deepl_prepare.epub.validator import validate_translated_html
    from epub_deepl_prepare.merge.builder import build
    from epub_deepl_prepare.restore.parser import parse_translated_html_bytes

    epub = read_epub_bytes(build_minimal_epub())
    merged = build(epub)
    doc = parse_translated_html_bytes(merged.encode("utf-8"))
    # Add an unknown section
    doc.sections["unknown-chapter.xhtml"] = "<p>extra</p>"
    with pytest.raises(TranslatedHtmlMismatch, match="Unknown sections"):
        validate_translated_html(epub, doc.sections)


@pytest.mark.unit
def test_check_output_not_exists_raises_when_exists(
    tmp_path: pathlib.Path,
) -> None:
    """OutputExists raised when output file exists and force=False."""
    from epub_deepl_prepare.epub.validator import check_output_not_exists

    existing = tmp_path / "out.html"
    existing.write_text("x")
    with pytest.raises(OutputExists, match="Output file exists"):
        check_output_not_exists(str(existing), force=False)


@pytest.mark.unit
def test_check_output_not_exists_no_raise_when_force(
    tmp_path: pathlib.Path,
) -> None:
    """No error raised when force=True even if file exists."""
    from epub_deepl_prepare.epub.validator import check_output_not_exists

    existing = tmp_path / "out.html"
    existing.write_text("x")
    check_output_not_exists(str(existing), force=True)  # Should not raise


@pytest.mark.unit
def test_check_output_not_input_raises_on_collision(tmp_path: pathlib.Path) -> None:
    """OutputEqualsInput raised when output path == input path (US-018)."""
    from epub_deepl_prepare.epub.validator import check_output_not_input

    p = str(tmp_path / "book.epub")
    with pytest.raises(OutputEqualsInput, match="Output path equals input path"):
        check_output_not_input(p, p)
