from __future__ import annotations

import dataclasses
from collections import deque
from collections.abc import Iterable, Generator
import itertools
from pathlib import Path
from typing import Optional

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.mathhub import Repository
from stextools.core.stexdoc import Symbol, Verbalization, STeXDocument, ModuleInfo


class SimpleSymbol:
    _symbol: Symbol
    _symbol_int: int
    _linker: Linker

    def __init__(self, symbol_int: int, linker: Linker):
        self._symbol = linker.symbol_ints.unintify(symbol_int)[1]
        self._symbol_int = symbol_int
        self._linker = linker

    def get_verbalizations(self, lang: Optional[str] = None) -> Generator['SimpleVerbalization']:
        for verb_int in self._linker.symb_to_verbs[self._symbol_int]:
            doc_int, verb = self._linker.verb_ints.unintify(verb_int)
            if lang is not None and verb.lang != lang:
                continue
            yield SimpleVerbalization(verb_int, self._linker)

    @property
    def path_rel_to_archive(self) -> str:
        return self.declaring_module.path_rel_to_archive + '?' + self._symbol.name

    @property
    def name(self) -> str:
        return self._symbol.name

    @property
    def declaring_file(self) -> 'SimpleFile':
        return self.declaring_module.file

    @property
    def macro_range(self) -> tuple[int, int]:
        return self._symbol.decl_def

    @property
    def declaring_module(self) -> 'SimpleModule':
        module = self._linker.symbol_to_module[self._symbol_int]
        return SimpleModule(module, self._linker)

    def __eq__(self, other) -> bool:
        return (isinstance(other, SimpleSymbol) and
                self._symbol_int == other._symbol_int and
                self._linker is other._linker)

    def __hash__(self) -> int:
        return hash((self._symbol_int, self._linker))


class SimpleModule:
    _module: ModuleInfo
    _module_int: int
    _linker: Linker

    def __init__(self, module_int: int, linker: Linker):
        doc, modstr = linker.module_ints.unintify(module_int)
        module = linker.document_ints.unintify(doc).get_doc_info(linker.mh).get_module(modstr)
        assert module is not None
        self._module = module
        self._module_int = module_int
        self._linker = linker

    @property
    def is_structure(self) -> bool:
        return self._module.is_structure

    @property
    def struct_name(self) -> Optional[str]:
        return self._module.struct_name

    def get_structures_containing_module(self) -> Optional['SimpleModule']:
        if self._module_int not in self._linker.structure_info:
            return None
        return SimpleModule(self._linker.structure_info[self._module_int][1], self._linker)

    @property
    def path_rel_to_archive(self) -> str:
        file_path = self.file.get_relative_path(drop_tex_extension=True, drop_lang_tag=True)
        module_path = self.path_in_doc

        # file name can be omitted if it's the same as the module name
        left, _, right = file_path.rpartition('/')
        if right == module_path.split('/')[0]:
            file_path = left

        return f'{file_path}?{module_path}'

    @property
    def file(self) -> 'SimpleFile':
        return SimpleFile(self._linker.module_to_file[self._module_int], self._linker)

    @property
    def path_in_doc(self) -> str:
        return self._module.name

    def imports_module(self, module: 'SimpleModule', reflexive: bool) -> bool:
        if reflexive and module == self:
            return True
        return module._module_int in self._linker.transitive_imports[self._module_int]

    def __eq__(self, other) -> bool:
        return (isinstance(other, SimpleModule) and
                self._module_int == other._module_int and
                self._linker is other._linker)

    def __hash__(self) -> int:
        return hash((self._module_int, self._linker))


class SimpleFile:
    _stex_doc: STeXDocument
    _doc_int: int
    _linker: Linker

    def __init__(self, doc_int: int, linker: Linker):
        self._stex_doc = linker.document_ints.unintify(doc_int)
        self._doc_int = doc_int
        self._linker = linker

    def get_relative_path(
            self, drop_toplevel_dir: bool = True, drop_tex_extension: bool = False, drop_lang_tag: bool = False
    ) -> str:
        if drop_lang_tag and not drop_tex_extension:
            raise ValueError('drop_lang_tag requires drop_tex_extension to be True')
        p = self._stex_doc.get_rel_path()
        if drop_tex_extension and p.endswith('.tex'):
            p = p[:-4]
        if drop_lang_tag and '.' in p:
            new_p, _, lang_tag = p.rpartition('.')
            if '/' not in lang_tag:   # crude check...
                p = new_p

        if drop_toplevel_dir:
            p = p.partition('/')[2]

        return p

    def iter_verbalizations(self) -> Generator['SimpleVerbalization']:
        for verb in self._stex_doc.get_doc_info(self._linker.mh).verbalizations:
            yield SimpleVerbalization(self._linker.verb_ints.intify((self._doc_int, verb)), self._linker)

    def symbol_is_in_scope_at(self, symbol: SimpleSymbol, offset: int) -> bool:
        required_module = symbol.declaring_module._module_int
        for mod, start, end in self._linker.available_module_ranges[self._doc_int]:
            if start <= offset < end and required_module in self._linker.transitive_imports[mod]:
                return True
        return False

    def explain_symbol_in_scope_at(
            self, symbol: SimpleSymbol, offset: int
    ) -> Optional[list[tuple[SimpleFile, tuple[int, int]]]]:
        required_module = symbol.declaring_module._module_int
        mh = self._linker.mh

        def dep_to_mod(doc, dep):
            target_doc, target_mod = dep.get_target(self._linker.mh, doc)
            if target_doc is None or target_mod is None:
                return None
            return self._linker.module_ints.intify((self._linker.document_ints.intify(target_doc), target_mod.name))

        for mod, start, end in self._linker.available_module_ranges[self._doc_int]:
            if start <= offset < end and required_module in self._linker.transitive_imports[mod]:
                # bfs to find shortest path
                # queu lists path (is this sufficiently memory efficient - or do we need predecessor graph?)
                queue = deque([[mod]])
                visited = {mod}
                while queue:
                    path = queue.popleft()
                    if path[-1] != required_module:
                        for child in self._linker.module_import_graph[path[-1]]:
                            if child not in visited:
                                visited.add(child)
                                queue.append(path + [child])
                        continue

                    # found a path
                    result: list[tuple[SimpleFile, tuple[int, int]]] = []
                    for dep in self._stex_doc.get_doc_info(mh).flattened_dependencies():
                        if dep.scope[0] > offset or dep.scope[1] <= offset:
                            continue
                        assert dep.intro_range
                        result.append((self, dep.intro_range))
                        break

                    if not result:
                        raise RuntimeError('I failed to find the first step of the import path - this is a bug')

                    for i, j in itertools.pairwise(path):
                        doc_int, module_name = self._linker.module_ints.unintify(i)
                        doc = self._linker.document_ints.unintify(doc_int)
                        module_info = doc.get_doc_info(mh).get_module(module_name)
                        if module_info is None:
                            continue
                        for dep in doc.get_doc_info(mh).flattened_dependencies():
                            if dep.is_use:
                                continue
                            if dep_to_mod(doc, dep) == j:
                                assert dep.intro_range
                                if dep.intro_range[0] < module_info.valid_range[0] or \
                                        dep.intro_range[1] > module_info.valid_range[1]:
                                    continue
                                result.append((SimpleFile(doc_int, self._linker), dep.intro_range))
                                break
                    return result

                raise RuntimeError('I failed to find the import path - this is a bug')
        return None   # symbol not in scope

    def get_compilation_dependencies(self) -> Generator['SimpleFile']:
        for dep_int in self._linker.file_import_graph[self._doc_int]:
            yield SimpleFile(dep_int, self._linker)

    @property
    def archive(self) -> 'SimpleArchive':
        return SimpleArchive(self._stex_doc.archive, self._linker)

    @property
    def path(self) -> Path:
        return self._stex_doc.path

    @property
    def lang(self) -> str:
        return self._stex_doc.get_doc_info(self._linker.mh).lang

    @property
    def declared_symbols(self) -> Generator[SimpleSymbol]:
        for module_int in self._linker.file_to_module[self._doc_int]:
            for symbol_int in self._linker.module_to_symbs[module_int]:
                yield SimpleSymbol(symbol_int, self._linker)

    def __eq__(self, other) -> bool:
        return (isinstance(other, SimpleFile) and
                self._doc_int == other._doc_int and
                self._linker is other._linker)

    def __hash__(self) -> int:
        return hash((self._doc_int, self._linker))


@dataclasses.dataclass
class SimpleArchive:
    _repo: Repository
    _linker: Linker

    @property
    def name(self) -> str:
        return self._repo.get_archive_name()

    def __eq__(self, other) -> bool:
        return (isinstance(other, SimpleArchive) and
                self._repo == other._repo and
                self._linker is other._linker)

    def __hash__(self) -> int:
        return hash((self._repo, self._linker))

    @property
    def path(self) -> Path:
        return self._repo.path

    @property
    def files(self) -> Iterable[SimpleFile]:
        for doc in self._repo.stex_doc_iter():
            yield SimpleFile(self._linker.document_ints.intify(doc), self._linker)


class SimpleVerbalization:
    _verbalization: Verbalization
    _doc_int: int
    _verbalization_int: int
    _linker: Linker

    def __init__(self, verbalization_int: int, linker: Linker):
        self._doc_int, self._verbalization = linker.verb_ints.unintify(verbalization_int)
        self._verbalization_int = verbalization_int
        self._linker = linker

    @property
    def verb_str(self) -> str:
        return self._verbalization.verbalization

    @property
    def lang(self) -> str:
        return self._verbalization.lang

    @property
    def is_defining(self) -> bool:
        return self._verbalization.is_defining

    @property
    def declaring_file(self) -> SimpleFile:
        return SimpleFile(self._doc_int, self._linker)

    @property
    def macro_range(self) -> tuple[int, int]:
        return self._verbalization.macro_range


def get_symbols(linker: Linker, *, name: Optional[str] = None) -> Generator[SimpleSymbol]:
    if name is None:
        for symbol_int in linker.symbol_ints.int_iter():
            yield SimpleSymbol(symbol_int, linker)
    else:
        for modsymb in linker.symbs_by_name[name]:
            yield SimpleSymbol(modsymb[1], linker)


def file_from_path(path: Path, linker: Linker) -> Optional[SimpleFile]:
    doc = linker.mh.get_stex_doc(path)
    if doc is None:
        return None
    return SimpleFile(linker.document_ints.intify(doc), linker)


def get_files(linker: Linker) -> Iterable[SimpleFile]:
    for doc_int in linker.document_ints.int_iter():
        yield SimpleFile(doc_int, linker)


def get_repos(linker: Linker) -> Iterable[SimpleArchive]:
    for repo in linker.mh.iter_stex_archives():
        yield SimpleArchive(repo, linker)


def get_linker() -> Linker:
    mh = Cache.get_mathhub(update_all=True)
    return Linker(mh)
