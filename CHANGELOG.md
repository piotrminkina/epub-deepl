# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

No versioned release has been cut yet — everything below is part of
the **Unreleased** working set. The maintainer will move entries under
a versioned heading (e.g. `## [0.1.0]`) when an intentional release is
tagged.

## [Unreleased]

### Added

- **CLI: `prepare` subcommand.** Bundles every XHTML in the OPF spine
  into a single HTML5 document with `<section data-source-href="…"
  data-spine-idx="N">` markers, an OPF metadata block, and an NCX nav
  block carrying `data-*` state for restore.
- **CLI: `restore` subcommand.** Reassembles the translated EPUB using
  the original EPUB as the structural template (see
  [ADR-0001](docs/adr/0001-original-epub-as-state.md)). Reconstructs
  each XHTML body, mutates OPF `<dc:title>` / `<dc:description>` /
  `<dc:subject>` / `<dc:language>`, and rebuilds NCX `<navLabel>` text
  via anchor resolution against restored chapter headings.
- **EPUB 3 nav-document (`nav.xhtml`) support.** `prepare` sends the
  navigation document's toc body into the translation payload
  alongside spine chapters, marked with `data-nav-doc="true"`
  (`data-source-href` remains the restore key, unaffected by the new
  marker); its `page-list` nav is excluded from translation via
  `translate="no"`, matching the existing MathML treatment. That
  `translate="no"` marker is payload-only: `restore` strips it back off
  each page-list `<nav>` unless the original document already carried
  one itself, in which case the original's exact value is restored
  instead — the injected marker never leaks into the final EPUB.
  `restore` rebuilds the nav doc afterwards, overwriting
  `<nav epub:type="toc">`
  link text via the same anchor-resolution strategy already used for
  NCX `<navLabel>`, so both navigation structures land on the same
  translated heading text. Per FR-4, EPUB 3.x requires the nav doc and
  treats NCX as optional (EPUB 2.0's NCX requirement is unchanged); an
  in-spine nav doc is restored through the ordinary spine path, a
  non-spine one through a new writer step placed right after NCX in
  ZIP-entry order.
- **Input validator** (FR-4): fail-fast on DRM, broken manifest,
  broken spine, non-XHTML spine items, missing NCX (`MissingNcx`,
  EPUB 2.0), missing nav document (`MissingNavDoc`, EPUB 3.x — the
  nav doc is required regardless of whether NCX is also present),
  input==output path collision, output exists without `--force`.
- **ZIP packaging** per EPUB OCF 1.0: `mimetype` first entry, STORED,
  zero `flag_bits`, no extra fields, rest DEFLATED.
- **Centralized lxml parser factory** (`epub/_safe_parser.py`) with
  XXE/billion-laughs/DTD/network defaults applied uniformly. See
  [ADR-0003](docs/adr/0003-centralized-parser-factory.md).
- **Per-Python-minor venv naming** (`.venv-${PY_MINOR}/`) — see
  [ADR-0004](docs/adr/0004-per-python-minor-venv.md). Host and
  container coexist without `.venv/` conflicts; `bin/epub-deepl`
  launcher picks the venv whose declared minor matches the current
  `python3`.
- **`bin/epub-deepl` launcher.** Self-locates the project root and
  execs the matching venv's Python with the CLI module. No
  `source activate` required; helpful error when no compatible venv
  exists.
- **Dev Container** based on `debian:bookworm-slim`. Python 3.11 + all
  `lxml` C-extension build deps + a SHA256-pinned `epubcheck` + non-root
  `devcontainer` user with UID matched to the host at creation time
  (no UID 1000 hardcoded). `common-utils` feature handles user setup
  and zsh.
- **Automated `epubcheck` zero-drift tests** (`@pytest.mark.epubcheck`).
  Asserts that round-tripping any EPUB without translation produces
  identical fatal/error/warning counts under W3C `epubcheck`. Promotes
  SM-4 from a manual recipe to a regression gate. Covers EPUB 3
  variants via `build_minimal_epub`'s `nav_landmarks`/`nav_page_list`
  (both hidden navs present alongside the toc nav) and `include_ncx`
  (nav-doc-only, no NCX) fixture parameters.
- **Non-ASCII end-to-end policy test.** Synthetic EPUB with Polish,
  CJK, and Cyrillic content in metadata + headings + body; asserts
  byte-exact preservation through the full CLI pipeline. Closes the
  test-corpus monoculture gap.
- **Portable test corpus.** `tests/corpus/alice-pg11.epub` bundled
  from Project Gutenberg (public domain, EPUB 2.0 + NCX) as the
  default real-world fixture. Override with the `EPUB_DEEPL_CORPUS`
  environment variable.
- **GitHub Actions CI.** Quality matrix on Python 3.11 / 3.12 / 3.13
  (ruff lint + format + mypy --strict + pytest). Separate job
  installs JRE 17 + SHA256-pinned `epubcheck` and runs the
  `@pytest.mark.epubcheck` synthetic-fixture tests. Concurrency
  group cancels superseded runs; least-privilege `permissions:
  contents: read`; per-job `timeout-minutes`.
- **Dependabot config** for the `github-actions` ecosystem with
  monthly grouped updates (`actions-minor-patch` + `actions-major`
  groups) to keep PR noise low.
- **`docs/lessons-learned.md`** capturing real-world gotchas
  (lxml Latin-1 default, per-minor venv layout, DeepL SVG-case
  lowering, identical-string translation drift), an empirical DeepL
  behaviour catalog, and a process retrospective.
- **`docs/adr/`** for architecture decisions:
  - ADR-0001: original EPUB as restore-time structural template
  - ADR-0002: BCP 47 pass-through between `<html lang>` and
    `<dc:language>`
  - ADR-0003: centralized lxml parser factory
  - ADR-0004: per-Python-minor venv naming
- **`docs/plans/`** for forward-looking design artifacts (PRD,
  tech-stack, tech-spec, test-plan).
- **CONTRIBUTING.md** with Dev Container + Native dev setup, quality
  gates, manual-validation recipe, project layout, atomic-commit
  conventions, and an issue-reporting checklist.
- **`.github/ISSUE_TEMPLATE/`** (bug + feature forms) and
  **`pull_request_template.md`** enforcing the quality-gate
  checklist.
- **Auto-split oversized DeepL payloads.** `prepare` now measures the
  rendered payload and, once it exceeds `--max-chars` (default
  `900,000` — a 10% margin below DeepL's 1,000,000-character document
  limit), packs spine sections into multiple parts at section
  boundaries (a chapter is never split mid-section) and writes them as
  `<stem>.<i>of<n>.html` instead of a single file. A payload that
  already fits is unaffected: output stays byte-identical to today's
  single-file behaviour. `--max-chars 0` disables splitting entirely.
  Each part carries advisory `data-part`/`data-parts-total` markers on
  `<body>`; `restore` now accepts multiple translated files
  (`restore INPUT.epub PART1 PART2 ... --output OUT.epub`), rejects
  duplicate file arguments up front, and reassembles one document from
  all parts before applying the existing restore pipeline — the
  completeness gate (spine hrefs vs. translated sections) is
  unaffected, since the part markers are advisory-only, never
  authoritative. A single section that alone exceeds a fresh part's
  budget raises `OversizedSection` naming the offending chapter, with
  remediation advice (raise `--max-chars` or split the source chapter).
  See [ADR-0006](docs/adr/0006-auto-split-oversized-payloads.md).

### Changed

- **Project renamed** from `epub-translation-prepare` →
  `epub-deepl-prepare` → `epub-deepl`. The first rename made the
  translation backend (DeepL) explicit in the name; the second
  removed the redundant `-prepare` suffix so the CLI reads
  `epub-deepl prepare` / `epub-deepl restore` symmetrically.
- **`--lang` is now optional** on `restore`. The target language is
  auto-detected from the translated HTML's `<html lang>` attribute
  and passed verbatim to OPF `<dc:language>` (both surfaces use
  BCP 47, so no normalisation is performed). Pass `--lang CODE`
  explicitly to override. Drift warning when the chosen primary
  subtag matches the source EPUB's. See
  [ADR-0002](docs/adr/0002-bcp47-passthrough.md).
- **README split into a user-facing README and a contributor-facing
  CONTRIBUTING.md.** The user path no longer requires the Dev
  Container; install via `pip install -e .` works on any host with
  Python 3.11+ and the `lxml` build deps.
- **Multiple `dc:language` elements are no longer collapsed to one;
  the first is set to the target language and extras are preserved.**

### Fixed

- **Dev Container `post-create.sh` failed with exit 127 on a stale
  venv.** A workspace rename (or image rebuild) severs the venv's
  `bin/` symlinks; the directory-existence check reused it anyway and
  `pip` died mid-bootstrap. The script now probes the interpreter
  directly and rebuilds the venv when it no longer executes.
- **OPF metadata rebuild dropped attributes (`id`, `xml:lang`,
  `opf:*`) from `dc:title`/`dc:description`/`dc:subject`, orphaning
  EPUB 3 `refines` metadata; text is now mutated in place.**
- **UTF-8 mojibake on non-ASCII body content.** `lxml.html.HTMLParser`
  was defaulting to ISO-8859-1 (HTML4 historical) when parsing the
  body-fragment wrapper, double-encoding Polish/CJK/Cyrillic bytes
  through Latin-1. Set `encoding="utf-8"` as the safe HTML parser's
  fallback.
- **SVG/MathML attribute case loss.** DeepL lowercases `viewBox` /
  `preserveAspectRatio` etc.; `epubcheck` rejects the result. Added
  `epub/_svg_case.py` with a closed enumeration of case-sensitive
  SVG/MathML attribute names; restored before serialisation.
- **`bin/epub-deepl` Python version-mismatch diagnostic.** When the
  selected venv's Python minor does not match the system `python3`,
  the launcher emits a precise, actionable error rather than the
  bare `No module named …` Python would otherwise produce. Now
  fully obsolete after per-minor venv naming landed (ADR-0004), but
  the safety net remains.

### Security

- **`.devcontainer/Dockerfile` pins `epubcheck-5.1.0.zip` by SHA256**
  (`74a59af8…`) — supply-chain integrity for the third-party JAR.
- **CI workflow uses least-privilege `permissions: contents: read`**
  and per-job `timeout-minutes` to bound a runaway job's quota
  consumption.
- **Centralized XXE-safe parser factory** disables external entity
  resolution, DTD loading, and network access on every XML parse
  path. Enforced by a unit test that greps the codebase for bare
  parser instantiation outside `epub/_safe_parser.py`.
