# ADR-0002: BCP 47 Language Tags Pass Through Verbatim

**Status:** Accepted
**Date:** 2026-06-10

## Context

`restore` must write a target-language value to OPF `<dc:language>`.
Three sources of truth for the value were considered:

1. `--lang CODE` flag (always required, current state at the time
   of decision).
2. `<html lang="…">` in the translated HTML (DeepL writes this
   correctly to the target language).
3. The input EPUB's source `<dc:language>`.

Once auto-detection from `<html lang>` was on the table, a follow-up
design question emerged: when the detected tag has a region subtag
(e.g. `pl-PL`) but the source EPUB used a different form (e.g.
`en-us`), what value goes to OPF?

Three transformation options:

- **(α) Pass-through verbatim.** What we read goes to OPF unchanged.
- **(β) Normalize.** Strip the region subtag, lowercase, etc.
- **(γ) Match input format.** If source had a region, preserve it
  from `<html lang>`; if source was plain, strip region.

## Decision

**Option (α): verbatim pass-through.** No normalization, no case
folding, no region manipulation. Driven by specification research:

- EPUB OPF `<dc:language>` MUST conform to BCP 47
  (EPUB Packages §5.6.3).
- HTML5 `<html lang>` MUST conform to RFC 5646, which is part of
  BCP 47 (HTML Living Standard).

Both surfaces declare the *same* grammar. Any tag valid in
`<html lang>` is by definition valid in `<dc:language>`. Any
transformation would lose translator intent (e.g., DeepL writing
`pl` means "Polish generic"; writing `pl-PL` means "Polish from
Poland" — these are not equivalent under BCP 47 §4.4) without
producing a more-correct result.

Resolution order in `cli._resolve_target_lang`:

1. `--lang` if provided — force, with WARN on disagreement with
   detected.
2. `<html lang>` if present and well-formed (after EPUB-mandated
   whitespace trim per §5.6.3).
3. Otherwise `UserError` with remediation hint.

Validation is **well-formedness only** (regex grammar check), not
registry lookup. Matches epubcheck's posture.

## Consequences

**Positive:**

- Spec-compliant by construction (both surfaces share BCP 47).
- Preserves translator intent.
- Trivial implementation — no transformation logic to maintain.
- Symmetric with `prepare`, which also takes the language from the
  document (`<dc:language>`) without any flag.

**Negative:**

- A translator that writes a malformed tag propagates the malformed
  tag to OPF unless `--lang` overrides. Mitigated by
  `is_well_formed()` rejecting grammar violations at restore time.

## Drift Detection

A side benefit: when the chosen target's primary subtag matches the
source EPUB's primary subtag (case-insensitive), `restore` emits
`[WARN]` — this catches the silent failure where the user uploads
to DeepL but downloads the original by mistake.

## Validation

The Polish translation of *Build a Large Language Model* round-tripped
with `<dc:language>pl</dc:language>` auto-detected from
`<html lang="pl">`, passing epubcheck with zero errors.

## References

- [EPUB Packages 3.2 §5.6.3](https://w3c.github.io/epub-specs/archive/epub32/spec/epub-packages.html#sec-opf-dclanguage)
- [W3C — Language tags in HTML and XML](https://www.w3.org/International/articles/language-tags/)
- [RFC 5646 / BCP 47](https://www.rfc-editor.org/rfc/rfc5646.html)
