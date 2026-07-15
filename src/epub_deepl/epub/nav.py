"""EPUB 3 navigation document (nav.xhtml) parsing and serialisation.

Mirrors `ncx.py`: parsing produces a model tree with synthetic, deterministic
entry ids (re-derived from the original EPUB on both prepare and restore,
independent of DeepL output); label resolution and rebuild follow the same
anchor-resolution and structure-guard patterns as the NCX pipeline.

Namespace-tolerant throughout: `epub:type` may appear either resolved
(`{http://www.idpf.org/2007/ops}type`) or, after lenient recovery-parsing of a
malformed document, as the literal attribute name `epub:type`; element tags
are matched by local name only, ignoring the XHTML namespace.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from epub_deepl.epub._safe_parser import parse_html_document, parse_xml_recover
from epub_deepl.epub.model import Epub, NavDoc, NavDocEntry
from epub_deepl.epub.ncx import normalize_whitespace, resolve_anchor_label
from epub_deepl.epub.xhtml import _find_body, _inner_html, replace_body_content
from epub_deepl.errors import MissingNavDoc
from epub_deepl.logging_setup import get_logger

_log = get_logger("epub.nav")

_OPS_NS = "http://www.idpf.org/2007/ops"


def _local_tag(tag: object) -> str:
    """Return the namespace-stripped local tag name, or "" for non-element nodes."""
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _epub_type_tokens(el: etree._Element) -> set[str]:
    """Return the whitespace-separated `epub:type` tokens on an element."""
    value = el.get(f"{{{_OPS_NS}}}type")
    if value is None:
        value = el.get("epub:type")
    if value is None:
        return set()
    return set(value.split())


def _text_content(el: etree._Element) -> str:
    """Return all text content under element, concatenated."""
    return "".join(str(t) for t in el.itertext())


def _direct_child(el: etree._Element, local_name: str) -> etree._Element | None:
    """Return the first direct child element with the given local tag name."""
    for child in el:
        if _local_tag(child.tag) == local_name:
            return child
    return None


def _find_toc_nav(tree: etree._Element) -> etree._Element | None:
    """Locate the toc `<nav>` element by preference order.

    1. `epub:type` token `toc` (the spec-mandated marker).
    2. `role="doc-toc"` (ARIA fallback some tools emit instead of/alongside epub:type).
    3. The first `<nav>` with a direct `<ol>` child (last-resort heuristic).
    """
    navs = [el for el in tree.iter() if _local_tag(el.tag) == "nav"]
    for nav in navs:
        if "toc" in _epub_type_tokens(nav):
            return nav
    for nav in navs:
        if nav.get("role") == "doc-toc":
            return nav
    for nav in navs:
        if _direct_child(nav, "ol") is not None:
            return nav
    return None


def _li_yields_entry(li: etree._Element) -> bool:
    """Return whether `li` produces a NavDocEntry when parsed (see `_parse_li`).

    An EPUB 3 toc `<ol>` may legally contain a bare divider `<li>` with no
    `<a>`/`<span>` direct child (e.g. `<li>Part Two</li>`) — structurally
    valid, but `_parse_li` skips it (contributes no entry, and never
    descends into a nested `<ol>` under it either). Shared by `_parse_li`
    and `_apply_labels_to_ol`'s structure guard so both agree on exactly
    which `<li>` elements count.
    """
    return _direct_child(li, "a") is not None or _direct_child(li, "span") is not None


def _parse_li(li: etree._Element, counter: list[int]) -> NavDocEntry | None:
    """Parse one `<li>` into a NavDocEntry, recursing into a nested `<ol>` if present.

    `counter` is incremented before the current entry's id is assigned, then
    threaded into the recursive call — true pre-order numbering, so a parent
    always gets a lower `navdoc-toc-{N}` id than any of its children.
    """
    if not _li_yields_entry(li):
        return None
    link = _direct_child(li, "a")
    if link is None:
        link = _direct_child(li, "span")
    assert link is not None  # guaranteed by the _li_yields_entry check above

    nested_ol = _direct_child(li, "ol")

    counter[0] += 1
    entry_id = f"navdoc-toc-{counter[0]}"
    label = normalize_whitespace(_text_content(link))
    href = link.get("href", "") if _local_tag(link.tag) == "a" else ""
    children = _parse_ol(nested_ol, counter) if nested_ol is not None else []

    return NavDocEntry(entry_id=entry_id, label=label, href=href, children=children)


def _parse_ol(ol: etree._Element, counter: list[int]) -> list[NavDocEntry]:
    """Parse every `<li>` direct child of `<ol>` into NavDocEntry, in document order."""
    entries: list[NavDocEntry] = []
    for child in ol:
        if _local_tag(child.tag) != "li":
            continue
        entry = _parse_li(child, counter)
        if entry is not None:
            entries.append(entry)
    return entries


def parse_nav_doc(nav_bytes: bytes, href: str, href_in_zip: str, in_spine: bool) -> NavDoc:
    """Parse raw nav document bytes into a NavDoc model object.

    Args:
        nav_bytes: raw bytes of the nav document, as read from the ZIP.
        href: OPF-relative href (manifest key space).
        href_in_zip: full ZIP path to the nav document.
        in_spine: whether the nav document is also a spine item.

    Raises:
        MissingNavDoc: nav_bytes could not be parsed as XML.
    """
    try:
        tree = parse_xml_recover(nav_bytes)
    except etree.XMLSyntaxError as exc:
        raise MissingNavDoc(f"Nav document malformed: {exc}") from exc

    toc_nav = _find_toc_nav(tree)
    if toc_nav is None:
        return NavDoc(
            href=href,
            href_in_zip=href_in_zip,
            raw_bytes=nav_bytes,
            toc_entries=[],
            has_toc_nav=False,
            in_spine=in_spine,
        )

    ol = _direct_child(toc_nav, "ol")
    counter = [0]
    toc_entries = _parse_ol(ol, counter) if ol is not None else []

    return NavDoc(
        href=href,
        href_in_zip=href_in_zip,
        raw_bytes=nav_bytes,
        toc_entries=toc_entries,
        has_toc_nav=True,
        in_spine=in_spine,
    )


def _is_page_list_nav(el: etree._Element) -> bool:
    """Match `<nav epub:type="page-list">` or the ARIA `role="doc-pagelist"` fallback."""
    return "page-list" in _epub_type_tokens(el) or el.get("role") == "doc-pagelist"


def _find_page_list_navs(tree: etree._Element) -> list[etree._Element]:
    """Return every page-list `<nav>` element under tree, in document order."""
    return [el for el in tree.iter() if _local_tag(el.tag) == "nav" and _is_page_list_nav(el)]


def _mark_page_list_no_translate(body: etree._Element) -> None:
    """Add translate="no" to every page-list `<nav>` under body.

    Matches both the `epub:type` token `page-list` and the ARIA
    `role="doc-pagelist"` fallback. Set on the `<nav>` element itself, not
    recursively on its content — HTML5 `translate="no"` is inherited by
    descendants, so pagination markers (roman numerals, print page numbers)
    pass through DeepL unchanged without needing per-descendant marking.
    """
    for el in body.iter():
        if _local_tag(el.tag) == "nav" and _is_page_list_nav(el):
            el.set("translate", "no")


def _strip_injected_page_list_translate(original_bytes: bytes, candidate_bytes: bytes) -> bytes:
    """Reconcile page-list `<nav>` `translate` attributes against the original.

    `extract_nav_body_html` unconditionally marks every page-list nav with
    `translate="no"` before it enters the DeepL payload — a payload-only
    instruction, not part of the document's real structure (the same
    category of ephemeral state as the `data-spine-idx`/`data-source-href`
    markers elsewhere in the payload/restore pipeline). Left untouched, that
    marker survives verbatim into the restored nav document, which mutates
    the file beyond the translation contract even though it's epubcheck-legal.

    Candidate page-list navs are matched positionally, in document order,
    against the page-list navs of the *original* `nav_doc.raw_bytes`: the
    original's absence of a `translate` attribute means the candidate's was
    injected and gets removed; a `translate` attribute the original author
    did supply (e.g. `translate="yes"`) is restored to its exact original
    value, overwriting whatever `extract_nav_body_html` set.

    A page-list count mismatch between original and candidate (DeepL altered
    the nav structure) — or a parse failure on either side — leaves
    `candidate_bytes` untouched, mirroring the toc structure guard's
    fail-safe philosophy.
    """
    try:
        candidate_tree = parse_xml_recover(candidate_bytes)
    except etree.XMLSyntaxError:
        return candidate_bytes
    try:
        original_tree = parse_xml_recover(original_bytes)
    except etree.XMLSyntaxError:
        return candidate_bytes

    original_navs = _find_page_list_navs(original_tree)
    candidate_navs = _find_page_list_navs(candidate_tree)
    if not candidate_navs or len(original_navs) != len(candidate_navs):
        return candidate_bytes

    changed = False
    for original_nav, candidate_nav in zip(original_navs, candidate_navs, strict=True):
        original_value = original_nav.get("translate")
        if original_value == candidate_nav.get("translate"):
            continue
        changed = True
        if original_value is None:
            if "translate" in candidate_nav.attrib:
                del candidate_nav.attrib["translate"]
        else:
            candidate_nav.set("translate", original_value)

    if not changed:
        return candidate_bytes

    return etree.tostring(
        candidate_tree,
        xml_declaration=True,
        encoding="UTF-8",
        method="xml",
        pretty_print=False,
    )


def extract_nav_body_html(nav_bytes: bytes) -> str:
    """Extract the nav document's `<body>` inner HTML for the DeepL payload.

    Every page-list nav is marked `translate="no"` before extraction (see
    `_mark_page_list_no_translate`), so pagination markers survive translation
    unchanged. The toc and landmarks navs are left untouched — DeepL
    translates their contents like ordinary spine body content, matching the
    hybrid label strategy (US-008-consistent heading fallback is applied
    afterwards via `resolve_nav_labels` + `rebuild_nav_doc_bytes`).
    """
    try:
        tree = parse_xml_recover(nav_bytes)
    except etree.XMLSyntaxError:
        html_tree = parse_html_document(nav_bytes)
        body = _find_body(html_tree)
        if body is None:
            return ""
        return _inner_html(body)

    body = _find_body(tree)
    if body is None:
        return ""

    _mark_page_list_no_translate(body)
    return _inner_html(body)


def _set_link_text(link: etree._Element, text: str) -> None:
    """Replace a toc `<a>`/`<span>` element's text, clearing any child markup."""
    for child in list(link):
        link.remove(child)
    link.text = text


def _apply_labels_to_ol(
    ol: etree._Element,
    entries: list[NavDocEntry],
    new_labels: dict[str, str],
) -> bool:
    """Walk a translated `<ol>` in lockstep with the original entries tree.

    Overwrites each `<a>`/`<span>` element's text in-place from `new_labels`
    where the entry's id is present. Returns False, with no mutation applied
    at the point of mismatch, as soon as the translated shape (li count,
    link presence, nested-ol presence) diverges from `entries` — the caller
    then discards all partial edits by falling back to the untouched
    translated body.

    Candidate `<li>` elements are filtered through `_li_yields_entry` before
    the count comparison and lockstep walk, so a bare divider `<li>` (legal
    in an EPUB 3 toc, e.g. `<li>Part Two</li>`) — which `_parse_li` already
    excludes from `entries` — doesn't trip the guard on a shape that is in
    fact unchanged. Divider `<li>` elements themselves are left untouched:
    they carry no id to relabel and are never pulled into the `zip` below.
    """
    lis = [child for child in ol if _local_tag(child.tag) == "li" and _li_yields_entry(child)]
    if len(lis) != len(entries):
        return False

    for li, entry in zip(lis, entries, strict=True):
        link = _direct_child(li, "a")
        if link is None:
            link = _direct_child(li, "span")
        if link is None:
            return False

        nested_ol = _direct_child(li, "ol")
        if entry.children:
            if nested_ol is None or not _apply_labels_to_ol(nested_ol, entry.children, new_labels):
                return False
        elif nested_ol is not None:
            return False

        if entry.entry_id in new_labels:
            _set_link_text(link, new_labels[entry.entry_id])

    return True


def rebuild_nav_doc_bytes(
    nav_doc: NavDoc,
    translated_body_html: str,
    new_labels: dict[str, str],  # entry_id → new label text
) -> bytes:
    """Return updated nav document bytes with toc link texts overwritten.

    `translated_body_html` (the DeepL-translated nav body, landmarks and toc
    included) is installed via `replace_body_content` first — this preserves
    DOCTYPE, xml declaration, `<head>`, and every attribute on `<html>`/
    `<body>`/`<nav>` exactly as in the original. A pre-order walk over the
    resulting toc `<ol>`, matched against `nav_doc.toc_entries` id-for-id
    (see `_apply_labels_to_ol`), then overwrites each link's text with
    `new_labels[entry_id]` where present.

    Structure guard: if the translated toc's `<ol>`/`<li>` shape no longer
    matches `nav_doc.toc_entries` (DeepL reordered, merged, or dropped list
    items), the translated body is kept as-is and a WARNING is logged instead
    of raising — a partial or garbled label overwrite would be worse than an
    already DeepL-translated, but unlabelled-by-heading, toc.

    Page-list navs also get their `translate` attribute reconciled against
    the original (see `_strip_injected_page_list_translate`) — this runs
    unconditionally, independent of the toc/label handling below, so a nav
    document with a page-list but no toc still has its injected marker
    removed.
    """
    new_bytes = replace_body_content(nav_doc.raw_bytes, translated_body_html)
    new_bytes = _strip_injected_page_list_translate(nav_doc.raw_bytes, new_bytes)

    if not nav_doc.has_toc_nav or not new_labels:
        return new_bytes

    try:
        tree = parse_xml_recover(new_bytes)
    except etree.XMLSyntaxError:
        return new_bytes

    toc_nav = _find_toc_nav(tree)
    if toc_nav is None:
        return new_bytes

    ol = _direct_child(toc_nav, "ol")
    if ol is None:
        return new_bytes

    if not _apply_labels_to_ol(ol, nav_doc.toc_entries, new_labels):
        _log.warning(
            "Nav doc %r: translated toc <ol> shape no longer matches the original; "
            "keeping translated body as-is",
            nav_doc.href_in_zip,
        )
        return new_bytes

    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        method="xml",
        pretty_print=False,
    )


def _iter_entries(entries: list[NavDocEntry]) -> Iterator[NavDocEntry]:
    """Yield every entry in the tree, pre-order (parent before its children)."""
    for entry in entries:
        yield entry
        yield from _iter_entries(entry.children)


def resolve_nav_labels(nav_doc: NavDoc, epub: Epub) -> dict[str, str]:
    """Resolve each toc entry's label via anchor resolution against translated XHTML.

    Mirrors NCX label resolution (`ncx.resolve_label`) but returns a flat
    dict — `entry_id -> label` — instead of mutating a tree, since the nav
    document's translated body already lives as a separate HTML string at
    this point; `rebuild_nav_doc_bytes` applies the results.

    Entries with no href, or whose anchor can't be resolved (fragment missing
    from the target and no heading fallback, the target is unparsable, escapes
    the ZIP root, or is not a manifest file), are omitted from the returned
    dict: the caller leaves the already DeepL-translated link text standing
    for those.  Mirrors the per-navPoint fallback in
    `restore.applier._resolve_all_labels` — one hostile or external href must
    not abort the whole restore.
    """
    labels: dict[str, str] = {}
    for entry in _iter_entries(nav_doc.toc_entries):
        if not entry.href:
            continue
        try:
            label = resolve_anchor_label(entry.href, nav_doc.href_in_zip, epub.opf_dir, epub)
        except Exception as exc:
            _log.warning("Anchor resolution failed for nav entry %r: %s", entry.entry_id, exc)
            continue
        if label is not None:
            labels[entry.entry_id] = label
    return labels
