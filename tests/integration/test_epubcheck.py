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

from epub_deepl_prepare.cli import main as cli_main

_EPUBCHECK = shutil.which("epubcheck")
_MSG_PATTERN = re.compile(
    r"(?P<f>\d+) fatals?\s*/\s*(?P<e>\d+) errors?\s*/\s*(?P<w>\d+) warnings?"
)

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
    rc = cli_main(
        ["restore", str(input_epub), str(prepared_html), "--output", str(out_epub)]
    )
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
    assert in_counts == out_counts, (
        f"epubcheck drift: IN={in_counts} OUT={out_counts}"
    )


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
    assert in_counts == out_counts, (
        f"{corpus_epub.name}: IN={in_counts} OUT={out_counts}"
    )
