"""Automated `epubcheck` validation tests.

These tests shell out to the W3C `epubcheck` binary and are gated by the
``@pytest.mark.epubcheck`` marker. They skip cleanly when the binary is
absent so the suite remains runnable on stripped-down dev hosts.

The binding assertion is **zero drift**: for every input EPUB that has
been round-tripped without translation, the output must have the same
fatal/error/warning counts as the input. The tool MUST NOT introduce
new validation errors. It is permitted (and expected) for the tool to
*preserve* errors that were already present in the input — those are
the publisher's responsibility, not ours.

Two real-world bug classes (SVG attribute case, UTF-8 mojibake) shipped
to the first restore precisely because `epubcheck` was a manual-only
gate. These tests close that gap.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

from epub_deepl.cli import main as cli_main
from tests.fixtures.minimal import NavPointSpec, XhtmlSpec, build_minimal_epub

_EPUBCHECK = shutil.which("epubcheck")
_MSG_PATTERN = re.compile(r"(?P<f>\d+) fatals?\s*/\s*(?P<e>\d+) errors?\s*/\s*(?P<w>\d+) warnings?")

pytestmark = pytest.mark.epubcheck


def _epubcheck_counts(epub_path: pathlib.Path) -> tuple[int, int, int]:
    """Return (fatals, errors, warnings) reported by `epubcheck` on
    ``epub_path``. Raises ``RuntimeError`` if the output cannot be
    parsed — never silently returns zeros, because that would be
    indistinguishable from a clean pass.
    """
    if _EPUBCHECK is None:  # pragma: no cover — guarded by pytest skip
        raise RuntimeError("epubcheck binary not on PATH")
    proc = subprocess.run(
        [_EPUBCHECK, str(epub_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    # epubcheck writes the summary to stderr regardless of exit code
    combined = proc.stderr + proc.stdout
    match = _MSG_PATTERN.search(combined)
    if match is None:
        raise RuntimeError(
            f"could not parse epubcheck output for {epub_path}:\n"
            f"--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
        )
    return int(match["f"]), int(match["e"]), int(match["w"])


def _roundtrip_without_translation(
    input_epub: pathlib.Path,
    tmp_path: pathlib.Path,
) -> pathlib.Path:
    """Prepare → restore (same language) → return path to restored EPUB."""
    prepared_html = tmp_path / f"{input_epub.stem}.prepare.html"
    out_epub = tmp_path / f"{input_epub.stem}.translated.epub"
    rc = cli_main(["prepare", str(input_epub), "--output", str(prepared_html)])
    assert rc == 0, "prepare failed"
    # `restore` auto-detects target lang from <html lang> which the prepared
    # HTML inherited from the input's <dc:language>. Drift WARN expected.
    rc = cli_main(["restore", str(input_epub), str(prepared_html), "--output", str(out_epub)])
    assert rc == 0, "restore failed"
    return out_epub


def _wide_epub_bytes_for_split(n_chapters: int = 5, filler: int = 400) -> bytes:
    """A synthetic EPUB 3 with `n_chapters`, each padded to `filler` chars,
    sized so a modest `--max-chars` reliably forces `prepare` to split.

    Passes an explicit `nav_map` (one entry per chapter, no fragment) —
    `build_minimal_epub`'s auto-derivation falls back to a hardcoded
    3-entry template referencing `#ch1-heading`/`#ch2-heading`/
    `#ch3-heading` once `len(xhtmls) >= 3`, anchors that don't exist in
    these padded bodies. Unlike the unit/CLI test suites, a *real*
    epubcheck run would flag those as dangling internal references, so
    the fix must be baked in here rather than discovered after the fact.
    """
    xhtmls = [
        XhtmlSpec(
            href=f"ch{i:02d}.xhtml",
            title=f"Chapter {i}",
            body_html=f"<p>{'X' * filler}</p>",
        )
        for i in range(1, n_chapters + 1)
    ]
    nav_map = [
        NavPointSpec(label=f"Chapter {i}", src=f"ch{i:02d}.xhtml", nav_id=f"navPoint-{i}")
        for i in range(1, n_chapters + 1)
    ]
    return build_minimal_epub(epub_version="3.0", xhtmls=xhtmls, nav_map=nav_map)


def _max_chars_forcing_split(epub_bytes: bytes) -> int:
    """Compute --max-chars from the payload's own measured envelope/
    preamble/section lengths (rather than a guessed constant) so packing
    reliably yields >1 parts — same technique as
    tests/unit/test_payload_split.py."""
    from epub_deepl.epub.reader import read_epub_bytes
    from epub_deepl.merge.builder import _PART_MARKER_RESERVE, _build_plan

    epub = read_epub_bytes(epub_bytes)
    plan = _build_plan(epub)
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    # Use the LARGEST section, not sections[0] -- for an EPUB 3 fixture,
    # section 0 is often the (small) non-spine nav doc, not a chapter, and
    # sizing off it would starve the budget for the actual chapters.
    max_section_len = max(len(section.html) for section in plan.sections)
    return envelope_len + _PART_MARKER_RESERVE + len(plan.preamble) + 2 * max_section_len


def _split_roundtrip_without_translation(
    input_epub: pathlib.Path,
    tmp_path: pathlib.Path,
    max_chars: int,
) -> pathlib.Path:
    """Prepare (forced split via --max-chars) → restore (same language,
    all parts) → return path to restored EPUB. Mirrors
    `_roundtrip_without_translation` but exercises the split/merge path
    end-to-end through the real CLI, including on-disk part discovery.
    """
    output = tmp_path / f"{input_epub.stem}.prepare.html"
    out_epub = tmp_path / f"{input_epub.stem}.translated.epub"
    rc = cli_main(
        ["prepare", str(input_epub), "--output", str(output), "--max-chars", str(max_chars)]
    )
    assert rc == 0, "prepare failed"
    assert not output.exists(), "base output must not exist once prepare has split the payload"

    parts = sorted(tmp_path.glob(f"{output.stem}.*of*{output.suffix}"))
    assert len(parts) > 1, "test setup must actually force a split"

    rc = cli_main(["restore", str(input_epub), *[str(p) for p in parts], "--output", str(out_epub)])
    assert rc == 0, "restore failed"
    return out_epub


@pytest.mark.skipif(_EPUBCHECK is None, reason="epubcheck not installed")
@pytest.mark.integration
def test_roundtrip_zero_epubcheck_drift_synthetic(
    synth_epub_file: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """Round-trip on the synthetic EPUB introduces zero new
    epubcheck-reported issues.
    """
    in_counts = _epubcheck_counts(synth_epub_file)
    out_path = _roundtrip_without_translation(synth_epub_file, tmp_path)
    out_counts = _epubcheck_counts(out_path)
    assert in_counts == out_counts, f"epubcheck drift: IN={in_counts} OUT={out_counts}"


@pytest.mark.skipif(_EPUBCHECK is None, reason="epubcheck not installed")
@pytest.mark.integration
def test_roundtrip_zero_epubcheck_drift_synthetic_epub3(
    synth_epub3_file: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """Round-trip on a synthetic EPUB 3 (NCX + non-spine nav doc) introduces
    zero new epubcheck-reported issues — the EPUB 3 counterpart of
    test_roundtrip_zero_epubcheck_drift_synthetic.
    """
    in_counts = _epubcheck_counts(synth_epub3_file)
    out_path = _roundtrip_without_translation(synth_epub3_file, tmp_path)
    out_counts = _epubcheck_counts(out_path)
    assert in_counts == out_counts, f"epubcheck drift: IN={in_counts} OUT={out_counts}"


@pytest.mark.skipif(_EPUBCHECK is None, reason="epubcheck not installed")
@pytest.mark.integration
def test_roundtrip_zero_epubcheck_drift_synthetic_epub3_landmarks_page_list(
    tmp_path: pathlib.Path,
) -> None:
    """Round-trip on a synthetic EPUB 3 with both NCX and a nav doc carrying
    landmarks + page-list navs (US-008's translate="no" exclusion) introduces
    zero new epubcheck-reported issues.
    """
    epub_path = tmp_path / "epub3_landmarks_pagelist.epub"
    epub_path.write_bytes(
        build_minimal_epub(epub_version="3.0", nav_landmarks=True, nav_page_list=True)
    )
    in_counts = _epubcheck_counts(epub_path)
    out_path = _roundtrip_without_translation(epub_path, tmp_path)
    out_counts = _epubcheck_counts(out_path)
    assert in_counts == out_counts, f"epubcheck drift: IN={in_counts} OUT={out_counts}"


@pytest.mark.skipif(_EPUBCHECK is None, reason="epubcheck not installed")
@pytest.mark.integration
def test_roundtrip_zero_epubcheck_drift_synthetic_epub3_nav_only(
    tmp_path: pathlib.Path,
) -> None:
    """Round-trip on a synthetic EPUB 3 with a nav doc only, no NCX (FR-4 nav
    matrix: EPUB 3.x requires the nav doc, NCX is optional), introduces zero
    new epubcheck-reported issues.
    """
    epub_path = tmp_path / "epub3_nav_only.epub"
    epub_path.write_bytes(build_minimal_epub(epub_version="3.0", include_ncx=False))
    in_counts = _epubcheck_counts(epub_path)
    out_path = _roundtrip_without_translation(epub_path, tmp_path)
    out_counts = _epubcheck_counts(out_path)
    assert in_counts == out_counts, f"epubcheck drift: IN={in_counts} OUT={out_counts}"


@pytest.mark.skipif(_EPUBCHECK is None, reason="epubcheck not installed")
@pytest.mark.integration
def test_roundtrip_zero_epubcheck_drift_forced_split(
    tmp_path: pathlib.Path,
) -> None:
    """Round-tripping a payload that `prepare` splits into multiple parts
    (--max-chars forced below the payload size) introduces zero new
    epubcheck-reported issues. Splitting is purely a transport concern; it
    must not corrupt the restored EPUB's structure (dangling anchors,
    broken spine ordering, missing nav entries, etc.).
    """
    epub_bytes = _wide_epub_bytes_for_split()
    max_chars = _max_chars_forcing_split(epub_bytes)

    epub_path = tmp_path / "wide_for_split.epub"
    epub_path.write_bytes(epub_bytes)

    in_counts = _epubcheck_counts(epub_path)
    out_path = _split_roundtrip_without_translation(epub_path, tmp_path, max_chars)
    out_counts = _epubcheck_counts(out_path)
    assert in_counts == out_counts, f"epubcheck drift: IN={in_counts} OUT={out_counts}"


@pytest.mark.skipif(_EPUBCHECK is None, reason="epubcheck not installed")
@pytest.mark.corpus
def test_roundtrip_zero_epubcheck_drift_corpus(
    corpus_epub: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """For every book in the corpus, round-trip preserves the
    epubcheck verdict exactly. SM-4 from the PRD — promoted from a
    manual recipe to an automated assertion.
    """
    in_counts = _epubcheck_counts(corpus_epub)
    out_path = _roundtrip_without_translation(corpus_epub, tmp_path)
    out_counts = _epubcheck_counts(out_path)
    assert in_counts == out_counts, f"{corpus_epub.name}: IN={in_counts} OUT={out_counts}"
