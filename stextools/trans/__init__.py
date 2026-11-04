"""stextools.trans: the `stextools trans` subcommand — turn an English (annotated) sTeX
module into a target-language translation template, auto-filling term translations
resolved via FLAMS against the SMGloM domain model."""
from .builder import build_template
from .extractor import extract_items
from .fill import compute_fills
from .patterns import LANG_ALIASES, lang_flag_tokens, resolve_lang_alias

__all__ = [
    "build_template",
    "extract_items",
    "compute_fills",
    "resolve_lang_alias",
    "LANG_ALIASES",
    "lang_flag_tokens",
]
