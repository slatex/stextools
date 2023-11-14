from __future__ import annotations

import dataclasses
import typing
from pathlib import Path
from typing import Optional, Iterator, Literal

from pylatexenc.latexwalker import LatexMacroNode, LatexWalker, LatexCommentNode, LatexCharsNode, LatexMathNode, \
    LatexSpecialsNode, LatexGroupNode, LatexEnvironmentNode

from stextools.macro_arg_utils import get_first_macro_arg_opt, OptArgKeyVals, get_first_main_arg
from stextools.macros import STEX_CONTEXT_DB

if typing.TYPE_CHECKING:
    from stextools.mathhub import MathHub, Repository


@dataclasses.dataclass(frozen=True, eq=True, repr=True)
class Dependency:
    archive: str
    # should always be set, but could be None if the file cannot be determined (still better than no dependency)
    file: Optional[str] = None
    module_name: Optional[str] = None
    is_lib: bool = False   # dependency is lib
    is_use: bool = False   # symbols from dependency not exported
    target_no_tex: bool = False  # e.g. for graphics and code snippets


@dataclasses.dataclass(repr=True)
class ModuleInfo:
    """Basic information about a document (dependencies, created symbols, verbalizations, etc.)"""
    name: str
    dependencies: list[Dependency] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(repr=True)
class DocInfo:
    # dependencies introduced outsidef of modules
    dependencies: list[Dependency] = dataclasses.field(default_factory=list)
    modules: list[ModuleInfo] = dataclasses.field(default_factory=list)

    def flattened_dependencies(self) -> Iterator[Dependency]:
        yield from self.dependencies
        for module in self.modules:
            yield from module.dependencies


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

    def produce(self, node: LatexMacroNode, from_archive: str, from_subdir: str, mh: MathHub) -> Optional[Dependency]:
        # dprint = print   # debug print
        dprint = lambda _: None
        dprint(f'PROCESSING {node.macroname}')
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
            dprint('no main arg')
            return None
        top_dir: Literal['lib', 'source'] = 'lib' if self.is_lib else 'source'   # type: ignore
        archive = mh.get_archive(target_archive or from_archive)

        if archive is None:    # not locally installed, but we still want to store a dependency
            dprint('archive not installed')
            return Dependency(archive=target_archive or from_archive, file=None, module_name=None,
                              is_lib=self.is_lib, is_use=self.is_use, target_no_tex=self.target_no_tex)

        if self.references_module:
            if '?' in main_arg:
                path, _, module_name = main_arg.partition('?')
            else:
                path = main_arg
                module_name = main_arg.split('/')[-1]

            path_options: list[str] = []
            if target_archive is None:      # try relative paths
                path_options.append(f'{from_subdir}/{path}')
                path_options.append(f'{from_subdir}/{path}/{module_name}')
            path_options.append(path)
            path_options.append(f'{path}/{module_name}')
            for path_option in path_options:
                file = archive.normalize_tex_file_ref(path_option, top_dir)
                if file is not None:
                    dprint(f'succeeded {path_option}, {file}')
                    return Dependency(archive.get_archive_name(), file, module_name=module_name,
                                      is_lib=self.is_lib, is_use=self.is_use, target_no_tex=self.target_no_tex)
                else:
                    dprint(f'failed {path_option}')

            # couldn't determine file, but still make dependency to archive
            return Dependency(archive.get_archive_name(), None, module_name=module_name,
                              is_lib=self.is_lib, is_use=self.is_use, target_no_tex=self.target_no_tex)
        else:
            if self.target_no_tex:
                # TODO: determine file (though we don't really care about it, to be honest)
                return Dependency(archive.get_archive_name(), None, module_name=None,
                                  is_lib=self.is_lib, is_use=self.is_use, target_no_tex=self.target_no_tex)
            else:
                path_options = []
                if target_archive is None:  # try relative paths
                    path_options.append(f'{from_subdir}/{main_arg}')
                path_options.append(main_arg)
                for path_option in path_options:
                    file = archive.normalize_tex_file_ref(path_option, top_dir)
                    if file is not None:
                        return Dependency(archive.get_archive_name(), file, module_name=None,
                                          is_lib=self.is_lib, is_use=self.is_use, target_no_tex=self.target_no_tex)

            # couldn't determine file, but still make dependency to archive
            return Dependency(archive.get_archive_name(), None, module_name=None,
                              is_lib=self.is_lib, is_use=self.is_use, target_no_tex=self.target_no_tex)


DEPENDENCY_PRODUCERS = [
    DependencyProducer('usemodule', references_module=True, opt_param_is_archive=True, is_use=True),
    DependencyProducer('requiremodule', references_module=True, opt_param_is_archive=True, is_use=True),
    DependencyProducer('importmodule', references_module=True, opt_param_is_archive=True),

    DependencyProducer('inputref', opt_param_is_archive=True),
    DependencyProducer('mhinput', opt_param_is_archive=True),

    DependencyProducer('mhgraphics', archive_in_params=True, target_no_tex=True),
    DependencyProducer('cmhgraphics', archive_in_params=True, target_no_tex=True),
    DependencyProducer('mhtikzinput', archive_in_params=True, target_no_tex=True),
    DependencyProducer('cmhtikzinput', archive_in_params=True, target_no_tex=True),
    DependencyProducer('lstinputmhlisting', archive_in_params=True, target_no_tex=True),

    DependencyProducer('includeproblem', archive_in_params=True),
    DependencyProducer('includeassignment', archive_in_params=True),

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
        self.path = path
        self._doc_info: Optional[DocInfo] = None

    def get_doc_info(self, mh: MathHub) -> DocInfo:
        if self._doc_info is None:
            self.create_doc_info(mh)
        assert self._doc_info is not None
        return self._doc_info

    def get_rel_path(self) -> str:
        return str(self.path.relative_to(self.archive.path).as_posix())

    def create_doc_info(self, mh: MathHub):
        """Create the DocInfo object for this document."""
        with open(self.path) as fp:
            walker = LatexWalker(fp.read(), latex_context=STEX_CONTEXT_DB)

        doc_info = DocInfo()

        def process(nodes, module_info: Optional[ModuleInfo] = None):
            for node in nodes:
                if node.nodeType() in {LatexCommentNode, LatexCharsNode, LatexMathNode, LatexSpecialsNode}:
                    pass    # TODO: should we do something with math nodes?
                elif node.nodeType() == LatexGroupNode:
                    process(node.nodelist, module_info)
                elif node.nodeType() == LatexEnvironmentNode:
                    # TODO: handle smodules
                    process(node.nodelist, module_info)
                elif node.nodeType() == LatexMacroNode:
                    assert isinstance(node, LatexMacroNode)
                    dp = DEPENDENCY_PRODUCER_BY_MACRONAME.get(node.macroname)
                    if dp:
                        dep = dp.produce(
                            node,
                            self.archive.get_archive_name(),
                            '/'.join(self.get_rel_path().split('/')[1:]),   # ignore 'source' or 'lib'
                            mh
                        )
                        if dep:
                            if module_info:
                                module_info.dependencies.append(dep)
                            else:
                                doc_info.dependencies.append(dep)
                else:
                    raise Exception(f'Unexpected node type: {node.nodeType()}')

        process(walker.get_latex_nodes()[0])
        self._doc_info = doc_info
