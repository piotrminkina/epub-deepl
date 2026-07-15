"""Apply translated content to an Epub model and write the output EPUB.

Restore flow (tech-spec §5):
  1. Parse translated HTML → TranslatedDoc
  2. Validate sections match spine
  3. Apply: update xhtmls, metadata, NCX labels
  4. Write ZIP via writer.write_epub_bytes / write_epub
"""

from __future__ import annotations

from epub_deepl.epub.model import Epub, NavPoint
from epub_deepl.epub.nav import rebuild_nav_doc_bytes, resolve_nav_labels
from epub_deepl.epub.ncx import resolve_label
from epub_deepl.epub.validator import validate_translated_html
from epub_deepl.epub.writer import write_epub, write_epub_bytes
from epub_deepl.epub.xhtml import replace_body_content
from epub_deepl.errors import TranslatedHtmlMismatch
from epub_deepl.logging_setup import get_logger
from epub_deepl.restore.parser import TranslatedDoc

_log = get_logger("restore.applier")


def apply_and_write(
    epub: Epub,
    doc: TranslatedDoc,
    target_language: str,
    output_path: str,
) -> None:
    """Apply translated content and write the output EPUB to output_path."""
    updated_xhtml, ncx_labels, doc_title, new_nav_doc_bytes = _apply(epub, doc, target_language)
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
        new_nav_doc_bytes=new_nav_doc_bytes,
    )


def apply_and_write_bytes(
    epub: Epub,
    doc: TranslatedDoc,
    target_language: str,
) -> bytes:
    """Apply translated content and return the output EPUB as bytes (for testing)."""
    updated_xhtml, ncx_labels, doc_title, new_nav_doc_bytes = _apply(epub, doc, target_language)
    return write_epub_bytes(
        epub=epub,
        updated_xhtml_bytes=updated_xhtml,
        new_metadata_titles=doc.titles or epub.metadata.titles,
        new_metadata_descriptions=doc.descriptions or epub.metadata.descriptions,
        new_metadata_subjects=doc.subjects or epub.metadata.subjects,
        target_language=target_language,
        new_ncx_labels=ncx_labels,
        new_doc_title=doc_title,
        new_nav_doc_bytes=new_nav_doc_bytes,
    )


def _apply(
    epub: Epub,
    doc: TranslatedDoc,
    target_language: str,
) -> tuple[dict[str, bytes], dict[str, str], str, bytes | None]:
    """Core application logic.

    Returns:
        updated_xhtml: href → updated bytes
        ncx_labels: nav_id → resolved label text
        doc_title: new docTitle string for NCX
        new_nav_doc_bytes: rebuilt EPUB 3 nav document bytes, for a
            *non-spine* nav doc only; None if there is no nav doc, or it is
            in-spine (its bytes are already folded into updated_xhtml then).
    """
    # Validate sections match spine
    validate_translated_html(epub, doc.sections)

    # Validate metadata field counts match (tech-spec §5.3)
    _validate_metadata_counts(epub, doc)

    # The nav doc's own translated body (in-spine or not) is withheld from
    # the generic spine loop below — unlike a plain chapter, its toc labels
    # need the hybrid anchor-resolution overwrite (resolve_nav_labels +
    # rebuild_nav_doc_bytes), not a bare replace_body_content swap.
    sections = dict(doc.sections)
    nav_doc_translated_body: str | None = None
    if epub.nav_doc is not None:
        nav_doc_translated_body = sections.pop(epub.nav_doc.href, None)

    # 1. Build updated XHTML bytes (replace body content)
    updated_xhtml: dict[str, bytes] = {}
    for href, translated_body in sections.items():
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

    # 3. Rebuild the EPUB 3 nav document — toc labels resolved the same way
    # as NCX, against the now-translated spine XHTML files from step 1.
    new_nav_doc_bytes: bytes | None = None
    if epub.nav_doc is not None and nav_doc_translated_body is not None:
        nav_labels = resolve_nav_labels(epub.nav_doc, epub)
        rebuilt_nav_bytes = rebuild_nav_doc_bytes(epub.nav_doc, nav_doc_translated_body, nav_labels)
        if epub.nav_doc.in_spine:
            updated_xhtml[epub.nav_doc.href] = rebuilt_nav_bytes
            nav_xhtml_file = epub.xhtmls.get(epub.nav_doc.href)
            if nav_xhtml_file is not None:
                nav_xhtml_file.raw_bytes = rebuilt_nav_bytes
        else:
            new_nav_doc_bytes = rebuilt_nav_bytes

    return updated_xhtml, ncx_labels, doc_title, new_nav_doc_bytes


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
