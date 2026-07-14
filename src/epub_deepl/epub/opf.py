"""OPF parsing and metadata manipulation.

Strategy for C-2 (byte-level preservation):
  We store the complete raw OPF bytes and restore by:
  1. Parsing with lxml.
  2. Mutating only the known-translatable dc:* elements' text in-place,
     leaving every attribute (id, xml:lang, opf:*) untouched.
  3. Re-serialising with etree.tostring(..., method='xml').

  Structural correctness (C-2) is enforced via canonical XML equality
  (etree.tostring(..., method='c14n2')) in unit tests, not byte equality.
  US-010 and US-013 explicitly permit re-serialisation cosmetic changes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import etree

from epub_deepl.epub._safe_parser import parse_xml
from epub_deepl.epub.model import ManifestItem, OpfMetadata, Spine, SpineRef
from epub_deepl.errors import NotAnEpub
from epub_deepl.logging_setup import get_logger

if TYPE_CHECKING:
    pass

_log = get_logger("epub.opf")

# Standard Dublin Core namespace in EPUB 2
_DC_NS = "http://purl.org/dc/elements/1.1/"
_OPF_NS = "http://www.idpf.org/2007/opf"

_DC = f"{{{_DC_NS}}}"
_OPF = f"{{{_OPF_NS}}}"


def _dc(tag: str) -> str:
    return f"{_DC}{tag}"


def _text_or_empty(el: etree._Element) -> str:
    return (el.text or "").strip()


def parse_metadata(opf_bytes: bytes) -> OpfMetadata:
    """Extract OpfMetadata from raw OPF bytes."""
    try:
        tree = parse_xml(opf_bytes)
    except etree.XMLSyntaxError as exc:
        raise NotAnEpub(f"OPF malformed: {exc}") from exc

    # Normalise: strip namespace from root if it is the OPF namespace
    metadata_el = tree.find(f"{_OPF}metadata")
    if metadata_el is None:
        metadata_el = tree.find("metadata")
    if metadata_el is None:
        raise NotAnEpub("OPF has no <metadata> element")

    def _all(tag: str) -> list[str]:
        results = []
        for el in metadata_el:
            if el.tag == _dc(tag):
                results.append(_text_or_empty(el))
        return results

    titles = _all("title")
    descriptions = _all("description")
    subjects = _all("subject")
    languages = _all("language")
    creators = _all("creator")
    publishers = _all("publisher")
    dates = _all("date")
    identifiers = _all("identifier")
    rights = _all("rights")

    language = languages[0] if languages else ""

    return OpfMetadata(
        titles=titles,
        descriptions=descriptions,
        subjects=subjects,
        language=language,
        creators=creators,
        publishers=publishers,
        dates=dates,
        identifiers=identifiers,
        rights=rights,
        extra_raw_xml=etree.tostring(metadata_el, encoding="unicode").encode("utf-8"),
    )


def parse_manifest(opf_bytes: bytes) -> dict[str, ManifestItem]:
    """Return manifest items keyed by item_id."""
    try:
        tree = parse_xml(opf_bytes)
    except etree.XMLSyntaxError as exc:
        raise NotAnEpub(f"OPF malformed: {exc}") from exc

    manifest_el = tree.find(f"{_OPF}manifest")
    if manifest_el is None:
        manifest_el = tree.find("manifest")
    if manifest_el is None:
        raise NotAnEpub("OPF has no <manifest> element")

    items: dict[str, ManifestItem] = {}
    for item in manifest_el:
        tag = item.tag
        if (isinstance(tag, str) and tag.endswith("}item")) or tag == "item":
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            properties = item.get("properties")
            if item_id:
                items[item_id] = ManifestItem(
                    item_id=item_id,
                    href=href,
                    media_type=media_type,
                    properties=properties,
                )

    return items


def parse_spine(opf_bytes: bytes) -> Spine:
    """Return Spine from raw OPF bytes."""
    try:
        tree = parse_xml(opf_bytes)
    except etree.XMLSyntaxError as exc:
        raise NotAnEpub(f"OPF malformed: {exc}") from exc

    spine_el = tree.find(f"{_OPF}spine")
    if spine_el is None:
        spine_el = tree.find("spine")
    if spine_el is None:
        raise NotAnEpub("OPF has no <spine> element")

    toc_idref = spine_el.get("toc")

    items: list[SpineRef] = []
    for ref in spine_el:
        tag = ref.tag
        if isinstance(tag, str) and (tag.endswith("}itemref") or tag == "itemref"):
            idref = ref.get("idref", "")
            linear_attr = ref.get("linear", "yes")
            linear = linear_attr.lower() != "no"
            if idref:
                items.append(SpineRef(idref=idref, linear=linear))

    return Spine(items=items, toc_idref=toc_idref)


def get_opf_path_from_container(container_bytes: bytes) -> str:
    """Parse META-INF/container.xml and return the OPF full-path."""
    try:
        tree = parse_xml(container_bytes)
    except etree.XMLSyntaxError as exc:
        raise NotAnEpub(f"container.xml malformed: {exc}") from exc

    # OCF namespace
    _OCF_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
    ns = {"c": _OCF_NS}

    rootfiles = tree.findall(".//c:rootfile", ns)
    if not rootfiles:
        # Try without namespace
        rootfiles = tree.findall(".//rootfile")
    if not rootfiles:
        raise NotAnEpub("container.xml has no <rootfile> element")

    full_path = rootfiles[0].get("full-path", "")
    if not full_path:
        raise NotAnEpub("container.xml <rootfile> missing full-path attribute")

    return full_path


_TRANSLATABLE_TAGS = {_dc("title"), _dc("description"), _dc("subject"), _dc("language")}


def _fallback_insert_pos(metadata_el: etree._Element) -> int:
    """Return the insertion index for a brand-new translatable element.

    Used only when a given tag has zero existing elements. Returns the
    index immediately after the LAST translatable-tag element currently
    present in <metadata> (or the end of <metadata> if none is present), so
    that title/description/subject/language — processed in that order —
    cluster together in that same order right after any pre-existing
    translatable block, instead of each new insert reversing the previous
    one.
    """
    last_index = -1
    for i, el in enumerate(metadata_el):
        if el.tag in _TRANSLATABLE_TAGS:
            last_index = i
    return last_index + 1 if last_index >= 0 else len(metadata_el)


def _anchor_tail(metadata_el: etree._Element, insert_pos: int) -> str:
    """Return the tail text to give element(s) inserted at insert_pos.

    Copies the tail of the immediately preceding sibling so a freshly
    inserted element doesn't get mashed onto the same line as its neighbour;
    falls back to a newline when there is no preceding sibling or tail.
    """
    if insert_pos > 0:
        preceding_tail = metadata_el[insert_pos - 1].tail
        if preceding_tail is not None:
            return preceding_tail
    return "\n"


def _clear_children(el: etree._Element) -> None:
    """Remove all child elements (and their tails) from el, keeping attributes.

    Required before mutating .text: lxml's text assignment only sets the
    text preceding the first child, so any pre-existing child elements (and
    stray tail text glued to them) would otherwise survive alongside the
    newly-assigned text.
    """
    for child in list(el):
        el.remove(child)


def _mutate_translatable_list(
    metadata_el: etree._Element,
    tag: str,
    new_values: list[str],
) -> None:
    """Mutate existing dc:<tag> elements' text in-place, preserving attributes.

    Pairwise assignment in document order. Any pre-existing child elements
    are cleared first (see ``_clear_children``). Extra new values beyond the
    existing element count get freshly created, attribute-less elements
    appended adjacent to the last existing one of that tag (or at
    ``_fallback_insert_pos`` if none existed). Fewer new values than existing
    elements leaves the surplus elements' text unchanged and logs a warning
    (counts are normally equal — validated upstream in
    restore/applier.py:_validate_metadata_counts).
    """
    existing = [el for el in metadata_el if el.tag == tag]
    for el, text in zip(existing, new_values, strict=False):
        _clear_children(el)
        el.text = text

    if len(new_values) > len(existing):
        if existing:
            insert_pos = list(metadata_el).index(existing[-1]) + 1
        else:
            insert_pos = _fallback_insert_pos(metadata_el)
        tail = _anchor_tail(metadata_el, insert_pos)
        for offset, text in enumerate(new_values[len(existing) :]):
            new_el = etree.Element(tag)
            new_el.text = text
            new_el.tail = tail
            metadata_el.insert(insert_pos + offset, new_el)
    elif len(new_values) < len(existing):
        _log.warning(
            "<%s>: %d existing element(s) but only %d translated value(s); "
            "%d surplus element(s) left unchanged",
            _strip_ns(tag),
            len(existing),
            len(new_values),
            len(existing) - len(new_values),
        )


def _set_language(metadata_el: etree._Element, target_language: str) -> None:
    """Set the first dc:language element's text to target_language.

    Creates and inserts one if none exists. Additional dc:language elements
    beyond the first are preserved unchanged and trigger a WARNING — this is
    a deliberate behaviour change from the previous collapse-to-one logic.
    """
    lang_elements = [el for el in metadata_el if el.tag == _dc("language")]
    if lang_elements:
        first = lang_elements[0]
        _clear_children(first)
        first.text = target_language
        if len(lang_elements) > 1:
            _log.warning(
                "%d <dc:language> elements found; only the first was set to %r, "
                "%d extra element(s) preserved unchanged",
                len(lang_elements),
                target_language,
                len(lang_elements) - 1,
            )
    else:
        insert_pos = _fallback_insert_pos(metadata_el)
        lang_el = etree.Element(_dc("language"))
        lang_el.text = target_language
        lang_el.tail = _anchor_tail(metadata_el, insert_pos)
        metadata_el.insert(insert_pos, lang_el)


def rebuild_opf_bytes(
    original_opf_bytes: bytes,
    new_metadata: OpfMetadata,
    target_language: str,
) -> bytes:
    """Return updated OPF bytes with translated metadata fields replaced.

    Mutates only dc:title, dc:description, dc:subject, dc:language text
    in-place inside the original OPF tree — every attribute (id, xml:lang,
    opf:*) on those elements is preserved, keeping e.g. EPUB 3
    ``<meta refines="#id">`` pairs and EPUB 2 ``opf:file-as`` intact. All
    other content — manifest, spine, guide, extension elements — is
    preserved structurally (canonical XML equality).

    C-2 mitigation: we do NOT try to preserve byte-for-byte; we accept lxml
    re-serialisation cosmetics (attribute ordering, namespace prefix choices).
    Structural equality is verified by c14n2 in tests.
    """
    try:
        tree = parse_xml(original_opf_bytes)
    except etree.XMLSyntaxError as exc:
        raise NotAnEpub(f"OPF malformed during rebuild: {exc}") from exc

    metadata_el = tree.find(f"{_OPF}metadata")
    if metadata_el is None:
        metadata_el = tree.find("metadata")
    if metadata_el is None:
        raise NotAnEpub("OPF has no <metadata> element during rebuild")

    _mutate_translatable_list(metadata_el, _dc("title"), new_metadata.titles)
    _mutate_translatable_list(metadata_el, _dc("description"), new_metadata.descriptions)
    _mutate_translatable_list(metadata_el, _dc("subject"), new_metadata.subjects)
    _set_language(metadata_el, target_language)

    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    )


def _strip_ns(tag: str) -> str:
    """Return local name without namespace prefix."""
    return re.sub(r"^\{[^}]+\}", "", tag)
