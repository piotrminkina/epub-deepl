"""Unit tests for BCP 47 well-formedness and primary-subtag extraction."""

from __future__ import annotations

import pytest

from epub_deepl_prepare.epub._bcp47 import is_well_formed, primary_subtag


@pytest.mark.parametrize(
    "tag",
    [
        "pl",
        "en",
        "EN",
        "en-US",
        "en-us",
        "pt-BR",
        "zh-Hant",
        "zh-Hant-TW",
        "en-US-x-private",
        "i-klingon",  # not a real grandfathered tag, but well-formed at grammar level
        "x-private",  # purely private use
        "a",  # 1-letter primary (BCP 47 grammar allows 1-8)
    ],
)
def test_is_well_formed_accepts_valid_tags(tag: str) -> None:
    assert is_well_formed(tag), f"expected {tag!r} to be well-formed"


@pytest.mark.parametrize(
    "tag",
    [
        "",
        " ",
        "pl ",  # trailing whitespace (caller is responsible for trimming first)
        " pl",
        "not a tag",  # whitespace inside
        "pl_PL",  # underscore is not a subtag separator
        "-pl",  # leading hyphen
        "pl-",  # trailing hyphen
        "pl--PL",  # empty subtag
        "12",  # primary subtag must start with letters
        "abcdefghi",  # subtag exceeds 8-character limit
        "pl-abcdefghi",  # subsequent subtag exceeds 8 chars
        "pl/PL",  # slash is not allowed
    ],
)
def test_is_well_formed_rejects_invalid(tag: str) -> None:
    assert not is_well_formed(tag), f"expected {tag!r} to be rejected"


def test_is_well_formed_rejects_non_string() -> None:
    assert not is_well_formed(None)  # type: ignore[arg-type]
    assert not is_well_formed(123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("pl", "pl"),
        ("PL", "pl"),
        ("en-US", "en"),
        ("EN-us", "en"),
        ("zh-Hant-TW", "zh"),
        ("en-US-x-private", "en"),
        ("", ""),
    ],
)
def test_primary_subtag(tag: str, expected: str) -> None:
    assert primary_subtag(tag) == expected


def test_primary_subtag_non_string_returns_empty() -> None:
    assert primary_subtag(None) == ""  # type: ignore[arg-type]
