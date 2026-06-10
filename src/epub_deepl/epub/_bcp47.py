"""BCP 47 language tag helpers (well-formedness + primary-subtag extraction).

Both EPUB OPF ``<dc:language>`` (EPUB Packages 3.x §5.6.3) and HTML5
``<html lang>`` (HTML Living Standard, MDN) declare BCP 47 / RFC 5646
as the tag syntax. We perform structural well-formedness checks only —
not a full subtag-registry validation, matching the practice of
epubcheck and W3C validators.

Rules used here:
  - Tag is composed of one or more subtags separated by hyphens.
  - Primary subtag: ASCII letters, length 1-8 (real registry uses 2-3
    for languages and 4 for reserved, but BCP 47 grammar allows 1-8).
  - Subsequent subtags: ASCII letters or digits, length 1-8.
  - Case is **not** semantically distinct per RFC 5646 §2.1.1
    ("mn-Cyrl-MN" == "MN-cYRL-mn"); comparisons are case-insensitive.
"""

from __future__ import annotations

import re

# Structural well-formedness:
#   primary = ALPHA{1,8}
#   subtag  = (ALPHA / DIGIT){1,8}
#   tag     = primary (-subtag)*
_WELL_FORMED = re.compile(r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$")


def is_well_formed(tag: str) -> bool:
    """Return True if ``tag`` is a structurally well-formed BCP 47 tag.

    Does NOT validate that subtags exist in the IANA Language Subtag
    Registry — that is intentionally beyond MVP scope and matches what
    epubcheck enforces in practice.
    """
    if not isinstance(tag, str):
        return False
    return bool(_WELL_FORMED.match(tag))


def primary_subtag(tag: str) -> str:
    """Return the primary language subtag (the part before the first
    hyphen) lowercased for case-insensitive comparison. Returns the
    empty string if ``tag`` is empty / not a string.
    """
    if not isinstance(tag, str) or not tag:
        return ""
    return tag.split("-", 1)[0].lower()
