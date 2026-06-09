"""OPF parsing and metadata manipulation.

Strategy for C-2 (byte-level preservation):
  We store the complete raw OPF bytes and restore by:
  1. Parsing with lxml.
  2. Mutating only the known-translatable dc:* elements in-place.
  3. Re-serialising with etree.tostring(..., method='xml').

  Structural correctness (C-2) is enforced via canonical XML equality
  (etree.tostring(..., method='c14n2')) in unit tests, not byte equality.
  US-010 and US-013 explicitly permit re-serialisation cosmetic changes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import etree

from epub_deepl_prepare.epub._safe_parser import parse_xml
from epub_deepl_prepare.epub.model import ManifestItem, OpfMetadata, Spine, SpineRef
from epub_deepl_prepare.errors import NotAnEpub

if TYPE_CHECKING:
    pass

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


def rebuild_opf_bytes(
    original_opf_bytes: bytes,
    new_metadata: OpfMetadata,
    target_language: str,
) -> bytes:
    """Return updated OPF bytes with translated metadata fields replaced.

    Mutates only dc:title, dc:description, dc:subject, dc:language in-place
    inside the original OPF tree.  All other content — manifest, spine, guide,
    extension elements — is preserved structurally (canonical XML equality).

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

    # Replace translatable fields in-place:
    # 1) Remove all existing instances of the translatable tags
    # 2) Insert new values preserving the original relative position

    _TRANSLATABLE_TAGS = {_dc("title"), _dc("description"), _dc("subject"), _dc("language")}

    # Collect positions and elements to remove
    to_remove = [(i, el) for i, el in enumerate(metadata_el) if el.tag in _TRANSLATABLE_TAGS]

    # Insert point: position of the first translatable element
    insert_pos = to_remove[0][0] if to_remove else len(list(metadata_el))

    # Remove in reverse order to preserve indices
    for _, el in reversed(to_remove):
        metadata_el.remove(el)

    # Build replacement elements
    replacements: list[etree._Element] = []

    # dc:title elements
    for title in new_metadata.titles:
        el = etree.Element(_dc("title"))
        el.text = title
        replacements.append(el)

    # dc:description elements
    for desc in new_metadata.descriptions:
        el = etree.Element(_dc("description"))
        el.text = desc
        replacements.append(el)

    # dc:subject elements
    for subj in new_metadata.subjects:
        el = etree.Element(_dc("subject"))
        el.text = subj
        replacements.append(el)

    # dc:language — exactly one, set to target_language
    lang_el = etree.Element(_dc("language"))
    lang_el.text = target_language
    replacements.append(lang_el)

    # Insert at original position
    for offset, el in enumerate(replacements):
        metadata_el.insert(insert_pos + offset, el)

    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    )


def _strip_ns(tag: str) -> str:
    """Return local name without namespace prefix."""
    return re.sub(r"^\{[^}]+\}", "", tag)
