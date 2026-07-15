"""Identity tests for the payload-plan refactor (WP1 of the auto-split feature),
plus the `build_split` packing/marker/error-path tests (WP2/WP6) — see
docs/adr/0006.

`build()` is now `_render_single(_build_plan(epub))`. The first block of
tests pins the composition two independent ways: (1) manually reassembling
the plan's own parts (`envelope_open` + `preamble` + section htmls +
`envelope_close`) and comparing against `build()`'s output by string
equality, bypassing `_render_single` entirely so a future bug there can't
hide from this test; and (2) the trivial contract that
`_render_single(_build_plan(e))` and `build(e)` are the same call by
construction.

The second block exercises `build_split`: passthrough cases (disabled,
fits-as-single, exact-boundary), forced multi-part splitting with its
invariants (budget respected, markers correct, preamble first-part-only,
no section lost/duplicated/reordered), and the `OversizedSection` error
path. These tests favour asserting invariants over hardcoding expected part
counts, since the exact packing depends on rendered section/envelope/
preamble lengths that are implementation details, not part of the contract.
"""

from __future__ import annotations

import re

import pytest

from epub_deepl.epub.reader import read_epub_bytes
from epub_deepl.errors import InternalError, OversizedSection
from epub_deepl.merge.builder import (
    _PART_MARKER_RESERVE,
    _build_plan,
    _render_single,
    build,
    build_split,
)
from tests.fixtures.minimal import NavPointSpec, XhtmlSpec, build_minimal_epub


def _assemble(plan) -> str:  # type: ignore[no-untyped-def]
    """Reassemble a `_PayloadPlan` into one document without using `_render_single`."""
    return (
        plan.envelope_open
        + plan.preamble
        + "".join(section.html for section in plan.sections)
        + plan.envelope_close
    )


@pytest.mark.unit
def test_build_matches_assembled_plan_parts_epub2_default(synth_epub_bytes: bytes) -> None:
    """EPUB 2 default fixture: build() == envelope_open + preamble + sections + envelope_close."""
    epub = read_epub_bytes(synth_epub_bytes)
    plan = _build_plan(epub)
    assert build(epub) == _assemble(plan)


@pytest.mark.unit
def test_build_matches_assembled_plan_parts_epub3_both_navs(synth_epub3_bytes: bytes) -> None:
    """EPUB 3 fixture with both NCX and a non-spine nav doc present."""
    epub = read_epub_bytes(synth_epub3_bytes)
    assert epub.ncx is not None
    assert epub.nav_doc is not None and not epub.nav_doc.in_spine

    plan = _build_plan(epub)
    assert build(epub) == _assemble(plan)


@pytest.mark.unit
def test_build_matches_assembled_plan_parts_nav_in_spine() -> None:
    """EPUB 3 fixture where the nav doc is itself a spine item."""
    epub_bytes = build_minimal_epub(epub_version="3.0", nav_in_spine=True)
    epub = read_epub_bytes(epub_bytes)
    assert epub.nav_doc is not None and epub.nav_doc.in_spine

    plan = _build_plan(epub)
    assert build(epub) == _assemble(plan)


@pytest.mark.unit
@pytest.mark.parametrize(
    "epub_bytes_fixture",
    ["synth_epub_bytes", "synth_epub3_bytes"],
)
def test_render_single_of_build_plan_equals_build(
    epub_bytes_fixture: str, request: pytest.FixtureRequest
) -> None:
    """`_render_single(_build_plan(e)) == build(e)` trivially holds by construction."""
    epub_bytes: bytes = request.getfixturevalue(epub_bytes_fixture)
    epub = read_epub_bytes(epub_bytes)
    assert _render_single(_build_plan(epub)) == build(epub)


# ---------------------------------------------------------------------------
# build_split: passthrough cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("max_chars", [0, -1, -100])
def test_build_split_disabled_returns_single_identical_to_build(
    synth_epub_bytes: bytes, max_chars: int
) -> None:
    """`max_chars <= 0` disables splitting: byte-identical single-file output,
    exactly as today (binding user decision from docs/adr/0006)."""
    epub = read_epub_bytes(synth_epub_bytes)
    assert build_split(epub, max_chars=max_chars) == [build(epub)]


@pytest.mark.unit
def test_build_split_default_max_chars_fits_as_single(synth_epub3_bytes: bytes) -> None:
    """A payload that already fits under the default budget stays a single,
    byte-identical file — the default DEFAULT_MAX_CHARS path."""
    epub = read_epub_bytes(synth_epub3_bytes)
    assert build_split(epub) == [build(epub)]


@pytest.mark.unit
def test_build_split_exact_boundary_equal_to_max_chars_stays_single() -> None:
    """`len(single) == max_chars` must still take the single-file path (the
    packing check is `<=`, not `<`)."""
    epub_bytes = build_minimal_epub(
        xhtmls=[XhtmlSpec(href="ch01.xhtml", title="Chapter 1", body_html="<p>Hello.</p>")]
    )
    epub = read_epub_bytes(epub_bytes)
    single = build(epub)
    assert build_split(epub, max_chars=len(single)) == [single]


# ---------------------------------------------------------------------------
# build_split: forced multi-part splitting
# ---------------------------------------------------------------------------


def _wide_epub_bytes(n_chapters: int = 5, filler: int = 400) -> bytes:
    """A synthetic EPUB 3 with `n_chapters`, each padded to `filler` chars,
    sized so a small `max_chars` reliably forces `build_split` into more
    than one part without tripping `OversizedSection`.

    Passes an explicit `nav_map` (one entry per chapter, no fragment) —
    `build_minimal_epub`'s auto-derivation falls back to a hardcoded
    3-entry template referencing `#ch1-heading`/`#ch2-heading`/
    `#ch3-heading` once `len(xhtmls) >= 3`, anchors that don't exist in
    these padded bodies.
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


@pytest.mark.unit
def test_build_split_forces_multiple_parts_within_budget() -> None:
    """A small enough `max_chars` forces >1 parts, and every returned part
    stays within that budget."""
    epub = read_epub_bytes(_wide_epub_bytes())
    plan = _build_plan(epub)
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    # Big enough for exactly two sections per part, forcing several parts
    # across five chapters.
    # Use the LARGEST section, not sections[0] -- for this EPUB 3 fixture,
    # section 0 is the (small) non-spine nav doc, not a chapter, and sizing
    # off it would starve the budget for the actual chapters.
    max_section_len = max(len(section.html) for section in plan.sections)
    max_chars = envelope_len + _PART_MARKER_RESERVE + len(plan.preamble) + 2 * max_section_len

    parts = build_split(epub, max_chars=max_chars)

    assert len(parts) > 1
    for part_html in parts:
        assert len(part_html) <= max_chars


@pytest.mark.unit
def test_build_split_preserves_section_order_without_loss_or_duplication() -> None:
    """Every section appears in exactly one part, in original spine order —
    packing must never drop, duplicate, or reorder a section."""
    epub = read_epub_bytes(_wide_epub_bytes())
    plan = _build_plan(epub)
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    # Use the LARGEST section, not sections[0] -- for this EPUB 3 fixture,
    # section 0 is the (small) non-spine nav doc, not a chapter, and sizing
    # off it would starve the budget for the actual chapters.
    max_section_len = max(len(section.html) for section in plan.sections)
    max_chars = envelope_len + _PART_MARKER_RESERVE + len(plan.preamble) + 2 * max_section_len

    parts = build_split(epub, max_chars=max_chars)
    assert len(parts) > 1

    hrefs_seen: list[str] = []
    for part_html in parts:
        hrefs_seen.extend(re.findall(r'data-source-href="([^"]+)"', part_html))
    assert hrefs_seen == [section.href for section in plan.sections]


@pytest.mark.unit
def test_build_split_parts_carry_correct_data_part_markers() -> None:
    """Each part's `<body>` carries `data-part="i"` / `data-parts-total="n"`
    matching its 1-based position, once split into more than one part."""
    epub = read_epub_bytes(_wide_epub_bytes())
    plan = _build_plan(epub)
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    # Use the LARGEST section, not sections[0] -- for this EPUB 3 fixture,
    # section 0 is the (small) non-spine nav doc, not a chapter, and sizing
    # off it would starve the budget for the actual chapters.
    max_section_len = max(len(section.html) for section in plan.sections)
    max_chars = envelope_len + _PART_MARKER_RESERVE + len(plan.preamble) + 2 * max_section_len

    parts = build_split(epub, max_chars=max_chars)
    n = len(parts)
    assert n > 1

    for i, part_html in enumerate(parts, start=1):
        assert f'data-part="{i}" data-parts-total="{n}"' in part_html


@pytest.mark.unit
def test_build_split_single_part_has_no_part_markers(synth_epub_bytes: bytes) -> None:
    """A single-part result (no split) reproduces the historical unmarked
    `<body>\\n` — no `data-part` attribute at all."""
    epub = read_epub_bytes(synth_epub_bytes)
    (single,) = build_split(epub)
    assert "data-part=" not in single
    assert "<body>\n" in single


@pytest.mark.unit
def test_build_split_preamble_appears_only_in_first_part() -> None:
    """The OPF-metadata header + NCX nav block belong to part 1 only — later
    parts must not repeat them."""
    epub = read_epub_bytes(_wide_epub_bytes())
    plan = _build_plan(epub)
    assert plan.preamble  # sanity: this fixture actually has a preamble
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    # Use the LARGEST section, not sections[0] -- for this EPUB 3 fixture,
    # section 0 is the (small) non-spine nav doc, not a chapter, and sizing
    # off it would starve the budget for the actual chapters.
    max_section_len = max(len(section.html) for section in plan.sections)
    max_chars = envelope_len + _PART_MARKER_RESERVE + len(plan.preamble) + 2 * max_section_len

    parts = build_split(epub, max_chars=max_chars)
    assert len(parts) > 1

    assert plan.preamble in parts[0]
    for part_html in parts[1:]:
        assert plan.preamble not in part_html


# ---------------------------------------------------------------------------
# build_split: OversizedSection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_split_oversized_section_raises_naming_href() -> None:
    """A single section that alone exceeds a fresh part's budget raises
    `OversizedSection` naming the offending href, with remediation advice."""
    epub_bytes = build_minimal_epub(
        xhtmls=[
            XhtmlSpec(
                href="ch01.xhtml",
                title="Chapter 1",
                body_html=f"<p>{'Y' * 2000}</p>",
            )
        ]
    )
    epub = read_epub_bytes(epub_bytes)

    with pytest.raises(OversizedSection, match=re.escape("ch01.xhtml")) as exc_info:
        build_split(epub, max_chars=100)
    assert "--max-chars" in str(exc_info.value)


# ---------------------------------------------------------------------------
# build_split: InternalError defensive post-check
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_split_internal_error_when_marker_reserve_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive post-check: if a packed part's *actual* rendered length
    (including its data-part/data-parts-total marker overhead) exceeds
    --max-chars despite fitting the section-only budget, build_split must
    raise InternalError rather than silently emit an oversized part. This
    is a packing-bug guard, not a reachable user-facing scenario under the
    real _PART_MARKER_RESERVE=64 -- exercised here by monkeypatching the
    reserve down to 0 so the (normally-covered) marker-attribute overhead
    is no longer budgeted for."""
    import epub_deepl.merge.builder as builder_mod

    epub_bytes = build_minimal_epub(
        xhtmls=[
            XhtmlSpec(href="ch01.xhtml", title="Chapter 1", body_html=f"<p>{'A' * 2000}</p>"),
            XhtmlSpec(href="ch02.xhtml", title="Chapter 2", body_html=f"<p>{'B' * 100}</p>"),
        ]
    )
    epub = read_epub_bytes(epub_bytes)
    plan = _build_plan(epub)
    envelope_len = len(plan.envelope_open) + len(plan.envelope_close)
    sec1_len = len(plan.sections[0].html)

    monkeypatch.setattr(builder_mod, "_PART_MARKER_RESERVE", 0)
    # Exact fit for part 1 with a zero reserve -- no slack left to absorb
    # the marker-attribute overhead the reserve normally covers.
    max_chars = envelope_len + len(plan.preamble) + sec1_len

    with pytest.raises(InternalError, match="packing bug"):
        builder_mod.build_split(epub, max_chars=max_chars)
