import dataclasses
from collections.abc import Iterable, Generator
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
            verb = self._linker.verb_ints.unintify(verb_int)[1]
            if lang is not None and verb.lang != lang:
                continue
            yield SimpleVerbalization(verb, self._linker)

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
        if right == module_path:
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

    def symbol_is_in_scope_at(self, symbol: SimpleSymbol, offset: int) -> bool:
        required_module = symbol.declaring_module._module_int
        for mod, start, end in self._linker.available_module_ranges[self._doc_int]:
            if start <= offset < end and required_module in self._linker.transitive_imports[mod]:
                return True
        return False

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


@dataclasses.dataclass
class SimpleVerbalization:
    _verbalization: Verbalization
    _linker: Linker

    @property
    def verb_str(self) -> str:
        return self._verbalization.verbalization


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


def get_linker() -> Linker:
    mh = Cache.get_mathhub(update_all=True)
    return Linker(mh)
