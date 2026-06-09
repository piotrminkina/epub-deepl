# Product Requirements Document (PRD) — epub-translation-prepare

**Status:** Draft v1 (MVP)
**Owner:** Solo developer (single user)
**Last updated:** 2026-06-09
**Related:** `tech-stack.md` (TBD), `tech-spec.md` (TBD), test plan (TBD)

---

## 1. Product Overview

`epub-translation-prepare` is a Python CLI tool that prepares an EPUB file for
translation by bundling all human-facing content into a single HTML5 document
suitable for upload to DeepL's HTML document translation, and then reassembles
the translated HTML back into a structurally identical EPUB.

The tool is invoked as two subcommands of a single binary:

- `prepare <input.epub>` — produces a single HTML payload for translation.
- `restore <input.epub> <translated.html> --lang <code>` — produces the
  translated EPUB, reusing the original EPUB as a structural template.

The MVP targets EPUB 2.0.1 books with NCX-based navigation (the format of the
user's existing corpus). EPUB 3 with `nav.xhtml` is out of MVP scope.

---

## 2. User Problem

The user is an individual reader with a DeepL Pro Starter subscription, which
grants 5 document translations per month. A single EPUB typically contains
10–50 separate XHTML files plus an OPF manifest and NCX navigation file.

Two failure modes exist for naive workflows:

1. **Quota exhaustion.** Uploading each XHTML file as its own DeepL document
   consumes the monthly quota in a single book.
2. **Structural loss.** Extracting text-only content, translating, then
   manually reassembling drops the table of contents, image metadata,
   per-chapter `<title>` elements, OPF metadata, and cross-file link
   integrity. Reassembling a valid EPUB by hand is error-prone and slow.

The user needs a deterministic round-trip: many XHTML files in → one HTML
document → translate externally → one HTML document → many XHTML files out,
with full preservation of every structural element that the e-reader exposes
to the reader.

---

## 3. Functional Requirements

### FR-1: `prepare` subcommand

- Read the input EPUB ZIP archive.
- Validate input before any output is produced (see FR-4).
- Extract human-visible content from these sources:
  - Body of every XHTML listed in the OPF spine, in spine order.
  - OPF metadata: `<dc:title>`, `<dc:description>`, `<dc:subject>` (all
    occurrences).
  - NCX text: `<docTitle><text>`, every `<navLabel><text>`.
- Bundle into a single HTML5 document with this structure:
  - `<!DOCTYPE html>` and `<html lang="…">` declaring the source language
    read from `<dc:language>`.
  - `<head>` containing `<meta charset="utf-8">`, `<title>` from OPF, and
    `<meta name="description" content="…">` from `<dc:description>`.
  - `<body>` containing:
    - A top-level metadata block exposing each `<dc:subject>` as visible
      text for translation.
    - A `<nav data-source="ncx">` block carrying every original NCX entry
      with its `src` attribute and `playOrder` preserved as `data-*`
      attributes, so `restore` can rebuild NCX after translation.
    - One `<section data-source-href="…" data-spine-idx="N">` per source
      XHTML, in spine order. Each section wraps an inner `<header>` that
      reproduces the source XHTML's `<title>` (translator context) and
      the original body content.
- Every MathML element receives a `translate="no"` attribute to signal
  DeepL to leave it untouched.
- Output is written to `<input-stem>.prepare.html` in the input's directory
  unless `--output` overrides.

### FR-2: `restore` subcommand

- Inputs: original EPUB (as structural template), translated HTML, target
  language code via `--lang`.
- Parse the translated HTML; locate every `<section data-source-href="…">`.
- Reconstruct each XHTML file by:
  - Reading the original file from the input EPUB.
  - Replacing the `<body>` content with the translated section's body.
  - Preserving the original DOCTYPE, root element, namespace declarations,
    `<head>` contents, and processing instructions.
- Rebuild the OPF:
  - Replace `<dc:title>`, `<dc:description>`, `<dc:subject>` with
    translated values extracted from the translated HTML.
  - Update `<dc:language>` to the value of `--lang`.
  - Leave `<dc:creator>`, `<dc:publisher>`, `<dc:date>`, `<dc:identifier>`,
    `<dc:rights>`, `<manifest>`, `<spine>`, and `<guide>` unchanged.
- Rebuild the NCX:
  - Preserve the full `<navMap>` structure, `<navPoint>` nesting,
    `playOrder` attributes, and `<content src="…">` attributes.
  - For each `<navLabel><text>`, perform anchor resolution: parse the
    corresponding `<content src="path#fragment"/>`, locate the element
    with `id="fragment"` in the restored XHTML, and use its text content
    (whitespace-normalized) as the new label. If the `src` has no
    fragment, use the first `<h1>`, `<h2>`, or `<h3>` (in document
    order) as the target.
  - Update `<docTitle><text>` from the translated OPF `<dc:title>`.
- Package the output as a ZIP archive with EPUB-required ordering:
  - `mimetype` first, STORED method, no extra fields, byte content
    exactly `application/epub+zip`.
  - All other files DEFLATED.
- Output is written to `<input-stem>.translated.epub` unless `--output`
  overrides.

### FR-3: CLI surface

- `epub-translation-prepare prepare <input.epub> [--output FILE] [--force]`
- `epub-translation-prepare restore <input.epub> <translated.html> --lang <code> [--output FILE] [--force]`
- `--lang` accepts a BCP 47 / ISO 639-1 language code (e.g. `pl`, `en`,
  `de`, `pt-BR`).
- `--force` overwrites existing output files; without it, an existing
  output causes a fail-fast exit.
- Exit codes:
  - `0` — success.
  - `1` — user error (bad input, missing file, validation failure,
    unsupported book).
  - `2` — internal error (unexpected exception).
- All errors emit a structured `[ERROR] <message>` line to stderr.
- Warnings emit `[WARN] <message>` to stderr and do not affect exit code.

### FR-4: Input validation (fail-fast)

Before producing any output, `prepare` must validate:

- File is a readable ZIP archive.
- ZIP contains `mimetype` and `META-INF/container.xml`.
- `mimetype` content is exactly `application/epub+zip`.
- `META-INF/container.xml` references a valid OPF path.
- The OPF is parseable XML with a `<package>` root and EPUB 2.0 version.
- OPF `<manifest>` is parseable; every `<item href="…">` resolves to a
  file in the ZIP.
- OPF `<spine>` is parseable; every `<itemref idref="…">` resolves to a
  manifest item.
- NCX file (referenced as `toc` in the spine or as `application/x-dtbncx+xml`
  in the manifest) exists and is parseable.
- No `META-INF/encryption.xml` (DRM detection).

`restore` must additionally validate:

- The translated HTML is parseable.
- Every `<section data-source-href="…">` resolves to a manifest entry in
  the input EPUB.
- The translated HTML contains at least the same set of `data-source-href`
  values as the input's spine (no missing sections).

### FR-5: Logging

- Default: only errors and warnings on stderr.
- `--verbose` flag: per-file progress to stderr.
- No logging to stdout (stdout is reserved for future structured output).

---

## 4. Project Scope Boundaries

### In scope (MVP)

- EPUB 2.0.1 with NCX-based navigation.
- Round-trip preservation of all human-visible content and OPF/NCX
  structural metadata required by e-readers.
- DeepL HTML document compatibility (output is HTML5 that DeepL accepts
  as a translatable document).
- Solo-user CLI workflow with manual upload/download to DeepL.

### Out of scope

- EPUB 3 with `nav.xhtml` navigation — deferred to post-MVP.
- DRM-protected EPUBs — detected and rejected, never supported.
- Automatic invocation of the DeepL API (user uploads/downloads manually).
- Automatic invocation of `epubcheck` (manual user step).
- Splitting books larger than DeepL's per-document character limit across
  multiple documents.
- GUI, web interface, daemon mode, or multi-user features.
- Translation memory, caching, or glossary support.
- Ruby annotation preservation strategy (warning only; pass-through).
- MathML translation (kept untranslated via `translate="no"`).
- Streaming or incremental processing (full in-memory pipeline).
- Cross-file link rewriting (`href="ch03.xhtml#sec2"` left as-is in merged
  HTML; the merged HTML is a translation payload, not a navigable
  document).

---

## 5. User Stories

### US-001: Prepare an EPUB for translation

**Description:** As the user, I want to convert an EPUB into a single
HTML file so I can upload it to DeepL as one document.

**Acceptance criteria:**

- Given a valid EPUB at `book.epub`, when I run `prepare book.epub`,
  then `book.prepare.html` is created in the same directory.
- The output is a single self-contained HTML5 document beginning with
  `<!DOCTYPE html>` and a `<html lang="…">` declaring the source language
  read from the input OPF `<dc:language>`.
- The output `<body>` contains exactly one `<section data-source-href="X">`
  per XHTML file in the OPF spine, in spine order, with
  `data-spine-idx="N"` reflecting the zero-based position.
- The output `<head>` contains `<title>` populated from OPF `<dc:title>`
  and `<meta name="description">` populated from `<dc:description>`.
- A `<nav data-source="ncx">` block at the start of `<body>` lists every
  original NCX `<navPoint>` with its `src` attribute and `playOrder`
  preserved as `data-*` attributes.
- Exit code is `0`.

### US-002: Restore an EPUB from translated HTML

**Description:** As the user, I want to take my translated HTML back from
DeepL and reconstruct the EPUB with translated content.

**Acceptance criteria:**

- Given `book.epub` and `book.translated.html`, when I run
  `restore book.epub book.translated.html --lang pl`, then
  `book.translated.epub` is created in the same directory.
- The output EPUB has identical file paths to the input (manifest and
  spine references resolve to the same href values).
- For each XHTML file, only `<body>` content differs from input; head,
  DOCTYPE, charset, and root element attributes are preserved.
- The output OPF `<dc:title>`, `<dc:description>`, `<dc:subject>` values
  are taken from the translated HTML's metadata block.
- The output OPF `<dc:language>` is `pl`.
- The output ZIP has `mimetype` as the first entry, STORED method, with
  byte content exactly `application/epub+zip`.
- Exit code is `0`.

### US-003: Fail fast on DRM-protected EPUB

**Description:** As the user, I want a clear error when the EPUB is
encrypted, before any processing.

**Acceptance criteria:**

- Given an EPUB containing `META-INF/encryption.xml`, when I run
  `prepare`, then exit code is `1`.
- stderr contains a line matching `^[ERROR] EPUB is encrypted \(DRM detected\)`.
- No output file is created.

### US-004: Fail fast on broken manifest

**Description:** As the user, I want a clear error when the OPF manifest
references files that are missing from the ZIP.

**Acceptance criteria:**

- Given an EPUB where the OPF manifest references at least one file not
  present in the ZIP, when I run `prepare`, then exit code is `1`.
- stderr identifies each missing href.
- No output file is created.

### US-005: Fail fast on broken spine

**Description:** As the user, I want a clear error when the spine
references manifest IDs that do not exist.

**Acceptance criteria:**

- Given an EPUB where at least one `<itemref idref="X">` in spine has no
  matching `<item id="X">` in manifest, when I run `prepare`, then exit
  code is `1`.
- stderr identifies each unresolved idref.
- No output file is created.

### US-006: Round-trip without translation is content-identical

**Description:** As the user, I want confidence that the tool does not
corrupt EPUBs even when no translation has been applied.

**Acceptance criteria:**

- Given a valid EPUB `X.epub` whose `<dc:language>` is `L`, when I run
  `prepare X.epub` followed by
  `restore X.epub X.prepare.html --lang L`, producing `X.translated.epub`,
  then `diff -r <unzipped X.epub> <unzipped X.translated.epub>` shows no
  differences in any file's textual content (file modification times and
  ZIP central directory ordering may differ).

### US-007: Restored EPUB carries translated metadata

**Description:** As the user, I want my e-reader to display the translated
title, description, and subjects.

**Acceptance criteria:**

- Given a translated HTML whose top-level metadata block contains
  translated `<dc:title>`, `<dc:description>`, and `<dc:subject>` values,
  the output OPF has matching values in the corresponding elements.

### US-008: NCX labels match chapter headings

**Description:** As the user, I want the table of contents in my reader
to match the chapter headings exactly, so navigation is consistent with
content.

**Acceptance criteria:**

- For every `<navPoint>` in the input NCX, the corresponding output
  `<navLabel><text>` equals the whitespace-normalized text content of
  the element referenced by that navPoint's `<content src="path#fragment"/>`
  in the restored XHTML.
- If `src` has no fragment, the target is the first `<h1>`, `<h2>`, or
  `<h3>` (whichever appears first in document order) in the referenced
  file.

### US-009: Target language declared in OPF

**Description:** As the user, I want my e-reader and any post-processing
tool to know the book's language.

**Acceptance criteria:**

- The output OPF `<dc:language>` equals the value passed to `--lang`.
- If the input has multiple `<dc:language>` elements, only the first is
  updated; subsequent ones are removed.

### US-010: Non-translated metadata preserved structurally

**Description:** As the user, I want author, publisher, identifier, date,
and rights notice to remain exactly as in the original.

**Acceptance criteria:**

- Output OPF `<dc:creator>`, `<dc:publisher>`, `<dc:date>`,
  `<dc:identifier>`, `<dc:rights>` have **structurally identical**
  content to the input: same element count, same text content
  (whitespace-equivalent), same attributes with same values.
- All `opf:*` namespaced attributes on these elements are preserved
  with identical names and values (order tolerance permitted).
- "Byte-identical" is **not** a requirement; XML re-serialisation may
  change attribute ordering, self-closing tag style, or entity encoding,
  as long as the semantic content is preserved.

### US-011: MathML survives round-trip untranslated

**Description:** As the user, I want math formulas to be left alone by
DeepL.

**Acceptance criteria:**

- In `prepare` output, every element in the MathML namespace
  (`http://www.w3.org/1998/Math/MathML`) carries `translate="no"`.
- In `restore` output, MathML element subtrees are byte-identical to
  input.

### US-012: Ruby annotations warned about

**Description:** As the user, I want to know when my book contains
features the tool does not specially handle, so I can verify the result
manually.

**Acceptance criteria:**

- When the input contains any `<ruby>` element, `prepare` emits a single
  stderr line matching `^[WARN] Ruby annotations detected in \d+ place\(s\)`.
- Exit code remains `0` and processing continues.

### US-013: Manifest and spine are structurally identical after round-trip

**Description:** As the user, I want absolute confidence about the EPUB's
file structure.

**Acceptance criteria:**

- The output OPF's `<manifest>` element contains the same set of `<item>`
  elements (same `id`, `href`, `media-type`, and any `properties`
  attribute), in the same order, as the input.
- The output OPF's `<spine>` element contains the same set of
  `<itemref>` elements (same `idref`, same `linear` attribute), in the
  same order, as the input.
- The spine's `toc` attribute (referencing NCX) is preserved.
- Comparison is via canonical XML form (sorted attributes,
  whitespace-normalised), not raw bytes.

### US-014: Output file naming and overwrite protection

**Description:** As the user, I want predictable file names and no silent
overwrites.

**Acceptance criteria:**

- `prepare book.epub` writes to `book.prepare.html`.
- `restore book.epub book.prepare.html --lang pl` writes to
  `book.translated.epub`.
- `--output FILE` overrides the default path.
- If the target output file exists and `--force` is absent, the tool
  exits with code `1` and stderr contains `^[ERROR] Output file exists`.

### US-015: Self-describing help

**Description:** As the user, I want to discover the tool's interface
without external documentation.

**Acceptance criteria:**

- Running the tool with no arguments or `--help` displays usage with
  both subcommands and a one-line description of each.
- Each subcommand's `--help` lists every flag with its description and
  default value.

### US-016: Output validity (manual verification)

**Description:** As the user, I want my translated books to be valid
EPUBs accepted by every reader.

**Acceptance criteria:**

- For every test corpus EPUB that passes `epubcheck` before processing,
  the output of the round-trip-without-translation case also passes
  `epubcheck` with no errors. (Verification is manual; the tool itself
  does not invoke `epubcheck`.)

### US-017: Authentication / authorization (not applicable)

**Description:** This tool runs locally and has no remote interface,
shared state, or stored credentials. No authentication or authorization
mechanism is needed.

**Acceptance criteria:** N/A — confirmed explicitly to satisfy the PRD
auth checklist.

### US-018: Input and output paths must not collide

**Description:** As the user, I want the tool to refuse to overwrite an
input file with output, regardless of `--force`.

**Acceptance criteria:**

- When the resolved output path equals the resolved input EPUB path
  (or the input translated HTML path for `restore`), the tool exits
  with code `1`.
- stderr contains a line matching `^[ERROR] Output path equals input path`.
- `--force` does not bypass this check (data-loss protection takes
  precedence over force).

### US-019: Missing or empty `<dc:language>` is tolerated

**Description:** As the user, I want the tool to handle EPUBs that omit
`<dc:language>` (a legal-violation that exists in many real books).

**Acceptance criteria:**

- When the input OPF has no `<dc:language>` element or has an empty one,
  `prepare` emits `[WARN] Source language not declared in OPF; using "und"`
  to stderr and uses BCP 47 `und` (Undetermined) as the value for
  `<html lang="…">` in the merged HTML.
- Exit code remains `0`.
- `restore` always writes the value of `--lang` regardless of input
  presence.

### US-020: Non-XHTML spine items are detected and reported

**Description:** As the user, I want clear handling of EPUBs whose spine
includes media types the tool cannot bundle (e.g. DTBook, legacy HTML).

**Acceptance criteria:**

- When a spine item's manifest media-type is not
  `application/xhtml+xml`, `prepare` exits with code `1`.
- stderr contains a line matching
  `^[ERROR] Unsupported spine media-type: ` listing the offending
  media-type and item href.
- The tool does not silently skip or mis-translate such items.

---

## 6. Success Metrics

| ID | Metric | Target | Measurement |
|---|---|---|---|
| SM-1 | Round-trip integrity (no translation) | 100% of test corpus | Composite check: (a) `diff -r` of unzipped EPUBs shows no content differences for all 4 books in `/tmp/nowe`; (b) output ZIP has `mimetype` as first entry, STORED, `flag_bits=0`, no extra-field bytes; (c) all other entries DEFLATED; (d) output passes `zipfile.ZipFile.testzip()` |
| SM-2 | Translation completeness | 100% of translatable fields | Manual inspection: every `<dc:title>`, `<dc:description>`, `<dc:subject>`, chapter heading, paragraph, `alt`/`title`/`aria-label` is in the target language after DeepL round-trip |
| SM-3 | TOC ↔ heading consistency | Byte-equal after whitespace normalization | For each `<navLabel><text>`, the value equals the resolved target element's normalized text content |
| SM-4 | EPUB validity | Output passes `epubcheck` | Run `epubcheck` on all 4 test books after round-trip-without-translation; no errors |
| SM-5 | DeepL quota economy | 1 document per book | Each book consumed exactly 1 of the 5/month Pro Starter slots |
| SM-6 | CLI turnaround | < 60 s combined `prepare` + `restore` per book | Wall-clock measurement on the largest book in the test corpus |
| SM-7 | R-8 regression coverage | Adversarial fixture exists and passes | Automated test simulates DeepL stripping `data-*` attributes, reordering attributes, and collapsing whitespace; restore must either succeed or fail with a precise diagnostic (not crash, not corrupt output) |

---

## 7. Risks & Challenges

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | DeepL modifies HTML structure unexpectedly (whitespace in `<pre>`, entity collapse, comment rewriting) | Medium | High | Restore uses lxml tolerant parsing; locate sections by `data-source-href`, not document offset; do not require byte-equality for translated content |
| R-2 | Large EPUBs exceed DeepL's per-document character limit | Low (novels), Medium (technical books) | Medium | Documented as known limitation; user falls back to per-chapter translation or `bilingual_book_maker` for oversized books |
| R-3 | NCX with deep nested `<navPoint>` hierarchy (textbooks) | Medium | Low | Recursive anchor resolution; explicit test against a deeply-nested book |
| R-4 | ID collisions across XHTML files cause wrong anchor resolution | Medium | Medium | Anchor resolution is scoped per-file via `data-source-href` mapping, never globally |
| R-5 | EPUB 2 XHTML 1.1 stricter than HTML5 (DeepL output may not validate as XHTML 1.1) | High | Medium | Restore re-serializes via lxml in XHTML mode; explicit XML declaration; HTML entities normalized to XML-safe forms |
| R-6 | Encoding edge cases: BOM, declared non-UTF-8 encoding, smart-quote substitution by DeepL | Medium | Low–Medium | Force UTF-8 throughout; strip BOM on read; preserve XML declaration verbatim |
| R-7 | OPF with non-standard extension namespaces (Apple, Kobo, Calibre custom metadata) | Low | Low | Restore uses input OPF as template; modifies only known-safe fields; unknown elements pass through untouched |
| R-8 | DeepL strips or modifies `data-*` attributes on `<section>` markers | Low (DeepL documents preserving attributes) | Catastrophic (round-trip breaks) | Validate every `data-source-href` resolves during restore; fail-fast with clear message if any are missing |

---

## 8. Technical Constraints

- **TC-1: Language.** Python 3.11 or newer (modern type hints, structural
  pattern matching for OPF/NCX dispatch).
- **TC-2: Dependencies.** Only `lxml` outside the standard library. No
  EPUB-specific libraries (`ebooklib`, `epubfile`); structural handling is
  in-house for full control.
- **TC-3: Standard library use.** `zipfile`, `argparse`, `pathlib`, `re`,
  `logging`, `sys`.
- **TC-4: EPUB ZIP layout.** Output ZIP must satisfy IDPF EPUB 2.0.1
  packaging rules: `mimetype` first, STORED, no extra fields, no
  general-purpose bit flags; everything else DEFLATED.
- **TC-5: Merged HTML format.** Valid HTML5, UTF-8, self-contained (no
  external CSS / image references in the merged file — DeepL processes
  the document in isolation). File size below DeepL's HTML per-document
  limit (verify against current DeepL documentation; declared in the
  region of 1 MB for HTML at the time of writing).
- **TC-6: Execution environment.** A devcontainer (per user direction)
  provides the development and test environment. Base image is a generic
  distribution (no predefined VS Code UID 1000 user); all tooling
  (Python, lxml, optional `epubcheck` for manual verification, dev
  tooling such as ruff/mypy/pytest) is installed via Dockerfile or
  devcontainer features. Implementation and tests run inside the same
  container that contributors and CI use, ensuring environment parity.
- **TC-7: No network I/O at runtime.** Translation is performed
  externally by DeepL (web UI or API, at the user's discretion). This
  tool only formats and reassembles; it never contacts a network.
- **TC-8: No persistent state.** No cache, no database, no temp files
  beyond OS-managed extraction during processing. Inputs and outputs
  are the only on-disk artifacts.
- **TC-9: Single-user execution.** No concurrent invocations expected;
  no locking, no daemon, no multi-process coordination.
- **TC-10: No telemetry.** No usage data, no crash reporting, no
  analytics.
