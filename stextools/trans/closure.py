"""
Reference-driven translation closure.

Given seed document(s), find the local English modules that must be translated so that
every symbol referenced (transitively) has a target-language verbalization, and order them
so that a symbol's definition is translated *before* anything that references it
(topological order). Translating in this order lets each new verbalization feed forward and
improves the suggestions for later ``\\sr``s.

This module is read-only: it only computes the ordered work-list and a report; it does not
translate or write anything.
"""
import os
import re
from collections import deque
from typing import Callable, Dict, List, Optional, Set, Tuple

from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import OpenedStexFLAMSFile
from stextools.snify.text_anno.local_stex_catalog import _verb_and_symb_extraction

from .fill import _silence_native_output


def _archive_of(uri: str) -> Optional[str]:
    m = re.search(r'[?&]a=([^&]+)', uri)
    return m.group(1) if m else None


def references(path: str) -> List[Tuple[str, str]]:
    """[(symbol uri, defining .en.tex path), ...] for every symbol referenced/used in `path`.

    FLAMS resolves each occurrence to a symbol and reports the file in which that symbol is
    defined, so we can follow references to their definitions (across archives).
    """
    annos = FLAMS.get_file_annotations(path)
    opened = OpenedStexFLAMSFile(path)
    out = []
    for e in _verb_and_symb_extraction(annos, opened):
        if isinstance(e, tuple):
            _lang, uri, symb_path, _verb, _s, _en = e
            out.append((uri, symb_path))
    return out


def _topo_order(deps: Dict[str, Set[str]]) -> List[str]:
    """Order `deps` keys so that every dependency precedes its dependents (cycle-tolerant)."""
    state: Dict[str, int] = {}   # 0/absent = unvisited, 1 = on stack, 2 = done
    order: List[str] = []

    def visit(n: str):
        """DFS post-order visit: emit `n` after its dependencies; skip nodes already done or on
        the current stack (the latter breaks dependency cycles)."""
        if state.get(n, 0) != 0:
            return                     # done, or on the stack (cycle) -> stop
        state[n] = 1
        for d in deps.get(n, ()):      # visit dependencies first
            visit(d)
        state[n] = 2
        order.append(n)

    for n in deps:
        visit(n)
    return [n for n in order if n in deps]


def reference_closure(
        seeds: List[str],
        index: Dict[str, list],
        scope: Optional[Callable[[Optional[str]], bool]] = None,
        translate_seeds: bool = False,
        max_depth: Optional[int] = None,
        max_modules: int = 500,
) -> Tuple[List[str], dict]:
    """Compute the ordered English modules to translate to cover the seeds' references.

    Args:
        seeds: seed document paths whose references drive the closure.
        index: uri -> [target-language verbalizations]; a symbol is already covered when
            its entry is non-empty.
        scope: optional predicate on a symbol's archive; return False to exclude it (and its
            defining module) from the closure. None keeps everything.
        translate_seeds: if True the seed files are themselves part of the closure (translate
            the file + its dependencies); if False only the referenced definitions are.
        max_depth: how far to follow references from the seeds. 1 = only the directly
            referenced definitions; None = the full transitive closure (can be very large).
        max_modules: safety bound on how many modules the closure may grow to.
    Returns:
        (ordered_modules, report). `ordered_modules` lists defining .en.tex paths, definitions
        before uses. `report` has counts and the reasons things were skipped.
    """
    covered = lambda uri: bool(index.get(uri))
    seeds = [os.path.abspath(s) for s in seeds]
    seed_set = set(seeds)

    deps: Dict[str, Set[str]] = {}          # module -> defining modules it depends on (in closure)
    external: Set[str] = set()              # referenced symbols with no local source
    out_of_scope: Set[str] = set()
    visited: Set[str] = set()
    depth_of: Dict[str, int] = {s: 0 for s in seeds}
    capped = False

    todo = deque((s, 0) for s in seeds)     # BFS so depth is the shortest-path depth
    while todo:
        f, d = todo.popleft()
        if f in visited:
            continue
        if len(visited) >= max_modules:
            capped = True
            break
        visited.add(f)
        f_deps: Set[str] = set()
        # only follow references while we still have depth budget
        if max_depth is None or d < max_depth:
            with _silence_native_output():
                refs = references(f)
            for uri, dpath in refs:
                if covered(uri):
                    continue                # already translated -> reuse, don't recurse
                if scope is not None and not scope(_archive_of(uri)):
                    out_of_scope.add(uri)
                    continue
                if not dpath or not os.path.exists(dpath):
                    external.add(uri)       # referenced but no local .en source
                    continue
                dpath = os.path.abspath(dpath)
                if dpath in seed_set and not translate_seeds:
                    continue
                f_deps.add(dpath)
                if dpath not in depth_of:
                    depth_of[dpath] = d + 1
                    todo.append((dpath, d + 1))
        deps[f] = f_deps

    # the modules we actually translate: everything visited, minus the seeds unless requested
    if not translate_seeds:
        for s in seeds:
            deps.pop(s, None)
            for v in deps.values():
                v.discard(s)

    def _archive_from_path(p: str) -> str:
        parts = p.replace("\\", "/").split("/source/")[0].split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else "?"

    order = _topo_order(deps)
    by_archive: Dict[str, int] = {}
    for m in order:
        a = _archive_from_path(m)
        by_archive[a] = by_archive.get(a, 0) + 1

    report = {
        "seeds": len(seeds),
        "modules_to_translate": len(order),
        "external_symbols": len(external),      # referenced, no local source (cannot translate)
        "out_of_scope_symbols": len(out_of_scope),
        "capped": capped,
        "by_archive": by_archive,
    }
    return order, report
