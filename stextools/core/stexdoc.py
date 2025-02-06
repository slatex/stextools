from __future__ import annotations

import dataclasses
import functools
import logging
import re
import typing
from pathlib import Path
from typing import Optional, Iterator, Literal

from pylatexenc.latexwalker import LatexMacroNode, LatexWalker, LatexCommentNode, LatexCharsNode, LatexMathNode, \
    LatexSpecialsNode, LatexGroupNode, LatexEnvironmentNode

from stextools.core.macros import STEX_CONTEXT_DB
from stextools.utils.macro_arg_utils import get_first_macro_arg_opt, OptArgKeyVals, get_first_main_arg

if typing.TYPE_CHECKING:
    from stextools.core.mathhub import MathHub, Repository


logger = logging.getLogger(__name__)


class DependencyPropFlag:  # note: enum.IntFlag is really slow -- maybe this is better in new Python versions?
    IS_LIB = 1
    IS_USE = 2
    TARGET_NO_TEX = 4
    IS_INPUT = 8
    IS_USE_STRUCT = 16


# NOTE: According to my benchmark, using `slots=True` noticably slows down pickling/unpickling

@dataclasses.dataclass(frozen=True, eq=True, repr=True)
class Dependency:
    archive: str
    # should always be set, but could be None if the file cannot be determined (still better than no dependency)
    file_hint: Optional[str]
    module_name: Optional[str]
    flags: int     # DependencyPropFlag
    scope: tuple[int, int]  # range of the document where the dependency is valid
    intro_range: Optional[tuple[int, int]] = None  # range of the document where the dependency is introduced
    file_may_be_relative: bool = False

    def get_target_path(self, mh: MathHub, src: STeXDocument) -> Optional[Path]:
        if self.file_hint is None:
            return None
        archive = mh.get_archive(self.archive)
        if archive is None:
            return None
        di = src.get_doc_info(mh)
        if self.module_name:
            if len(self.module_name) > 150:
                logger.warning(f'Ignoring very long module name in {src.path}: {self.module_name[:150]}...')
                logger.warning(
                    f'If this is not caused by malformed TeX, please report this issue along with the document.')
                return None
            if r := archive.resolve_path_ref(self.file_hint + '/' + self.module_name, 'lib' if self.is_lib else 'source', di.lang):
                return r

        if r := archive.resolve_path_ref(self.file_hint, 'lib' if self.is_lib else 'source', di.lang):
            return r
        if self.file_may_be_relative and src.archive.get_archive_name() == self.archive:
            # try to resolve relative to the source file
            s = src.get_rel_path().split('/')
            file_hint = '/'.join(s[1:-1]) + '/' + self.file_hint
            directory = str(src.get_rel_path()).split('/')[0]
            if r := archive.resolve_path_ref(file_hint, directory, di.lang):  # type: ignore
                return r
            if self.module_name:
                return archive.resolve_path_ref(self.file_hint + '/' + self.module_name, directory, di.lang)  # type: ignore
        return None

    @property
    def is_lib(self) -> bool:
        """Dependency is a library"""
        return bool(self.flags & DependencyPropFlag.IS_LIB)

    @property
    def is_use(self) -> bool:
        """Symbols from the dependency are not exported"""
        return bool(self.flags & DependencyPropFlag.IS_USE)

    @property
    def is_use_struct(self) -> bool:
        """ \\usestructure """
        return bool(self.flags & DependencyPropFlag.IS_USE_STRUCT)

    @property
    def target_no_tex(self) -> bool:
        """Dependency is not a TeX file (e.g. graphics, code snippets)"""
        return bool(self.flags & DependencyPropFlag.TARGET_NO_TEX)

    @property
    def is_input(self) -> bool:
        """Dependency is being inputted"""
        return bool(self.flags & DependencyPropFlag.IS_INPUT)

    def get_target_stexdoc(self, mh: MathHub, src: 'STeXDocument') -> Optional['STeXDocument']:
        path = self.get_target_path(mh, src)
        if path is None:
            return None
        return mh.get_stex_doc(path)
        # if self.file is None:
        #     return None
        # archive = mh.get_archive(self.archive)
        # if archive is None:
        #     return None
        # return archive.get_stex_doc(
        #     ('lib' if self.is_lib else 'source') + '/' + self.file
        # )

    @functools.cache
    def get_target(self, mh: MathHub, src: 'STeXDocument') -> tuple[Optional['STeXDocument'], Optional['ModuleInfo']]:
        doc = self.get_target_stexdoc(mh, src)
        if doc is None or self.module_name is None:
            return None, None
        # return doc, doc.get_doc_info(mh).get_module(self.module_name)
        # optimization
        return doc, (doc._doc_info or doc.get_doc_info(mh)).get_module(self.module_name)


@dataclasses.dataclass(frozen=True, eq=True, repr=True)
class Symbol:
    name: str
    decl_def: tuple[int, int]    # (start, end) of the \symdecl/\symdef (if available)


@dataclasses.dataclass(frozen=True, eq=True, repr=True)
class Verbalization:
    symbol_name: str
    verbalization: str
    lang: str
    macro_range: tuple[int, int]
    symbol_path_hint: Optional[str] = None  # e.g. for "foo/bar?baz", we have "foo/bar" as hint and "baz" as symbol_name
    is_defining: bool = False   # verbalization is definiendum

    @classmethod
    def from_macro(cls, node: LatexMacroNode, lang: str) -> Optional[Verbalization]:
        prefix = ''
        postfix = ''
        if not node.nodeargd:
            return None
        if node.macroname in {'sr', 'definiendum'}:
            symbol = node.nodeargd.argnlist[-2].latex_verbatim()[1:-1]
            verbalization = node.nodeargd.argnlist[-1].latex_verbatim()[1:-1]
        else:
            params = OptArgKeyVals.from_first_macro_arg(node.nodeargd)
            if params:
                prefix = params.get_val('pre') or ''
                postfix = params.get_val('post') or ''
            symbol = node.nodeargd.argnlist[-1].latex_verbatim()[1:-1]
            verbalization = symbol.split('?')[-1]
        if node.macroname in {'Sn', 'Sns', 'Definame'}:
            if verbalization:
                verbalization = verbalization[0].upper() + verbalization[1:]
            else:
                return None
        if node.macroname in {'sns', 'Sns'}:
            verbalization += 's'

        verbalization = prefix + verbalization + postfix

        symbol = re.sub(r'\s+', ' ', symbol)
        verbalization = re.sub(r'\s+', ' ', verbalization)
        symbol_path_hint, _, symbol_name = symbol.rpartition('?')

        return cls(
            symbol_name=symbol_name,
            verbalization=verbalization,
            lang=lang,
            symbol_path_hint=symbol_path_hint if symbol_path_hint else None,
            macro_range=(node.pos, node.pos + node.len),
            is_defining=node.macroname in {'definiendum', 'definame', 'Definame'},
        )


@dataclasses.dataclass(repr=True)
class ModuleInfo:
    """Basic information about a document (dependencies, created symbols, verbalizations, etc.)"""
    name: str
    valid_range: tuple[int, int]
    struct_name: Optional[str] = None
    dependencies: list[Dependency] = dataclasses.field(default_factory=list)
    symbols: list[Symbol] = dataclasses.field(default_factory=list)
    # submodules
    modules: list[ModuleInfo] = dataclasses.field(default_factory=list)
    is_structure: bool = False
    struct_deps: Optional[list[str]] = None

    def flattened_dependencies(self) -> Iterator[Dependency]:
        yield from self.dependencies
        for module in self.modules:
            yield from module.dependencies

    def iter_modules(self) -> Iterator[ModuleInfo]:
        yield self
        for module in self.modules:
            yield from module.iter_modules()


@dataclasses.dataclass(repr=True)
class DocInfo:
    # dependencies introduced outside of modules
    last_modified: float
    lang: str
    dependencies: list[Dependency] = dataclasses.field(default_factory=list)
    modules: list[ModuleInfo] = dataclasses.field(default_factory=list)
    verbalizations: list[Verbalization] = dataclasses.field(default_factory=list)
    module_by_name: dict[str, ModuleInfo] = dataclasses.field(default_factory=dict)

    def flattened_dependencies(self) -> Iterator[Dependency]:
        """Iterate over all dependencies in the document, including those in modules."""
        yield from self.dependencies
        for module in self.modules:
            yield from module.flattened_dependencies()

    def iter_modules(self) -> Iterator[ModuleInfo]:
        for module in self.modules:
            yield from module.iter_modules()

    def get_module(self, name: str) -> Optional[ModuleInfo]:
        return self.module_by_name.get(name)

    def finalize(self):
        for module in self.iter_modules():
            self.module_by_name[module.name] = module


@dataclasses.dataclass
class DependencyProducer:
    macroname: str
    references_module: bool = False   # usually, a file is referenced
    opt_param_is_archive: bool = False   # \macro[ARCHIVE]{file}
    archive_in_params: bool = False  # keyvals: \macro[...,archive=ARCHIVE,...]{file}

    # field values for created dependencies
    is_lib: bool = False
    is_use: bool = False
    target_no_tex: bool = False
    is_input: bool = False
    is_use_struct: bool = False

    def produce(self, node: LatexMacroNode, from_archive: str, from_subdir: str, mh: MathHub,
                scope: tuple[int, int], lang: str = '*') -> Optional[Dependency]:
        flag = 0   # DependencyPropFlag(0)
        if self.is_lib:
            flag |= DependencyPropFlag.IS_LIB
        if self.is_use:
            flag |= DependencyPropFlag.IS_USE
        if self.target_no_tex:
            flag |= DependencyPropFlag.TARGET_NO_TEX
        if self.is_input:
            flag |= DependencyPropFlag.IS_INPUT
        if self.is_use_struct:
            flag |= DependencyPropFlag.IS_USE_STRUCT

        # STEP 1: Determine the target archive
        target_archive: Optional[str] = None
        if self.opt_param_is_archive:
            opt_arg = get_first_macro_arg_opt(node.nodeargd)
            if opt_arg:
                target_archive = opt_arg.strip()
        elif self.archive_in_params:
            params = OptArgKeyVals.from_first_macro_arg(node.nodeargd)
            if params and (value := params.get_val('archive')):
                target_archive = value

        # STEP 2: Determine file and module (this is hacky and I don't know the precise rules used in stex...)
        main_arg = get_first_main_arg(node.nodeargd)

        if main_arg is None:
            return None
        top_dir: Literal['lib', 'source'] = 'lib' if self.is_lib else 'source'   # type: ignore
        archive = mh.get_archive(target_archive or from_archive)
        intro_range: tuple[int, int] = (node.pos, node.pos + node.len)

        if archive is None:    # not locally installed, but we still want to store a dependency
            return Dependency(archive=target_archive or from_archive, file_hint=None,
                              file_may_be_relative=True, module_name=None,
                              flags=int(flag), scope=scope, intro_range=intro_range)

        if self.references_module:
            if '?' in main_arg:
                path, _, module_name = main_arg.partition('?')
            else:
                path = main_arg
                module_name = main_arg.split('/')[-1]

            return Dependency(archive.get_archive_name(), file_hint=path, file_may_be_relative=True,
                              module_name=module_name, flags=int(flag), scope=scope,
                              intro_range=intro_range)
        else:
            if self.target_no_tex:
                # TODO: determine file (though we don't really care about it, to be honest)
                return Dependency(archive.get_archive_name(), None, module_name=None,
                                  flags=int(flag), scope=scope, intro_range=intro_range)
            else:
                return Dependency(archive.get_archive_name(), file_hint=main_arg, file_may_be_relative=True,
                                  module_name=None, flags=int(flag), scope=scope, intro_range=intro_range)


DEPENDENCY_PRODUCERS = [
    DependencyProducer('usemodule', references_module=True, opt_param_is_archive=True, is_use=True),
    DependencyProducer('requiremodule', references_module=True, opt_param_is_archive=True, is_use=True),
    DependencyProducer('importmodule', references_module=True, opt_param_is_archive=True),

    DependencyProducer('usestructure', references_module=True, is_use_struct=True),

    DependencyProducer('inputref', opt_param_is_archive=True, is_input=True),
    DependencyProducer('mhinput', opt_param_is_archive=True, is_input=True),
    DependencyProducer('input', is_input=True),
    DependencyProducer('include', is_input=True),

    DependencyProducer('mhgraphics', archive_in_params=True, target_no_tex=True),
    DependencyProducer('cmhgraphics', archive_in_params=True, target_no_tex=True),
    DependencyProducer('mhtikzinput', archive_in_params=True, target_no_tex=True),
    DependencyProducer('cmhtikzinput', archive_in_params=True, target_no_tex=True),
    DependencyProducer('lstinputmhlisting', archive_in_params=True, target_no_tex=True),

    DependencyProducer('includeproblem', archive_in_params=True, is_input=True),
    DependencyProducer('includeassignment', archive_in_params=True, is_input=True),

    DependencyProducer('libinput', opt_param_is_archive=True, is_lib=True),
    DependencyProducer('addmhbibresource', archive_in_params=True, target_no_tex=True, is_lib=True),

    # these two reference packages etc., so we ignore them:
    #   DependencyProducer('libusepackage', opt_param_is_archive=True, is_lib=True),
    #   DependencyProducer('libusetikzlibrary', archive_in_params=True, target_no_tex=True, is_lib=True),
]
DEPENDENCY_PRODUCER_BY_MACRONAME: dict[str, DependencyProducer] = {dp.macroname: dp for dp in DEPENDENCY_PRODUCERS}


class STeXDocument:
    def __init__(self, archive: Repository, path: Path):
        self.archive = archive
        self.path = path.absolute()   # .resolve()  (TODO: resolve is slow - do we need it?)
        self._doc_info: Optional[DocInfo] = None

    def get_doc_info(self, mh: MathHub) -> DocInfo:
        if self._doc_info is None:
            self.create_doc_info(mh)
        assert self._doc_info is not None
        return self._doc_info

    def get_rel_path(self) -> str:
        return str(self.path.relative_to(self.archive.path).as_posix())

    def delete_doc_info_if_outdated(self):
        if self._doc_info is None:
            return
        try:
            if self.path.stat().st_mtime > self._doc_info.last_modified:
                self._doc_info = None
        except FileNotFoundError:
            self._doc_info = None

    def create_doc_info(self, mh: MathHub):
        """Create the DocInfo object for this document."""
        try:
            with open(self.path) as fp:
                text = fp.read()
        except FileNotFoundError:
            logger.error(f'File not found: {self.path}')
            text = ''

        walker = LatexWalker(text, latex_context=STEX_CONTEXT_DB)

        name_segments = self.path.name.split('.')
        doc_info = DocInfo(self.path.stat().st_mtime, 'en' if len(name_segments) < 3 else name_segments[-2])
        # TODO: update lang in case it is specified in the document (e.g. \documentclass[lang=de]{stex})

        def process(nodes, parent_range: tuple[int, int], module_info: Optional[ModuleInfo] = None):
            parent_module_info = module_info
            for node in nodes:
                module_info = parent_module_info   # reset
                if node.nodeType() in {LatexCommentNode, LatexCharsNode, LatexMathNode, LatexSpecialsNode}:
                    pass    # TODO: should we do something with math nodes?
                elif node.nodeType() == LatexGroupNode:
                    process(node.nodelist, (node.pos, node.pos + node.len), module_info)
                elif node.nodeType() == LatexEnvironmentNode:
                    # TODO: handle smodules
                    if node.environmentname == 'smodule':
                        if node.nodeargd is None:
                            logger.error(f'{self.path}: malformed smodule - skipping it')
                            continue
                        name = node.nodeargd.argnlist[1].latex_verbatim()[1:-1]
                        if module_info:
                            name = f'{module_info.name}/{name}'
                        new_module_info = ModuleInfo(name=name, valid_range=(node.pos, node.pos + node.len))
                        if module_info:
                            module_info.modules.append(new_module_info)
                        else:
                            doc_info.modules.append(new_module_info)
                        module_info = new_module_info

                        # e.g. "set.de.tex" has something like an import to "set.en.tex",
                        # which is indicated with `sig=en` as a parameter in the smodule environment
                        params = OptArgKeyVals.from_first_macro_arg(node.nodeargd)
                        if params and (sig_val := params.get_val('sig')):
                            file: Path = self.path
                            name_parts = file.name.split('.')
                            file_ok: bool = True
                            if len(name_parts) > 2:
                                name_parts[-2] = sig_val
                                file = file.with_name('.'.join(name_parts))
                                if not file.exists():
                                    file_ok = False
                            else:
                                file_ok = False

                            module_info.dependencies.append(
                                Dependency(self.archive.get_archive_name(),
                                           file_hint=file.relative_to(self.archive.path / 'source').as_posix() if file_ok else None,
                                           # file.relative_to(self.archive.path / 'source').as_posix() if file_ok else None,
                                           module_name=name,
                                           flags=0,  # was: int(DependencyPropFlag.IS_USE), but I think it should actuall be import...
                                           scope=(node.pos, node.pos + node.len), intro_range=(node.pos, node.pos + node.len))
                            )
                    elif node.environmentname in {'mathstructure', 'extstructure'}:
                        is_ext = node.environmentname == 'extstructure'
                        name = node.nodeargd.argnlist[1 if is_ext else 0].latex_verbatim()[1:-1]
                        if not module_info:
                            logger.warning(f'{self.path}: structure "{name}" declared outside of a module')
                            continue
                        opt_args = node.nodeargd.argnlist[2 if is_ext else 1]
                        symb_name = opt_args.latex_verbatim()[1:-1].split(',')[0] if opt_args else name
                        module_info.symbols.append(Symbol(name=symb_name, decl_def=(node.pos, node.pos + node.len)))
                        new_module_info = ModuleInfo(
                            name=f'{module_info.name}/{name}-module',
                            struct_name=name,
                            valid_range=(node.pos, node.pos + node.len),
                            is_structure=True,
                            struct_deps=[
                                dep.strip() for dep in node.nodeargd.argnlist[3].latex_verbatim()[1:-1].split(',') if dep.strip()
                            ] if is_ext else [],
                        )
                        module_info.modules.append(new_module_info)
                        module_info = new_module_info

                    process(node.nodelist, (node.pos, node.pos + node.len), module_info)
                elif node.nodeType() == LatexMacroNode:
                    assert isinstance(node, LatexMacroNode)
                    dp = DEPENDENCY_PRODUCER_BY_MACRONAME.get(node.macroname)
                    if dp:
                        lang = '*'
                        _parts = self.path.name.split('.')
                        if len(_parts) > 2:
                            lang = _parts[-2]
                        dep = dp.produce(
                            node,
                            self.archive.get_archive_name(),
                            '/'.join(self.get_rel_path().split('/')[1:]),   # ignore 'source' or 'lib'
                            mh,
                            parent_range,
                            lang
                        )
                        if dep:
                            if module_info:
                                module_info.dependencies.append(dep)
                            else:
                                doc_info.dependencies.append(dep)

                    elif node.macroname in {'symdef', 'symdecl'}:
                        if node.macroname == 'symdef':
                            arg = node.nodeargd.argnlist[1]
                            if arg:
                                params = OptArgKeyVals(arg.nodelist)
                                symbol = params.get_val('name')
                            else:
                                symbol = None
                            if symbol is None:
                                symbol = node.nodeargd.argnlist[0].latex_verbatim()[1:-1]
                        elif node.macroname == 'symdecl':
                            symbol = node.nodeargd.argnlist[-1].latex_verbatim()[1:-1]
                        else:
                            raise RuntimeError('Unexpected macroname')

                        if not module_info:
                            logger.warning(f'{self.path}: symbol "{symbol}" declared outside of a module')
                        else:
                            assert symbol is not None
                            module_info.symbols.append(
                                Symbol(name=symbol, decl_def=(node.pos, node.pos + node.len))
                            )

                    elif node.macroname in {
                        'definiendum', 'definame', 'Definame',
                        'sn', 'sns', 'Sn', 'Sns', 'sr',
                    }:
                        verb = Verbalization.from_macro(node, doc_info.lang)
                        if verb:
                            doc_info.verbalizations.append(verb)
                else:
                    raise Exception(f'Unexpected node type: {node.nodeType()}')

        process(walker.get_latex_nodes()[0], (0, walker.get_latex_nodes()[2]))
        doc_info.finalize()
        self._doc_info = doc_info
