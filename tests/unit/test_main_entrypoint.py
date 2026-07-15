"""Regression test for `python -m epub_deepl` exit-code propagation.

`src/epub_deepl/__main__.py` is a thin wrapper around `cli.main()`. A prior
version called `main()` without using its return value, so `python -m
epub_deepl` always exited 0 -- even when `main()` returned a non-zero exit
code -- silently masking failures for any script driving the module form of
the CLI. The `epub-deepl` console script was unaffected: `cli.py` itself
already has `if __name__ == "__main__": sys.exit(main())` at module scope.

These tests exercise the real `__main__` execution path via
`runpy.run_module`, which is what `python -m epub_deepl` does under the
hood -- calling `epub_deepl.cli.main()` directly, as other CLI tests do,
would bypass `__main__.py` entirely and would not have caught this bug.
"""

from __future__ import annotations

import pathlib
import runpy
import sys

import pytest


def _run_as_module(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["epub_deepl", *argv])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("epub_deepl", run_name="__main__")
    assert isinstance(exc_info.value.code, int), (
        f"expected an int exit code, got {exc_info.value.code!r}"
    )
    return exc_info.value.code


def test_module_entrypoint_propagates_failure_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing invocation (missing input file) must exit 1, not 0."""
    rc = _run_as_module(["prepare", "/nonexistent/does-not-exist.epub"], monkeypatch)
    assert rc == 1


def test_module_entrypoint_propagates_success_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    synth_epub_file: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    """A successful invocation must exit 0 (the regression guard cuts both
    ways -- confirms the fix does not e.g. hardcode a non-zero exit)."""
    output = tmp_path / "test.prepare.html"
    rc = _run_as_module(["prepare", str(synth_epub_file), "--output", str(output)], monkeypatch)
    assert rc == 0
    assert output.exists()
