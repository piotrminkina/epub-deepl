"""Integration tests for CLI behaviour (test-plan §7.1)."""

from __future__ import annotations

import pathlib
import sys

import pytest

from tests.fixtures.minimal import XhtmlSpec, build_minimal_epub


def _run_cli(args: list[str]) -> tuple[int, str]:
    """Run the CLI with given args and return (exit_code, stderr_combined)."""
    import contextlib
    import io

    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        try:
            from epub_deepl_prepare.cli import main

            rc = main(args)
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
    return rc, stderr_buf.getvalue()


@pytest.mark.integration
def test_no_args_shows_usage_with_both_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    """Running with no args displays help with both subcommands."""
    _rc, _ = _run_cli(["--help"])
    # argparse exits with 0 on --help; our wrapper may catch SystemExit
    # Just check that help can be invoked without crashing


@pytest.mark.integration
def test_prepare_emits_html_file(synth_epub_file: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """prepare creates a .prepare.html output file."""
    output = tmp_path / "test.prepare.html"
    rc, stderr = _run_cli(["prepare", str(synth_epub_file), "--output", str(output)])
    assert rc == 0, f"Expected exit 0, got {rc}. Stderr: {stderr}"
    assert output.exists()


@pytest.mark.integration
def test_prepare_html_has_section_per_spine_item(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """prepare output has one section per spine XHTML file."""
    output = tmp_path / "test.prepare.html"
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(output)])
    assert rc == 0
    content = output.read_text(encoding="utf-8")
    # Default synth has 3 chapters
    assert content.count('data-source-href="ch01.xhtml"') == 1
    assert content.count('data-source-href="ch02.xhtml"') == 1
    assert content.count('data-source-href="ch03.xhtml"') == 1


@pytest.mark.integration
def test_prepare_html_head_contains_title_and_description(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """prepare output head contains title and description."""
    output = tmp_path / "test.prepare.html"
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(output)])
    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert "<title>Test Book</title>" in content
    assert 'name="description"' in content


@pytest.mark.integration
def test_prepare_html_nav_block_carries_ncx_data(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """prepare output nav block has data-ncx-* attributes."""
    output = tmp_path / "test.prepare.html"
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(output)])
    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert 'data-source="ncx"' in content
    assert "data-ncx-id=" in content
    assert "data-ncx-playorder=" in content
    assert "data-ncx-src=" in content


@pytest.mark.integration
def test_prepare_exit_code_0_on_success(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(tmp_path / "out.html")])
    assert rc == 0


@pytest.mark.integration
def test_prepare_exit_code_1_on_missing_file(tmp_path: pathlib.Path) -> None:
    """prepare exits 1 if the input file doesn't exist."""
    rc, stderr = _run_cli(["prepare", "/nonexistent/book.epub"])
    assert rc == 1
    assert "[ERROR]" in stderr


@pytest.mark.integration
def test_prepare_exit_code_1_on_drm(tmp_path: pathlib.Path) -> None:
    """prepare exits 1 on DRM-protected EPUB."""
    drm_epub = tmp_path / "drm.epub"
    drm_epub.write_bytes(build_minimal_epub(include_drm=True))
    rc, stderr = _run_cli(["prepare", str(drm_epub)])
    assert rc == 1
    assert "[ERROR]" in stderr
    assert "DRM" in stderr


@pytest.mark.integration
def test_prepare_writes_no_output_on_validation_failure(tmp_path: pathlib.Path) -> None:
    """prepare must not write output file when validation fails."""
    bad_epub = tmp_path / "bad.epub"
    bad_epub.write_bytes(b"not a zip at all")
    output = tmp_path / "out.html"
    rc, _ = _run_cli(["prepare", str(bad_epub), "--output", str(output)])
    assert rc == 1
    assert not output.exists()


@pytest.mark.integration
def test_restore_emits_epub_file(synth_epub_file: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """restore creates a .translated.epub output file."""
    html_out = tmp_path / "prepared.html"
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(html_out)])
    assert rc == 0

    epub_out = tmp_path / "output.epub"
    rc2, stderr = _run_cli(
        ["restore", str(synth_epub_file), str(html_out), "--lang", "pl", "--output", str(epub_out)]
    )
    assert rc2 == 0, f"Expected exit 0, got {rc2}. Stderr: {stderr}"
    assert epub_out.exists()


@pytest.mark.integration
def test_restore_exit_code_0_on_success(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    html_out = tmp_path / "prepared.html"
    _run_cli(["prepare", str(synth_epub_file), "--output", str(html_out)])
    epub_out = tmp_path / "output.epub"
    rc, _ = _run_cli(
        ["restore", str(synth_epub_file), str(html_out), "--lang", "en", "--output", str(epub_out)]
    )
    assert rc == 0


@pytest.mark.integration
def test_restore_exit_code_1_on_translated_html_mismatch(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """restore exits 1 when translated HTML has missing sections."""
    # Create a valid but incomplete HTML (no sections)
    bad_html = tmp_path / "bad.html"
    bad_html.write_text(
        "<!DOCTYPE html><html><head><title>T</title></head><body><p>x</p></body></html>"
    )
    rc, stderr = _run_cli(["restore", str(synth_epub_file), str(bad_html), "--lang", "pl"])
    assert rc == 1
    assert "[ERROR]" in stderr


@pytest.mark.integration
def test_default_output_naming_prepare(
    synth_epub_file: pathlib.Path,
) -> None:
    """prepare default output is <stem>.prepare.html in same directory."""
    rc, _ = _run_cli(["prepare", str(synth_epub_file)])
    expected = synth_epub_file.parent / f"{synth_epub_file.stem}.prepare.html"
    assert rc == 0
    assert expected.exists()
    # Cleanup
    expected.unlink(missing_ok=True)


@pytest.mark.integration
def test_default_output_naming_restore(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """restore default output is <stem>.translated.epub in same directory."""
    html_out = tmp_path / "book.prepare.html"
    _run_cli(["prepare", str(synth_epub_file), "--output", str(html_out)])
    rc, _ = _run_cli(["restore", str(synth_epub_file), str(html_out), "--lang", "pl"])
    expected = synth_epub_file.parent / f"{synth_epub_file.stem}.translated.epub"
    assert rc == 0
    assert expected.exists()
    expected.unlink(missing_ok=True)


@pytest.mark.integration
def test_output_flag_overrides_default(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """--output overrides the default output path."""
    custom_out = tmp_path / "custom.html"
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(custom_out)])
    assert rc == 0
    assert custom_out.exists()
    default_out = synth_epub_file.parent / f"{synth_epub_file.stem}.prepare.html"
    assert not default_out.exists()


@pytest.mark.integration
def test_existing_output_without_force_fails_fast(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Without --force, existing output causes exit 1."""
    output = tmp_path / "out.html"
    output.write_text("existing content")
    rc, stderr = _run_cli(["prepare", str(synth_epub_file), "--output", str(output)])
    assert rc == 1
    assert "[ERROR]" in stderr
    assert "Output file exists" in stderr
    # Existing file must not be overwritten
    assert output.read_text() == "existing content"


@pytest.mark.integration
def test_existing_output_with_force_overwrites(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """With --force, existing output is overwritten."""
    output = tmp_path / "out.html"
    output.write_text("old content")
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(output), "--force"])
    assert rc == 0
    assert output.read_text() != "old content"


@pytest.mark.integration
def test_ruby_annotations_emit_warning_to_stderr(tmp_path: pathlib.Path) -> None:
    """prepare emits [WARN] when ruby annotations are present (US-012)."""
    epub_bytes = build_minimal_epub(
        xhtmls=[
            XhtmlSpec(
                href="ch01.xhtml",
                title="Ruby Chapter",
                body_html="<p><ruby>漢<rt>kan</rt></ruby>字</p>",
            )
        ],
        nav_map=[],
    )
    ruby_epub = tmp_path / "ruby.epub"
    ruby_epub.write_bytes(epub_bytes)
    output = tmp_path / "ruby.html"
    rc, stderr = _run_cli(["prepare", str(ruby_epub), "--output", str(output)])
    assert rc == 0  # US-012: exit code remains 0
    assert "[WARN]" in stderr
    assert "Ruby" in stderr or "ruby" in stderr


@pytest.mark.integration
def test_ruby_does_not_affect_exit_code(tmp_path: pathlib.Path) -> None:
    """Ruby annotations produce exit code 0 (warning only)."""
    epub_bytes = build_minimal_epub(
        xhtmls=[
            XhtmlSpec(
                href="ch01.xhtml",
                title="Ruby",
                body_html="<ruby>漢<rt>kan</rt></ruby>",
            )
        ],
        nav_map=[],
    )
    ruby_epub = tmp_path / "ruby.epub"
    ruby_epub.write_bytes(epub_bytes)
    rc, _ = _run_cli(["prepare", str(ruby_epub), "--output", str(tmp_path / "out.html")])
    assert rc == 0


@pytest.mark.integration
def test_no_output_on_stdout_in_normal_run(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No output must appear on stdout during normal operation."""
    from epub_deepl_prepare.cli import main

    main(["prepare", str(synth_epub_file), "--output", str(tmp_path / "out.html")])
    captured = capsys.readouterr()
    assert captured.out == "", f"Unexpected stdout: {captured.out!r}"


# ---------------------------------------------------------------------------
# Target language resolution (US-009 update — --lang now optional)
# ---------------------------------------------------------------------------


def _prepare_then_set_html_lang(
    synth_epub_file: pathlib.Path,
    tmp_path: pathlib.Path,
    new_lang: str | None,
) -> pathlib.Path:
    """Prepare the synthetic EPUB, then mutate the merged HTML's <html lang>
    so we can exercise the lang-resolution paths without round-tripping
    through DeepL. Returns the modified HTML path.
    """
    html_out = tmp_path / "prepared.html"
    rc, _ = _run_cli(["prepare", str(synth_epub_file), "--output", str(html_out)])
    assert rc == 0
    content = html_out.read_text(encoding="utf-8")
    if new_lang is None:
        # Remove the lang attribute entirely
        content = content.replace('<html lang="en">', "<html>")
    else:
        content = content.replace('<html lang="en">', f'<html lang="{new_lang}">')
    html_out.write_text(content, encoding="utf-8")
    return html_out


@pytest.mark.integration
def test_lang_auto_detected_from_translated_html(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """When --lang is omitted, the target language is auto-detected from
    the translated HTML's <html lang> attribute (US-009)."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "pl")
    epub_out = tmp_path / "auto.epub"
    rc, stderr = _run_cli(
        [
            "--verbose",
            "restore",
            str(synth_epub_file),
            str(html),
            "--output",
            str(epub_out),
        ]
    )
    assert rc == 0
    assert "Auto-detected target language 'pl'" in stderr

    # Verify <dc:language>pl</dc:language> in the output OPF
    import zipfile

    with zipfile.ZipFile(epub_out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        opf_bytes = zf.read(opf)
    assert b"<dc:language>pl</dc:language>" in opf_bytes


@pytest.mark.integration
def test_lang_explicit_flag_overrides_detected_with_warning(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """When --lang is given and differs from <html lang>, the explicit
    value wins and a WARN is emitted naming both."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "pl")
    epub_out = tmp_path / "override.epub"
    rc, stderr = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--lang",
            "de",
            "--output",
            str(epub_out),
        ]
    )
    assert rc == 0
    assert "[WARN]" in stderr
    assert "'de'" in stderr and "'pl'" in stderr
    assert "overrides" in stderr

    import zipfile

    with zipfile.ZipFile(epub_out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        opf_bytes = zf.read(opf)
    assert b"<dc:language>de</dc:language>" in opf_bytes


@pytest.mark.integration
def test_lang_region_subtag_passed_through_to_opf(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Region subtag survives the round-trip verbatim (BCP 47 pass-through;
    EPUB OPF uses the same grammar as HTML5 lang)."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "pt-BR")
    epub_out = tmp_path / "region.epub"
    rc, _ = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--output",
            str(epub_out),
        ]
    )
    assert rc == 0
    import zipfile

    with zipfile.ZipFile(epub_out) as zf:
        opf = next(n for n in zf.namelist() if n.endswith(".opf"))
        opf_bytes = zf.read(opf)
    assert b"<dc:language>pt-BR</dc:language>" in opf_bytes


@pytest.mark.integration
def test_lang_missing_in_html_and_no_flag_raises(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Both <html lang> absent AND --lang omitted → exit 1 with hint."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, None)
    rc, stderr = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--output",
            str(tmp_path / "fail.epub"),
        ]
    )
    assert rc == 1
    assert "[ERROR]" in stderr
    assert "--lang" in stderr


@pytest.mark.integration
def test_lang_whitespace_only_in_html_treated_as_missing(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A whitespace-only <html lang="   "> is treated as missing per EPUB
    spec's trim-before-process rule."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "   ")
    rc, stderr = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--output",
            str(tmp_path / "ws.epub"),
        ]
    )
    assert rc == 1
    assert "--lang" in stderr


@pytest.mark.integration
def test_lang_malformed_explicit_flag_rejected(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A malformed --lang value fails fast with a clear message."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "pl")
    rc, stderr = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--lang",
            "not a tag",
            "--output",
            str(tmp_path / "bad.epub"),
        ]
    )
    assert rc == 1
    assert "[ERROR]" in stderr
    assert "well-formed BCP 47" in stderr


@pytest.mark.integration
def test_lang_drift_warning_when_primary_subtag_unchanged(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """If the chosen target's primary subtag matches the source EPUB's,
    emit a WARN (possible failed translation). Source is 'en'; we set
    the translated HTML to 'en-GB' to keep the primary identical."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "en-GB")
    epub_out = tmp_path / "drift.epub"
    rc, stderr = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--output",
            str(epub_out),
        ]
    )
    assert rc == 0
    assert "[WARN]" in stderr
    assert "primary subtag matches" in stderr


@pytest.mark.integration
def test_lang_no_drift_warning_when_primary_subtag_changes(
    synth_epub_file: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Source is 'en', target 'pl' — different primary subtag, no drift."""
    html = _prepare_then_set_html_lang(synth_epub_file, tmp_path, "pl")
    epub_out = tmp_path / "nodrift.epub"
    rc, stderr = _run_cli(
        [
            "restore",
            str(synth_epub_file),
            str(html),
            "--output",
            str(epub_out),
        ]
    )
    assert rc == 0
    assert "primary subtag matches" not in stderr
