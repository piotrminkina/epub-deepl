# Contributing to EPUB DeepL

This document covers the development workflow: setting up the environment,
running the test suite, lint and type checks, code style, and the
documentation map. End-user install and usage instructions live in
[README.md](README.md) — they intentionally do not require any of the
machinery described here.

---

## Development Environment

Two paths are supported. The Dev Container is recommended because it
reproduces the exact toolchain used during MVP development and matches
the environment the project's automated checks were validated against.
The native path works fine for casual contributions; you accept the
responsibility of matching tool versions yourself.

### Path 1 — Dev Container (recommended)

Prerequisites on the host:

- Docker Engine ≥ 20.10 (or Podman with `docker` shim)
- `@devcontainers/cli` (`npm install -g @devcontainers/cli`)
- A JetBrains IDE (PyCharm preferred) or plain shell access

```bash
git clone <your-fork> epub-deepl
cd epub-deepl
devcontainer up --workspace-folder .
# Container creates .venv-3.11/ (per the container's Python minor —
# see ADR-0004 on per-Python-minor venv naming).
devcontainer exec --workspace-folder . bash -lc 'source .venv-3.11/bin/activate'
```

First `devcontainer up` builds the Debian-based image, installs the
`common-utils` feature (which creates the non-root `devcontainer` user
with UID matched to the host), and runs `post-create.sh` which creates
`.venv-${PY_MINOR}/` and `pip install -e ".[dev]"`. Subsequent runs
reuse the cached image and venv.

What the container provides out of the box:

- Python 3.11 (Debian 12 system package)
- All `lxml` C-extension build dependencies (`libxml2-dev`,
  `libxslt1-dev`, `zlib1g-dev`, `build-essential`, `pkg-config`)
- `default-jre-headless` + a pre-installed, SHA256-pinned `epubcheck`
  5.1.0 (callable as `epubcheck <file.epub>`)
- Standard utilities for round-trip integrity checks: `unzip`,
  `diffutils`, `git`, `curl`

Corpus EPUBs live in `tests/corpus/` (gitignored except for the
bundled Project Gutenberg Alice fixture and its README). To run
corpus tests against your own collection without copying files,
either drop them into `tests/corpus/` or point at any directory via
the `EPUB_DEEPL_CORPUS` environment variable.

> **Identity model:** the container runs as a non-root user
> (`devcontainer`) whose UID is matched to the host at container
> creation time via `common-utils`' `userUid: "automatic"`. No
> hardcoded UID 1000. Bind-mounted files retain host ownership.

### Path 2 — Native (no container)

Any host with Python 3.11+ and the `lxml` build dependencies works:

```bash
# Debian / Ubuntu
sudo apt install python3.11 python3.11-venv python3.11-dev \
                 libxml2-dev libxslt1-dev zlib1g-dev build-essential

# Fedora / RHEL
sudo dnf install python3.11 python3.11-devel \
                 libxml2-devel libxslt-devel zlib-devel gcc

git clone <your-fork> epub-deepl
cd epub-deepl
# Name the venv after the Python minor so it coexists with venvs from
# other interpreters (e.g. the container's .venv-3.11/). See ADR-0004.
PY_MINOR="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -m venv ".venv-${PY_MINOR}"
source ".venv-${PY_MINOR}/bin/activate"
pip install -e ".[dev]"
```

The `bin/epub-deepl` launcher auto-discovers the matching venv: it
picks `.venv-${PY_MINOR}/` first, then falls back to `.venv/` (legacy)
only if `pyvenv.cfg` declares the current Python minor. If no
compatible venv exists, the launcher emits a concrete creation
recipe instead of a bare `No module named …`.

For `epubcheck` (manual SM-4 release gate), install the W3C reference
implementation from its release page. Pin to 5.1.0 to match the
container baseline.

---

## Running the Test Suite

```bash
# Activate the venv matching your current Python (see ADR-0004):
source ".venv-$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/bin/activate"

# Fast tests only (unit + synth integration; skips the corpus)
pytest

# Full suite including corpus parametrization
pytest -m 'not corpus or corpus'

# Just the corpus parametrization (requires tests/corpus/ populated,
# or set EPUB_DEEPL_CORPUS to point at your own EPUB directory)
pytest -m corpus

# Same, against an out-of-tree corpus
EPUB_DEEPL_CORPUS=/path/to/library pytest -m corpus

# Single file
pytest tests/unit/test_anchor_resolution.py -v

# Single test
pytest tests/unit/test_anchor_resolution.py::test_resolve_label_with_fragment -v
```

The full suite runs in under a minute on a developer laptop. Corpus
tests skip gracefully when the corpus directory is absent or empty,
so the suite remains runnable on any machine without preparing real
EPUB fixtures.

### Coverage

```bash
pytest --cov --cov-report=term-missing
```

Floor: 85% statement coverage overall; 100% on `epub/validator.py` and
`epub/writer.py` (highest-risk modules per
[`docs/plans/test-plan.md`](docs/plans/test-plan.md) §10).

---

## Lint, Format, Type Check

```bash
# Lint (no autofix)
ruff check src tests

# Lint with autofix
ruff check src tests --fix

# Format (Black-compatible)
ruff format src tests

# Strict type check (lxml-stubs noise tolerated; document any new
# `# type: ignore` comments inline)
mypy --strict src/epub_deepl
```

All three commands must return clean before opening a PR.

### Shellcheck (for `.bash` / `.sh` files only)

```bash
# Install on the host (not present in the container by design):
sudo apt install shellcheck       # Debian / Ubuntu
sudo dnf install ShellCheck       # Fedora

shellcheck bin/epub-deepl .devcontainer/post-create.sh
```

Every script must pass `shellcheck` with zero warnings.

---

## Manual EPUB Validation

`epubcheck` is the W3C reference validator and is the binding release
gate (SM-4 from the PRD). It is not invoked from the test suite (Java
runtime requirement; cost > benefit for the MVP) — run it manually
before each release:

```bash
# Round-trip-without-translation should produce zero new errors.
# --lang is unnecessary when the merged HTML still carries the original
# source language; pass it explicitly to force a different value.
epub-deepl prepare tests/corpus/alice-pg11.epub
epub-deepl restore tests/corpus/alice-pg11.epub \
    tests/corpus/alice-pg11.prepare.html \
    --output /tmp/alice.translated.epub

epubcheck tests/corpus/alice-pg11.epub  # baseline
epubcheck /tmp/alice.translated.epub     # after round-trip
```

The drift warning emitted on round-trip-without-translation is expected
(the source language is preserved unchanged) — it's the same mechanism
that catches a real failed-translation upload.

The acceptance criterion: identical fatal / error / warning counts
before and after. Any new error introduced by the tool is a bug.

---

## Code Style

- Python 3.11 syntax (modern type hints, `X | Y` unions, `Self`).
- `mypy --strict` clean — no untyped functions, no implicit `Any`.
- Module-level imports only (no lazy imports inside functions unless
  there is a documented reason, e.g. circular-import avoidance).
- Lines ≤ 100 characters (`ruff` enforces).
- Docstrings use the reStructuredText / PEP 257 conventions; not
  numpydoc, not Google style.
- Centralised security boundaries:
  - All lxml parsers constructed via `epub/_safe_parser.py`.
  - All XPath fragment literals quoted via `xpath_literal()` in
    `epub/ncx.py`.

When unsure, match the surrounding code's style; the codebase is small
enough that local consistency is the right baseline.

---

## Project Layout

```
.
├── .devcontainer/                 Dev Container definition (Dockerfile,
│                                  devcontainer.json, post-create.sh)
├── bin/                           Bash CLI launcher (per-Python-minor venv)
├── docs/
│   ├── adr/                       Architecture Decision Records
│   ├── lessons-learned.md         Operational gotchas, DeepL behaviour
│   │                              catalog, process retrospective
│   └── plans/                     Forward-looking design artifacts
│       ├── prd.md                 Product requirements (US-001..US-020,
│       │                          SM-1..SM-7)
│       ├── tech-stack.md          Technology choices, alternatives
│       ├── tech-spec.md           Internal architecture, data model,
│       │                          flows, anchor resolution, ZIP rules
│       └── test-plan.md           Test pyramid, fixtures, coverage matrix
├── src/epub_deepl/        Source package
│   ├── cli.py                     argparse entry; dispatches to prepare/restore
│   ├── errors.py                  Typed exception hierarchy
│   ├── logging_setup.py           stderr formatting, --verbose flag
│   ├── epub/                      EPUB I/O and structural model
│   │   ├── _safe_parser.py        Centralised lxml parser factory (XXE-safe)
│   │   ├── _svg_case.py           SVG/MathML attribute case restoration
│   │   ├── model.py               Dataclasses: Epub, ManifestItem, etc.
│   │   ├── reader.py              ZIP → Epub model
│   │   ├── writer.py              Epub model → ZIP (mimetype-first STORED)
│   │   ├── validator.py           Fail-fast input validation
│   │   ├── opf.py                 OPF parse + edit
│   │   ├── ncx.py                 NCX parse + edit + anchor resolution
│   │   └── xhtml.py               XHTML body extraction/replacement
│   ├── merge/builder.py           Epub model → merged HTML5
│   └── restore/                   Translated HTML → updated Epub model
│       ├── parser.py
│       └── applier.py
└── tests/
    ├── conftest.py                Shared fixtures (corpus_dir, factories)
    ├── fixtures/minimal.py        Synthetic EPUB factory
    ├── unit/                      Per-module unit tests
    └── integration/               CLI + round-trip integration tests
```

For a deeper understanding of the architecture, start with
[`docs/plans/tech-spec.md`](docs/plans/tech-spec.md) §1 (overview), then
§4–5 (prepare and restore flows), then §6 (anchor resolution algorithm).

---

## Quality Gates

Every change must pass these gates before merging:

| Gate | Command |
|---|---|
| Lint | `ruff check src tests` |
| Format | `ruff format --check src tests` |
| Types | `mypy --strict src/epub_deepl` |
| Tests | `pytest -m 'not corpus or corpus'` |
| Shell scripts | `shellcheck bin/* .devcontainer/*.sh` |
| Round-trip integrity | Manual `epubcheck` per the recipe above |

Coverage floors per module are documented in
[`docs/plans/test-plan.md`](docs/plans/test-plan.md) §10.

---

## Commit Conventions

- Atomic commits: each commit is one indivisible design decision. A
  refactor spanning 10 files = 1 commit, not 10. A bug fix + a
  surrounding cleanup = 2 commits.
- Litmus test before splitting an in-flight change: *"if I checkout the
  predecessor commit, does the tree build, lint, type-check, and pass
  tests?"* If no — do not split.
- Use Conventional Commits prefixes for clarity (`feat:`, `fix:`,
  `docs:`, `chore:`, `refactor:`, `test:`).

---

## Reporting Issues

Open an issue on the project's tracker with:

- Input EPUB metadata (size, EPUB version, source) — not the file
  itself unless you can confirm it carries no DRM and the publisher's
  terms permit redistribution
- Exact command line invoked
- `--verbose` output (entire stderr)
- `epubcheck` output for input AND output, side-by-side

If the bug is structural (TOC drift, manifest mismatch, lost metadata),
attach the relevant fragments of the input OPF / NCX as well.
