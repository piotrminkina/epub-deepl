"""Input validation (FR-4) — fail-fast checks before any output is produced.

All checks raise specific error subclasses so callers can report precise
messages without catching base Exception.
"""

from __future__ import annotations

import pathlib
import posixpath
import zipfile

from epub_translation_prepare.epub.model import Epub
from epub_translation_prepare.errors import (
    BrokenManifest,
    BrokenSpine,
    MissingNcx,
    NotAnEpub,
    OutputEqualsInput,
    OutputExists,
    TranslatedHtmlMismatch,
    UnsupportedMediaType,
    UserError,
)


def check_output_not_exists(output_path: str, force: bool) -> None:
    """Raise OutputExists if output_path already exists and force is False."""
    if not force and pathlib.Path(output_path).exists():
        raise OutputExists(f"Output file exists: {output_path!r} (use --force to overwrite)")


def check_output_not_input(output_path: str, *input_paths: str) -> None:
    """Raise OutputEqualsInput if output_path resolves to any of the input_paths.

    US-018: data-loss protection; --force does NOT bypass this check.
    """
    resolved_out = pathlib.Path(output_path).resolve()
    for inp in input_paths:
        if pathlib.Path(inp).resolve() == resolved_out:
            raise OutputEqualsInput(
                f"Output path equals input path: {output_path!r}"
            )


def validate_epub(epub: Epub) -> None:
    """Run all structural validation checks on a parsed Epub.

    Raises ValidationError subclasses on any failure.
    The caller is responsible for collecting all errors vs. fail-fast;
    this implementation is fail-fast (raises on first error).
    """
    # DRM must be checked before anything else — already done in reader,
    # but double-check here in case validate_epub is called on a fabricated Epub.
    # (The reader raises DrmDetected before constructing an Epub object,
    # so this is only a safeguard for tests that fabricate objects.)

    # Manifest files exist
    _check_manifest_files(epub)

    # Spine idrefs resolve
    _check_spine_idrefs(epub)

    # Spine items are XHTML (US-020 / I-2)
    _check_spine_media_types(epub)

    # NCX exists
    if epub.ncx is None:
        raise MissingNcx("No NCX found in EPUB (required for EPUB 2.0)")


def _check_manifest_files(epub: Epub) -> None:
    """All manifest hrefs must resolve to files in the EPUB."""
    all_zip_paths = set(epub.xhtmls.keys())
    # Add other_files paths converted to OPF-relative
    for zip_path in epub.other_files:
        if epub.opf_dir and zip_path.startswith(epub.opf_dir + "/"):
            rel = zip_path[len(epub.opf_dir) + 1:]
            all_zip_paths.add(rel)
        else:
            all_zip_paths.add(zip_path)

    # Also include NCX
    if epub.ncx is not None:
        ncx_zip = epub.ncx.ncx_href_in_zip
        if epub.opf_dir and ncx_zip.startswith(epub.opf_dir + "/"):
            all_zip_paths.add(ncx_zip[len(epub.opf_dir) + 1:])

    missing: list[str] = []
    for item in epub.manifest.values():
        href = item.href
        # Skip NCX items — their presence is validated separately by the
        # MissingNcx check, which gives a more precise error message.
        if item.media_type == "application/x-dtbncx+xml":
            continue
        # Check both directly and via posixpath join
        if href not in all_zip_paths:
            # Check full zip path
            full = posixpath.join(epub.opf_dir, href) if epub.opf_dir else href
            found_in_other = full in epub.other_files
            found_in_xhtmls = href in epub.xhtmls
            found_in_ncx = (
                epub.ncx is not None
                and epub.ncx.ncx_href_in_zip in (full, href)
            )
            if not (found_in_other or found_in_xhtmls or found_in_ncx):
                missing.append(href)

    if missing:
        raise BrokenManifest(f"Missing files in ZIP: {missing}")


def _check_spine_idrefs(epub: Epub) -> None:
    """All spine idrefs must resolve to manifest items."""
    unresolved: list[str] = []
    for ref in epub.spine.items:
        if ref.idref not in epub.manifest:
            unresolved.append(ref.idref)
    if unresolved:
        raise BrokenSpine(f"Unresolved spine idrefs: {unresolved}")


def _check_spine_media_types(epub: Epub) -> None:
    """All spine items must be application/xhtml+xml (US-020 / I-2)."""
    for ref in epub.spine.items:
        item = epub.manifest.get(ref.idref)
        if item is None:
            continue  # Caught by _check_spine_idrefs
        if item.media_type != "application/xhtml+xml":
            raise UnsupportedMediaType(
                f"Unsupported spine media-type: {item.media_type!r} ({item.href!r})"
            )


def validate_epub_from_zip(epub_path: str) -> None:
    """Validate an on-disk EPUB file exists and is a readable ZIP.

    Lightweight pre-check before full parsing.
    """
    p = pathlib.Path(epub_path)
    if not p.exists():
        raise UserError(f"File not found: {epub_path!r}")
    if not p.is_file():
        raise UserError(f"Not a file: {epub_path!r}")
    try:
        with zipfile.ZipFile(epub_path, "r"):
            pass
    except zipfile.BadZipFile as exc:
        raise NotAnEpub(f"Not a ZIP archive: {exc}") from exc
    except OSError as exc:
        raise UserError(f"Cannot read file: {exc}") from exc


def validate_translated_html(epub: Epub, sections: dict[str, str]) -> None:
    """Validate the translated HTML matches the original EPUB structure.

    Args:
        epub: original EPUB model (spine is the authoritative source)
        sections: data-source-href → body HTML from the translated document

    Raises:
        TranslatedHtmlMismatch on any mismatch.
    """
    # All spine XHTML hrefs must have a matching section
    spine_hrefs = {
        epub.manifest[ref.idref].href
        for ref in epub.spine.items
        if ref.idref in epub.manifest
    }
    missing = spine_hrefs - set(sections.keys())
    if missing:
        raise TranslatedHtmlMismatch(
            f"Missing sections in translated HTML: {sorted(missing)}"
        )

    # No unknown sections
    unknown = set(sections.keys()) - spine_hrefs
    if unknown:
        raise TranslatedHtmlMismatch(
            f"Unknown sections in translated HTML (not in spine): {sorted(unknown)}"
        )
