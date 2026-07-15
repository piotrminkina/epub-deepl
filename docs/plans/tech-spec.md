# Technical Specification — epub-deepl

**Status:** Draft v1
**Related:** `prd.md` (requirements), `tech-stack.md` (technology choices)

---

## 1. Architecture Overview

The tool is a stateless transformation pipeline with two symmetric flows.
There is no daemon, no cache, no persistent state, no concurrency. Inputs
and outputs are explicit files; processing is fully in-memory.

```
prepare:  EPUB ZIP → [parse] → [validate] → [merge] → [serialize] → HTML5 file
restore:  EPUB ZIP + HTML5 file → [parse] → [validate] → [reassemble] → EPUB ZIP
```

The original EPUB ZIP is the **single source of structural truth**. The
merged HTML is only a transport format for translatable content. No
external state file is generated or required.

---

## 2. Package Layout

```
epub-deepl/
├── pyproject.toml
├── README.md
├── docs/plans/
│   ├── prd.md
│   ├── tech-stack.md
│   ├── tech-spec.md           ← this document
│   └── test-plan.md
├── src/
│   └── epub_deepl/
│       ├── __init__.py
│       ├── __main__.py        ← `python -m epub_deepl`
│       ├── cli.py             ← argparse, dispatch to prepare/restore
│       ├── errors.py          ← typed exception hierarchy
│       ├── logging_setup.py   ← stderr formatting, --verbose flag
│       ├── epub/
│       │   ├── __init__.py
│       │   ├── model.py       ← dataclasses: Epub, ManifestItem, Spine, NavPoint, OpfMetadata
│       │   ├── reader.py      ← parse EPUB ZIP → Epub model
│       │   ├── writer.py      ← serialize Epub model → ZIP with mimetype-first STORED
│       │   ├── validator.py   ← FR-4 input validation
│       │   ├── opf.py         ← OPF parse + edit (metadata fields)
│       │   ├── ncx.py         ← NCX parse + edit + anchor resolution
│       │   └── xhtml.py       ← XHTML body extraction and replacement
│       ├── merge/
│       │   ├── __init__.py
│       │   └── builder.py     ← Epub model → merged HTML5 string
│       └── restore/
│           ├── __init__.py
│           ├── parser.py      ← merged HTML5 → translated content map
│           └── applier.py     ← apply translations + write output ZIP
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   └── minimal.py         ← synthetic EPUB factory
    ├── unit/
    │   ├── test_opf.py
    │   ├── test_ncx.py
    │   ├── test_anchor_resolution.py
    │   ├── test_zip_packaging.py
    │   └── test_validator.py
    └── integration/
        ├── test_roundtrip.py  ← corpus
        └── test_cli.py
```

---

## 3. Core Abstractions

### Data model (`epub/model.py`)

Plain dataclasses, all `frozen=False` for in-place edits during restore.

```python
@dataclass
class ManifestItem:
    item_id: str        # OPF <item id="...">
    href: str           # OPF <item href="..."> relative to OPF directory
    media_type: str     # e.g. application/xhtml+xml
    properties: str | None = None  # space-separated tokens (e.g. "nav"); used to locate the EPUB 3 nav document

@dataclass
class SpineRef:
    idref: str          # references ManifestItem.item_id
    linear: bool = True # spine linear="yes" default

@dataclass
class Spine:
    items: list[SpineRef]
    toc_idref: str | None  # spine toc="..." attribute; references NCX item

@dataclass
class OpfMetadata:
    titles: list[str]
    descriptions: list[str]
    subjects: list[str]
    language: str
    creators: list[str]          # not translated
    publishers: list[str]        # not translated
    dates: list[str]             # not translated
    identifiers: list[str]       # not translated
    rights: list[str]            # not translated
    extra: bytes                 # opaque XML bytes preserving everything else verbatim

@dataclass
class NavPoint:
    nav_id: str
    play_order: int
    label: str
    src: str             # path#fragment relative to NCX directory
    children: list[NavPoint] = field(default_factory=list)

@dataclass
class Ncx:
    doc_title: str
    nav_map: list[NavPoint]
    raw_xml: bytes       # original bytes for round-trip fidelity

@dataclass
class XhtmlFile:
    href: str            # path relative to OPF directory
    raw_bytes: bytes     # original bytes (head + body) for restore template
    body_html: str       # extracted <body> inner content as serialized HTML5

@dataclass
class NavDocEntry:
    entry_id: str        # synthetic deterministic id "navdoc-toc-{N}" (pre-order);
                          # re-derived from the EPUB on every prepare/restore, never depends on DeepL
    label: str
    href: str             # "path#fragment" relative to the nav document's own location

@dataclass
class NavDoc:
    href: str             # path relative to OPF directory
    href_in_zip: str      # full ZIP path
    raw_bytes: bytes      # original bytes for round-trip fidelity
    toc_entries: list[NavDocEntry]
    has_toc_nav: bool     # False if no epub:type="toc" nav (or doc-toc role) was found
    in_spine: bool        # True if the nav document is also a spine item

@dataclass
class Epub:
    opf_path: str        # full path inside ZIP (e.g. OEBPS/content.opf)
    opf_dir: str         # dirname of opf_path
    manifest: dict[str, ManifestItem]   # by item_id
    spine: Spine
    metadata: OpfMetadata
    ncx: Ncx | None
    xhtmls: dict[str, XhtmlFile]        # by href (manifest-relative)
    other_files: dict[str, bytes]       # everything else (CSS, images, fonts), zip-path → bytes
    nav_doc: NavDoc | None = None        # EPUB 3.x navigation document; None for EPUB 2.x or when absent
    epub_version: str = "2.0"            # OPF package version attribute, verbatim
    major_version: int = 2               # int(epub_version.split(".", 1)[0]); gates nav-doc discovery
```

### Exception hierarchy (`errors.py`)

```python
class EpubTranslationError(Exception):
    """Base."""

class UserError(EpubTranslationError):
    """Exits with code 1; printed to stderr as [ERROR]."""

class ValidationError(UserError):
    """Specific subclass for input validation failures."""

class DrmDetected(ValidationError): ...
class BrokenManifest(ValidationError): ...
class BrokenSpine(ValidationError): ...
class MissingNcx(ValidationError): ...
class MissingNavDoc(ValidationError): ...
class NotAnEpub(ValidationError): ...
class TranslatedHtmlMismatch(ValidationError):
    """data-source-href in translated HTML doesn't match input EPUB spine."""

class OutputExists(UserError): ...

class InternalError(EpubTranslationError):
    """Exits with code 2; should never happen — indicates a bug."""
```

### Parser / writer protocols

No abstract protocols — single concrete implementations per file. Adding
abstractions before a second implementation exists would be premature.

---

## 4. Prepare Flow

### 4.1 Sequence

```
1. cli.parse_args()                          → PrepareArgs(input_path, output_path, force,
                                                 verbose, max_chars=DEFAULT_MAX_CHARS)
                                                 max_chars < 0 → UserError; > 1_000_000 → WARN
2. reader.read_epub(input_path)              → Epub
3. validator.validate_epub(epub)             → raise on any FR-4 failure
4. ruby_count = builder.count_ruby(epub)     → emit WARN if > 0
5. parts = builder.build_split(epub, max_chars) → list[str]; len == 1 unless the payload
                                                 exceeds max_chars (§4.3a)
6. output_paths = _split_output_paths(output_path, len(parts))
                                                → [output_path] unchanged when len(parts) == 1;
                                                  otherwise book.prepare.1ofN.html, … (§4.3a)
7. validator.check_output_exists(...)        → raise OutputExists if exists and not force,
                                                 checked for EVERY path in output_paths
                                                 BEFORE any file is written
8. write each part to its output_paths entry → INFO per file with its char count
9. if len(parts) > 1: emit one [WARN] listing the parts written, instructing the user to
   translate every part separately and pass all of them to `restore`
10. exit 0
```

### 4.2 `reader.read_epub` — parsing rules

1. Open input as `zipfile.ZipFile` in read mode.
2. Read `mimetype`; assert exactly `application/epub+zip`. Whitespace
   tolerated only as a trailing newline (some publishers do this).
3. Read `META-INF/container.xml`; extract `full-path` of the active
   rendition's OPF.
4. Read OPF; parse with lxml in XML mode with these security flags:
   - `resolve_entities=False`
   - `load_dtd=False`
   - `no_network=True`
   - `huge_tree=False`

   Capture the root `<package version="…">` attribute verbatim as
   `epub_version`, and `major_version = int(epub_version.split(".", 1)[0])`
   (defaults to `"2.0"` / `2` if absent, matching the `Epub` dataclass
   default). Version-range enforcement (2.x/3.x only) is a validator
   concern (§8), not a reader concern.
5. Extract:
   - **Metadata** (`<metadata>` element): all `<dc:*>` children, preserve
     element order; capture remaining content as `extra: bytes` via
     `etree.tostring(metadata, with_tail=False)` excluding the known
     fields, by serialising the original metadata block and patching the
     known fields back during restore (avoids losing custom `<meta>` or
     publisher-specific extensions).
   - **Manifest:** for each `<item>`, build `ManifestItem`. Resolve `href`
     against OPF directory.
   - **Spine:** read `toc` attribute (idref of NCX); iterate `<itemref>`.
6. Locate NCX: manifest item whose `item_id == spine.toc_idref`, or
   fallback to media-type `application/x-dtbncx+xml`. Read and parse with
   the same security flags. Build `Ncx` object including a deep copy of
   the raw bytes for round-trip fidelity.
7. Locate the EPUB 3 navigation document — **gated on `major_version >= 3`**
   (EPUB 2.x parsing is otherwise byte-identical to before this feature):
   the first manifest `<item>` whose `properties` token list contains
   `nav`. If no such item exists, or its href does not resolve to a ZIP
   entry, raise `MissingNavDoc`. Add the nav document's ZIP path to
   `skip_paths` (it must never also appear in `other_files`). Detect
   whether the nav document is itself a spine item (`in_spine`) by
   checking whether its `item_id` appears in `spine.items`.
8. For every spine item whose manifest media-type is
   `application/xhtml+xml`, read the file bytes; parse with
   `lxml.html.fromstring` in XHTML mode; extract `<body>` inner HTML as a
   string via `lxml.etree.tostring(body, method='html', encoding='unicode')`.
9. Collect all remaining files (CSS, images, fonts, etc.) as raw bytes
   keyed by their ZIP path, excluding `skip_paths`; these pass through
   unchanged in restore.

### 4.3 `builder.build` — merged HTML structure

The output is a single HTML5 document. Pseudocode:

```html
<!DOCTYPE html>
<html lang="{source_language_from_dc_language}">
<head>
  <meta charset="utf-8">
  <title>{first_dc_title}</title>
  <meta name="description" content="{first_dc_description}">
</head>
<body>
  <header data-source="opf-metadata">
    <h1 data-dc="title">{first_dc_title}</h1>
    {% for desc in dc_descriptions %}
    <p data-dc="description">{desc}</p>
    {% endfor %}
    {% for subj in dc_subjects %}
    <span data-dc="subject">{subj}</span>
    {% endfor %}
    {% for extra_title in remaining_dc_titles %}
    <h2 data-dc="title" data-dc-index="{i}">{extra_title}</h2>
    {% endfor %}
  </header>

  <nav data-source="ncx">
    <h2 data-ncx="doctitle">{ncx_doctitle}</h2>
    <ol>
      {% for nav_point in nav_map_flattened %}
      <li data-ncx-id="{nav_id}"
          data-ncx-playorder="{play_order}"
          data-ncx-src="{src}"
          data-ncx-depth="{depth}">
        {label}
      </li>
      {% endfor %}
    </ol>
  </nav>

  {% if epub.nav_doc and not epub.nav_doc.in_spine %}
  <section data-source-href="{nav_doc.href}" data-nav-doc="true">
    <header data-section-meta="true">
      <h1 data-xhtml-title="true">{nav_doc_head_title}</h1>
    </header>
    {extract_nav_body_html(nav_doc.raw_bytes)}
  </section>
  {% endif %}

  {% for xhtml in spine_order %}
  <section data-source-href="{xhtml.href}"
           data-spine-idx="{idx}">
    <header data-section-meta="true">
      <h1 data-xhtml-title="true">{xhtml_head_title}</h1>
    </header>
    {xhtml.body_html}
  </section>
  {% endfor %}
</body>
</html>
```

Notes:

- The `<nav data-source="ncx">` block is **flattened** to a single `<ol>`
  with `data-ncx-depth` capturing nesting level. Restoration rebuilds
  the hierarchy from `data-ncx-depth` and original `<nav_map>` structure
  in the unchanged input. Keeping it flat reduces translation surface
  ambiguity (DeepL handles flat lists more predictably than nested ones).
- Every MathML element receives `translate="no"` before merging.
- Ruby annotations are not specially marked; they are detected and
  warned about (US-012).
- Cross-file hrefs in XHTML body content (e.g.
  `<a href="ch03.xhtml#sec2">`) are **not rewritten**. The merged HTML is
  not a navigable document; restoration places the link back in its
  original file where the href resolves correctly.
- When the EPUB 3 nav document is **not** a spine item, it is emitted as
  its own `<section data-source-href="{href}" data-nav-doc="true">`,
  immediately after the NCX block, with its body from
  `extract_nav_body_html` (which marks every `page-list` nav
  `translate="no"`). When the nav document **is** a spine item, no
  separate section is emitted — its existing spine section's body is
  swapped for the marked variant instead, so the nav document is never
  translated twice.

### 4.3a Payload plan and splitting (`build_split`)

`build(epub)` is internally `_render_single(_build_plan(epub))` — an
extraction, not a behavior change: output stays byte-identical to
before this feature.

```python
@dataclass
class _PayloadSection:
    href: str
    html: str                      # the <section ...>...</section> markup, incl. header

@dataclass
class _PayloadPlan:
    envelope_open: str              # <!DOCTYPE html><html lang="…">...<body>
    preamble: str                   # OPF metadata header + NCX block (part 1 only)
    sections: list[_PayloadSection] # non-spine nav-doc first, then spine order
    envelope_close: str              # </body></html>

def _build_plan(epub: Epub) -> _PayloadPlan: ...
def _render_single(plan: _PayloadPlan) -> str: ...
def _body_open(part: tuple[int, int] | None) -> str:
    # part=None                → "<body>" (today's single-file shape, byte-identical)
    # part=(i, n) and n >= 1   → '<body data-part="{i}" data-parts-total="{n}">' when n >= 2,
    #                            else "<body>" — markers appear ONLY when a split occurs
```

`build_split(epub, max_chars=DEFAULT_MAX_CHARS) -> list[str]` packs
`plan.sections` into one or more rendered documents:

- `DEFAULT_MAX_CHARS = 900_000` — a ~10% margin under DeepL's
  1,000,000-character document limit. `_PART_MARKER_RESERVE = 64`
  chars reserved per part for the `data-part`/`data-parts-total`
  attribute text so a part's rendered size never creeps past
  `max_chars` once markers are added.
- Short-circuit to `[_render_single(plan)]` (today's exact output) when
  `max_chars <= 0`, or the single-render output already fits, or the
  plan has no sections at all.
- Otherwise, pack greedily in `plan.sections` order (spine order, with
  a non-spine nav-doc section first, matching §4.3): a part's budget is
  `max_chars − len(envelope_open) − len(envelope_close) −
  _PART_MARKER_RESERVE`, minus `len(preamble)` for part 1 only — every
  later part starts fresh with no preamble. Sections are appended to the
  current part while they fit; a section that doesn't fit starts a new
  part.
- If a single section alone exceeds a **fresh** part's budget, raise
  `OversizedSection` (`errors.py`) naming the section's `href`, its
  character size, and the remediation (raise `--max-chars`, or split
  that chapter in the source EPUB before running `prepare`). This is
  the one case `build_split` cannot resolve automatically.
- Every returned part is a complete, self-contained HTML5 document:
  full `envelope_open`/`envelope_close`, and — critically — the same
  `<html lang>` as the single-file case, so ADR-0002's language
  auto-detection works from any individual part. `data-part="i"
  data-parts-total="n"` is added to `<body>` only when `n >= 2`; a
  single-part result (whether via short-circuit or because everything
  happened to fit in one pack) carries no markers and is
  indistinguishable from today's `<body>`.
- Defensive post-check: if any rendered part's length still exceeds
  `max_chars` (an arithmetic bug in the reserve/budget accounting,
  never a user-facing condition), raise `InternalError` rather than
  silently emitting an oversized file.

`_split_output_paths(output_path, n)` derives the per-part filenames:
`n == 1` returns `[output_path]` unchanged; `n > 1` inserts
`.{i}of{n}` before the final suffix (`book.prepare.html` →
`book.prepare.1of2.html`, `book.prepare.2of2.html`), handling
suffix-less paths safely.

---

## 5. Restore Flow

### 5.1 Sequence

```
1. cli.parse_args()                             → RestoreArgs(input_epub, translated: list[Path]
                                                     (nargs="+"), lang|None, output, force)
2. pre-check: reject duplicate resolved paths in `translated`      → UserError
3. validator.check_output_not_input(output, input_epub, *translated) → UserError on collision
4. validator.check_output_exists(...)
5. reader.read_epub(input_epub)                 → Epub (used as template)
6. for each path in translated:
     parser.parse_translated_html(path)         → TranslatedDoc (incl. html_lang,
                                                    part_index, parts_total — §5.2)
7. doc = parser.merge_translated_docs(           → single logical TranslatedDoc (§5.2a);
          [(path, parsed_doc), ...])               a single-file input passes through unchanged
8. cli._resolve_target_lang(args.lang, doc.html_lang, epub.metadata.language)
                                                → target_lang (per US-009; §5.1a)
9. validator.validate_translated(epub, doc)     → raise TranslatedHtmlMismatch if mismatch
10. applier.apply(epub, doc, target_lang)       → updates epub.metadata, epub.ncx,
                                                  epub.xhtmls in place; returns
                                                  new_nav_doc_bytes: bytes | None
11. writer.write_epub(epub, output_path,
                      new_nav_doc_bytes=...)     → ZIP with mimetype-first STORED
12. exit 0
```

Steps 9 onward are unchanged from the single-file flow — `merge_translated_docs`
produces the same `TranslatedDoc` shape the validator/applier/writer already
consume, so multi-part support required no changes downstream of step 7.

### 5.1a Target language resolution (US-009)

Both EPUB OPF `<dc:language>` and HTML5 `<html lang>` use BCP 47 / RFC
5646 as the tag grammar (EPUB Packages §5.6.3; HTML Living Standard).
The resolver passes values through verbatim — no region stripping, no
case folding — because both surfaces share the same spec and any
transformation would lose information without value.

```
explicit = args.lang                          # may be None
detected = doc.html_lang                      # trimmed; None if missing/empty
source   = epub.metadata.language

if explicit is not None:
    if not is_well_formed(explicit):
        raise UserError("--lang value … is not a well-formed BCP 47 tag")
    target = explicit
    if detected and detected != explicit:
        WARN("--lang overrides target language detected in translated HTML")
elif detected is not None:
    if not is_well_formed(detected):
        raise UserError("<html lang=…> is not well-formed; pass --lang explicitly")
    target = detected
    INFO("Auto-detected target language … from translated HTML")
else:
    raise UserError("pass --lang CODE explicitly")

# Informational drift detection — never fails.
if source and primary_subtag(source) == primary_subtag(target):
    WARN("primary subtag matches source; verify translation actually happened")
```

`is_well_formed` and `primary_subtag` live in `epub/_bcp47.py`. The
well-formedness regex (`^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$`) covers
the BCP 47 grammar without consulting the IANA Language Subtag Registry,
matching epubcheck's posture (well-formedness > strict registry lookup).

### 5.2 `parser.parse_translated_html`

Parses the translated HTML with `lxml.html` in HTML5 mode (lenient).
Builds:

```python
@dataclass
class TranslatedDoc:
    titles: list[str]                       # by data-dc="title" order
    descriptions: list[str]                 # by data-dc="description" order
    subjects: list[str]                     # by data-dc="subject" order
    ncx_doctitle: str
    nav_labels: dict[str, str]              # data-ncx-id → translated label
    sections: dict[str, str]                # data-source-href → translated body HTML
    part_index: int | None = None           # advisory: data-part on <body>, tolerant int parse
    parts_total: int | None = None          # advisory: data-parts-total on <body>
```

Selection rules (XPath, namespace-agnostic on HTML5 input):

- Titles: `//header[@data-source='opf-metadata']//*[@data-dc='title']`
- Descriptions: `//header[@data-source='opf-metadata']//*[@data-dc='description']`
- Subjects: `//header[@data-source='opf-metadata']//*[@data-dc='subject']`
- NCX doctitle: `//nav[@data-source='ncx']//*[@data-ncx='doctitle']/text()`
- NCX labels: `//nav[@data-source='ncx']//li[@data-ncx-id]`
- Sections: `//section[@data-source-href]`
- Part markers: `//body/@data-part`, `//body/@data-parts-total` — parsed
  tolerantly as `int`; absent or non-numeric values become `None` rather
  than raising, since the markers are advisory only (§4.3a).

### 5.2a `parser.merge_translated_docs` — combining split payloads

```python
def merge_translated_docs(docs: list[tuple[Path, TranslatedDoc]]) -> TranslatedDoc: ...
```

Combines one `TranslatedDoc` per translated file (in whatever order the
user passed them to `restore`) into the single logical document the rest
of the pipeline expects:

- **Single input:** returned unchanged, silently — no merge bookkeeping
  or logging for the common case.
- **Sections:** unioned by `data-source-href` across all inputs. A
  duplicate href appearing in two different files raises
  `TranslatedHtmlMismatch`, naming the href and both file paths — this
  is a hard error because it means the same section is ambiguous, not
  merely redundant.
- **Metadata (`titles`/`descriptions`/`subjects`) and `ncx_doctitle`/
  `nav_labels`:** these live in the shared preamble emitted by
  `build_split` on part 1 only (§4.3a), so the first input that carries
  a non-empty value wins wholesale; every other input that *also*
  carries a non-empty value logs a `WARN` (translation duplicated data
  that should have been part-1-only, e.g. a hand-edited file) but does
  not raise.
- **`html_lang`:** first non-`None` value across the inputs wins; if two
  inputs disagree, `WARN`s and recommends passing `--lang` explicitly
  rather than relying on auto-detection.
- **Part markers (`part_index`/`parts_total`):** sanity-checked only —
  totals that disagree across files, a `parts_total` that doesn't match
  the number of files passed, or gaps in the `part_index` sequence each
  produce a `WARN`, never a raise (the markers are advisory, per
  §4.3a); markers entirely absent from every input merge silently, with
  no warning at all.
- Logs via a dedicated module logger, `get_logger("restore.parser")`.

### 5.3 `applier.apply`

If `epub.nav_doc` is present and **not** `in_spine`, pop its
`data-source-href` entry out of `translated_doc.sections` before the
spine loop below — its body is handled separately (see "For the nav
document" below), never mistaken for a spine XHTML.

For each section in `translated_doc.sections`:

1. Look up `epub.xhtmls[href]`.
2. Parse `xhtml.raw_bytes` to a tree.
3. Replace the tree's `<body>` content with the parsed translated section
   body. The original `<body>` attributes (e.g. `class`, `id`) are
   preserved.
4. Re-serialise to bytes via `lxml.etree.tostring(tree, method='xml',
   xml_declaration=True, encoding='UTF-8')`. The source is always XHTML
   (both EPUB 2.x and reflowable EPUB 3.x spine items are validated as
   100% XHTML — see FR-4), so XML serialisation applies uniformly
   regardless of `major_version`.
5. Update `xhtml.raw_bytes` in place.

For OPF metadata:

1. Replace `metadata.titles` from `translated_doc.titles`, preserving the
   element count. If counts differ, raise `TranslatedHtmlMismatch`.
2. Same for descriptions and subjects.
3. Set `metadata.language = lang`.
4. Other fields untouched.

For NCX:

- Run anchor resolution (§6) to compute each `<navLabel>` from the
  translated XHTML files. The values from `translated_doc.nav_labels`
  are used **only** as a fallback for navPoints whose `src` does not
  resolve to a translated section (e.g. fragment points to an element
  with no detectable text).
- Update `<docTitle><text>` from `translated_doc.ncx_doctitle` (or
  fallback to first title from metadata).

For the nav document (EPUB 3.x only, when `epub.nav_doc` is present):

- If `in_spine` is `False`: run `resolve_nav_labels(nav_doc, epub)`
  (§6, via the shared `resolve_anchor_label`) to compute overwritten
  labels for every `toc` entry whose anchor resolves; entries that
  don't resolve keep the DeepL-translated body text already in the
  rebuilt nav body. Call `rebuild_nav_doc_bytes(nav_doc,
  translated_body_html, new_labels)` to produce `new_nav_doc_bytes`. Its
  **structure guard** compares the translated `toc` `<ol>`/`<li>` shape
  against the original pre-order walk; on mismatch it keeps the
  translated body as-is and emits `[WARN]` instead of overwriting with
  misaligned labels. `applier.apply` returns `new_nav_doc_bytes` to the
  caller (§5.1 step 7) for the writer to use.
- If `in_spine` is `True`: the same resolve/rebuild pass runs, but the
  result is written directly into that spine item's `updated_xhtml`
  instead of being returned separately — the nav document is restored
  through the ordinary XHTML path, and `new_nav_doc_bytes` is `None`.

### 5.4 Writer

`writer.write_epub(epub, output_path, new_nav_doc_bytes: bytes | None = None)`
performs:

1. Open a `zipfile.ZipFile` in write mode.
2. **First entry: `mimetype`.** Use `ZipInfo`:
   - `filename = 'mimetype'`
   - `compress_type = ZIP_STORED`
   - `external_attr = 0o644 << 16`
   - `flag_bits = 0` (no general-purpose bits, no UTF-8 flag — pure ASCII)
   - `extra = b''` (no extra fields — critical, several validators reject
     STORED entries with extra fields)
   - Content: exactly `b'application/epub+zip'` (20 bytes, no trailing
     newline).
3. **Second entry: `META-INF/container.xml`** — copied from input EPUB
   bytes unchanged.
4. **OPF:** updated by parsing the original OPF with lxml in XML mode
   (preserving namespace prefixes via `nsmap` capture and replay),
   mutating only the known-translatable elements
   (`<dc:title>`, `<dc:description>`, `<dc:subject>`, `<dc:language>`)
   in place, then serialising via `etree.tostring(tree,
   xml_declaration=True, encoding='UTF-8', pretty_print=False)`. The
   result is **structurally identical** to the input (same elements,
   same attributes, same text where unchanged) but not necessarily
   byte-identical: attribute order, self-closing style, and whitespace
   between attributes may change. PRD US-010 and US-013 explicitly
   accept this trade-off.

   Implementation guard: a unit test (`test_opf_preserves_non_translated_fields`)
   asserts equality at the **canonical-XML** level using
   `lxml.etree.tostring(..., method='c14n2')` for the non-translated
   subtree. This catches any real semantic drift while tolerating
   cosmetic serialisation differences.

5. **NCX:** updated by parsing the original NCX bytes with lxml in XML
   mode, replacing only `<docTitle><text>` and each `<navLabel><text>`
   nodes (matched by their parent's `id` attribute, since each
   `<navPoint id>` is the stable identity), and re-serialising. The
   `<navMap>` structure, `playOrder` attributes, `<content src>`
   attributes, and `<head><meta>` `dtb:*` entries are preserved
   structurally (canonical XML equality), not byte-for-byte.
6. **Nav document** (EPUB 3.x only, when `epub.nav_doc` is present and
   not `in_spine`): write `new_nav_doc_bytes` if the caller supplied it
   (§5.3); otherwise fall back to `nav_doc.raw_bytes` unchanged, so the
   file is never dropped from the output ZIP even if restore skipped it.
   When `in_spine` is `True`, the nav document was already written as
   part of "All XHTML files" below — this step is a no-op.
7. **All XHTML files:** updated `raw_bytes`.
8. **All other files** (`other_files`): byte-identical pass-through.

---

## 6. Anchor Resolution Algorithm

Defines US-008 acceptance criteria precisely. Shared by NCX `<navLabel>`
resolution and EPUB 3 nav-document `<a>` label resolution — see
[ADR-0005](adr/0005-hybrid-navdoc-label-strategy.md).

### Input

- `src`: `"chapter-03.xhtml#sec2"` — relative to the referring file's own
  location (the NCX for `<navLabel>` entries, the nav document for
  `epub:type="toc"` `<a>` entries)
- `epub.xhtmls`: keyed by href relative to OPF directory
- The restored translated XHTML for the target file

### Algorithm

Path resolution uses **URL-style rules** (forward slashes,
percent-decoding for `%20` etc.), not filesystem rules. `src` is
resolved relative to the referring file's own location, **not** the OPF
directory. The result is then re-expressed relative to the OPF
directory so it can be looked up in `epub.xhtmls`, which is keyed by
OPF-relative href.

```python
from urllib.parse import urljoin, unquote

def resolve_anchor_label(
    src: str, base_href_in_zip: str, opf_dir: str, epub: Epub
) -> str | None:
    """
    Shared by NCX label resolution (resolve_label, below) and EPUB 3
    nav-document label resolution (epub/nav.py's resolve_nav_labels).
    Returns None where the caller should apply its own fallback (NCX:
    the flat merged-HTML label; nav doc: the DeepL-translated anchor
    text already present in the rebuilt body).

    base_href_in_zip: full ZIP path of the file src is relative to — the
                      NCX file for NCX entries, the nav document for nav
                      entries (e.g. "OEBPS/toc.ncx" or "OEBPS/nav.xhtml").
    opf_dir: ZIP path of the OPF's directory (e.g. "OEBPS")
    """
    src_path = src                     # e.g. "Text/ch03.xhtml#sec2"
    if "#" in src_path:
        path_part, fragment = src_path.split("#", 1)
    else:
        path_part, fragment = src_path, None

    if path_part:
        # Resolve src relative to base_href_in_zip's own location (NOT to
        # OPF). urljoin with a "directory base" requires trailing slash.
        #
        # Both operands are prefixed with "/" before urljoin/relpath run,
        # turning the containment check below into a true absolute-path
        # comparison. Without this prefix, a book whose OPF sits at the ZIP
        # root (opf_dir == "") with its NCX/nav in a subdirectory (e.g.
        # "OEBPS/toc.ncx") made urljoin's "../" backtracking inconsistent
        # with the plain-string `startswith` check that followed it —
        # spuriously raising "escapes OPF root" for every single entry.
        #
        # Percent-decoding runs BEFORE urljoin, not after: urljoin only
        # collapses literal "../"/"./" segments (RFC 3986 dot-segment
        # removal). A percent-encoded segment such as "%2e%2e" is opaque to
        # it and passes straight through — decoding afterward let an
        # encoded ".." ride past both escape checks below and only become a
        # real ".." once nothing was left to catch it.
        base_dir_url = "/" + posixpath.dirname(base_href_in_zip) + "/"
        joined = urljoin(base_dir_url, unquote(path_part))
        if not joined.startswith("/"):
            raise InternalError(f"src escapes ZIP root: {src}")
        # Second, independent canonicalization pass: collapse any residual
        # "." / ".." left over from the join, and refuse to proceed if a
        # ".." survives. The containment check below is a raw string
        # prefix test, so it must never see a path that could still
        # traverse via a leftover dot-segment.
        normalized = posixpath.normpath(joined)
        if any(segment == ".." for segment in normalized.split("/")):
            raise InternalError(f"src escapes ZIP root: {src}")
        target_zip_path = normalized.lstrip("/")
    else:
        # Empty path component — a bare "#fragment" or a fully empty src —
        # resolves to base_href_in_zip itself, matching standard URL
        # fragment semantics ("this same document").
        target_zip_path = base_href_in_zip

    abs_opf_dir = "/" + opf_dir.rstrip("/")
    abs_target = "/" + target_zip_path
    if not (abs_target == abs_opf_dir or abs_target.startswith(abs_opf_dir + "/")):
        raise InternalError(f"src escapes OPF root: {target_zip_path}")

    # Re-express relative to OPF directory for the xhtmls map lookup.
    target_href = posixpath.relpath(target_zip_path, opf_dir)

    xhtml = epub.xhtmls.get(target_href)
    if xhtml is None:
        raise InternalError(f"points to non-manifest file: {target_href}")

    tree = parse_html(xhtml.raw_bytes)

    if fragment:
        # Anchor by id attribute, scoped to this file only.
        element = tree.xpath(f"//*[@id={xpath_literal(fragment)}]")
        if not element:
            # Fragment exists in the referring doc but element missing in
            # the (translated) XHTML. Try first heading; if none, let the
            # caller apply its own fallback.
            return _heading_fallback(tree)
        target = element[0]
    else:
        target = _first_heading(tree)
        if target is None:
            return None

    return normalize_whitespace(text_content(target))


def resolve_label(nav_point: NavPoint, ncx_href_in_zip: str, opf_dir: str, epub: Epub) -> str:
    """
    Thin wrapper preserving the pre-EPUB-3 signature and always-a-label
    return contract, so every existing test_anchor_resolution.py test
    passes unchanged.
    """
    label = resolve_anchor_label(nav_point.src, ncx_href_in_zip, opf_dir, epub)
    return label if label is not None else _flat_label_fallback(nav_point.nav_id)


def _first_heading(tree):
    for tag in ("h1", "h2", "h3"):
        nodes = tree.xpath(f"//{tag}")
        if nodes:
            return nodes[0]
    return None


def normalize_whitespace(s: str) -> str:
    return " ".join(s.split())
```

### Properties

- Per-file scoping (anchor lookup never crosses `data-source-href`
  boundary) eliminates R-4 (ID collisions across files).
- Whitespace normalisation ensures byte-identical comparison with the
  reader's display logic.
- `resolve_label` (NCX) falls back to `_flat_label_fallback` when
  `resolve_anchor_label` returns `None` — the translated nav label from
  the merged HTML carries the day, accepting the minor risk of
  TOC↔heading drift but never producing an empty label.
  `resolve_nav_labels` (nav document, `epub/nav.py`) instead omits the
  entry from its returned mapping when `resolve_anchor_label` returns
  `None`, leaving the DeepL-translated anchor text already present in
  the rebuilt body standing.
- **Absolute-path normalization fix:** both the referring file's
  directory (the `urljoin` base) and `opf_dir` (the root-containment
  check) are prefixed with `"/"` before `urljoin`/`relpath` run — see
  the algorithm comment above for the bug this closes.
- **Percent-decoding ordering fix:** `path_part` is `unquote()`-d before
  `urljoin`, not after — decoding afterward let a percent-encoded ".."
  (e.g. `%2e%2e`) pass both the ZIP-root and OPF-root escape checks
  unresolved (opaque to `urljoin`'s dot-segment removal) and only decode
  into a real ".." once past them. `posixpath.normpath` then acts as a
  second, independent canonicalization pass before the OPF-root
  containment check, which is a raw string-prefix test and must never
  see a path that could still traverse via a residual dot-segment.
- **Heading-quality caveat (per devils-advocate I-5):** `_first_heading`
  is a heuristic. If a chapter starts with an epigraph `<h1>` and the
  real chapter title is `<h2>`, the heuristic picks the epigraph. The
  PRD acceptance criterion (US-008) explicitly accepts this trade-off
  because no general-purpose chapter-title detector exists; users who
  hit this pattern manually edit the resulting NCX or report it for a
  per-book override mechanism (post-MVP).

### XPath literal helper

```python
def xpath_literal(s: str) -> str:
    """
    Quote a string for safe embedding into an XPath 1.0 expression.
    XPath 1.0 has no escape syntax inside string literals, so any string
    containing both ' and " must be expressed via concat().
    """
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"
```

Used wherever a fragment-derived value is embedded in an XPath:
`tree.xpath(f"//*[@id={xpath_literal(fragment)}]")`. Closes the
injection / lookup-failure gap raised by devils-advocate review.

---

## 7. ZIP Packaging Rules (EPUB)

EPUB 2.0.1, OCF 1.0 section 3.2 (and EPUB 3.0 section 4.3.2) mandate:

1. The first file in the ZIP archive must be named exactly `mimetype`.
2. The content of `mimetype` must be exactly `application/epub+zip` —
   20 ASCII bytes, no trailing newline, no BOM.
3. `mimetype` must be stored using ZIP's STORED method (no compression).
4. `mimetype` must have no extra field bytes.
5. `mimetype` must not be encrypted.

Standard `zipfile.ZipFile.writestr(name, content, compress_type=...)`
does not satisfy these constraints reliably because:

- It writes a non-zero general-purpose bit flag for ASCII content
  (specifically the UTF-8 flag, bit 11) starting from Python 3.6+ unless
  explicitly overridden.
- Some validators (older `epubcheck` releases, some embedded readers)
  reject the UTF-8 flag on STORED entries.

The writer therefore constructs `ZipInfo` manually:

```python
info = zipfile.ZipInfo("mimetype")
info.compress_type = zipfile.ZIP_STORED
info.external_attr = 0o644 << 16  # file mode bits
info.flag_bits = 0
zf.writestr(info, b"application/epub+zip")
```

A unit test (`test_zip_packaging.py`) verifies the binary layout
byte-by-byte and confirms a known-good EPUB produced by the writer
passes `epubcheck` in a manual integration check.

---

## 8. Validation Rules (FR-4)

### Prepare-side validation

| Check | On failure |
|---|---|
| File exists and is readable | `UserError("File not found / not readable")` |
| File is a valid ZIP | `NotAnEpub("Not a ZIP archive")` |
| Total uncompressed size ≤ 500 MB (zip-bomb guard; enforced by the reader before any parsing) | `NotAnEpub("EPUB exceeds size cap (N > M bytes)")` |
| ZIP contains `mimetype` | `NotAnEpub("Missing mimetype entry")` |
| `mimetype` content correct | `NotAnEpub("mimetype is not application/epub+zip")` |
| ZIP contains `META-INF/container.xml` | `NotAnEpub("Missing container.xml")` |
| `container.xml` references a valid OPF | `NotAnEpub("container.xml does not reference a valid OPF")` |
| Exactly one active rendition (first `<rootfile>`) | `NotAnEpub("Multi-rendition EPUB; rendition disambiguation out of MVP scope")` if 2+ rootfiles exist |
| OPF parseable | `NotAnEpub("OPF malformed")` |
| OPF root is `<package>` with `version` starting with `2` or `3` | `NotAnEpub("Unsupported EPUB version")` |
| Every spine `<itemref>` resolves to a manifest item whose media-type is `application/xhtml+xml` | `UserError("Unsupported spine media-type: ...")` — covers US-020 |
| All `<item>` files exist in ZIP | `BrokenManifest("Missing files: ...")` |
| All `<itemref>` resolve to manifest items | `BrokenSpine("Unresolved idref: ...")` |
| Navigation document present per version — 2.x: NCX exists and is parseable | `MissingNcx("No NCX, or NCX malformed")` |
| Navigation document present per version — 3.x: a manifest item with `properties` token `nav` exists and is parseable (NCX optional) | `MissingNavDoc("No nav document, or nav document malformed")` |
| No `META-INF/encryption.xml` | `DrmDetected(...)` |
| Input path != output path (resolved/symlink-aware) | `UserError("Output path equals input path")` — covers US-018 |
| `<dc:language>` is **soft-validated**: missing or empty allowed, with `[WARN]` and `und` fallback | (no failure; warning only — covers US-019) |

### Restore-side validation

| Check | On failure |
|---|---|
| Translated HTML is parseable | `UserError("Translated HTML malformed")` |
| Every spine XHTML href, plus the non-spine nav document's href (if any), has a matching `<section data-source-href>` | `TranslatedHtmlMismatch("Missing sections: ...")` |
| Every `<section data-source-href>` matches a manifest XHTML | `TranslatedHtmlMismatch("Unknown sections: ...")` |
| OPF metadata field counts match (e.g. same number of `<dc:title>` instances) | `TranslatedHtmlMismatch("Title count mismatch: input N, translated M")` |

---

## 9. Edge Cases and Decisions

| Edge case | Decision |
|---|---|
| Empty XHTML body | Pass through; section is emitted as `<section data-source-href="...">` with empty contents. Restored body remains empty. |
| Identical `<dc:subject>` values | Both included; DeepL translates both; restore preserves both. |
| Empty `<dc:description>` | Skipped in metadata block; not emitted; restore does not synthesise. |
| Multi-language source EPUB (multiple `<dc:language>`) | Use first as `<html lang="...">` in merged HTML; warn. Restore writes only one `<dc:language>` (the `--lang` value). |
| Nested `<navPoint>` (multi-level TOC) | Flattened in `<nav>` with `data-ncx-depth`; restored to original hierarchy from input NCX bytes. |
| `<navPoint>` whose `src` is just `path.xhtml` with no fragment | Anchor resolution uses first `<h1>` / `<h2>` / `<h3>`. |
| `<navPoint>` whose target id exists but the element is empty (e.g. anchor inside a `<div>` wrapper) | Walk up to nearest heading ancestor; if none, fall back to flat nav label. |
| `<navPoint>` whose target href doesn't match any manifest file | `InternalError` — book is structurally broken; should have been caught earlier. |
| Calibre / Apple Books non-standard `opf:meta` extensions | Preserved verbatim via `OpfMetadata.extra` bytes. |
| EPUB with `<dc:language>xml:lang` attribute | Read text content; `xml:lang` is preserved on the element via byte-level patching. |
| Mixed-script content (Latin + CJK in one paragraph) | Pass-through; DeepL handles. |
| BOM at start of XHTML files | Stripped on read; not re-emitted. |
| XML processing instructions (`<?xml-stylesheet ...?>`) | Preserved via raw byte template. |

---

## 10. Security Considerations

### XXE (XML External Entity) attacks

EPUBs are user-controlled XML. A malicious EPUB could declare external
entities pointing to local files (e.g. `<!ENTITY xxe SYSTEM "file:///etc/passwd">`)
or remote URLs, attempting to exfiltrate data through DTD-based attacks.

**Mitigation:** every `lxml.etree.XMLParser` and `lxml.html.HTMLParser`
construction sets:

```python
XMLParser(
    resolve_entities=False,
    load_dtd=False,
    no_network=True,
    huge_tree=False,
)
```

Centralised in `epub/_safe_parser.py`; no other parser constructions are
permitted (enforced by a ruff custom rule or a test that greps the
codebase).

### Zip bomb

`zipfile` is vulnerable to zip bombs (massively-deflated entries).
Mitigation: **input EPUB total uncompressed size** is checked against a
hard cap of 500 MB (`_MAX_EPUB_SIZE_BYTES` in `epub/reader.py`, checked
before any parsing). The cap is a constant, not a flag: 500 MB sits far
above any legitimate book, so configurability would be dead weight — a
`--max-size` flag can be added post-MVP if a real corpus ever needs it.
Exceeding the cap raises `NotAnEpub("EPUB exceeds size cap …")`, a
`ValidationError` subclass (exit 1).

### Path traversal in ZIP entries

A malicious EPUB could include entries named `../../../etc/passwd`. The
writer never extracts files to disk (operates in-memory throughout), so
this is not directly exploitable. The reader, however, joins paths during
manifest resolution; the resolver uses `pathlib.PurePosixPath.resolve()`
and asserts the result remains inside the EPUB root.

---

## 11. Concurrency Model

None. The tool is single-process, single-threaded, synchronous. The
entire EPUB is processed in memory. For a typical corpus book, peak
memory stays below 200 MB (a ~30 MB compressed / ~60 MB decompressed
technical book is the practical upper bound observed). This is
acceptable for the target user (single workstation).

If memory ever becomes a concern (e.g. ≥ 200 MB books), the design would
shift to streaming OPF/NCX processing and on-demand XHTML reads from the
ZIP — but this is post-MVP.

---

## 12. Logging Strategy

- **stderr only.** stdout reserved for future structured machine-readable
  output.
- Format: `[LEVEL] message` with no timestamps (tool runs are short;
  noise without value).
- Levels used: `ERROR`, `WARN`, `INFO` (only with `--verbose`).
- No stack traces leak to stderr in user-error paths; internal errors
  show stack via `logging.exception()` for diagnosability.
