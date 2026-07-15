"""Extract translatable items (module id/title, imports, term macros) from an sTeX source."""
import re
from typing import Any, Dict, Tuple

from .patterns import (
    RE_CMHTIKZ,
    RE_DEFINAME,
    RE_DEFINIENDUM,
    RE_EXTSTRUCT,
    RE_IMPORT,
    RE_DEFNOTATION,
    RE_SMODULE,
    RE_SMODULE_TITLE,
    RE_SR,
    RE_SYMDECL,
    RE_SYMDEF,
    RE_USES,
    RE_VARDER,
    SECOND_ARG_MACROS,
    SINGLE_ARG_MACROS,
)


# The human-facing English word to translate: the symbol-name part of a key.
# e.g. "functions?argument" -> "argument"; "?operation" -> "operation";
#      "?idempotent/idempotent?idempotent" -> "idempotent"; "group" -> "group"
# args:
#     key: The symbol key, which may contain prefixes and suffixes.
# returns:
#     The human-facing English word to translate.
def _display_surface(key: str) -> str:
    s = key.split('?')[-1]
    s = s.split('/')[-1]
    return re.sub(r'\s+', ' ', s).strip()   # collapse newlines/indentation in multi-line keys


_PLURAL_ES = re.compile(r'(?:s|x|z|ch|sh)$', re.IGNORECASE)
_PLURAL_Y = re.compile(r'[^aeiouAEIOU]y$')


# Naive English pluralizer, good enough for a translator-facing placeholder hint.
# Only the last space-separated word is inflected (e.g. "measure space" -> "measure spaces").
# args:
#     word: The English word to pluralize.
# returns:
#     The pluralized form of the word, following basic English pluralization rules.
def _pluralize(word: str) -> str:
    if not word:
        return word
    head, _, last = word.rpartition(' ')
    prefix = head + ' ' if head else ''
    if _PLURAL_ES.search(last):
        last = last + 'es'
    elif _PLURAL_Y.search(last):
        last = last[:-1] + 'ies'
    else:
        last = last + 's'
    return prefix + last


# Build the placeholder surface (the English text a translator will replace) for a
# single-argument macro, honouring number/suffix hints carried by the macro:
#   \sns / \Sns  -> plural form of the symbol name
#   [post=X]     -> the symbol name with X appended (post=s therefore means plural too)
# Returns (surface, is_plural).
# args:
#   head: The full macro invocation (e.g., "\sn[post=s]{sensor}").
#   key: The symbol key.
# returns:
#   A tuple containing the placeholder surface (the English text a translator will replace)
def _single_arg_surface(head: str, key: str) -> Tuple[str, bool]:
    base = _display_surface(key)
    token_m = re.match(r'\\([A-Za-z]+)', head)
    token = token_m.group(1) if token_m else ''
    opt_m = re.search(r'\[([^\]]*)\]', head)
    post_m = re.search(r'post\s*=\s*([^,\]]+)', opt_m.group(1)) if opt_m else None

    if token.lower() == 'sns':          # plural symbol-name reference (\sns / \Sns)
        return _pluralize(base), True
    if post_m:                          # surface suffix, e.g. post=s -> "operations"
        suffix = post_m.group(1).strip()
        return base + suffix, suffix == 's'
    return base, False

# Extract all translatable items from the sTeX text.
# args:
#     text: The sTeX text to extract items from.
# returns:
#     A dictionary containing the extracted items.
def extract_items(text: str) -> Dict[str, Any]:
    out = {
        "module_id": None,
        "title": None,
        "imports": [],
        "symdecls": [],
        "symdefs": [],
        "usestructure": None,
        "extstructure": None,
        "cmhtikz": [],
        "items": [],
    }

    # Extract module ID and title
    m = RE_SMODULE.search(text)
    if m:
        out["module_id"] = m.group('id').strip()

    # Extract title from smodule options if present
    mtitle = RE_SMODULE_TITLE.search(text)
    if mtitle:
        out["title"] = mtitle.group('title').strip()
    else:
        # Extract title from smodule options if present
        sm_opts = re.search(r'\\begin\{smodule\}\s*\[(?P<opts>[^\]]+)\]', text)
        if sm_opts:
            opts = sm_opts.group('opts')
            # accept both braced (title={...}) and unbraced (title=Foo Bar) forms
            t = re.search(r'title\s*=\s*\{([^}]+)\}', opts) or re.search(r'title\s*=\s*([^,\]]+)', opts)
            if t:
                out["title"] = t.group(1).strip()

    for im in RE_IMPORT.finditer(text):
        out["imports"].append(im.group('mod').strip())

    for s in RE_SYMDECL.finditer(text):
        out["symdecls"].append(s.group('id').strip())

    for s in RE_SYMDEF.finditer(text):
        out["symdefs"].append({
            "id": s.group('id').strip(),
            "notation": s.group('notation').strip(),
        })

    m = RE_USES.search(text)
    if m:
        out["usestructure"] = m.group('id').strip()

    m = RE_EXTSTRUCT.search(text)
    if m:
        out["extstructure"] = {"id": m.group('id').strip(), "opts": m.group('opts')}

    for m in RE_CMHTIKZ.finditer(text):
        out["cmhtikz"].append(m.group('path').strip())

    # Process macros that take two arguments (key and text)
    for regex, typ in SECOND_ARG_MACROS:
        for mm in regex.finditer(text):
            key = mm.groupdict().get('key') or ''
            textarg = mm.groupdict().get('text') or mm.groupdict().get('def') or ''
            out["items"].append({
                "type": typ,
                "key": re.sub(r'\s+', ' ', key).strip(),
                "text": re.sub(r'\s+', ' ', textarg).strip(),
                "plural": False,
                "span": mm.span(),
            })

    # Process single-argument macros
    for regex, typ in SINGLE_ARG_MACROS:
        for mm in regex.finditer(text):
            key = (mm.groupdict().get('key') or '').strip()
            surface, plural = _single_arg_surface(mm.group(0), key)
            out["items"].append({
                "type": typ,
                "key": key,
                "text": surface,
                "plural": plural,
                "span": mm.span(),
            })

    return out
