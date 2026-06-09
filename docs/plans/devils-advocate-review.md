# Devil's Advocate Review — epub-translation-prepare

**Mode:** Devil's Advocate (primary) + Unknown Unknowns (secondary).
**Scope:** `prd.md`, `tech-stack.md`, `tech-spec.md`, `test-plan.md`.
**Posture:** This is pure critique. Solutions are deliberately omitted so the
author engages with each problem on its own terms.

---

## Executive Summary

The plan is internally consistent and PRD coverage is unusually thorough for a
solo MVP, but four critical issues threaten the round-trip correctness contract,
and roughly a dozen secondary issues will surface as silent bugs during
implementation unless addressed in advance. The single biggest weakness:
**the acceptance test for "round-trip integrity" cannot detect the very class
of bug it claims to detect** (see C-1). The second biggest: **the OPF and NCX
preservation strategy talks about byte-level fidelity but is built on
techniques that cannot deliver byte-level fidelity** (see C-2).

---

## CRITICAL Findings (blocks release if shipped as-is)

### C-1. SM-1 / US-006 round-trip test is a false-positive factory

PRD US-006 and SM-1 specify the acceptance criterion as
"`diff -r` of *unzipped* EPUBs shows no differences in any file's textual
content". This criterion accepts the following broken outputs:

- A ZIP where `mimetype` is **not** the first entry (a critical EPUB
  packaging requirement). `diff -r` after unzip sees the same files
  regardless of central-directory order.
- A ZIP where `mimetype` is DEFLATED instead of STORED. Same content, same
  filename, same `diff -r` result.
- A ZIP with `extra` field bytes on `mimetype`. Same content, same `diff -r`
  result.
- A ZIP using UTF-8 general-purpose bit flag on STORED entries (the precise
  regression older `epubcheck` releases reject — explicitly called out in
  tech-spec §7).

Every defence the tech-spec builds in §7 (mimetype-first, STORED, no extra
fields, flag_bits=0) is structurally outside the acceptance test's
detection window. The test cannot fail when these go wrong. Result:
**SM-4 (epubcheck) is the actual gate on these properties, and SM-4 is manual
and out-of-band.** The automated suite gives green checkmarks on ZIPs that
would be rejected by any conformant reader.

### C-2. "Byte-level preservation" for OPF/NCX is undeliverable as designed

Tech-spec §4.2 step 5 and §5.4 step 4 require:

- Preserving `<dc:creator>`, `<dc:publisher>`, etc. "byte-identical".
- Updating `<dc:title>`, `<dc:description>` via "in-place patching".
- For NCX: "in-place patching of `raw_xml`" mutating only `<docTitle><text>`
  and each `<navLabel><text>`.

Two unrecoverable techniques are being conflated:

- **Parse → modify → serialise via lxml:** lossy. lxml's `etree.tostring`
  *reorders attributes* in some cases, *changes self-closing tag style*
  (`<x/>` ↔ `<x></x>`), *normalises entities* (`&#x2014;` → `—`), and *can
  alter namespace prefix declarations* (especially with mixed default and
  prefixed namespaces, which OPF uses heavily for `opf:` and `dc:`). Result:
  US-013 (manifest and spine byte-identical) and US-010 (non-translated
  fields byte-identical) **will fail on a non-trivial fraction of real
  EPUBs**, including some books in the corpus.

- **String/regex patching of raw bytes:** also lossy and dangerous. The
  spec waves at this with "in-place patching" but offers no algorithm.
  `<dc:title>` may contain embedded `<![CDATA[...]]>`, HTML entities,
  nested elements (rare but legal in OPF), or `xml:lang` attributes that
  must be preserved on the element itself, not the text.

Tech-spec's `OpfMetadata.extra: bytes` is described as "opaque XML bytes
preserving everything else verbatim" but offers no mechanism to splice
modified fields back into that opaque blob without re-parsing — which
defeats the byte-level claim.

The PRD's US-013 acceptance criterion ("manifest and spine byte-identical")
sets a bar that the current architecture cannot meet.

### C-3. Anchor-resolution algorithm has a path normalisation bug

Tech-spec §6 contains:

```python
target_href = normalize_path(join(ncx_dir, path_part), base=epub.opf_dir)
```

Two problems:

- `normalize_path` is not defined and the choice of normaliser determines
  behaviour. EPUB requires path resolution using **URL-style** rules
  (forward slashes, percent-decoding for `%20`, no Windows backslashes),
  not filesystem `pathlib` rules. Using `pathlib.PurePosixPath.resolve()`
  also fails because `PurePosixPath` does **not have a `.resolve()` method**
  — `.resolve()` belongs to concrete `Path` only and performs filesystem
  operations. This is asserted in tech-spec §10 as a security control; the
  control does not exist.
- "Relative to NCX directory, then to OPF directory" inverts EPUB semantics.
  NCX `src` attributes are resolved relative to the **NCX file's own
  location**, full stop. The OPF directory is not in the chain. The current
  formulation will produce wrong target hrefs whenever NCX and OPF live in
  different directories (which is the *standard* case: OPF in `OEBPS/`,
  NCX in `OEBPS/toc.ncx`, XHTML in `OEBPS/Text/`).

### C-4. R-8 (DeepL strips `data-*`) is the highest-impact risk and the test plan does not test it

Tech-stack §10 designates a 15-minute manual spike for R-8. The test plan
omits any regression test for `data-*` preservation through actual DeepL.
The `simulated_translation` fixture is a labelled identity transform — by
construction, it cannot exercise the failure mode. If DeepL silently
changes behaviour in a future deployment (and DeepL has a history of
quiet HTML-handling changes), the entire round-trip breaks with no
warning from the automated suite. The contract "tool works with DeepL" is
not enforced anywhere.

Compounding: the fallback in tech-stack §9 ("Re-encode markers as HTML
comments") is also unverified. Comments are documented by DeepL as
preserved, but DeepL has been observed in the field stripping certain
comment patterns. The fallback may be no safer than the primary strategy
— and there is no test of that either.

---

## IMPORTANT Findings (significant — fix before implementation)

### I-1. `dc:language` may be absent in the input EPUB

PRD US-001 and tech-spec §4.3 both source `<html lang="…">` for the merged
HTML from `<dc:language>`. EPUB 2 spec mandates `<dc:language>`, but
real-world publishers (especially older self-published ones and converted
Mobi files) omit it. The current design has no fallback path. `prepare`
will throw an `AttributeError` or write `lang="None"` (depending on which
line crashes first).

### I-2. Spine items may include non-XHTML files

EPUB 2 spec allows spine items of media-type `application/x-dtbook+xml`
(DTBook) or even `text/html` (legacy). The plan assumes
`application/xhtml+xml` everywhere. A book with a single legacy HTML page
in the spine triggers either an `assert` or silent skip — both wrong.

### I-3. EPUB with multiple OPF "renditions" (EPUB 3 Multiple Renditions)

The validator targets "EPUB 2 only" but the rejection mechanism is "OPF
root version != 2.0". EPUB 3 books exist that include EPUB 2-compatible
renditions and declare version 2.0 in one OPF and 3.0 in another. The
`container.xml` may have multiple `<rootfile>` entries. The current logic
picks "the active rendition" without specifying *how*. Picking the first
silently may select an unsupported rendition. Picking by version may break
EPUB 3 books that include an EPUB 2 fallback.

### I-4. `simulated_translation` fixture cannot detect whitespace bugs

The fixture prefixes each text node with `«PL»`. It does not introduce
trailing whitespace, leading whitespace, doubled spaces, or HTML entity
re-encoding — all common DeepL behaviours. A bug where restore loses
trailing newlines (very common when re-extracting `<body>` inner HTML)
will be invisible to the simulated fixture. Real DeepL would expose the
bug; the test suite would not.

### I-5. NCX label "anchor resolution" can pick the wrong heading

Tech-spec §6 `_first_heading` walks `h1`, `h2`, `h3` and returns the first.
Real-world EPUBs commonly put a section divider, drop-cap epigraph, or
publisher logo wrapper as the first `<h1>` of a chapter, with the real
chapter title as `<h2>`. After translation, the NCX label will display
the epigraph text instead of the chapter title. The reader's TOC will look
wrong but `epubcheck` will accept it — silent failure.

### I-6. Counter-based metadata mapping is brittle

US-007 acceptance and tech-spec §5.3 require the count of `<dc:title>` in
input to equal the count in translated HTML. DeepL is known to:

- Split long titles into two `<h1>` elements occasionally.
- Collapse identical adjacent subjects into one element.
- Promote inline emphasis around a title into a separate child element.

Any of these breaks the count assertion and aborts the entire restore.
The user has no recovery path except manually editing the translated HTML.

### I-7. `pyproject.toml` Python floor mismatch with apt-installed Python

Tech-stack §2 specifies Python ≥ 3.11. Tech-stack §5 says "Python 3.12
installed via `apt-get install python3 python3-venv python3-dev`". Debian
12 (bookworm) ships **Python 3.11**, not 3.12. The apt route never produces
3.12 on bookworm without third-party repos. The devcontainer build will
either:

- Install Python 3.11 (satisfies the floor but contradicts the stack doc),
- Or fail.

### I-8. `xml.etree` is forbidden but `defusedxml` is also rejected

Tech-stack §8 rejects `defusedxml` on the grounds that "security goals
[are] achieved via lxml parser flags instead". This is true for XXE
defence, but `defusedxml` also defends against:

- Billion laughs attack (exponential entity expansion).
- Quadratic blowup attack.
- DTD retrieval DoS.

`lxml` `resolve_entities=False` blocks billion-laughs **only if the parser
also disables internal entity expansion** — which is a separate setting
(`recover=False, no_network=True, huge_tree=False` are all relevant). The
defence may be incomplete. The mitigation is asserted without a test.

### I-9. Input path equal to output path is not validated

US-014 covers "output exists, --force absent". No criterion handles
`prepare book.epub --output book.epub`. The current design would truncate
the input mid-read on some OS/filesystem combinations or write garbage
into the only copy. No automatic guard.

### I-10. `pyproject.toml` `hatch` is declared but devcontainer uses `pip install -e .`

Tech-stack §3 (build) prefers `hatch`. Tech-stack §5 (devcontainer) uses
`pip install -e .[dev]`. Mixed tooling is fine but unstated: `hatch`
manages its own virtualenvs, and using `pip install -e` outside a `hatch`
environment bypasses `hatch env` resolution. The dev environment story is
muddled. A new contributor wouldn't know whether to use `hatch shell` or
the bare `.venv`.

### I-11. `lxml-stubs` is *not maintained by the lxml authors*

Tech-stack §3 calls `lxml-stubs` "official lxml type stubs". They are
community-maintained, often lag the latest lxml release, and have known
gaps around `lxml.html`. mypy strict mode will produce false positives or
missing-attribute errors on legitimate code. Either tolerate the noise
(unprofessional in a strict-mode setup) or carry `# type: ignore` proliferation.

### I-12. Test plan SM-2 is not testable as written

Test plan §5 marks SM-2 ("Translation completeness 100% of translatable
fields") as "Partial; automated structural + manual". But the *number*
of translatable fields per book is not pre-computed anywhere, so "100%"
is a denominator without a numerator. There is no way to know whether a
single field was missed. Real DeepL output sampled by hand is not "100%
verified" by any reasonable interpretation.

### I-13. Coverage floor 85% is misleading on a tool whose value is correctness

Per-line coverage of 85% on a structural transformation tool is easy to
hit while missing the dangerous paths: error fallthroughs, malformed-input
recovery, partial-translation handling. The plan does not require
branch-coverage on critical modules, only line coverage. Branch coverage
should be the binding constraint here, especially in `validator.py` and
`ncx.py`.

### I-14. Devcontainer pre-create hook to "match host UID at runtime"

Tech-stack §5 says "non-root user created at container build time, with a
UID chosen at runtime via a small entrypoint shim". This pattern has well-known
limitations:

- Build-time `useradd` bakes a UID into the image; runtime renumbering
  requires `usermod -u` on every start, which is slow and can corrupt
  ownership of cached files in the image's `$HOME`.
- `entrypoint` runs as root to perform the renumber, then drops privs.
  Compatibility with VS Code's devcontainer remoteUser is non-obvious;
  may produce silent permission errors on mounted plugins.
- Rootless Podman remaps UIDs anyway; the shim becomes a no-op or
  produces double-translation.

This is presented as a clean solution; it is in fact one of the trickier
parts of devcontainer work and deserves a dedicated spike.

### I-15. Test corpus diversity is overstated

Test plan §8 calls the corpus "diverse: 2 technical, 1 novel, 1 workbook".
But all 4 are **English-language**, **EPUB 2.0 with NCX**, and three of
the four are from the same author / publisher pipeline (Manning / Leanpub
style). They likely share OPF and NCX generation tooling. A bug in that
specific tooling's output style would be tested four times. The corpus
is monoculture-prone.

### I-16. No corpus EPUB with: cover image only, embedded fonts, CSS, scripts

The corpus comprises text-heavy reading material. Missing classes:

- Books with substantive `META-INF` extensions (Apple Books metadata, Adobe
  Adept).
- Books with `<guide>` element in OPF (pre-EPUB-3 navigational hints).
- Books with embedded fonts that may declare `font-name` in CSS that DeepL
  picks up as translatable text via `content:` properties.
- Books with `<script>` tags in XHTML (EPUB 2 deprecates but doesn't ban).
- Books with `<object>` or `<embed>` in XHTML.

None of these are tested.

### I-17. The plan never specifies what character set the output HTML uses

Tech-spec §4.3 shows `<meta charset="utf-8">` in the merged HTML. Good. But
DeepL has been observed *re-encoding* documents to platform defaults
(Windows-1252 fallback in some pipelines). The restore parser must
defend against re-encoded input but no test does.

---

## NICE-TO-HAVE Findings (polish, defer-acceptable)

### N-1. No version pinning strategy beyond `lxml >= 5.0`

A floor without a ceiling is reckless in long-tail projects. `lxml 6.0`
may rename a flag.

### N-2. Logging strategy says "no timestamps" but `--verbose` emits per-file progress

Per-file progress without timestamps cannot be used to spot a slow file —
the precise diagnostic value of verbose mode evaporates.

### N-3. Exit code 2 "should never happen — indicates a bug"

Aspirational. Many internal-error paths route through 2; users will see
exit code 2 in practice and not know what to do.

### N-4. No `--dry-run` flag

A tool that mutates one file based on another, with `--force` capable of
overwriting, deserves a dry-run preview. Not in PRD; not in spec.

### N-5. README is absent

The plan documents are detailed but no `README.md` exists. A solo project
without a README at the root is one rotated SSH key away from being
re-discovered by future-self with zero context.

### N-6. `hatch` is recommended over `uv` "for now" with no re-evaluation trigger

Decision deferred without a tripwire. Will rot.

### N-7. No CHANGELOG strategy

For a tool whose contract is structural preservation, a changelog tracking
exactly which structural decisions changed across versions is a high-value
artifact. Absent.

### N-8. Test markers `unit`, `integration`, `corpus` — no `slow` marker

Some integration tests will be slow (full corpus). No way to opt out of
slow tests without also opting out of corpus tests. Granularity is missing.

---

## Unknown Unknowns (assumptions the plan doesn't surface)

### UU-1. DeepL Pro Starter HTML translation limit is not actually 1 MB

The PRD assumes "DeepL's HTML document limit … declared in the region of
1 MB for HTML at the time of writing". This is folk-knowledge. The
official DeepL support page lists size limits per format but the HTML
number changes over time and across tiers. The 1 MB number may be
half-remembered from the .docx limit. The whole optimisation may not
actually work for a typical novel.

### UU-2. DeepL's HTML translation behaves differently on web upload vs API

The PRD says the user uploads/downloads manually. The web UI may apply
different post-processing than the API (HTML sanitisation, link rewriting,
attribute filtering). The plan is silent on which interface is authoritative.

### UU-3. `mimetype` STORED with `flag_bits=0` may not be sufficient for all readers

Some Android readers (Moon+ Reader Pro, ReadEra) have historically rejected
EPUBs whose `mimetype` ZIP entry has any local file header extras at all,
including extras Python may add by default. The mitigation in tech-spec §7
sets `extra = b''` *via assignment to `ZipInfo.extra`*, but `zipfile` may
still emit a length-prefixed empty extra field. Behaviour varies by
Python minor version. No test pins this.

### UU-4. Apple Books strict metadata requirements

Apple Books rejects EPUBs whose `<dc:identifier>` does not match a specific
format under certain entitlement profiles. The plan preserves identifier
verbatim — but if the input was synthesised by Calibre (one of the corpus
books almost certainly is), the identifier may already be in a form Apple
Books rejects. The tool inherits the bug; the user may attribute it to the
tool.

### UU-5. `epubcheck` is the spec, not the spec

`epubcheck` is the W3C reference validator but is itself imperfect.
Different `epubcheck` versions accept or reject the same file. The plan
treats `epubcheck`-passes as the success metric (SM-4); the version is
unspecified. Two contributors with different `epubcheck` installs will
get different SM-4 results.

### UU-6. The OPF `<package>` element's `unique-identifier` attribute

OPF requires a `unique-identifier="..."` attribute on `<package>` pointing
to the `id` of the `<dc:identifier>` to treat as canonical. If the input
EPUB has multiple `<dc:identifier>` (common: ISBN + UUID), the canonical
one must be identifiable. Restore preserves all identifiers but the spec
does not say which is canonical — and the canonical one may not be the
first.

### UU-7. Calibre may have produced the corpus

Three of four corpus books have filenames suggesting Calibre processing
(e.g. `Build_a_Large_Language_Model_(From_Scrat.epub` — Calibre's typical
underscore-and-truncate). Calibre's OPF/NCX style is *idiosyncratic* —
namespace prefix choices, empty attribute serialisation, `dtb:depth`
hardcoded to wrong values. The corpus thus *tests one EPUB-producing
pipeline*, not "real-world EPUBs in general". A book from a major
publisher (O'Reilly, Manning's own pipeline, Macmillan) may break the
tool in ways the corpus does not surface.

### UU-8. No consideration for stripping personalised metadata

Some publisher EPUBs include the purchaser's email or account ID as a
`<meta>` element ("watermark"). Translation could leak that to DeepL,
which is a privacy issue not raised anywhere in PRD or tech-stack §7
(security).

---

## Pre-Mortem Summary

**Date of failure: ~6 weeks after first release.**

The tool ships and works on the corpus. The author translates 3 books
successfully. The fourth book — a different publisher's EPUB acquired
later — produces an EPUB that Apple Books refuses to open. epubcheck
flags 14 errors related to `<dc:identifier>` and `<manifest>` namespace
prefix changes. Investigation reveals:

- **OPF byte-identical preservation** failed (per C-2). The lxml
  serialisation reordered `xmlns:opf` and `xmlns:dc` namespace prefixes
  on the manifest items, which is legal XML but cosmetically different —
  and Apple Books' parser is strict about prefix stability.
- **NCX anchor resolution** picked an epigraph as the chapter title (per
  I-5). The user noticed only after reading three chapters.
- **R-8 quietly happened on the fourth book**: DeepL stripped one
  `data-source-href` because the section it labelled had been collapsed
  into the prior section during translation. Restore failed with
  `TranslatedHtmlMismatch` (per C-4). The user spent four hours debugging
  before realising no automated test could have caught it.

The user shelves the tool and goes back to per-chapter manual translation.

The plan as written contains every fact needed to predict this outcome.
Each finding above was a leading indicator. The MVP launched without
addressing C-1 through C-4 because the test suite reported green on the
corpus, and the corpus is monoculture (UU-7). The launch decision was
data-supported in a way that excluded the bad data.

---

## Concentration of Risk

If the author addresses only four items before writing any code, they
should be:

- **C-1** (the round-trip test does not test round-trip).
- **C-2** (byte-level preservation strategy is unbuildable as described).
- **C-3** (anchor resolution path logic is wrong).
- **C-4** (the highest-impact risk is the least-tested).

Everything else can be deferred without compromising release-readiness.
These four cannot.
