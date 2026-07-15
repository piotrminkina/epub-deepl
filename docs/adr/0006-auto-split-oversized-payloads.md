# ADR-0006: Auto-Split Oversized DeepL Payloads at Section Boundaries

**Status:** Accepted
**Date:** 2026-07-15

## Context

DeepL's document translation service rejects files over 1,000,000
characters. `prepare` bundles the whole book's spine into one HTML
payload (ADR-0001), so a large enough book simply exceeds the limit —
previously a documented out-of-scope limitation (`README.md`,
`docs/plans/prd.md` R-2), with no automated remedy.

A real-world reference book confirms this isn't a rare edge case: a
technical EPUB 3 title (`legacyepub.epub`) produces a merged payload of
**1,496,069 characters** — 50% over the limit. Measuring how much of
that is unavoidable (as opposed to shrinkable envelope markup) shows
payload slimming cannot close the gap on its own: the book's **pure
text content alone is 1,140,333 characters**, already 14% over the
limit before a single `<section>`, `<header>`, or `data-*` attribute is
counted. Whatever markup could be trimmed does not change the outcome —
the payload has to be broken into multiple documents.

Three strategies were considered:

- **(a) Slim the payload** (shorter attribute names, dropped
  incidental markup, compacted whitespace) and hope the result fits.
  Measured insufficient on the reference book (see above) — text
  content alone already exceeds the limit, so no amount of markup
  trimming reaches a fix. Would also add a permanent complexity/fragility
  tax to every book, including ones nowhere near the limit, for a
  best-effort payoff that fails on the books that most need it.
- **(b) Split at arbitrary character offsets, including mid-section.**
  Would maximize packing density and minimize part count, but requires
  either re-parsing a section split across two files at restore time or
  inventing a mid-document resumption marker — real complexity for a
  marginal reduction in part count over splitting only between
  sections. Deferred: nothing in the current design forecloses adding
  intra-section splitting later if a book's single-section budget
  becomes a real obstacle (§ Consequences, Negative); it just isn't
  needed for the reference case or the general case today.
- **(c) Split only between sections, packing greedily in spine order,
  with the split threshold configurable.** Sections are already the
  natural, atomic translation unit — each is a direct `<body>` child
  (`merge/builder.py`) representing one spine XHTML or the EPUB 3
  nav document. Splitting only ever between them means no new
  cross-file resumption logic is needed; each part is simply a subset
  of the same sections the single-file payload would have contained.

## Decision

**Option (c): auto-split by default at section boundaries.**
`build_split` packs whole sections greedily, in spine order, into parts
that each stay under a configurable `--max-chars` threshold, defaulting
to `DEFAULT_MAX_CHARS = 900_000` — a ~10% margin under DeepL's
1,000,000-character limit, leaving headroom for whatever the specific
book's envelope and part markers add. `--max-chars 0` disables
splitting outright, and a payload that already fits under the threshold
produces exactly the same single file as before this feature — the
split mechanism is purely additive, never a behavior change for the
common case.

Only **part 1** carries the shared preamble (OPF metadata header + NCX
block): those are book-level, not section-level, so duplicating them
into every part would waste budget and complicate restore's metadata
handling for no benefit. Every part, however, carries the **full
envelope** — `<!DOCTYPE html>`, `<html lang="…">`, `</body></html>` —
so each one is independently valid as a translatable document, and
critically so that ADR-0002's `<html lang>` auto-detection continues to
work from *any* individual part, not just the first.

A part boundary is marked only advisory-ly: `data-part="i"
data-parts-total="n"` on `<body>`, added only when a book actually
splits (`n >= 2`). These markers exist purely to help `restore` warn on
suspicious input (a missing part, a part count mismatch) — they carry
no correctness weight. The hard completeness gate remains what it
always was: `validate_translated_html`'s set-equality check that every
`data-source-href` from the original spine is present across the
combined translated input. A book split into two parts and reassembled
with the markers stripped out entirely still restores correctly and
silently; a book restored with a section actually missing still fails
loudly, exactly as it does today for a single file.

`restore` accepts one or more translated files (`nargs="+"`, replacing
the previous single-file argument) and merges them via
`merge_translated_docs` before the usual per-section rebuild. Merging
is **order-independent**: sections are re-associated by their
`data-source-href`, not by which file they arrived in or what order
they were passed on the command line, so the user translating the
parts out of sequence (or a script assembling `restore`'s argument list
in whatever order `ls` returns) never breaks reassembly.

The non-spine EPUB 3 nav-document section (ADR-0005) needs no special
casing: it is simply first in section order like today, so it lands in
part 1 under normal budgets. If a low enough `--max-chars` pushes it
into a later part, that's harmless — restore reassembles the full
section set regardless of which part any individual section landed in.

## Consequences

**Positive:**

- Books that exceed DeepL's limit go from an unmitigated, documented
  out-of-scope gap to a fully automated multi-part workflow — no manual
  per-chapter fallback, no third-party tool required.
- Zero behavior change for the overwhelming majority of books that
  already fit under the threshold: `build_split`'s single-part
  short-circuit path renders byte-identically to today's `build`.
- The split unit (a whole section) matches the project's existing
  atomic-content model, so no new cross-file content-resumption logic,
  no new restore-time ambiguity, and no new failure mode beyond the one
  genuinely new edge case (a single oversized section — see Negative).
- Advisory-only markers mean a book's split/merge round-trip degrades
  gracefully even if markers are stripped or mangled somewhere in the
  DeepL pipeline — the union-by-href completeness gate is unaffected.

**Negative:**

- A single section (one spine XHTML or the nav document) that alone
  exceeds a fresh part's budget cannot be handled automatically —
  `build_split` raises `OversizedSection` naming the offending href,
  its size, and the remediation (raise `--max-chars`, or split that
  chapter in the source EPUB before running `prepare`). This is
  accepted as a rare, actionable failure rather than solved via
  intra-section splitting (rejected alternative (b)) — no observed
  real-world book has hit it, and the fix when it does occur is a
  single explicit flag or a source-EPUB edit, not a design gap.
- Translation-job economy for a split book is not free: DeepL Pro
  Starter's per-month document quota is consumed at `ceil(payload /
  900_000)` documents instead of 1, proportionally reducing how many
  oversized books fit in a month's quota compared to books that fit in
  a single part. Still strictly better than the previous per-chapter
  fallback, which consumed one document per spine file.
- The user takes on one extra manual step per additional part (upload,
  translate, download) — the tool cannot reduce this further without
  DeepL API automation, which remains explicitly out of scope
  (`docs/plans/prd.md` § Out of scope).
