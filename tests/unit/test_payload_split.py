"""Identity tests for the payload-plan refactor (WP1 of the auto-split feature).

`build()` is now `_render_single(_build_plan(epub))`. These tests pin the
composition two independent ways: (1) manually reassembling the plan's own
parts (`envelope_open` + `preamble` + section htmls + `envelope_close`) and
comparing against `build()`'s output by string equality, bypassing
`_render_single` entirely so a future bug there can't hide from this test;
and (2) the trivial contract that `_render_single(_build_plan(e))` and
`build(e)` are the same call by construction. WP2 will extend this file with
the actual multi-part split tests (`build_split`) — see docs/adr/0006.
"""

from __future__ import annotations

import pytest

from epub_deepl.epub.reader import read_epub_bytes
from epub_deepl.merge.builder import _build_plan, _render_single, build
from tests.fixtures.minimal import build_minimal_epub


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
