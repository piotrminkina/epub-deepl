# ADR-0001: Original EPUB as Structural Source of Truth During Restore

**Status:** Accepted
**Date:** 2026-06-10

## Context

Restoring a translated EPUB from a single HTML payload requires
knowing the full structure that the translation cannot carry: every
file in the manifest (including non-XHTML resources — CSS, images,
fonts), the spine ordering, the NCX hierarchy, the OPF
`unique-identifier` mapping, namespace declarations, processing
instructions, and per-file XHTML headers.

Two architectural options were considered during the early planning
session:

- **(a) External state file.** `prepare` emits a `state.json` (or
  similar) alongside the merged HTML, recording everything `restore`
  needs that cannot survive a DeepL round-trip.
- **(b) Original EPUB as template.** `restore` takes both the original
  EPUB and the translated HTML as inputs. The original is read-only
  and serves as the structural source of truth; `restore` mutates
  only translatable elements.

## Decision

**Option (b).** No external state file is generated or consumed.
`restore` requires two positional arguments — the original EPUB and
the translated HTML — plus optional `--lang`.

## Consequences

**Positive:**

- Zero risk of state file desynchronizing from the original EPUB
  (impossible by construction — the original IS the state).
- No file format to design, maintain, or version.
- Atomic: the original EPUB on disk is its own canonical state.
- Simpler restore logic — no parser for a state schema.

**Negative:**

- The user must keep the original EPUB accessible at restore time.
  Documented in the README usage section.
- The restore CLI has 2 positional args instead of 1.

## Validation

Content-identical round-trip (per US-006) confirmed across the
4-book corpus and one real DeepL translation (Polish). The original
EPUB's manifest and spine survive byte-identically in the canonical
XML form (US-013).
