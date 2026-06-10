# Lessons Learned — epub-deepl

**Last validated:** 2026-06-10

This file collects operational gotchas, empirical observations about
external systems, and process retrospectives from the project's
implementation phase.

Unlike the architecture decisions in [`docs/adr/`](adr/), these
entries have a **time-decay**: they were true at the date above, but
external systems (DeepL, lxml, Python distros) may shift. Re-validate
before treating them as authoritative for new work.

---

## Real-world gotchas

### G-1. `lxml.html.HTMLParser` defaults to Latin-1

When parsing bytes that carry no encoding declaration — no
`<meta charset>`, no XML declaration, no BOM — libxml2's HTML mode
falls back to **ISO-8859-1** (HTML4 historical default), not UTF-8.

**Symptom we hit:** `epub/xhtml.py::replace_body_content` wraps the
translated body fragment as `<div>...</div>` and re-parses. The
wrapper has no charset declaration. Polish UTF-8 input (`ż` =
`0xC5 0xBC`) was interpreted as Latin-1 (`Å¼` = U+00C5 + U+00BC),
then re-encoded to UTF-8 on output (`0xC3 0x85 0xC2 0xBC`) — classic
double-encoding mojibake.

**Fix:** pass `encoding="utf-8"` to `lxml.html.HTMLParser` as the
fallback. Documents that declare their own charset override this; the
fallback only activates when no declaration is present.

**Why the test suite missed it:** synthetic and corpus EPUBs were
ASCII-only. The bug only manifests on non-ASCII characters in body
fragments. Regression test added:
`test_replace_body_preserves_non_ascii_utf8`.

Pinned in: [ADR-0003](adr/0003-centralized-parser-factory.md),
`epub/_safe_parser.py::html_parser` docstring.

### G-2. Python venv is per-minor-version

A virtualenv built with Python 3.11 lives in
`.venv/lib/python3.11/site-packages/`. `.venv/bin/python` is a symlink
to `python3` resolved at invocation time. On a host where
`/usr/bin/python3` is 3.14, the venv's site-packages directory is
invisible to the interpreter — no errors, no warnings, just an empty
sys.path relative to the venv. The result: `No module named X` for
every editable install in that venv.

`pyvenv.cfg` carries `version = X.Y.Z` but this is **metadata only**;
Python does not enforce it against the running interpreter.

**Practical implication:** a venv built inside the Dev Container
(Python 3.11 on Debian 12) cannot be reused from a Fedora 41+ host
(Python 3.13+) — even though both can execute the same source.

**Mitigation in this repo (final):** [ADR-0004](adr/0004-per-python-minor-venv.md)
adopted **per-Python-minor venv naming**: each venv lives at
`.venv-${PY_MINOR}/` (e.g. `.venv-3.11/`, `.venv-3.14/`). The
`bin/epub-deepl` launcher resolves the venv by matching the system
`python3` minor against the venv directory name and `pyvenv.cfg`'s
declared version. Host and container coexist without conflict —
each owns its own venv directory.

`.venv/` (unversioned) is supported as a soft fallback for migration:
the launcher uses it only when its `pyvenv.cfg version` matches the
current Python minor. New `post-create.sh` runs always create the
versioned variant.

If no compatible venv exists, the launcher emits a concrete creation
recipe instead of letting Python produce a bare `No module named …`.

**Intermediate mitigation (earlier, single-venv era):** the launcher
just detected the version mismatch and printed a remediation message
asking the user to rebuild or invoke through the container. This was
sufficient to surface the problem but did not let the two
environments coexist. Per-minor naming makes coexistence the default.

### G-3. DeepL lowercases SVG/MathML camelCase attributes

DeepL's HTML translation pipeline normalises attribute names to
lowercase — HTML4 parser behaviour. SVG attributes that the SVG spec
mandates in camelCase (`viewBox`, `preserveAspectRatio`,
`gradientTransform`, etc.) come back lowercased. epubcheck rejects
these:

```
attribute "viewbox" not allowed here; expected attribute … "viewBox"
```

**Mitigation:** `epub/_svg_case.py` carries a closed enumeration of
57 SVG/MathML case-sensitive attribute names. After parsing translated
HTML, every SVG/MathML element subtree gets its lowercased attributes
rewritten back to spec form. Scoped per-subtree (root local name
`svg` or `math`) so plain HTML attributes are untouched.

**Coverage:** SVG 1.1 attribute set; MathML 3 selected attributes
(less complete — extend if a real corpus surfaces a missing one).

### G-4. Translation engines do not preserve identical-string identity

When the same source text appears in two positions, DeepL may
translate them differently:

```
<title>Build a Large Language Model</title>           → "Stwórz duży..."
<h1 data-dc="title">Build a Large Language Model</h1> → "Zbuduj duży..."
```

**Implication for our pipeline:**

- For OPF `<dc:title>`, we use the `<h1 data-dc="title">` value (in
  the merged-HTML metadata block). The HTML `<head><title>` is
  discarded.
- For NCX `<navLabel>`, anchor resolution reads the chapter heading
  text from the *restored* XHTML — single source of truth. Even if
  DeepL produced a different translation in the nav block, the TOC
  matches the chapter heading.

Document this if a user ever asks why two locations have different
translations: it's DeepL's behavior, not ours, and our resolution
strategy keeps the e-reader experience consistent.

---

## DeepL behavior catalog (empirical)

**Validated against:** one full translation of *Build a Large Language
Model (From Scratch)* (EN → PL via DeepL Pro Starter web-UI document
upload), 2026-06-10.

### What DeepL preserves verbatim

- All `data-*` attributes — verified for 401 markers (22
  `data-source-href` + 22 `data-spine-idx` + 114 `data-ncx-id` + 114
  `data-ncx-src` + 114 `data-ncx-playorder` + 114 `data-ncx-depth` +
  1 `data-dc="title"`). Zero loss.
- Element `id` attributes — 530 unique IDs preserved (critical for
  anchor resolution).
- Structural tags and nesting: `<section>`, `<nav>`, `<header>`,
  `<li>`.
- HTML5 named entities (`&copy;`, `&times;`, `&aacute;` etc.).
- HTML comments (not specifically stress-tested but observed
  preserved).

### What DeepL transforms

| Surface | Transformation |
|---|---|
| `<html lang>` | Set to target language (`en-us` → `pl`) |
| SVG/MathML attributes | camelCase → lowercase (G-3) |
| Prose whitespace | Runs of spaces collapsed; may change line breaks |
| Identical source strings | Translated independently per occurrence (G-4) |

### Document size envelope

- 1,128,009 bytes / 1,125,075 characters HTML payload — **accepted
  and translated successfully** on Pro Starter.
- Slightly above the often-quoted "~1 MB" — the practical limit is
  not strictly `1,048,576` bytes (or is higher on some tiers).
- One book → one DeepL document → consumes 1 of 5 monthly slots on
  Pro Starter.

### Quality observations

- Nav labels translate sensibly (`copyright` → `prawa autorskie`,
  `acknowledgments` → `podziękowania`).
- Title translation with slight inconsistency between positions (G-4).
- Body prose is standard DeepL output — idiomatic, generally adequate.

---

## Process retrospective

### P-1. Devils-advocate caught architectural issues; real use found new classes

A pre-implementation **devils-advocate review** was run against the
planning documents (PRD, tech-stack, tech-spec, test-plan) before any
code landed. It surfaced 4 critical findings (C-1..C-4) and 17
important findings (I-1..I-17). All 21 were addressed — folded into
the planning documents directly, then enforced by the implementation
that followed. The MVP shipped without any of the predicted weaknesses
lurking.

But **two new bug classes emerged in real-world usage** that the
review did not anticipate. Both were addressed in commits subsequent
to the MVP and are now permanently regressed against.

| Bug | Surfaced via | Why the review missed it |
|---|---|---|
| **C-5: SVG/MathML attribute case lowercased by HTML4 parsers.** `lxml.html` (libxml2 HTML4 mode) and DeepL both normalise attribute names to lowercase. SVG spec requires `viewBox`/`preserveAspectRatio` etc. in camelCase; epubcheck rejects lowercased variants. | Manual `epubcheck` on first restore output (corpus book with embedded SVG titlepage). | Synthetic SVG in tests was minimal; test suite never invoked `epubcheck` automatically. |
| **UTF-8 mojibake in body fragments.** `lxml.html.HTMLParser` defaults to ISO-8859-1 for input without a charset declaration. Polish UTF-8 bytes round-tripped as double-encoded mojibake in chapter bodies AND (via anchor resolution) in NCX navLabels. | First real Polish DeepL translation. | The entire corpus + synthetic fixtures was ASCII-only. The bug had been latent since initial implementation. |

Both bug classes share a property: **they manifest only on real
external-system output combined with real content.** No self-contained
reasoning about the code could have predicted them without explicit
non-ASCII fixtures or an automated `epubcheck` gate.

Lessons folded into the next review cycle:

1. **Synthetic fixtures must include non-ASCII content** as a matter
   of policy. Now enforced by `test_replace_body_preserves_non_ascii_utf8`
   (unit) and `test_roundtrip_preserves_non_ascii_content_end_to_end`
   (integration). See P-2.
2. **`epubcheck` must be exercised in CI**, not just as a manual
   release gate. Now enforced by the `@pytest.mark.epubcheck` marker
   tests and a dedicated GitHub Actions job that installs JRE +
   hash-pinned epubcheck.
3. **Devils-advocate is necessary but not sufficient.** The
   unknown-unknowns section in the original review tried to surface
   this category, but by definition it cannot enumerate the
   unknown-unknowns themselves. Real-world spike runs (S-1, S-2 in
   tech-stack §10) are the complementary discipline.

The original `devils-advocate-review.md` document was removed from
the repo when its findings stopped being a useful reading order for
outside contributors — every critical finding had been addressed and
documented elsewhere (PRD acceptance criteria, ADRs, this file). The
content remains available via git history at commit `57980ea`.

### P-2. Test corpus monoculture is a real risk

The 4-book test corpus is English-only and produced by similar
publishing pipelines (Manning / Calibre). No non-ASCII content. The
UTF-8 mojibake bug existed in the code from initial implementation
but stayed invisible until the first non-English real translation.

**Mitigation taken:** the regression test
`test_replace_body_preserves_non_ascii_utf8` explicitly synthesises a
Polish body fragment and asserts absence of mojibake.

**For future corpus extensions:** prefer adding books with
**deliberately diverse content** (CJK, Arabic, math symbols, mixed
scripts, RTL text) over adding more ASCII books.

### P-3. Container ↔ host parity matters more than the test count

The builder agent ran the full test suite in the Dev Container
(Python 3.11). The end user invokes the CLI on host (Python 3.14 on
Fedora 41+). The two environments diverge in subtle ways that 164
passing tests in one cannot prove for the other:

- Python's default encoding behavior (older Pythons more permissive)
- libxml2 / lxml versions
- Locale defaults

Cure: make the parity issue **loud** when it bites. The bin/
launcher's version-mismatch diagnostic addresses the most common
manifestation. Cron-run the test suite on host periodically if
sustained dual-environment use becomes the norm.

### P-4. Atomic commit discipline is net-positive but not free

The repo has 11 commits to date; each is independently checkout-able
and runnable. Bisecting a regression is trivial; reverting a single
feature is a single revert.

The discipline cost ~5-10 minutes of upfront thought per commit and
caught at least one sequencing error before push (the README
referenced files that hadn't landed yet in an earlier draft).

One commit (`1e93cc8`, project rename) had stale old-name references
in docstrings that needed a follow-up (`8eed2ed`). The litmus test
("if I checkout N-1, does the tree work?") was technically met —
tests passed — but cosmetic inconsistency was caught only by
post-rename grep. **Lesson:** for sweeping renames, a follow-up commit
is nearly inevitable; design for it rather than chase perfection in
commit N.

### P-5. `epubcheck` is the binding gate; running it in the test suite is wrong

`epubcheck` is the authoritative EPUB validator and detected both
real-world bugs (G-3 and the UTF-8 mojibake), neither of which the
automated suite caught.

Integrating `epubcheck` into the test suite would require a JRE
runtime everywhere the suite runs — expensive and brittle.

The choice this project made: keep `epubcheck` as a **documented
manual gate** (SM-4 in the PRD), pre-install it in the Dev Container
for one-command access, document the recipe in `CONTRIBUTING.md`,
and accept that pre-release manual verification is necessary.

This trade-off was correct for the MVP. If the project ever has
multiple contributors, an opt-in `pytest -m epubcheck` marker that
shells out to `epubcheck` per test corpus book would be a reasonable
upgrade.
