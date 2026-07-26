"""
FLAMS-based translation fill for `stextools trans`.

Resolves each translatable macro in an sTeX source to its symbol URI (via FLAMS, the
same machinery snify uses) and looks up a target-language verbalization for it, so the
generated template can be auto-filled with real translations where the domain model
(SMGloM) already has them.
"""
import contextlib
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import OpenedStexFLAMSFile
from stextools.snify.text_anno.local_stex_catalog import (
    local_flams_stex_catalogs,
    _verb_and_symb_extraction,
)

from .extractor import extract_items

os.environ.setdefault("RUST_LOG", "error")


@contextlib.contextmanager
def _silence_native_output():
    """Silence native (Rust/FLAMS) stdout+stderr. STEX_TRANS_VERBOSE=1 keeps it visible.

    Skipped on Windows: redirecting the console file descriptors there can invalidate the
    console handle that click/colorama use afterwards (OSError: Windows error 6). The FLAMS
    log noise is cosmetic, so we simply leave it visible on Windows.
    """
    if os.environ.get("STEX_TRANS_VERBOSE") or sys.platform == "win32":
        yield
        return
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(devnull)
        os.close(saved_out)
        os.close(saved_err)


def _flams_annotations(path: str) -> List[Tuple[int, int, str]]:
    """[(start, end, uri), ...] for each \\sn/\\sr/\\definame/\\definiendum occurrence.
    args:
        path: Path to the sTeX file.
    returns:
        A list of tuples, each containing the start index, end index, and symbol URI for
        each translatable macro occurrence in the sTeX file.
    """
    annos = FLAMS.get_file_annotations(path)
    opened = OpenedStexFLAMSFile(path)
    out = []
    for e in _verb_and_symb_extraction(annos, opened):
        if isinstance(e, tuple):
            _lang, uri, _symb_path, _verb, start, end = e
            out.append((start, end, uri))
    return out


def _verb_index(lang: str) -> Optional[Dict[str, List[str]]]:
    """uri -> [verbalization, ...] ranked by frequency, or None if the lang has no catalog.
    args:
        lang: The target language code (e.g., 'de', 'fr').
    returns:
        A dictionary mapping symbol URIs to a list of verbalizations in the target language."""
    cat = local_flams_stex_catalogs().get(lang)
    if cat is None:
        return None
    index: Dict[str, List[str]] = {}
    for symbol in cat.symb_iter():
        counts: Counter = Counter()
        for v in cat.symb_to_verb.get(symbol, []):
            nv = re.sub(r"\s+", " ", v.verb).strip()
            if nv:
                counts[nv] += 1
        index[symbol.uri] = [w for w, _ in counts.most_common()]
    return index


_LOOKS_PLURAL = re.compile(r"(en|e|s)$", re.IGNORECASE)


def _is_plural_looking(word: str) -> bool:
    """Check if a word looks like it might be plural.
    args:
        word: The word to check.
    returns:
        True if the word looks plural, False otherwise. A word is considered plural if it ends 
        with "en", "e", or "s" and is longer than 3 characters."""
    return bool(_LOOKS_PLURAL.search(word)) and len(word) > 3


def rank_candidates(verbs: List[str], want_plural: bool) -> List[str]:
    """Verbalizations best-first. For plural (\\sns) items, prefer a plural form.
    args:
        verbs: A list of candidate verbalizations for a symbol.
        want_plural: A boolean indicating whether a plural form is desired.
    returns:
        A list of verbalizations ranked by preference, with the most preferred first.
        If a plural form is desired, the function will prioritize plural-looking forms. 
        If no plural forms are found, it will return the original list of verbs."""
    if not want_plural or not verbs:
        return list(verbs)
    base = verbs[0]
    if _is_plural_looking(base):
        return list(verbs)
    supers = sorted((v for v in verbs[1:]
                     if v.lower().startswith(base.lower()) and len(v) > len(base)), key=len)
    if supers:
        chosen = supers[0]
        return [chosen] + [v for v in verbs if v != chosen]
    en = [v for v in verbs if v.lower().endswith("en")]
    if en:
        return en[:1] + [v for v in verbs if v != en[0]]
    return list(verbs)


def _uri_for_item(item: Dict, annos: List[Tuple[int, int, str]]) -> Optional[str]:
    """The FLAMS annotation whose range sits inside this item's span (tightest wins).
    args:
        item: A dictionary containing the metadata of the symbol, including its span.
        annos: A list of tuples, each containing the start index, end index, and symbol URI for
               each translatable macro occurrence in the sTeX file.
    returns:
        The symbol URI corresponding to the item, or None if no matching annotation is found."""
    s, e = item["span"]
    best = None
    for (a, b, uri) in annos:
        if s <= a and b <= e and (best is None or (b - a) < (best[1] - best[0])):
            best = (a, b, uri)
    return best[2] if best else None


_BUILD_INDEX = object()   # sentinel: build the verbalization index on demand


def build_index(lang: str):
    """Build the target-language verbalization index once, so it can be reused across many
    files in a batch run (building the catalog is the expensive part). Pass the result as
    the `index` argument of compute_fills().
    args:
        lang: the target language code.
    returns:
        uri -> [verbalization, ...] dict, or None if the language has no catalog.
    """
    with _silence_native_output():
        return _verb_index(lang)


def compute_fills(text: str, path: str, lang: str, select=None, index=_BUILD_INDEX,
                  chosen_by_uri=None, ask_new_definienda=False) -> Tuple[Dict[Tuple[int, int], str], Dict]:
    """Resolve + fill placeholders with target-language verbalizations.

    `select(item, candidates, context, default) -> chosen | None` is called only when a
    symbol has more than one candidate; None keeps the placeholder. When select is None
    (or a single candidate), the top-ranked candidate is taken automatically. Choices are
    remembered per symbol URI so repeated symbols get consistent translations.

    args:
        text: The content of the sTeX file as a string.
        path: The path to the sTeX file.
        lang: The target language code.
        select: A function to select a candidate verbalization, or None.
        index: prebuilt uri -> [verbalizations] to reuse (built on demand otherwise).
        chosen_by_uri: a dict of already-chosen translations per symbol URI to reuse and
            extend. Pass a shared dict across files for run-wide consistency; the same dict
            is updated in place with this file's choices.
    returns:
        A tuple containing:
        - A dictionary mapping (start, end) spans in the text to the chosen verbalization.
        - A statistics dictionary with counts of filled, kept placeholders, no verbalization,
          unresolved symbols, whether the catalog language is available, the `todo` list, and
          `new_verbs` (list of (uri, translation) for defined terms translated here — used to
          feed the index forward during closure translation).
    """
    parsed = extract_items(text)
    items = parsed["items"]
    with _silence_native_output():
        annos = _flams_annotations(path)
        if index is _BUILD_INDEX:
            index = _verb_index(lang)

    stats = {"filled": 0, "kept_placeholder": 0, "no_verbalization": 0, "unresolved": 0,
             "catalog_language_available": index is not None, "todo": [], "new_verbs": []}
    if index is None:
        index = {}
    if chosen_by_uri is None:
        chosen_by_uri = {}

    def _todo(item, reason):
        stats["todo"].append({"key": item["key"], "surface": item["text"], "reason": reason})

    fills: Dict[Tuple[int, int], str] = {}
    title_by_key: Dict[str, str] = {}   # defined-term key -> its chosen translation (for the title)
    for item in sorted(items, key=lambda it: it["span"][0]):
        uri = _uri_for_item(item, annos)
        if not uri:
            stats["unresolved"] += 1
            _todo(item, "unresolved")
            continue
        cands = rank_candidates(index.get(uri, []), item.get("plural"))
        if not cands:
            # a defined term with no existing translation: let the author supply one so it
            # can be filled here and fed forward to later modules in a closure run
            if ask_new_definienda and select is not None and item["type"] in ("definame", "definiendum"):
                s, e = item["span"]
                before = re.sub(r"\s+", " ", text[max(0, s - 50):s]).lstrip()
                target = re.sub(r"\s+", " ", text[s:e])
                after = re.sub(r"\s+", " ", text[e:e + 30]).rstrip()
                choice = select(item, [], (before, target, after), None)
                if choice:
                    chosen_by_uri[uri] = choice
                    fills[tuple(item["span"])] = choice
                    stats["filled"] += 1
                    stats["new_verbs"].append((uri, choice))
                    title_by_key.setdefault(item["key"].strip().lower(), choice)
                    continue
            stats["no_verbalization"] += 1
            _todo(item, "no-verbalization")
            continue
        default = chosen_by_uri.get(uri, cands[0])
        ordered = [default] + [c for c in cands if c != default]

        if select is None or len(cands) == 1:
            choice = default
        else:
            s, e = item["span"]
            # context split around the term so the selector can highlight it
            before = re.sub(r"\s+", " ", text[max(0, s - 50):s]).lstrip()
            target = re.sub(r"\s+", " ", text[s:e])
            after = re.sub(r"\s+", " ", text[e:e + 30]).rstrip()
            choice = select(item, ordered, (before, target, after), default)

        if choice is None:
            stats["kept_placeholder"] += 1
            _todo(item, "kept")
            continue
        chosen_by_uri[uri] = choice
        fills[tuple(item["span"])] = choice
        stats["filled"] += 1
        if item["type"] in ("definame", "definiendum"):
            title_by_key.setdefault(item["key"].strip().lower(), choice)
            stats["new_verbs"].append((uri, choice))   # a new target-language verbalization

    # The module title verbalizes its primary defined term: reuse that term's translation.
    title = (parsed.get("title") or "").strip().lower()
    if title and title in title_by_key:
        t = title_by_key[title]
        fills["title"] = t[:1].upper() + t[1:]   # titles are capitalized
    return fills, stats
