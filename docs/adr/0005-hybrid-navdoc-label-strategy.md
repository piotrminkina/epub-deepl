# ADR-0005: Hybrid Nav-Document Label Strategy for EPUB 3 Navigation

**Status:** Accepted
**Date:** 2026-07-15

## Context

Reflowable EPUB 3.x support requires the tool to handle the EPUB 3
navigation document (`nav.xhtml`, identified by the manifest
`properties` token `nav`) alongside — or instead of — the EPUB 2 NCX.
Unlike the NCX, which is a pure metadata file (`<navLabel><text>`
entries with no other reader-visible role), the nav document is a
**real XHTML content document**: its body is rendered directly by
reading systems as the book's table-of-contents page, and it typically
carries additional navigation aids (`landmarks`, `page-list`) beyond
the `toc` entries the tool already understands from NCX handling.

TOC ↔ chapter-heading consistency is this project's signature
guarantee (US-008, SM-3): every navigation label must match the
translated heading it points to, rather than an independent
translation of the same string. Any nav-document strategy has to
preserve that guarantee for the `toc` nav while still producing a
usable, translated page for everything else the nav document exposes.

Three strategies were considered:

- **(a) Flatten the nav document into a payload block, like NCX.** Emit
  its `toc` entries as a flat `<nav data-source="navdoc">` block
  (mirroring the existing NCX block), discarding the original body.
- **(b) Verbatim passthrough.** Never place the nav document body in
  the DeepL payload; carry it through restore byte-identical.
- **(c) Hybrid.** Put the real `<body>` in the payload as ordinary
  translatable content, then overwrite only the `toc` entry labels
  after restore via the same anchor-resolution mechanism NCX already
  uses.

## Decision

**Option (c): hybrid.** The nav document's `<body>` is included in the
DeepL payload as ordinary translatable content — a
`<section data-source-href="…" data-nav-doc="true">` — so its
"Contents" heading, `landmarks` labels, and any surrounding prose all
get translated like any other spine file. After the spine bodies have
been restored, the `toc` nav's `<a>` entry labels are then
**overwritten** by anchor resolution: for each entry,
`resolve_anchor_label` (§6, shared with NCX handling) locates the
element the entry's `href` points to in the *translated* spine file and
uses its text — the same mechanism and guarantee as the existing NCX
`<navLabel>` handling. Where the anchor doesn't resolve (e.g. a cover
or title page with no heading), the DeepL-translated body text is left
standing instead of being overwritten.

`page-list` navs are excluded from translation by marking them
`translate="no"` in the payload — page numbers must survive
untranslated. A structure guard protects the overwrite pass: if DeepL
has reshaped the `toc` `<ol>`/`<li>` tree (added, removed, or
re-nested entries), the parallel pre-order walk used to overwrite
labels no longer lines up with the original entries, and the whole
translated body is kept as-is with a `[WARN]` instead of overwriting
with misaligned labels.

Both navigation documents are updated consistently: EPUB 2.x still
requires NCX (unchanged); EPUB 3.x requires the nav document, with NCX
optional — when a book ships both (as commercial EPUB 3 books commonly
do), both are kept in sync.

## Consequences

**Positive:**

- Nav document translation reaches full reader-visible completeness
  (Contents heading, landmarks, toc) via the ordinary content pipeline
  — no new payload shape to design beyond the existing section
  mechanism.
- TOC ↔ heading consistency (US-008/SM-3) extends unchanged to EPUB 3.x
  wherever an anchor resolves.
- Both navs (NCX + nav document) stay mutually consistent when a book
  ships both, matching how a hand-edited EPUB would be maintained.
- Option (a) would have lost the `landmarks` list and any surrounding
  prose as translatable content, and required synthesizing a plausible
  `<body>` on restore instead of round-tripping the original one.
  Option (b) would have left the reader-visible "Contents" heading,
  landmarks labels, and toc entries untranslated — an obviously
  incomplete translation, and a regression from what NCX handling
  already achieves for EPUB 2.

**Negative:**

- For heading-less targets (cover, title, dedication pages), the NCX
  fallback label and the nav-document fallback label are two
  **independent** DeepL translations of the same source string, and may
  differ slightly in wording. Accepted: both are legitimate DeepL
  translations of the same fallback text — a bounded, cosmetic-only
  drift, not a correctness bug.
- The structure guard means a sufficiently mangled DeepL output falls
  back to a nav body whose toc labels are DeepL's direct translation of
  the anchor text rather than the resolved heading text, for that one
  book. This is the same trade-off the tool already accepts elsewhere
  for adversarial DeepL output (SM-7): fail safely rather than silently
  corrupt.
