# EPUB DeepL

[![CI](https://github.com/piotrminkina/epub-deepl/actions/workflows/ci.yml/badge.svg)](https://github.com/piotrminkina/epub-deepl/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-d7ff64)](https://docs.astral.sh/ruff/)

A Python CLI that translates an EPUB through DeepL with **maximum
structural fidelity to the original**. The translated book reads in any
e-reader exactly like the source minus the translated text — TOC labels
match chapter headings, manifest and spine are byte-for-byte equivalent,
embedded SVG attributes survive, non-ASCII characters round-trip cleanly
through Unicode.

The naive alternative — unzip the EPUB, translate each XHTML separately,
repackage by hand — is expensive on three axes that this tool collapses
into a single upload/download cycle per book:

1. **Structural fragility.** Manual reassembly drops the TOC,
   mis-orders the spine, breaks cross-file links, mangles OPF metadata
   or NCX navigation. Producing a valid EPUB by hand is error-prone
   and slow.
2. **Operator time.** Tens of file-by-file upload/download cycles
   per book.
3. **Translation-job count.** Per-document translation services
   (e.g. DeepL Pro Starter, with its 5-documents-per-month limit)
   charge once per file. An EPUB with 10–50 XHTMLs exhausts the
   monthly quota on one book; this tool spends one document per book.

**Status:** working MVP, no versioned release cut yet. Supports EPUB 2.x
with NCX-based navigation and reflowable EPUB 3.x with nav-document
navigation (NCX optional). Fixed-layout EPUB, SVG-in-spine content, and
media overlays are out of scope.

## Install

The tool is a standard Python package. Any environment with Python 3.11+ and
the system libraries for `lxml` (typically present, or installable via
`apt install libxml2 libxslt1.1`) is sufficient.

```bash
git clone <your-fork> epub-deepl
cd epub-deepl

# Per ADR-0004 the venv is named after the host's Python minor so it
# coexists with venvs from other interpreters (e.g. a Dev Container's).
PY_MINOR="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -m venv ".venv-${PY_MINOR}"
source ".venv-${PY_MINOR}/bin/activate"
pip install -e .
epub-deepl --help
```

To skip activating the virtualenv each session, use the `bin/` launcher
(see below) or symlink it into a directory on your `PATH`.

> **Contributing or developing the tool?** See
> [CONTRIBUTING.md](CONTRIBUTING.md) for the recommended Dev Container
> workflow, test commands, and code style.

## Usage

The CLI has two subcommands, designed around a manual DeepL upload/download
step.

```bash
# 1. Bundle the EPUB into a single HTML for DeepL
epub-deepl prepare path/to/book.epub
#   → produces path/to/book.prepare.html
#   → a payload over --max-chars (default 900,000) is instead split at
#     section boundaries into book.prepare.1of2.html, book.prepare.2of2.html, ...

# 2. Upload the file(s) to https://www.deepl.com/translator/files,
#    choose target language, download the translated HTML. Translate
#    every part separately when the payload was split.

# 3. Reassemble the translated EPUB
epub-deepl restore path/to/book.epub path/to/book.translated.html
#   → produces path/to/book.translated.epub
#   → when the payload was split, pass every translated part instead,
#     in any order:
#     epub-deepl restore path/to/book.epub \
#       path/to/book.translated.1of2.html path/to/book.translated.2of2.html
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

`bin/epub-deepl` is a thin Bash wrapper that self-locates the project
root and execs the matching venv's Python with the CLI module. It
picks `.venv-${PY_MINOR}/` for the current `python3`, falling back to
legacy `.venv/` only if its `pyvenv.cfg` declares the matching minor
(see [ADR-0004](docs/adr/0004-per-python-minor-venv.md)). Use it for
shell aliases, cron jobs, or editor integrations where activating a
virtualenv first is awkward:

```bash
# Run from any directory
/path/to/repo/bin/epub-deepl prepare book.epub

# Or place on PATH
ln -s "$(pwd)/bin/epub-deepl" ~/.local/bin/
epub-deepl prepare book.epub
```

The wrapper fails fast with a concrete creation recipe when no
compatible venv exists.

## Commands

| Command | Description |
|---|---|
| `epub-deepl prepare <input.epub> [--max-chars N]` | Validate input and emit `<stem>.prepare.html` — or `<stem>.prepare.1ofN.html`, `<stem>.prepare.2ofN.html`, … when the payload exceeds `--max-chars` |
| `epub-deepl restore <input.epub> <translated.html>... [--lang <code>]` | Validate translated HTML against the input EPUB and emit `<stem>.translated.epub`. Accepts one file, or every part of a split payload in any order. `--lang` is optional (auto-detected from `<html lang>`). |
| `epub-deepl --help` | Top-level usage |
| `<subcommand> --help` | Flags for a specific subcommand |

Common flags on both subcommands:

| Flag | Effect |
|---|---|
| `--output FILE` | Override the default output path |
| `--force` | Overwrite existing output (does NOT bypass input-equals-output guard) |
| `--verbose` | Per-file progress to stderr |

Flag specific to `prepare`:

| Flag | Effect |
|---|---|
| `--max-chars N` | Split the payload at section boundaries whenever it would exceed `N` characters (default `900,000`, a ~10% margin under DeepL's 1,000,000-character document limit). `--max-chars 0` disables splitting; a payload under the threshold is unaffected — output is byte-identical to today's single file. |

Exit codes: `0` success, `1` user error (bad input / validation failure /
output collision / a single section too large to fit any part), `2` internal
error.

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

For EPUB 3.x books, the navigation document's body travels through the
same content pipeline as any spine file — its "Contents" heading,
landmarks, and page-list all get translated — and afterwards its
`epub:type="toc"` entry labels are overwritten by the same anchor
resolution used for NCX, so both navigation documents stay TOC ↔
heading-consistent when a book ships both.

When the merged payload would exceed `--max-chars`, `prepare` packs
sections into multiple parts instead of raising an error — never
splitting inside a section, only between them. Every part carries the
full envelope (OPF metadata header, NCX block, `<html lang>`), so each
one translates as a complete, self-contained document; only the first
part carries the shared preamble to avoid duplicating it across parts.
`restore` accepts every translated part in any order and merges them
back into a single document before the usual per-file rebuild — order
never matters because sections are re-associated by their
`data-source-href`, not by which file they arrived in. See
[ADR-0006](docs/adr/0006-auto-split-oversized-payloads.md) for the
full design rationale.

Detailed architecture and edge cases:
[`docs/plans/tech-spec.md`](docs/plans/tech-spec.md).

## Scope

### In scope (MVP)

- EPUB 2.x with NCX-based navigation
- Reflowable EPUB 3.x with nav-document navigation (NCX optional; both
  kept in sync when present)
- Round-trip preservation of all human-visible content + OPF / NCX
  structural metadata required by e-readers
- Embedded (inline-in-XHTML) SVG and MathML round-trip with
  spec-mandated camelCase attribute names restored (see FR-6 / US-022
  in [`docs/plans/prd.md`](docs/plans/prd.md))
- DeepL HTML document compatibility (HTML5 self-contained payload)
- Solo-user CLI workflow with manual upload / download to DeepL
- Pre-flight validation of the input EPUB (fail-fast on DRM, broken
  manifest, broken spine, non-XHTML spine items, missing NCX/nav document)
- Automatic splitting of oversized payloads across multiple DeepL
  documents at section boundaries (see
  [ADR-0006](docs/adr/0006-auto-split-oversized-payloads.md))

### Out of scope

- Fixed-layout EPUB, SVG-in-spine spine items, and EPUB media overlays
  (rejected regardless of EPUB version)
- DRM-protected EPUBs (detected and rejected; never supported)
- Automated DeepL API integration (user uploads manually)
- Automated `epubcheck` invocation (manual user step)
- GUI, web interface, daemon mode, multi-user features
- Translation memory, caching, or glossary support

Full requirements with user stories: [`docs/plans/prd.md`](docs/plans/prd.md).

## Project Status

**MVP working set, no versioned release yet.** Validated against a
diverse EPUB 2.0 + NCX corpus (technical, novel, workbook genres).
Full corpus round-trip preserves the `epubcheck` baseline (zero new
errors introduced by the tool). Real-DeepL spike completed: one full
Polish translation round-tripped cleanly, R-8 (DeepL preserves
`data-*` attributes) empirically validated.

CI matrix tests Python 3.11 / 3.12 / 3.13 on every push and PR; a
dedicated CI job re-runs the synthetic `epubcheck` zero-drift tests
with a JRE installed.

Per-release notes in [`CHANGELOG.md`](CHANGELOG.md);
empirical operational gotchas in
[`docs/lessons-learned.md`](docs/lessons-learned.md);
architecture decisions in [`docs/adr/`](docs/adr/).

Known limitations:

- Navigation document `<head><title>` stays untranslated — consistent
  with all spine files
- `package/@xml:lang` deliberately stays in the source language
- Where a navigation label's anchor doesn't resolve, the NCX and
  nav-document fallback labels are two independent DeepL translations of
  the same string and may differ slightly
- Apple Books / Calibre-specific metadata quirks — observed but not
  specially handled
- A single chapter/section exceeding `--max-chars` still can't be
  split — auto-split only ever breaks between sections, never inside
  one. Raise `--max-chars` or split the offending chapter in the
  source EPUB.
- Embedded SVG: attribute-name case is restored after translation
  (`viewBox`, `preserveAspectRatio`, …), but element-*name* case
  (`linearGradient`, `clipPath`, …) is not — a book embedding such
  elements fails its `epubcheck` step after restore. Deferred until
  observed in a real corpus; see
  [`docs/TODO.md`](docs/TODO.md).

## License

MIT — see [LICENSE](LICENSE).

---

*A book translated as one DeepL document — or N for oversized books —
instead of one per chapter: the math still works out to many more books
per month than the naive per-chapter workflow, with a TOC that actually
matches the chapter headings.*
