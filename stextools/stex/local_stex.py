"""
Code for working with local sTeX archives.

This is mostly generic code, more specific code is in separate modules (for example for the catalogs).
"""
from collections import deque
from functools import cached_property
from pathlib import Path
from typing import Optional, Iterable

from stextools.stex.flams import FLAMS
from stextools.utils.json_iter import json_iter


class FlamsUri:
    root: str
    archive: str = ''
    path: str = ''
    module: str = ''
    symbol: str = ''

    def __init__(self, uri: str):
        if not isinstance(uri, str):
            raise TypeError(f'Expected a string, got {type(uri)}')
        parts = uri.split("?")
        self.root = parts[0]
        if len(parts) == 1:
            return
        assert len(parts) == 2, f'Unexpected FLAMS URI: {uri}'
        args = parts[1].split('&')
        for arg in args:
            key, value = arg.split('=')
            if key == 'a':
                self.archive = value
            elif key == 'p':
                self.path = value
            elif key == 'm':
                self.module = value
            elif key == 's':
                self.symbol = value
            else:
                raise ValueError(f'Unexpected FLAMS URI argument: {key}={value}')

    def __str__(self):
        parts = []
        if self.archive:
            parts.append(f'a={self.archive}')
        if self.path:
            parts.append(f'p={self.path}')
        if self.module:
            parts.append(f'm={self.module}')
        if self.symbol:
            parts.append(f's={self.symbol}')
        return '?'.join([self.root, '&'.join(parts)])

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __repr__(self):
        return f'FlamsUri({str(self)!r})'




class OpenedStexFLAMSFile:
    def __init__(self, path: str):
        self.path = path

    @cached_property
    def text(self) -> str:
        with open(self.path, 'r', encoding='utf-8') as f:
            return f.read()

    @cached_property
    def _linecharcount(self) -> list[int]:
        """ returns a list l where l[i] is the number of characters until the beginning of line i
            In FLAMS, lines are apparently 0-indexed.
        """
        result: list[int] = [0]
        value = 0
        for line in self.text.splitlines(keepends=True):
            value += len(line)
            result.append(value)
        return result

    def line_col_to_offset(self, line: int, col: int) -> int:
        lc = self._linecharcount
        return lc[line] + col

    def flams_range_to_offsets(self, flams_range) -> tuple[int, int]:
        lc = self._linecharcount
        start = lc[flams_range['start']['line']] + flams_range['start']['col']
        end = lc[flams_range['end']['line']] + flams_range['end']['col']
        return start, end


def lang_from_path(path: str | Path) -> str:
    if isinstance(path, Path):
        segments = path.name.split('.')
    else:
        segments = path.split('/')[-1].split('.')
    lang = 'en'   # default
    if len(segments) > 2 and len(segments[-2]) < 4:
        lang = segments[-2]
    return lang


def _find_module(annotations, uri: str) -> Optional[dict]:
    if isinstance(annotations, dict):
        for k, v in annotations.items():
            if k == 'Module' and v['uri'] == uri:
                return v
            elif k in {'ImportModule', 'UseModule', 'Symdef', 'Symref', 'SymName', 'Notation', 'SemanticMacro'}:
                continue
            else:
                return _find_module(v, uri)
    elif isinstance(annotations, list):
        for item in annotations:
            result = _find_module(item, uri)
            if result is not None:
                return result
    return None

def _find_imports(module_annotation) -> Iterable[tuple[str, str]]:
    if isinstance(module_annotation, dict):
        for k, v in module_annotation.items():
            if k == 'ImportModule':
                yield v['module']['uri'], v['module']['full_path']
            elif k in {'UseModule', 'Symdef', 'Symref', 'SymName', 'Notation', 'SemanticMacro'}:
                continue
            else:
                yield from _find_imports(v)
    elif isinstance(module_annotation, list):
        for item in module_annotation:
            result = _find_imports(item)
            if result is not None:
                yield from result


def get_transitive_structs(structures: list[tuple[str, str]]) -> dict[str, str]:
    """
    given a list of (structure_uri, structure_path) pairs,
    return a dictionary mapping structure URIs to their paths those structures and the ones they import transitively
    (usemodules not included)
    """
    result: dict[str, str] = { uri: path for uri, path in structures }

    def search(uri: str, path: str):
        annos = FLAMS.get_file_annotations(path)

        for j in json_iter(annos):
            if isinstance(j, dict) and 'MathStructure' in j:
                s = j['MathStructure']
                if s['uri']['uri'] == uri:
                    for ext0 in s.get('extends', []):
                        for ext1 in ext0:
                            if 'uri' in ext1 and ext1['uri'] not in result:
                                result[ext1['uri']] = ext1['filepath']
                                search(ext1['uri'], ext1['filepath'])

    for uri, path in structures:
        search(uri, path)

    return result


def get_transitive_imports(modules: list[tuple[str, str]]) -> dict[str, str]:
    """
    given a list of (module_uri, module_path) pairs,
    return a dictionary mapping module URIs to their paths those modules and the ones they import transitively
    (usemodules not included)
    """
    result: dict[str, str] = { uri: path for uri, path in modules }

    def search(uri: str, path: str):
        annos = FLAMS.get_file_annotations(path)

        module = _find_module(annos, uri)
        if module is None:
            return
        for import_uri, import_path in _find_imports(module):
            if import_uri not in result:
                result[import_uri] = import_path
                search(import_uri, import_path)

    for uri, path in modules:
        search(uri, path)

    return result


def get_module_import_sequence(available_modules: list[tuple[str, str]], target_module: str) -> Optional[list[tuple[str, str]]]:
    """
    if available_modules are (module_uri, module_path) pairs that are currently available,
    it returns None if target_module is not transitively available from them,
    and otherwise an import sequence (list of (module_uri, module_path) pairs) that leads to target_module
    """
    covered_modules: dict[str, str] = { uri: path for uri, path in available_modules }
    predecessors: dict[str, str] = {}
    to_process: deque[tuple[str, str]] = deque(available_modules)

    # bfs to find shortest import path
    while to_process:
        uri, path = to_process.popleft()
        if uri == target_module:
            # reconstruct path
            result: list[tuple[str, str]] = [(uri, path)]
            while uri in predecessors:
                uri = predecessors[uri]
                path = covered_modules[uri]
                result.append((uri, path))
            result.reverse()
            return result

        annos = FLAMS.get_file_annotations(path)

        module = _find_module(annos, uri)
        if module is None:
            continue
        for import_uri, import_path in _find_imports(module):
            if import_uri not in covered_modules:
                covered_modules[import_uri] = import_path
                predecessors[import_uri] = uri
                to_process.append((import_uri, import_path))

