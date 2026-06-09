"""Typed exception hierarchy for epub-translation-prepare.

Exit code mapping:
    UserError subclasses → exit code 1
    InternalError → exit code 2
"""


class EpubTranslationError(Exception):
    """Base exception for all tool errors."""


class UserError(EpubTranslationError):
    """Exits with code 1; message printed to stderr as [ERROR]."""


class ValidationError(UserError):
    """Specific subclass for input validation failures."""


class DrmDetected(ValidationError):
    """EPUB contains META-INF/encryption.xml — DRM protected."""


class BrokenManifest(ValidationError):
    """OPF manifest references files missing from the ZIP."""


class BrokenSpine(ValidationError):
    """OPF spine contains idrefs that don't resolve to manifest items."""


class MissingNcx(ValidationError):
    """NCX file missing or unparseable."""


class NotAnEpub(ValidationError):
    """File is not a valid EPUB 2.0 archive."""


class UnsupportedMediaType(ValidationError):
    """Spine item has a media-type the tool cannot handle (US-020)."""


class TranslatedHtmlMismatch(ValidationError):
    """data-source-href in translated HTML doesn't match input EPUB spine."""


class OutputExists(UserError):
    """Output file already exists and --force was not passed."""


class OutputEqualsInput(UserError):
    """Output path resolves to the same file as an input path (US-018)."""


class InternalError(EpubTranslationError):
    """Exits with code 2; indicates a bug in the tool, not in user input."""
