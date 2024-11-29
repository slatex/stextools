from pathlib import Path

from stextools.core.cache import Cache
from stextools.core.linker import Linker


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
                covered.add(child)
                dfs(child, stack + [i])
        stack.pop()

    start = linker.document_ints.intify(mh.get_stex_doc(Path(file)))

    try:
        dfs(start, [])
    except CycleFound as e:
        print('I found the following cycle:')
        for i in e.cycle:
            print(linker.document_ints.unintify(i).path)
    else:
        print('No cycle found.')
