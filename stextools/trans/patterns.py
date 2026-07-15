"""Regex patterns for parsing sTeX term macros, plus the language-alias table."""
import re
from typing import Dict, List, Pattern, Tuple

# The following dictionary maps canonical language codes to a list of aliases that can be used to refer to that language. 
# This allows for flexible input of language codes in the command-line interface or other contexts.
LANG_ALIASES: Dict[str, List[str]] = {
    "de": ["de", "german"],
    "zhs": ["zhs", "chinese", "zh", "zh-cn", "zh_cn", "ch"],
    "fr": ["fr", "french"],
    "jp": ["jp", "japanese"],
}

# normalize language aliases to canonical codes
# arg: a language code or alias (e.g., 'de', 'german', 'zhs', 'chinese')
# returns: the canonical language code (e.g., 'de', 'zhs')  
def resolve_lang_alias(arg: str) -> str:
    a = arg.lower()
    for canon, aliases in LANG_ALIASES.items():
        if a in aliases:
            return canon
    return arg


# Every token that may be used as a shorthand CLI flag (e.g. de, german, zhs, chinese).
# Derived from LANG_ALIASES so adding a language there automatically enables its flags.
# returns: a sorted list of all language flag tokens
def lang_flag_tokens() -> List[str]:
    tokens = set(LANG_ALIASES)
    for aliases in LANG_ALIASES.values():
        tokens.update(aliases)
    return sorted(tokens)


# ---------------------------
# Regex patterns (conservative)
# ---------------------------
RE_SMODULE = re.compile(
    r'\\begin\{smodule\}\s*(?:\[(?P<opts>[^\]]*)\])?\s*\{(?P<id>[^}]+)\}',
    re.MULTILINE,
)
RE_SMODULE_TITLE = re.compile(
    r'\\begin\{smodule\}\s*\[(?P<opts>[^\]]*title\s*=\s*\{(?P<title>[^}]+)\}[^\]]*)\]\s*\{(?P<id>[^}]+)\}',
    re.MULTILINE,
)
RE_SYMDECL = re.compile(r'\\symdecl\*?\{(?P<id>[^}]+)\}')
RE_SYMDEF = re.compile(r'\\symdef\{(?P<id>[^}]+)\}\[.*?\]\{(?P<notation>.*?)\}', re.DOTALL)
RE_IMPORT = re.compile(r'\\importmodule(?:\[[^\]]*\])?\{(?P<mod>[^}]+)\}')
RE_USES = re.compile(r'\\usestructure\{(?P<id>[^}]+)\}')
RE_EXTSTRUCT = re.compile(r'\\begin\{extstructure\}\{(?P<id>[^}]+)\}\s*(?:\[(?P<opts>[^\]]*)\])?', re.MULTILINE)
RE_DEFINIENDUM = re.compile(r'\\definiendum(?:\[[^\]]*\])?\{(?P<key>[^}]+)\}\{(?P<text>[^}]+)\}')
# \definame and its capitalized variant \Definame (single-argument defined term)
RE_DEFINAME= re.compile(r'\\[dD]efiname(?:\[.*?\])?\{(?P<key>[^}]+)\}(?!\{)')
RE_SR = re.compile(r'\\sr\{(?P<key>[^}]+)\}\{(?P<text>[^}]+)\}')
# Symbol-name references: \sn, plural \sns, and capitalized \Sn/\Sns, each with an
# optional [..] option (e.g. \sn[post=y]{sensor}).
RE_SN = re.compile(r'\\[sS]ns?(?:\[[^\]]*\])?\{(?P<key>[^}]+)\}')
RE_DEFNOTATION = re.compile(r'\\defnotation\{(?P<text>[^}]+)\}')
RE_VARDER = re.compile(r'\\vardef\{(?P<id>[^}]+)\}\{(?P<def>[^}]+)\}')
RE_CMHTIKZ = re.compile(r'\\cmhtikzinput(?:\[.*?\])?\{(?P<path>[^}]+)\}')

# List of macros that take two arguments (key and text) for translation.
# NB: \defnotation is deliberately excluded -- in the SMGloM data model a symbol has
# both verbalizations (words, translatable) and notations (math rendering, NOT
# translatable). \defnotation introduces a notation, so it must be left untouched.
SECOND_ARG_MACROS: List[Tuple[Pattern[str], str]] = [
    (RE_DEFINIENDUM, 'definiendum'),
    (RE_SR, 'sr'),
]
 
# List of macros that take one argument (key) for translation
SINGLE_ARG_MACROS: List[Tuple[Pattern[str], str]] = [
    (RE_DEFINAME, 'definame'),
    (RE_SN, 'sn'),
]
