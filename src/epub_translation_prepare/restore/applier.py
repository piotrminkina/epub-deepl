"""Apply translated content to an Epub model and write the output EPUB.

Restore flow (tech-spec §5):
  1. Parse translated HTML → TranslatedDoc
  2. Validate sections match spine
  3. Apply: update xhtmls, metadata, NCX labels
  4. Write ZIP via writer.write_epub_bytes / write_epub
"""

from __future__ import annotations

from epub_translation_prepare.epub.model import Epub, NavPoint
from epub_translation_prepare.epub.ncx import resolve_label
from epub_translation_prepare.epub.validator import validate_translated_html
from epub_translation_prepare.epub.writer import write_epub, write_epub_bytes
from epub_translation_prepare.epub.xhtml import replace_body_content
from epub_translation_prepare.errors import TranslatedHtmlMismatch
from epub_translation_prepare.logging_setup import get_logger
from epub_translation_prepare.restore.parser import TranslatedDoc

_log = get_logger("restore.applier")


def apply_and_write(
    epub: Epub,
    doc: TranslatedDoc,
    target_language: str,
    output_path: str,
) -> None:
    """Apply translated content and write the output EPUB to output_path."""
    updated_xhtml, ncx_labels, doc_title = _apply(epub, doc, target_language)
    write_epub(
        epub=epub,
        output_path=output_path,
        updated_xhtml_bytes=updated_xhtml,
        new_metadata_titles=doc.titles or epub.metadata.titles,
        new_metadata_descriptions=doc.descriptions or epub.metadata.descriptions,
        new_metadata_subjects=doc.subjects or epub.metadata.subjects,
        target_language=target_language,
        new_ncx_labels=ncx_labels,
        new_doc_title=doc_title,
    )


def apply_and_write_bytes(
    epub: Epub,
    doc: TranslatedDoc,
    target_language: str,
) -> bytes:
    """Apply translated content and return the output EPUB as bytes (for testing)."""
    updated_xhtml, ncx_labels, doc_title = _apply(epub, doc, target_language)
    return write_epub_bytes(
        epub=epub,
        updated_xhtml_bytes=updated_xhtml,
        new_metadata_titles=doc.titles or epub.metadata.titles,
        new_metadata_descriptions=doc.descriptions or epub.metadata.descriptions,
        new_metadata_subjects=doc.subjects or epub.metadata.subjects,
        target_language=target_language,
        new_ncx_labels=ncx_labels,
        new_doc_title=doc_title,
    )


def _apply(
    epub: Epub,
    doc: TranslatedDoc,
    target_language: str,
) -> tuple[dict[str, bytes], dict[str, str], str]:
    """Core application logic.

    Returns:
        updated_xhtml: href → updated bytes
        ncx_labels: nav_id → resolved label text
        doc_title: new docTitle string for NCX
    """
    # Validate sections match spine
    validate_translated_html(epub, doc.sections)

    # Validate metadata field counts match (tech-spec §5.3)
    _validate_metadata_counts(epub, doc)

    # 1. Build updated XHTML bytes (replace body content)
    updated_xhtml: dict[str, bytes] = {}
    for href, translated_body in doc.sections.items():
        xhtml_file = epub.xhtmls.get(href)
        if xhtml_file is None:
            raise TranslatedHtmlMismatch(f"Section href not in epub.xhtmls: {href!r}")
        updated_bytes = replace_body_content(xhtml_file.raw_bytes, translated_body)
        updated_xhtml[href] = updated_bytes
        # Update the model in place so anchor resolution uses translated text
        xhtml_file.raw_bytes = updated_bytes

    # 2. Compute NCX labels via anchor resolution
    ncx_labels: dict[str, str] = {}
    doc_title = ""

    if epub.ncx is not None:
        # Determine doc_title from translated HTML or fallback to first title
        doc_title = doc.ncx_doctitle or (doc.titles[0] if doc.titles else epub.ncx.doc_title)

        # Compute labels for all nav points (recursive)
        _resolve_all_labels(
            epub.ncx.nav_map,
            ncx_href_in_zip=epub.ncx.ncx_href_in_zip,
            opf_dir=epub.opf_dir,
            epub=epub,
            flat_labels=doc.nav_labels,
            out=ncx_labels,
        )

    return updated_xhtml, ncx_labels, doc_title


def _validate_metadata_counts(epub: Epub, doc: TranslatedDoc) -> None:
    """Raise TranslatedHtmlMismatch if translatable field counts differ.

    Per tech-spec §5.3: if counts differ, restore cannot safely map
    translated values back to original positions.
    """
    checks = [
        ("titles", epub.metadata.titles, doc.titles),
        ("descriptions", epub.metadata.descriptions, doc.descriptions),
        ("subjects", epub.metadata.subjects, doc.subjects),
    ]
    for field_name, original, translated in checks:
        if translated and len(original) != len(translated):
            raise TranslatedHtmlMismatch(
                f"{field_name} count mismatch: "
                f"input has {len(original)}, translated has {len(translated)}"
            )


def _resolve_all_labels(
    nav_points: list[NavPoint],
    ncx_href_in_zip: str,
    opf_dir: str,
    epub: Epub,
    flat_labels: dict[str, str],
    out: dict[str, str],
) -> None:
    """Recursively resolve labels for all nav points."""
    for np in nav_points:
        try:
            label = resolve_label(
                nav_point=np,
                ncx_href_in_zip=ncx_href_in_zip,
                opf_dir=opf_dir,
                epub=epub,
                flat_labels=flat_labels,
            )
        except Exception as exc:
            _log.warning("Anchor resolution failed for nav_id=%r: %s", np.nav_id, exc)
            label = flat_labels.get(np.nav_id, np.label)
        out[np.nav_id] = label
        if np.children:
            _resolve_all_labels(
                np.children,
                ncx_href_in_zip=ncx_href_in_zip,
                opf_dir=opf_dir,
                epub=epub,
                flat_labels=flat_labels,
                out=out,
            )
