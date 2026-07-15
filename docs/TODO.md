# Project TODO — deferred items

Deliberately deferred work. Each entry records the risk assessment
behind the deferral and the concrete evidence that would promote it to
implementation, so the decision can be revisited on data rather than
re-argued from scratch.

## SVG element-*name* case restoration

**Deferred:** 2026-07-15

**Context.** The HTML parser used for translated content lowercases
element names as well as attribute names. `epub/_svg_case.py` restores
only *attribute* case (US-022 / FR-6), so an embedded SVG using
case-sensitive element names — `linearGradient`, `radialGradient`,
`clipPath`, `textPath`, `foreignObject`, filter primitives
(`feGaussianBlur`, …) — would come back from `restore` with lowercased
tags: invalid SVG that epubcheck rejects and readers won't render.

**Why deferred (risk assessment).**

- *Probability: low.* The bundled corpus contains exactly one inline
  SVG (Project Gutenberg EPUB 3), built from lowercase-safe elements
  only (`svg`, `image`) — while its attributes (`viewBox`,
  `preserveAspectRatio`) are precisely what US-022 covers. Gradient /
  clip-path artwork embedded in reflowable, text-first EPUBs is rare;
  it is characteristic of fixed-layout books, which are out of scope
  (PRD §4).
- *Impact: bounded and loud.* The failure is caught by the user's
  `epubcheck` verification step (US-016) as a validation error before
  the book ships — late, but never silent corruption; the text content
  is unaffected.

**Promotion trigger.** The first real corpus book (or user report) with
a case-sensitive SVG element name inside spine XHTML.

**Implementation sketch (when promoted).** Add US-023 to the PRD first;
then extend `_svg_case.py` with the closed SVG element-name enumeration
and rename tags within `<svg>` subtrees under the same scoping rules as
attributes; mirror the US-022 test layout (unit + round-trip +
epubcheck drift).

**References.** `docs/plans/test-plan.md` §6.13 (known gap);
`README.md` "Known limitations".
