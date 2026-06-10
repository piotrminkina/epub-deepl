"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import pathlib
import tempfile
from collections.abc import Callable

import pytest

from tests.fixtures.minimal import XhtmlSpec, build_minimal_epub

CORPUS_DIR = pathlib.Path("/tmp/nowe")


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: fast, no I/O beyond temp files")
    config.addinivalue_line("markers", "integration: synthetic EPUB end-to-end")
    config.addinivalue_line("markers", "corpus: requires /tmp/nowe; opt-in")
    config.addinivalue_line(
        "markers",
        "epubcheck: requires the `epubcheck` binary on PATH (W3C validator); opt-in",
    )


@pytest.fixture(scope="session")
def corpus_dir() -> pathlib.Path | None:
    """Return the corpus directory if it contains EPUB files, else None."""
    if not CORPUS_DIR.exists():
        return None
    epubs = list(CORPUS_DIR.glob("*.epub"))
    if not epubs:
        return None
    return CORPUS_DIR


@pytest.fixture(
    scope="session",
    params=list(CORPUS_DIR.glob("*.epub")) if CORPUS_DIR.exists() else [],
    ids=lambda p: p.stem[:40] if hasattr(p, "stem") else str(p),
)
def corpus_epub(request: pytest.FixtureRequest) -> pathlib.Path:
    """Parametrized fixture yielding each corpus EPUB path."""
    epub_path: pathlib.Path = request.param
    if not epub_path.exists():
        pytest.skip(f"Corpus EPUB not found: {epub_path}")
    return epub_path


@pytest.fixture
def synth_epub_bytes() -> bytes:
    """A minimal 3-chapter synthetic EPUB as bytes."""
    return build_minimal_epub()


@pytest.fixture
def synth_epub_file(tmp_path: pathlib.Path, synth_epub_bytes: bytes) -> pathlib.Path:
    """Write the synthetic EPUB to a temp file and return its path."""
    p = tmp_path / "test.epub"
    p.write_bytes(synth_epub_bytes)
    return p


@pytest.fixture
def tmp_epub(tmp_path: pathlib.Path) -> pathlib.Path:
    """An empty temp path suitable for write tests."""
    return tmp_path / "output.epub"


@pytest.fixture
def build_epub() -> Callable[..., bytes]:
    """Return the build_minimal_epub factory for parameterised construction."""
    return build_minimal_epub
