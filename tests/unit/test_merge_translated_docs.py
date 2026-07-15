"""Tests for `merge_translated_docs` (WP3/WP6 of the auto-split feature).

`merge_translated_docs` reassembles one `TranslatedDoc` from the
`(path, TranslatedDoc)` pairs produced by parsing each part of a split
payload. A single doc passes through unchanged and silent. With multiple
docs: sections are unioned (duplicate href → `TranslatedHtmlMismatch`);
the metadata trio, the NCX block, and `html_lang` each use first-non-empty-
carrier-wins with a WARN on any extra carrier; and the advisory
`part_index`/`parts_total` markers are sanity-checked WARN-only, never
raised — the real completeness gate lives in
`validator.validate_translated_html`'s section-vs-spine set equality, not
here. See docs/adr/0006 and `restore/parser.py::merge_translated_docs`.
"""

from __future__ import annotations

import logging

import pytest

from epub_deepl.errors import TranslatedHtmlMismatch
from epub_deepl.restore.parser import TranslatedDoc, merge_translated_docs

_LOGGER_NAME = "epub_deepl.restore.parser"


# ---------------------------------------------------------------------------
# Single-doc passthrough
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_single_doc_passes_through_unchanged_and_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc = TranslatedDoc(
        titles=["T"],
        sections={"ch01.xhtml": "<p>x</p>"},
        html_lang="en",
        part_index=1,
        parts_total=1,
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc)])
    assert merged is doc
    assert caplog.records == []


@pytest.mark.unit
def test_single_doc_without_any_part_markers_stays_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Team-lead's binding resolution for BLOCK cycle 1: the single-doc
    fast path's new WARN-on-marker-mismatch behavior must not regress the
    far more common case -- an ordinary, never-split payload restored from
    exactly one file, carrying no part markers at all. `_check_part_markers`
    is silent whenever no doc carries a marker; this pins that today's
    silence for the no-markers case is unaffected by the fix."""
    doc = TranslatedDoc(sections={"ch01.xhtml": "a"})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("book.html", doc)])

    assert merged is doc
    assert caplog.records == []


@pytest.mark.unit
def test_single_doc_with_mismatching_parts_total_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression test (BLOCK cycle 1, task #22): a lone file whose own
    `data-parts-total` disagrees with the single-file count it was given to
    restore -- e.g. the user forgot a part -- must still surface the
    advisory WARN. The `len(docs) == 1` fast path previously returned
    before `_check_part_markers` ran at all, so the single most likely real
    user mistake silently degraded to the generic completeness error with
    no specific diagnostic."""
    doc = TranslatedDoc(sections={"ch01.xhtml": "a"}, part_index=1, parts_total=2)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc)])

    assert merged is doc
    assert any("file(s) were given" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Section union / duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_multiple_docs_union_sections_across_parts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "<p>one</p>"})
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "<p>two</p>"})
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])
    assert merged.sections == {"ch01.xhtml": "<p>one</p>", "ch02.xhtml": "<p>two</p>"}
    assert caplog.records == []


@pytest.mark.unit
def test_duplicate_href_across_parts_raises_translated_html_mismatch() -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "<p>a</p>"})
    doc2 = TranslatedDoc(sections={"ch01.xhtml": "<p>b</p>"})

    with pytest.raises(TranslatedHtmlMismatch) as exc_info:
        merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])
    message = str(exc_info.value)
    assert "ch01.xhtml" in message
    assert "part1.html" in message
    assert "part2.html" in message


# ---------------------------------------------------------------------------
# Metadata trio: first carrier wins, extra carrier WARNs
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("field", ["titles", "descriptions", "subjects"])
def test_metadata_field_first_carrier_wins_and_extra_carrier_warns(
    field: str, caplog: pytest.LogCaptureFixture
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, **{field: ["first"]})
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, **{field: ["second"]})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert getattr(merged, field) == ["first"]
    assert any(
        field in record.getMessage() and "part2.html" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.unit
def test_metadata_field_absent_from_all_parts_stays_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"})
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert merged.titles == []
    assert merged.descriptions == []
    assert merged.subjects == []
    assert caplog.records == []


# ---------------------------------------------------------------------------
# NCX block: first carrier wins, extra carrier WARNs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ncx_block_first_carrier_wins_and_extra_carrier_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(
        sections={"ch01.xhtml": "a"},
        ncx_doctitle="Book",
        nav_labels={"navPoint-1": "One"},
    )
    doc2 = TranslatedDoc(
        sections={"ch02.xhtml": "b"},
        ncx_doctitle="Other",
        nav_labels={"navPoint-2": "Two"},
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert merged.ncx_doctitle == "Book"
    assert merged.nav_labels == {"navPoint-1": "One"}
    assert any(
        "NCX" in record.getMessage() and "part2.html" in record.getMessage()
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# html_lang: first non-None wins, conflict WARNs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_html_lang_first_non_none_wins_and_conflict_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, html_lang="en")
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, html_lang="de")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert merged.html_lang == "en"
    assert any("--lang" in record.getMessage() for record in caplog.records)


@pytest.mark.unit
def test_html_lang_only_second_doc_sets_it_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, html_lang=None)
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, html_lang="fr")

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merged = merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert merged.html_lang == "fr"
    assert caplog.records == []


# ---------------------------------------------------------------------------
# Part-marker sanity checks: WARN only, never raise
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_part_markers_agreeing_totals_and_contiguous_indices_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, part_index=1, parts_total=2)
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, part_index=2, parts_total=2)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert caplog.records == []


@pytest.mark.unit
def test_part_markers_disagreeing_totals_warns_but_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, part_index=1, parts_total=2)
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, part_index=2, parts_total=3)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert any("disagrees" in record.getMessage() for record in caplog.records)


@pytest.mark.unit
def test_part_markers_total_mismatching_file_count_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both parts agree `parts_total=3`, but only two files were given to
    restore — e.g. the user lost or forgot to pass the third part."""
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, part_index=1, parts_total=3)
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, part_index=2, parts_total=3)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert any("file(s) were given" in record.getMessage() for record in caplog.records)


@pytest.mark.unit
def test_part_markers_noncontiguous_indices_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A gap in the `data-part` sequence (1, 3 — missing 2) is WARNed."""
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"}, part_index=1, parts_total=None)
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"}, part_index=3, parts_total=None)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert any("contiguous" in record.getMessage() for record in caplog.records)


@pytest.mark.unit
def test_part_markers_absent_from_every_part_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No `data-part`/`data-parts-total` anywhere — nothing to sanity-check,
    so no warning is emitted (the markers are purely advisory)."""
    doc1 = TranslatedDoc(sections={"ch01.xhtml": "a"})
    doc2 = TranslatedDoc(sections={"ch02.xhtml": "b"})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        merge_translated_docs([("part1.html", doc1), ("part2.html", doc2)])

    assert caplog.records == []
