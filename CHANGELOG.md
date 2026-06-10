# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **CI workflow** (GitHub Actions). Matrix-tests `ruff check`,
  `ruff format`, `mypy --strict`, and pytest across Python 3.11 / 3.12 /
  3.13. Separate job installs JRE 17 + a hash-pinned `epubcheck` and
  runs the `@pytest.mark.epubcheck` synthetic-fixture tests.
- **Automated `epubcheck` zero-drift tests** (`@pytest.mark.epubcheck`).
  Asserts that round-tripping any EPUB without translation produces
  identical fatal/error/warning counts under W3C `epubcheck`. Promotes
  SM-4 from a manual recipe to a regression gate.
- **Non-ASCII end-to-end policy test**. Synthetic EPUB with Polish,
  CJK, and Cyrillic content in metadata + headings + body; asserts
  byte-exact preservation through the full CLI pipeline. Closes the
  test-corpus monoculture gap from `lessons-learned.md` P-2.
- **3 ADRs** in `docs/adr/`: original-EPUB-as-state, BCP 47
  pass-through, centralized parser factory.
- **`docs/plans/lessons-learned.md`** capturing real-world gotchas
  (G-1..G-4), empirical DeepL behaviour catalog, and process
  retrospective (P-1..P-5).
- **`bin/epub-deepl`** launcher that self-locates the project
  venv and detects Python minor-version mismatch with an actionable
  diagnostic.
- **CONTRIBUTING.md** with the Dev Container workflow, quality gates,
  and code style conventions.

### Changed

- **`--lang` is now optional**. Restore auto-detects the target
  language from the translated HTML's `<html lang>` attribute and
  passes the value verbatim to OPF `<dc:language>`. Both surfaces use
  BCP 47, so no normalization is performed. Pass `--lang CODE`
  explicitly to override. Drift warning when the chosen primary
  subtag matches the source EPUB's. (See [ADR-0002](docs/adr/0002-bcp47-passthrough.md).)
- **Project renamed** from `epub-translation-prepare` to
  `epub-deepl`. Package, CLI, module, and devcontainer
  identifiers updated; display name "EPUB DeepL" on
  human-facing surfaces.
- **README split into user-facing README + CONTRIBUTING.md**. README
  no longer requires the Dev Container to run the tool.

### Fixed

- **UTF-8 mojibake on non-ASCII body content**. `lxml.html.HTMLParser`
  was defaulting to ISO-8859-1 (HTML4 historical) when parsing the
  body-fragment wrapper, double-encoding Polish/CJK/Cyrillic bytes
  through Latin-1. Set `encoding="utf-8"` as the safe HTML parser's
  fallback. (`fed9a6d`)
- **SVG/MathML attribute case loss**. DeepL lowercases `viewBox` /
  `preserveAspectRatio` etc.; epubcheck rejects the result. Added
  `epub/_svg_case.py` with a closed enumeration of 57 case-sensitive
  attributes; restored before serialization. (`7c84805`)
- **Devcontainer venv self-healing**. `post-create.sh` detects a venv
  built with a different Python minor than the current interpreter
  and rebuilds, preventing a "No module named pip" crash on
  host↔container handoffs. (`2b0093a`)

### Security

- `.devcontainer/Dockerfile` pins `epubcheck-5.1.0.zip` by SHA256
  (`74a59af8…`) — supply-chain integrity for the third-party JAR.
  (`a28ee38`)

## [0.1.0] — Initial MVP

Round-trip pipeline EPUB ↔ HTML for DeepL document translation.

### Added

- **`prepare`**: bundle every XHTML in the OPF spine into a single
  HTML5 document with `<section data-source-href="…" data-spine-idx="N">`
  markers, OPF metadata block, and NCX nav block carrying `data-*`
  state for restore.
- **`restore`**: reassemble the translated EPUB using the original as
  the structural template (see
  [ADR-0001](docs/adr/0001-original-epub-as-state.md)). Reconstructs
  each XHTML body, mutates OPF `<dc:title>` / `<dc:description>` /
  `<dc:subject>` / `<dc:language>`, and rebuilds NCX `<navLabel>`
  text via anchor resolution against restored chapter headings.
- **Input validator** (FR-4): fail-fast on DRM, broken manifest,
  broken spine, non-XHTML spine items, missing NCX, input==output
  path collision, output exists without `--force`.
- **ZIP packaging** per EPUB OCF 1.0: `mimetype` first entry, STORED,
  zero `flag_bits`, no extra fields, rest DEFLATED.
- **Centralized lxml parser factory** (`epub/_safe_parser.py`) with
  XXE/billion-laughs/DTD/network defaults applied uniformly. See
  [ADR-0003](docs/adr/0003-centralized-parser-factory.md).
- **Dev Container** based on `debian:bookworm-slim` with Python 3.11,
  lxml build dependencies, hash-pinned epubcheck, and a non-root user
  (`devcontainer`) whose UID is matched to the host at container
  creation via `common-utils` (no UID 1000 hardcoded).
- **Test suite**: 118 unit + synth integration + corpus tests at
  initial release; grew to 175+ over the unreleased window.
- **Planning artifacts** in `docs/plans/`: PRD, tech-stack, tech-spec,
  test-plan, devils-advocate review.

[Unreleased]: https://github.com/OWNER/REPO/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/REPO/releases/tag/v0.1.0
