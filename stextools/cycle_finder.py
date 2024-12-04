import itertools
from pathlib import Path

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.utils.ui import print_highlight_selection


class CycleFound(Exception):
    def __init__(self, cycle: list[int]):
        self.cycle = cycle


def cycle_finder(file: str):
    mh = Cache.get_mathhub(update_all=True)
    linker = Linker(mh)

    graph = linker.file_import_graph

    covered: set[int] = set()

    def dfs(i: int, stack: list[int]):
        if i in stack:
            raise CycleFound(stack + [i])
        stack.append(i)
        for child in graph[i]:
            if child not in covered:
                dfs(child, stack)
                covered.add(child)
        stack.pop()

    start = linker.document_ints.intify(mh.get_stex_doc(Path(file)))

    try:
        dfs(start, [])
    except CycleFound as e:
        print(click.style('I found the following cycle:', bg='bright_cyan'))
        for i, j in itertools.pairwise(e.cycle):
            doc = linker.document_ints.unintify(i)
            print(click.style(doc.path, bold=True))
            for dep in doc.get_doc_info(mh).flattened_dependencies():
                if dep.is_use:
                    continue
                target_doc = dep.get_target(mh, doc)[0]
                if target_doc is None:
                    continue
                if linker.document_ints.intify(target_doc) == j:
                    print_highlight_selection(
                        doc.path.read_text(), dep.intro_range[0], dep.intro_range[1], 1, bold=False
                    )
                    break

        doc = linker.document_ints.unintify(e.cycle[-1])
        print(click.style(doc.path, bold=True))
    else:
        print('No cycle found.')
