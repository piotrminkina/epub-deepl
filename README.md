# EPUB DeepL Prepare

<!--
  Badge URLs include OWNER/REPO placeholders. Replace with the actual
  GitHub path (e.g. `piotrminkina/epub-deepl-prepare`) once the repo
  is published.
-->

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-d7ff64)](https://docs.astral.sh/ruff/)

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

## Install

The tool is a standard Python package. Any environment with Python 3.11+ and
the system libraries for `lxml` (typically present, or installable via
`apt install libxml2 libxslt1.1`) is sufficient.

```bash
git clone <your-fork> epub-deepl-prepare
cd epub-deepl-prepare
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
epub-deepl-prepare --help
```

If you prefer to invoke the tool without activating the virtualenv each
session, use the `bin/` launcher (see below) or symlink it into a directory
on your `PATH`.

> **Contributing or developing the tool?** See
> [CONTRIBUTING.md](CONTRIBUTING.md) for the recommended Dev Container
> workflow, test commands, and code style.

## Usage

The CLI has two subcommands, designed around a manual DeepL upload/download
step.

```bash
# 1. Bundle the EPUB into a single HTML for DeepL
epub-deepl-prepare prepare path/to/book.epub
#   → produces path/to/book.prepare.html

# 2. Upload book.prepare.html to https://www.deepl.com/translator/files,
#    choose target language, download the translated HTML.

# 3. Reassemble the translated EPUB
epub-deepl-prepare restore path/to/book.epub path/to/book.translated.html
#   → produces path/to/book.translated.epub
```

The target language is auto-detected from the translated HTML's
`<html lang>` attribute (DeepL sets it correctly). Pass
`--lang <code>` to override the detection — useful when the
translator left the source language tag in place or when you want a
specific BCP 47 variant (e.g. `--lang pt-BR`).

The original EPUB is read-only during `restore` and acts as the structural
template; only translated body content, OPF metadata (`dc:title`,
`dc:description`, `dc:subject`, `dc:language`), and NCX navigation labels
are mutated.

### `bin/` launcher (no venv activation)

`bin/epub-deepl-prepare` is a thin Bash wrapper that self-locates the
project's `.venv` interpreter directly. Use it when invoking the tool from
outside an activated virtualenv — shell aliases, cron jobs, editor
integrations:

```bash
# Run from any directory
/path/to/repo/bin/epub-deepl-prepare prepare book.epub

# Or place on PATH
ln -s "$(pwd)/bin/epub-deepl-prepare" ~/.local/bin/
epub-deepl-prepare prepare book.epub
```

The wrapper fails fast with a diagnostic if the virtualenv is missing.

## Commands

| Command | Description |
|---|---|
| `epub-deepl-prepare prepare <input.epub>` | Validate input and emit `<stem>.prepare.html` |
| `epub-deepl-prepare restore <input.epub> <translated.html> [--lang <code>]` | Validate translated HTML against the input EPUB and emit `<stem>.translated.epub`. `--lang` is optional (auto-detected from `<html lang>`). |
| `epub-deepl-prepare --help` | Top-level usage |
| `<subcommand> --help` | Flags for a specific subcommand |

Common flags on both subcommands:

| Flag | Effect |
|---|---|
| `--output FILE` | Override the default output path |
| `--force` | Overwrite existing output (does NOT bypass input-equals-output guard) |
| `--verbose` | Per-file progress to stderr |

Exit codes: `0` success, `1` user error (bad input / validation failure /
output collision), `2` internal error.

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

Detailed architecture and edge cases:
[`docs/plans/tech-spec.md`](docs/plans/tech-spec.md).

## Scope

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
- Automated DeepL API integration (user uploads manually)
- Automated `epubcheck` invocation (manual user step)
- Books exceeding DeepL's per-document character limit
- GUI, web interface, daemon mode, multi-user features
- Translation memory, caching, or glossary support

Full requirements with user stories: [`docs/plans/prd.md`](docs/plans/prd.md).

## Project Status

**MVP draft v1.** Tested against a 4-EPUB corpus (technical, novel,
workbook genres; all EPUB 2.0 + NCX). 175 unit + integration tests pass;
full corpus round-trip preserves the `epubcheck` baseline (0 errors in →
0 errors out). Real-DeepL spike completed: one full Polish translation
of a 22-chapter / 114-navPoint book round-tripped cleanly, R-8 (DeepL
preserves `data-*` attributes) empirically validated.

CI matrix tests Python 3.11 / 3.12 / 3.13 on every push and PR; a
dedicated CI job re-runs the synthetic `epubcheck` zero-drift tests
with a JRE installed.

Open items tracked in
[`docs/plans/devils-advocate-review.md`](docs/plans/devils-advocate-review.md)
and per-release notes in [`CHANGELOG.md`](CHANGELOG.md):

- EPUB 3 + `nav.xhtml` support — deferred to post-MVP
- Apple Books / Calibre-specific metadata quirks — observed but not
  specially handled
- Books exceeding DeepL's per-document character limit (~1 MB+) — no
  automatic chunking; user falls back to per-chapter workflow

## License

MIT — see [LICENSE](LICENSE).

---

*A 1 MB book translated as one DeepL document instead of 30 chapters: the
math works out to 30× the books you can translate per month, with a TOC
that actually matches the chapter headings.*
