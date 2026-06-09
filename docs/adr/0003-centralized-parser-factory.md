# ADR-0003: Centralized lxml Parser Factory as Single Source of Truth

**Status:** Accepted
**Date:** 2026-06-10

## Context

The project parses several formats with `lxml`:

- **XML** (`OPF`, `NCX`, `XHTML 1.1` content) via `lxml.etree`
- **HTML5** (the translated DeepL output, body fragments during
  restore) via `lxml.html`

Each parser construction needs security defaults:

- `resolve_entities=False` to block XXE and billion-laughs attacks
- `load_dtd=False` to block DTD retrieval DoS
- `no_network=True` to block any URL fetch
- `huge_tree=False` to limit memory exposure

Scattering parser instantiation across modules invites drift:
one module forgets a flag, an XXE vector slips in, the security
posture is not auditable from a single source.

Additionally, `lxml.html`'s HTMLParser has a counter-intuitive default
(it falls back to ISO-8859-1 — the HTML4 historical default — when the
parsed bytes carry no encoding declaration). The project parses
encoding-less wrapper fragments (`<div>{body}</div>`), so this default
needs to be overridden.

## Decision

`src/epub_deepl_prepare/epub/_safe_parser.py` is the **sole authorized
factory** for parser construction. All other modules import
`parse_xml`, `parse_xml_recover`, or `parse_html_document` and never
instantiate `lxml.etree.XMLParser` or `lxml.html.HTMLParser` directly.

The factory:

- applies security flags uniformly (XML side);
- applies `encoding="utf-8"` as the HTML fallback charset;
- is enforced by `tests/unit/test_safe_parser.py`, which greps the
  codebase for bare parser instantiation outside the factory.

## Consequences

**Positive:**

- Security defaults applied uniformly. Audit surface = one module.
- Single point of fix when libxml2 defaults change. **This paid off
  directly:** the UTF-8 mojibake bug was a one-line addition
  (`encoding="utf-8"`) in this module that immediately fixed all
  HTML parsing sites correctly. Had the parser construction been
  scattered, the fix would have needed to be replicated and could
  have missed sites.
- New contributors learning the codebase have a single file to read
  to understand the security posture.

**Negative:**

- Indirection through a function call. Negligible runtime cost; small
  cognitive cost for readers expecting direct lxml.
- The grep-based enforcement in `test_safe_parser.py` is best-effort:
  a contributor could write `from lxml import etree as e; e.XMLParser(…)`
  to evade. The convention is documented as a hard rule and reviewed
  on changes.

## Validation

- All 21 source modules pass `mypy --strict`.
- 7 unit tests in `test_safe_parser.py` exercise XXE / billion-laughs
  / network / huge-tree rejection.
- 1 regression test (`test_replace_body_preserves_non_ascii_utf8`)
  pins the HTML parser's UTF-8 fallback.
- Single-line fix for the UTF-8 mojibake bug (commit `fed9a6d`)
  validated the design's responsiveness.
