"""stextools.trans: the `stextools trans` subcommand — turn an annotated sTeX module into a
translation template for another language (English to German, German to English, ...),
auto-filling term translations resolved via FLAMS against the SMGloM domain model."""
from .builder import build_template, direction_problem, is_generated_template
from .extractor import extract_items
from .fill import compute_fills
from .patterns import LANG_ALIASES, base_name, lang_flag_tokens, lang_of_path, resolve_lang_alias

__all__ = [
    "build_template",
    "direction_problem",
    "is_generated_template",
    "extract_items",
    "compute_fills",
    "resolve_lang_alias",
    "lang_of_path",
    "base_name",
    "LANG_ALIASES",
    "lang_flag_tokens",
]
