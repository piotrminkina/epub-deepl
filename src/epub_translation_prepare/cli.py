"""CLI entry point for epub-translation-prepare.

Subcommands:
  prepare <input.epub> [--output FILE] [--force] [--verbose]
  restore <input.epub> <translated.html> --lang CODE [--output FILE] [--force] [--verbose]

Exit codes:
  0 — success
  1 — user error (bad input, validation failure, file not found, etc.)
  2 — internal error (unexpected exception / bug)
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import traceback

from epub_translation_prepare import __version__
from epub_translation_prepare.epub.reader import read_epub
from epub_translation_prepare.epub.validator import (
    check_output_not_exists,
    check_output_not_input,
    validate_epub,
)
from epub_translation_prepare.errors import EpubTranslationError, InternalError, UserError
from epub_translation_prepare.logging_setup import configure, get_logger
from epub_translation_prepare.merge.builder import build, count_ruby
from epub_translation_prepare.restore.applier import apply_and_write
from epub_translation_prepare.restore.parser import parse_translated_html

_log = get_logger("cli")


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epub-translation-prepare",
        description=(
            "Prepare an EPUB for translation via DeepL (prepare), "
            "or reassemble the translated EPUB (restore)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Emit per-file progress to stderr"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # prepare subcommand
    prep = sub.add_parser(
        "prepare",
        help="Bundle an EPUB's content into a single HTML5 file for DeepL translation.",
    )
    prep.add_argument("input", metavar="INPUT.epub", help="Path to the source EPUB file")
    prep.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Output path (default: <input-stem>.prepare.html in the same directory)",
    )
    prep.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists",
    )

    # restore subcommand
    res = sub.add_parser(
        "restore",
        help="Reassemble a translated EPUB from the original EPUB and translated HTML.",
    )
    res.add_argument("input", metavar="INPUT.epub", help="Path to the original EPUB file")
    res.add_argument(
        "translated",
        metavar="TRANSLATED.html",
        help="Path to the translated HTML file",
    )
    res.add_argument(
        "--lang",
        required=True,
        metavar="CODE",
        help="Target language code (BCP 47, e.g. pl, en, de, pt-BR)",
    )
    res.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Output path (default: <input-stem>.translated.epub in the same directory)",
    )
    res.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists",
    )

    return parser


def _default_prepare_output(input_path: str) -> str:
    p = pathlib.Path(input_path)
    return str(p.parent / f"{p.stem}.prepare.html")


def _default_restore_output(input_path: str) -> str:
    p = pathlib.Path(input_path)
    return str(p.parent / f"{p.stem}.translated.epub")


def _run_prepare(args: argparse.Namespace) -> int:
    input_path = args.input
    output_path = args.output or _default_prepare_output(input_path)

    # US-018: output must not equal any input path
    check_output_not_input(output_path, input_path)
    # US-014: fail-fast if output exists and --force not given
    check_output_not_exists(output_path, args.force)

    _log.info("Reading EPUB: %s", input_path)
    epub = read_epub(input_path)

    # I-1 / US-019: warn if source language is missing
    if not epub.metadata.language:
        _log.warning('Source language not declared in OPF; using "und"')
        epub.metadata.language = "und"

    validate_epub(epub)

    # US-012: warn about ruby annotations
    ruby_count = count_ruby(epub)
    if ruby_count > 0:
        _log.warning("Ruby annotations detected in %d place(s)", ruby_count)

    _log.info("Building merged HTML...")
    merged_html = build(epub)

    _log.info("Writing output: %s", output_path)
    pathlib.Path(output_path).write_text(merged_html, encoding="utf-8")

    return 0


def _run_restore(args: argparse.Namespace) -> int:
    input_path = args.input
    translated_path = args.translated
    target_lang = args.lang
    output_path = args.output or _default_restore_output(input_path)

    # US-018
    check_output_not_input(output_path, input_path, translated_path)
    # US-014
    check_output_not_exists(output_path, args.force)

    _log.info("Reading original EPUB: %s", input_path)
    epub = read_epub(input_path)

    # I-1: ensure language field exists
    if not epub.metadata.language:
        epub.metadata.language = "und"

    validate_epub(epub)

    _log.info("Parsing translated HTML: %s", translated_path)
    doc = parse_translated_html(translated_path)

    _log.info("Applying translations and writing output: %s", output_path)
    apply_and_write(epub, doc, target_lang, output_path)

    return 0


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Dispatch to the correct subcommand handler."""
    if args.command == "prepare":
        return _run_prepare(args)
    if args.command == "restore":
        return _run_restore(args)
    parser.print_help()
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point — returns exit code."""
    parser = _make_parser()
    args = parser.parse_args(argv)

    configure(verbose=getattr(args, "verbose", False))

    try:
        return _dispatch(args, parser)
    except UserError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except InternalError as exc:
        print(f"[ERROR] Internal error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
    except EpubTranslationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Unexpected error: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
