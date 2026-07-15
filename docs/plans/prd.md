# Product Requirements Document (PRD) — epub-deepl

**Status:** Draft v1 (MVP)
**Owner:** Solo developer (single user)
**Last updated:** 2026-06-09
**Related:** `tech-stack.md` (TBD), `tech-spec.md` (TBD), test plan (TBD)

---

## 1. Product Overview

`epub-deepl` is a Python CLI that translates an EPUB through DeepL with
**maximum structural fidelity to the original**. The translated book
reads in any e-reader exactly like the source minus the translated text:
TOC labels track chapter headings, manifest and spine survive
byte-for-byte, embedded SVG attribute case is preserved, non-ASCII
characters round-trip cleanly through Unicode.

Mechanically, the tool bundles all human-facing content (XHTML body
text, OPF metadata, NCX navigation labels) into a single HTML5
document for upload to DeepL's document-translation feature, then
reassembles a structurally-identical EPUB from the translated HTML
using the original EPUB as the structural template.

Two subcommands of a single binary:

- `prepare <input.epub>` — produces a single HTML payload for translation.
- `restore <input.epub> <translated.html> [--lang <code>]` — produces
  the translated EPUB, reusing the original EPUB as a structural template.

The MVP targets EPUB 2.0.1 books with NCX-based navigation (the format
the maintainer's corpus is in), and now extends to reflowable EPUB 3.x
books with nav-document navigation (NCX optional). Fixed-layout EPUB,
SVG-in-spine content, and media overlays remain out of MVP scope.

---

## 2. User Problem

The user wants to translate an EPUB through a per-document translation
service (DeepL) while keeping the result **structurally faithful to the
original** — TOC, manifest, spine, NCX, embedded SVG, and Unicode
encoding all intact, so the translated book reads in any e-reader
exactly like the source minus the translated text.

A single EPUB typically contains 10–50 separate XHTML files plus an
OPF manifest and an NCX navigation file. The naive workflow (unzip,
translate each file separately, repackage by hand) is expensive on
three axes:

1. **Structural fragility.** Manual reassembly drops the table of
   contents, mis-orders the spine, breaks cross-file links, mangles
   OPF metadata or NCX navigation, and easily produces an EPUB that
   fails `epubcheck` or renders incorrectly in real readers.
   Producing a valid EPUB by hand is error-prone and slow.
2. **Operator time.** Tens of file-by-file upload, download, and
   reassembly cycles per book.
3. **Translation-job count.** Per-document translation services
   charge once per file. With DeepL Pro Starter's 5-documents-per-
   month limit, an EPUB with ~20 XHTMLs exhausts the quota on a
   single book.

The user needs a deterministic round-trip: many XHTML files in → one
HTML document → translate externally → one HTML document → many XHTML
files out, with full preservation of every structural element the
e-reader exposes to the reader, and a single quota-counter increment
per book as a consequence.

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

- `epub-deepl prepare <input.epub> [--output FILE] [--force]`
- `epub-deepl restore <input.epub> <translated.html> [--lang <code>] [--output FILE] [--force]`
- `--lang` accepts a BCP 47 tag (e.g. `pl`, `en`, `de`, `pt-BR`). It is
  optional; auto-detected from the translated HTML's `<html lang>` when
  omitted. See US-009 for the full resolution order.
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
- The OPF is parseable XML with a `<package>` root and a `version`
  attribute starting with `2` or `3` (EPUB 2.x or 3.x).
- OPF `<manifest>` is parseable; every `<item href="…">` resolves to a
  file in the ZIP.
- OPF `<spine>` is parseable; every `<itemref idref="…">` resolves to a
  manifest item.
- Navigation document requirement depends on EPUB version:
  - EPUB 2.x: NCX file (referenced as `toc` in the spine or as
    `application/x-dtbncx+xml` in the manifest) exists and is parseable.
  - EPUB 3.x: a manifest `<item>` whose `properties` token list contains
    `nav` exists and is parseable; NCX is optional and, when present, is
    kept in sync with the nav document.
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
- Reflowable EPUB 3.x with nav-document navigation (NCX optional; both
  kept in sync when present).
- Round-trip preservation of all human-visible content and OPF/NCX
  structural metadata required by e-readers.
- DeepL HTML document compatibility (output is HTML5 that DeepL accepts
  as a translatable document).
- Solo-user CLI workflow with manual upload/download to DeepL.
- Automatic splitting of payloads exceeding DeepL's per-document
  character limit across multiple documents, packed at section
  boundaries (see [ADR-0006](../adr/0006-auto-split-oversized-payloads.md)).

### Out of scope

- Fixed-layout EPUB, SVG-in-spine spine items, and EPUB media overlays
  — rejected regardless of EPUB version.
- DRM-protected EPUBs — detected and rejected, never supported.
- Automatic invocation of the DeepL API (user uploads/downloads manually).
- Automatic invocation of `epubcheck` (manual user step).
- Splitting a single chapter/section that alone exceeds `--max-chars`
  (auto-split only breaks between sections, never inside one).
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

### US-009: Target language resolution and OPF declaration

**Description:** As the user, I want the tool to figure out the target
language automatically when DeepL has already declared it in the
translated HTML, and to accept an explicit override when I need one.
Both EPUB OPF `<dc:language>` and HTML5 `<html lang>` use the same
syntax (BCP 47 / RFC 5646), so values pass through verbatim without
normalisation.

**Acceptance criteria:**

- `--lang` is optional. Resolution order:
  1. `--lang CODE` (when provided) — force; emits `[WARN]` if it
     differs from `<html lang>` detected in the translated HTML.
  2. `<html lang="…">` from the translated HTML's root element, after
     leading/trailing whitespace is trimmed (EPUB Packages §5.6.3
     mandates this trim).
  3. Otherwise `UserError`: stderr line containing `--lang`, exit 1.
- The chosen value is validated as well-formed BCP 47 (regex
  `^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$`). Not well-formed → `UserError`
  with diagnostic. Strict registry-lookup validation is intentionally
  out of scope (matches epubcheck's posture).
- The chosen value is written verbatim to OPF `<dc:language>`. No
  region stripping, no case folding. `pl-PL` stays `pl-PL`; `pl`
  stays `pl`.
- If the input EPUB has multiple `<dc:language>` elements, only the
  first is updated; subsequent ones are removed.
- Drift warning (informational, does not fail): if the chosen target's
  **primary subtag** (case-insensitive) matches the source EPUB's
  primary subtag, emit `[WARN]` naming both values — possible
  indication that translation did not actually run (e.g. user uploaded
  to DeepL but downloaded the original).

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

### US-021: Oversized payloads are split automatically at section boundaries

**Description:** As the user, I want a book whose merged payload exceeds
DeepL's per-document character limit to still translate in one workflow,
without hand-splitting the EPUB myself.

**Acceptance criteria:**

- `prepare` accepts `--max-chars N` (default `900,000`, a ~10% margin
  under DeepL's 1,000,000-character limit).
- When the merged payload is at or under `--max-chars`, output is exactly
  one `<stem>.prepare.html` file, byte-identical to the output produced
  without the flag — the split mechanism never changes behavior for
  books that already fit.
- When the payload exceeds `--max-chars`, `prepare` instead emits
  `<stem>.prepare.1ofN.html`, `<stem>.prepare.2ofN.html`, … packing
  whole sections greedily in spine order; no section is ever split
  across two parts. `prepare` exits `0` and emits one `[WARN]` listing
  the parts written and instructing the user to translate each
  separately.
- `--max-chars 0` disables splitting outright — the payload emits as
  one file regardless of size.
- A single section that alone exceeds a fresh part's budget makes
  `prepare` exit `1` with an error naming the offending section's href,
  its size, and the remediation (raise `--max-chars`, or split that
  chapter in the source EPUB) — this is the only case not handled by
  the automatic path.
- `restore` accepts one or more translated files (`nargs="+"`) in any
  order; passing every part of a split payload merges them back into a
  single logical document before the usual per-section rebuild. Order
  never matters because sections are re-associated by their
  `data-source-href`, not by file position.
- If a required section is missing from the combined set of translated
  files, `restore` exits `1` naming the missing section(s), identical to
  today's single-file behavior.

---

## 6. Success Metrics

| ID | Metric | Target | Measurement |
|---|---|---|---|
| SM-1 | Round-trip integrity (no translation) | 100% of test corpus | Composite check: (a) `diff -r` of unzipped EPUBs shows no content differences for all 4 books in the corpus directory; (b) output ZIP has `mimetype` as first entry, STORED, `flag_bits=0`, no extra-field bytes; (c) all other entries DEFLATED; (d) output passes `zipfile.ZipFile.testzip()` |
| SM-2 | Translation completeness | 100% of translatable fields | Manual inspection: every `<dc:title>`, `<dc:description>`, `<dc:subject>`, chapter heading, paragraph, `alt`/`title`/`aria-label` is in the target language after DeepL round-trip |
| SM-3 | TOC ↔ heading consistency | Byte-equal after whitespace normalization | For each `<navLabel><text>`, the value equals the resolved target element's normalized text content |
| SM-4 | EPUB validity | Output passes `epubcheck` | Run `epubcheck` on all 4 test books after round-trip-without-translation; no errors |
| SM-5 | Translation-job economy | `ceil(payload / 900,000)` DeepL documents per book (1 for the vast majority) | One translator upload per book for payloads at or under the 900k default; oversized books auto-split into the minimum number of parts needed. Under DeepL Pro Starter's 5-documents-per-month limit, a 1-document book allows roughly 5 books/month — vs ~1 book per month under per-XHTML translation; a split book proportionally trades slot count for still-automatic reassembly. |
| SM-6 | CLI turnaround | < 60 s combined `prepare` + `restore` per book | Wall-clock measurement on the largest book in the test corpus |
| SM-7 | R-8 regression coverage | Adversarial fixture exists and passes | Automated test simulates DeepL stripping `data-*` attributes, reordering attributes, and collapsing whitespace; restore must either succeed or fail with a precise diagnostic (not crash, not corrupt output) |

---

## 7. Risks & Challenges

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | DeepL modifies HTML structure unexpectedly (whitespace in `<pre>`, entity collapse, comment rewriting) | Medium | High | Restore uses lxml tolerant parsing; locate sections by `data-source-href`, not document offset; do not require byte-equality for translated content |
| R-2 | Large EPUBs exceed DeepL's per-document character limit | Low (novels), Medium (technical books) | Medium | Auto-split at section boundaries above `--max-chars` (default 900k), with order-independent multi-file `restore`; see [ADR-0006](../adr/0006-auto-split-oversized-payloads.md). Only a single section exceeding a part's budget remains unmitigated (user raises `--max-chars` or splits that chapter in the source EPUB). |
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
  the document in isolation). Character count below DeepL's
  1,000,000-character per-document limit is enforced automatically:
  `prepare` packs sections into multiple part files at a configurable
  `--max-chars` threshold (default 900,000, a ~10% margin) rather than
  relying on the merged file staying under the limit by chance — see
  [ADR-0006](../adr/0006-auto-split-oversized-payloads.md).
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
