# epub-translation-prepare

A Python CLI that bundles all human-facing content of an EPUB into **a single
HTML document** suitable for DeepL's document-translation feature, then
reassembles the translated HTML back into a **structurally identical EPUB**.

The motivation is economy: DeepL Pro Starter grants 5 document translations
per month, but an EPUB contains 10–50 separate XHTML files. Translating each
separately exhausts the monthly quota on a single book. This tool reduces a
book to one DeepL document while preserving the table of contents, OPF
metadata, NCX navigation, manifest, spine, and all non-translated structural
identifiers.

**Status:** MVP draft v1. Targets EPUB 2.0 + NCX (the format of the typical
corpus). EPUB 3 + `nav.xhtml` is out of MVP scope.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python ≥ 3.11 | Modern typing, pattern matching, `tomllib` |
| XML / HTML | `lxml ≥ 5.0` (only non-stdlib runtime dep) | Cython libxml2; handles XHTML 1.1, HTML5, namespaced XML uniformly |
| Packaging / build | `hatchling` + `hatch` | PEP 517, minimal boilerplate |
| Test runner | `pytest ≥ 8` + `pytest-cov` | Standard; parametrized corpus tests |
| Lint + format | `ruff` | Replaces flake8, isort, black, pyupgrade |
| Type check | `mypy --strict` + `lxml-stubs` | Hard guarantee for structural-fidelity contract |
| Dev environment | Dev Container (`debian:bookworm-slim` base) | Reproducible across hosts; no UID-1000 baked-in |
| Manual EPUB validation | `epubcheck 5.1.0` (W3C) — pre-installed in container | Out-of-band release gate |

Full rationale and alternatives considered: [`docs/plans/tech-stack.md`](docs/plans/tech-stack.md).

## Getting Started

### Prerequisites

The recommended workflow uses the project's Dev Container, which provisions
every tool listed above without polluting the host:

- Docker Engine ≥ 20.10 (or Podman with `docker` shim)
- `@devcontainers/cli` (`npm install -g @devcontainers/cli`)
- A JetBrains IDE (PyCharm preferred) **or** plain shell access

Native (non-container) install also works on any host with Python 3.11+ and
the system packages `libxml2-dev libxslt1-dev zlib1g-dev` (Debian / Ubuntu)
or equivalents.

### Installation — Dev Container (recommended)

```bash
git clone <your-fork> epub-translation-prepare
cd epub-translation-prepare
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash -lc 'source .venv/bin/activate && epub-translation-prepare --help'
```

First `devcontainer up` builds the Debian-based image, installs the
`common-utils` feature (which creates the non-root `devcontainer` user with
UID matched to the host), runs the post-create script that creates `.venv`
and `pip install -e ".[dev]"`. Subsequent runs reuse the cached image.

The `/tmp/nowe` directory is bind-mounted **read-only** into the container
as the test corpus location — if you keep your EPUB collection elsewhere,
edit `mounts` in `.devcontainer/devcontainer.json`.

### Installation — native

```bash
git clone <your-fork> epub-translation-prepare
cd epub-translation-prepare
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
epub-translation-prepare --help
```

### Running

The CLI has two subcommands, intended to be invoked around a manual DeepL
upload / download step.

```bash
# 1. Bundle the EPUB into a single HTML for DeepL
epub-translation-prepare prepare path/to/book.epub
#   → produces path/to/book.prepare.html

# 2. Upload book.prepare.html to https://www.deepl.com/translator/files,
#    choose target language, download the translated HTML.

# 3. Reassemble the translated EPUB
epub-translation-prepare restore path/to/book.epub path/to/book.translated.html --lang pl
#   → produces path/to/book.translated.epub
```

#### `bin/` launcher (no venv activation)

`bin/epub-translation-prepare` is a thin Bash wrapper that locates the
project's `.venv` interpreter directly. Use it when you want to invoke the
tool from outside the activated virtualenv (e.g. from a shell alias, a cron
job, or your editor's external-tool integration):

```bash
# Run from any directory
/path/to/repo/bin/epub-translation-prepare prepare book.epub

# Or place on PATH
ln -s "$(pwd)/bin/epub-translation-prepare" ~/.local/bin/
epub-translation-prepare prepare book.epub
```

The wrapper self-locates via `${BASH_SOURCE[0]}` and execs
`.venv/bin/python -m epub_translation_prepare`. It fails fast with a
diagnostic if the virtualenv is missing.

The original EPUB is read-only during `restore` and acts as the structural
template; only translated body content, OPF metadata (`dc:title`,
`dc:description`, `dc:subject`, `dc:language`), and NCX navigation labels
are mutated.

## Available Commands

| Command | Description |
|---|---|
| `epub-translation-prepare prepare <input.epub>` | Validate input EPUB and emit `<stem>.prepare.html` |
| `epub-translation-prepare restore <input.epub> <translated.html> --lang <code>` | Validate translated HTML against the input EPUB and emit `<stem>.translated.epub` |
| `epub-translation-prepare --help` | Show top-level usage |
| `<subcommand> --help` | Show flags for a specific subcommand |

Common flags on both subcommands:

| Flag | Effect |
|---|---|
| `--output FILE` | Override the default output path |
| `--force` | Overwrite existing output (does NOT bypass input-equals-output guard) |
| `--verbose` | Per-file progress to stderr |

Exit codes: `0` success, `1` user error (bad input / validation failure /
output collision), `2` internal error.

### Developer commands (inside the Dev Container)

```bash
source .venv/bin/activate

# Run the full test suite (unit + synth integration + corpus on /tmp/nowe)
pytest -m 'not corpus or corpus'

# Fast tests only (skip corpus)
pytest

# Lint and format
ruff check src tests
ruff format src tests

# Strict type check
mypy --strict src/epub_translation_prepare

# Manual EPUB validation (post-release gate per SM-4)
epubcheck path/to/output.translated.epub
```

## How It Works

`prepare` walks the input EPUB's spine in reading order and emits a single
HTML5 document. Each source XHTML becomes a `<section
data-source-href="…" data-spine-idx="N">`. OPF metadata is exposed as
visible content under `<header data-source="opf-metadata">`. NCX entries
are serialised as a flat `<nav data-source="ncx">` block with `data-*`
attributes preserving `src` and `playOrder` for restore.

`restore` parses the translated HTML, locates every `data-source-href`,
and rebuilds each XHTML by replacing only the `<body>` content of the
original. The OPF and NCX trees are mutated in-place — manifest, spine,
identifiers, and namespace structure pass through unchanged. NCX
`<navLabel>` text is recomputed via **anchor resolution**: for each
`<content src="path#fragment"/>`, the algorithm locates the element with
that fragment ID in the restored XHTML and uses its translated heading
text — guaranteeing TOC ↔ chapter-heading consistency without translating
the labels twice.

Detailed architecture, data model, and edge cases:
[`docs/plans/tech-spec.md`](docs/plans/tech-spec.md).

## Project Scope

### In scope (MVP)

- EPUB 2.0.1 with NCX-based navigation
- Round-trip preservation of all human-visible content + OPF / NCX
  structural metadata required by e-readers
- DeepL HTML document compatibility (HTML5 self-contained payload)
- Solo-user CLI workflow with manual upload / download to DeepL
- Pre-flight validation of the input EPUB (fail-fast on DRM, broken
  manifest, broken spine, non-XHTML spine items, missing NCX)

### Out of scope

- EPUB 3 with `nav.xhtml` navigation (deferred — post-MVP)
- DRM-protected EPUBs (detected and rejected; never supported)
- Automated DeepL API integration (user does the upload manually)
- Automated `epubcheck` invocation (manual user step)
- Books exceeding DeepL's per-document character limit
- GUI, web interface, daemon mode, multi-user features
- Translation memory, caching, or glossary support

Full requirements with user stories: [`docs/plans/prd.md`](docs/plans/prd.md).

## Quality Gates

The MVP holds the following invariants, all verified automatically inside
the Dev Container:

| Gate | Verification |
|---|---|
| Round-trip integrity without translation | `diff -r` of unzipped EPUBs + ZIP-level invariants (mimetype-first, STORED, `flag_bits=0`) — green across the 4-book test corpus |
| EPUB validity preservation | `epubcheck` reports identical fatal / error / warning counts before and after round-trip (zero drift) |
| SVG / MathML attribute case | `viewBox`, `preserveAspectRatio`, etc. preserved on output (epubcheck-required) |
| Adversarial DeepL simulation | Random-seeded fixture strips `data-*`, reorders attributes, collapses whitespace; restore must either succeed correctly or fail with a precise diagnostic |
| Anchor resolution scoping | NCX label lookup scoped per-XHTML; no ID-collision cross-file false positives |

## Project Status

**MVP draft v1.** Tested against a 4-EPUB corpus (technical, novel,
workbook genres; all EPUB 2.0 + NCX). All 118 unit and integration tests
pass; full corpus round-trip preserves epubcheck baseline (0 errors in →
0 errors out).

Open items tracked in [`docs/plans/devils-advocate-review.md`](docs/plans/devils-advocate-review.md):
- R-8 spike (real DeepL preserves `data-*` attributes) — manual verification recommended before first production use
- EPUB 3 + `nav.xhtml` support — deferred to post-MVP
- Apple Books / Calibre-specific metadata quirks — observed but not specially handled

## Documentation Layout

```
docs/plans/
├── prd.md                       Requirements, user stories US-001…US-020, success metrics SM-1…SM-7
├── tech-stack.md                Technology choices, dependency analysis, alternatives rejected
├── tech-spec.md                 Internal architecture, data model, flows, anchor resolution, ZIP packaging
├── test-plan.md                 Test pyramid, fixture strategy, coverage matrix
└── devils-advocate-review.md    Critical findings (C-1…C-4) + adversarial review
```

## License

MIT — see [LICENSE](LICENSE).

---

*A 1 MB book translated as one DeepL document instead of 30 chapters: the
math works out to 30× the books you can translate per month, with a TOC
that actually matches the chapter headings.*
