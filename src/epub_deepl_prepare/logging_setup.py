"""Stderr logging configuration for epub-deepl-prepare.

Format: [LEVEL] message  (no timestamps; tool runs are short)
Levels: ERROR, WARN, INFO (only with --verbose)
"""

import logging
import sys
from typing import ClassVar


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    def __init__(self) -> None:
        super().__init__(stream=sys.stderr)


class _BracketFormatter(logging.Formatter):
    _LEVEL_MAP: ClassVar[dict[int, str]] = {
        logging.ERROR: "ERROR",
        logging.WARNING: "WARN",
        logging.INFO: "INFO",
        logging.DEBUG: "DEBUG",
    }

    def format(self, record: logging.LogRecord) -> str:
        level_name = self._LEVEL_MAP.get(record.levelno, record.levelname)
        message = record.getMessage()
        return f"[{level_name}] {message}"


def configure(verbose: bool = False) -> None:
    """Set up root logger for the tool.

    After this call, use `logging.getLogger(__name__)` in each module.
    """
    root = logging.getLogger("epub_deepl_prepare")
    root.handlers.clear()

    handler = _StderrHandler()
    handler.setFormatter(_BracketFormatter())
    root.addHandler(handler)

    root.setLevel(logging.DEBUG if verbose else logging.WARNING)
    # Prevent propagation to root logger (avoids double-printing).
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the tool's namespace."""
    return logging.getLogger(f"epub_deepl_prepare.{name}")
