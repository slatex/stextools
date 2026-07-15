"""Build a target-language sTeX translation template from an English source (optionally filling translations)."""
import functools
import re
from typing import Any, Dict, List, Tuple

from .extractor import extract_items

# create a placeholder for translation, or return the original text if no placeholders are desired
# args:
#     orig_text: The original English text to be translated.
#     key: The symbol key.
#     lang: The target language code.
#     opts: A dictionary of options.
# returns:
#     A string that is either a placeholder for translation (if placeholders are desired) 
#     or the original text (if placeholders are not desired).
def _make_placeholder(orig_text: str, key: str, lang: str, opts: Dict[str, Any]) -> str:
    return f"<<TRANSLATE[{lang}]: {orig_text or key}>>" if opts.get("insert_placeholders", True) else (orig_text or key)

# normalize a key for use in the sn command
# args:
#     key_raw: The raw symbol key to normalize.
# returns:
#     The normalized symbol key.
def _normalize_sn_key(key_raw: str) -> str:
    return re.sub(r"\s+", " ", key_raw).strip()

# replace \definame / \Definame with \definiendum and a placeholder for translation.
# The definame option (e.g. [post=s]) is a surface-generation hint that is already folded
# into the placeholder text, so it is dropped rather than carried onto \definiendum.
# args:
#     slice_text: The slice of text containing the \definame command to replace.
#     key: The symbol key.
#     placeholder: The placeholder for translation.
# returns:
#     A tuple containing the modified text and the number of replacements made.
def _replace_definame(slice_text: str, key: str, placeholder: str) -> Tuple[str, int]:
    pat = re.compile(r'\\[dD]efiname(?:\[.*?\])?\{' + re.escape(key) + r'\}(?!\{)', re.DOTALL)

    # Build the \definiendum replacement (key + placeholder) for a matched \definame.
    def _repl(m: re.Match) -> str:
        return f'\\definiendum{{{key}}}{{{placeholder}}}'

    return pat.subn(_repl, slice_text, count=1)

# replace \sn/\sns/\Sn/\Sns{...} (with optional [..] option) with \sr{normalized_key}{placeholder}
# args:
#     slice_text: The slice of text containing the \sn command to replace.
#     placeholder: The placeholder for translation.
# returns:
#     A tuple containing the modified text and the number of replacements made.
def _replace_sn(slice_text: str, placeholder: str) -> Tuple[str, int]:
    pat = re.compile(r'\\[sS]ns?(?:\[[^\]]*\])?\{(.*?)\}', re.DOTALL)

    # The replacement function normalizes the key and constructs the new \sr command with the placeholder.
    # args:
    #     m: The match object.
    # returns:
    #     The replacement string.
    def _repl(m: re.Match) -> str:
        key_norm = _normalize_sn_key(m.group(1))
        return f'\\sr{{{key_norm}}}{{{placeholder}}}'

    return pat.subn(_repl, slice_text, count=1)

# replace item text based on its type
# args:
#     slice_text: The slice of text containing the item to replace.
#     typ: The type of the item.
#     key: The symbol key.
#     placeholder: The placeholder for translation.
# returns:
#     A tuple containing the modified text and the number of replacements made.
def _replace_item_text(slice_text: str, typ: Any|None, key: str, placeholder: str) -> Tuple[str, int]:
    
    # if typ is definiendum, replace the display text with a placeholder (keeping any [..] option)
    if typ == 'definiendum':
        pat = re.compile(r'(\\definiendum(?:\[[^\]]*\])?\{' + re.escape(key) + r'\}\{)(.*?)(\})', re.DOTALL)
        return pat.subn(lambda m: m.group(1) + placeholder + m.group(3), slice_text, count=1)

    # if typ is definame, replace with \definiendum{key}{placeholder}
    if typ == 'definame':
        return _replace_definame(slice_text, key, placeholder)

    # if typ is sr, replace the display text with a placeholder
    if typ == 'sr':
        pat = re.compile(r'(\\sr\{' + re.escape(key) + r'\}\{)(.*?)(\})', re.DOTALL)
        return pat.subn(lambda m: m.group(1) + placeholder + m.group(3), slice_text, count=1)

    # ????? if typ is notation, replace with \notation{placeholder} ?????
    # if typ == 'notation':
    #     pat = re.compile(r'(\\notation\{)(.*?)(\})', re.DOTALL)
    #     return pat.subn(r'\1' + placeholder + r'\3', slice_text, count=1)

    # if typ is sn, replace with \sr{normalized_key}{placeholder}
    if typ == 'sn':
        return _replace_sn(slice_text, placeholder)

    return slice_text, 0

# process the extracted items and replace them in the text with placeholders for translation
# (or, when a fill is supplied for an item's span, with the chosen translation)
# args:
#     text: The original text.
#     items: The list of extracted items.
#     lang: The target language code.
#     opts: The options for translation.
#     report: The report dictionary to update.
#     fills: A dictionary mapping spans to their filled translations.
# returns:
#     The text with placeholders or filled translations.
def _process_items(text: str, items: List[Dict[str, Any]], lang: str, opts: Dict[str, Any], report: Dict[str, Any],
                   fills: Dict[Tuple[int, int], str] = None) -> str:
    working_text = text
    items_by_span = sorted(items, key=lambda it: it.get("span", (0, 0))[0], reverse=True)

    for item in items_by_span:
        typ = item.get("type")
        key = item.get("key", "")
        orig_text = item.get("text", "")
        span = item.get("span")
        if not span:
            continue

        fill = fills.get(tuple(span)) if fills else None
        placeholder = fill if fill is not None else _make_placeholder(orig_text, key, lang, opts)
        start, end = span
        slice_text = working_text[start:end]
        replaced, n = _replace_item_text(slice_text, typ, key, placeholder)

        if n:
            working_text = working_text[:start] + replaced + working_text[end:]
            report["items"].append({
                "type": typ, "key": key, "orig": orig_text,
                "filled": fill if fill is not None else None,
                "placeholder": (placeholder if fill is None and opts.get("insert_placeholders", True) else ""),
            })

    return working_text

# Macros that declare English-only module material: whole lines are dropped from the template.
_LINE_MACROS: List[str] = [
    "importmodule",
    "usemodule",
    "symdecl",
    "textsymdecl",
    "symdef",
    "notation",
]

# Remove a \STEXexport{...} block (may span multiple lines and contain nested braces),
# which carries English-only macro definitions.
# args:
#     text: The original text.
#     report: The report dictionary to update.
# returns:
#     The text with the \STEXexport block removed.
def _remove_stexexport(text: str, report: Dict[str, Any]) -> str:
    pat = re.compile(r'\\STEXexport\s*\{')
    while True:
        m = pat.search(text)
        if not m:
            break
        depth = 0
        end = None
        for k in range(m.end() - 1, len(text)):
            c = text[k]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
        if end is None:
            break  # unbalanced braces; leave it for manual review
        # also swallow trailing spaces and one newline so we don't leave a blank line
        while end < len(text) and text[end] in ' \t':
            end += 1
        if end < len(text) and text[end] == '\n':
            end += 1
        text = text[:m.start()] + text[end:]
        report["actions"].append("Removed \\STEXexport block")
    return text

# Remove lines that declare English-only module material (imports, symbol declarations, etc.)
# args:
#     text: The original text.
#     report: The report dictionary to update.
# returns:
#     The text with the lines removed.
def _remove_line_patterns(text: str, report: Dict[str, Any]) -> str:
    text = _remove_stexexport(text, report)

    for macro in _LINE_MACROS:
        # match a full line (optionally indented) whose first macro is \<macro>
        text, n = re.subn(r'^[ \t]*\\' + macro + r'\b.*(?:\r?\n)?', '', text, flags=re.MULTILINE)
        if n:
            report["actions"].append(f"Removed {n} \\{macro} line(s)")

    return text

# replace \extstructure with \usestructure and remove the closing \end{extstructure}
# args:
#     match: The regex match object for the \extstructure command.
# returns:
#     The replacement string for the \usestructure command.
def _replace_extstructure(match: re.Match) -> str:
    ext_id = match.group('id').strip()
    return f"\\usestructure{{{ext_id}}}\n"

# Fix smodule options, ensuring that the title is included and that the sig option is set to "en" if not already present. 
# Add a placeholder for translation if desired.
# args:
#     match: The regex match object for the \begin{smodule} command.
#     parsed: The parsed module information.
#     lang: The target language code.
#     opts: The translation options.
#     title_fill: The resolved translation of the title, or None to use a placeholder.
# returns:
#     The modified \begin{smodule} command.
def _fix_smodule_opts(match: re.Match, parsed: Dict[str, Any], lang: str, opts: Dict[str, Any],
                      title_fill: str = None) -> str:
    opts_str = match.group('opts') or ''
    mod_id = parsed["module_id"] or match.group('id')
    # strip any existing title, whether braced (title={...}) or unbraced (title=Foo Bar)
    opts_clean = re.sub(r',?\s*title\s*=\s*(?:\{[^}]*\}|[^,\]]+)', '', opts_str)

    if 'sig=' not in opts_clean:
        opts_clean = f"sig=en{(',' + opts_clean) if opts_clean.strip() else ''}"

    if parsed.get('title'):
        title_val = parsed['title']
        if title_fill:
            title_placeholder = title_fill
        else:
            title_placeholder = f"<<TRANSLATE[{lang}]: {title_val}>>" if opts.get("insert_placeholders", True) else title_val
        if 'title=' in opts_clean:
            opts_clean = re.sub(r'title\s*=\s*\{[^}]*\}', f'title={{{title_placeholder}}}', opts_clean)
        else:
            opts_clean = f"{opts_clean},title={{{title_placeholder}}}"

    return f"\\begin{{smodule}}[{opts_clean}]{{{mod_id}}}"

# Ensure the document class includes the language option
# args:
#     text: The original text.
#     lang: The target language code.
# returns:
#     The text with the document class modified to include the language option.
def _ensure_documentclass_lang(text: str, lang: str) -> str:
    text = re.sub(
        r'\\documentclass\[(?P<opts>[^\]]*)\]\{stex\}',
        lambda m: f"\\documentclass[lang={lang}]{{stex}}" if 'lang=' not in m.group('opts') else m.group(0),
        text,
    )
    if '\\documentclass{stex}' in text:
        text = text.replace('\\documentclass{stex}', f'\\documentclass[lang={lang}]{{stex}}')
    return text

# Rewrite paths for cmhtikz images based on the target language
# args:
#     text: The original text.
#     cmhtikz_list: The list of cmhtikz image paths.
#     lang: The target language code.
# returns:
#     The text with the paths updated for the target language.
def _rewrite_cmhtikz(text: str, cmhtikz_list: List[str], lang: str) -> str:
    for path in cmhtikz_list:
        if re.search(r'\.(en|eng|english)(?:\.tex)?$', path):
            base = re.sub(r'\.(en|eng|english)(?:\.tex)?$', '', path)
            target_path = f"{base}.{lang}"
            text = text.replace(path, target_path)
    return text

# Tidy up whitespace left behind after removing English-only lines: collapse runs of
# blank lines and drop a blank line immediately after the module/structure openings.
# args:
#     text: The original text.
# returns:
#     The text with blank lines tidied up.
def _tidy_blank_lines(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'(\\begin\{smodule\}[^\n]*\n)\n+', r'\1', text)
    text = re.sub(r'(\\usestructure\{[^}]*\}[^\n]*\n)\n+', r'\1', text)
    return text

# Add a review comment to the top of the document indicating that it is a translation template and that placeholders should be verified
# args:
#     text: The original text.
#     lang: The target language code.
#     report: The report dictionary to update.
# returns:
#     The text with the review comment added.
def _add_review_comment(text: str, lang: str, report: Dict[str, Any]) -> str:
    header_comment = f"% TRANSLATION TEMPLATE for lang={lang}\n% REVIEW: verify placeholders and math tokens; semantic IDs must remain unchanged\n"
    report["actions"].append("Added header review comment")
    return header_comment + text

# Build a translation template from the original text, replacing items with placeholders for translation and generating a report of the actions taken
# Returns the modified text and a report dictionary containing the module ID, target language, items processed, and actions taken.
# This is were the main processing of the translation template occurs, including extracting items, replacing them with placeholders, and cleaning up the text.
# args:
#     original_text: The original English text to be translated.
#     lang: The target language code.
#     opts: A dictionary of options for translation, including whether to insert placeholders and add review comments.
#     fills: An optional dictionary mapping spans to their filled translations.
# returns:
#     A tuple containing the modified text and a report dictionary.
def build_template(original_text: str, lang: str, opts: Dict[str, Any],
                   fills: Dict[Tuple[int, int], str] = None) -> Tuple[str, Dict[str, Any]]:
    parsed = extract_items(original_text)
    report: Dict[str, Any] = {"module_id": parsed.get("module_id"), "lang": lang, "items": [], "actions": []}

    # a fills entry keyed "title" (not a span) carries the resolved title translation
    title_fill = fills.get("title") if fills else None

    working_text = _process_items(original_text, parsed.get("items", []), lang, opts, report, fills)
    working_text = _remove_line_patterns(working_text, report)

    working_text = re.sub(
        r'\\begin\{extstructure\}\{(?P<id>[^}]+)\}(?:\[[^\]]*\])?\{[^}]+\}',
        _replace_extstructure,
        working_text,
    )
    report["actions"].append("Converted \\extstructure to \\usestructure")
    working_text = re.sub(r'\\end\{extstructure\}\s*\n', '', working_text)

    # \begin{mathstructure}{id}[title] ... \end{mathstructure} becomes a plain
    # \usestructure{id} reference in the translated module.
    working_text, n_math = re.subn(
        r'\\begin\{mathstructure\}\s*\{(?P<id>[^}]+)\}(?:\[[^\]]*\])?[ \t]*\r?\n?',
        lambda m: f"\\usestructure{{{m.group('id').strip()}}}\n",
        working_text,
    )
    if n_math:
        report["actions"].append("Converted \\mathstructure to \\usestructure")
        working_text = re.sub(r'\\end\{mathstructure\}\s*\n', '', working_text)

    working_text = _ensure_documentclass_lang(working_text, lang)

    if parsed.get("module_id"):
        working_text = re.sub(
            r'\\begin\{smodule\}\s*(?:\[(?P<opts>[^\]]*)\])?\s*\{(?P<id>' + re.escape(parsed.get("module_id")) + r')\}',
            functools.partial(_fix_smodule_opts, parsed=parsed, lang=lang, opts=opts, title_fill=title_fill),
            working_text,
        )

    working_text = _rewrite_cmhtikz(working_text, parsed.get("cmhtikz", []), lang)
    working_text = _tidy_blank_lines(working_text)

    if opts.get("add_review_comments", True):
        working_text = _add_review_comment(working_text, lang, report)

    return working_text, report
