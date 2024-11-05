import dataclasses
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

    def get_verbalizations(self, lang: Optional[str] = None) -> list['SimpleVerbalization']:
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


class SimpleModule:
    _module: ModuleInfo
    _module_int: int
    _linker: Linker

    def __init__(self, module_int: int, linker: Linker):
        doc, modstr = linker.module_ints.unintify(module_int)
        self._module = linker.document_ints.unintify(doc).get_doc_info(linker.mh).get_module(modstr)
        self._module_int = module_int
        self._linker = linker

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

    @property
    def archive(self) -> 'SimpleArchive':
        return SimpleArchive(self._stex_doc.archive, self._linker)

    @property
    def path(self) -> Path:
        return self._stex_doc.path

    @property
    def lang(self) -> str:
        return self._stex_doc.get_doc_info(self._linker.mh).lang


@dataclasses.dataclass
class SimpleArchive:
    _repo: Repository
    _linker: Linker

    @property
    def name(self) -> str:
        return self._repo.get_archive_name()


@dataclasses.dataclass
class SimpleVerbalization:
    _verbalization: Verbalization
    _linker: Linker

    @property
    def verb_str(self) -> str:
        return self._verbalization.verbalization


def get_symbols(linker: Linker) -> list[SimpleSymbol]:
    for symbol_int in linker.symbol_ints.int_iter():
        yield SimpleSymbol(symbol_int, linker)


def file_from_path(path: Path, linker: Linker) -> SimpleFile:
    doc = linker.mh.get_stex_doc(path)
    return SimpleFile(linker.document_ints.intify(doc), linker)


def get_linker() -> Linker:
    mh = Cache.get_mathhub(update_all=True)
    return Linker(mh)
