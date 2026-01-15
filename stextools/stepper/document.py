import abc
import dataclasses
import functools
import itertools
import logging
from pathlib import Path
from typing import Iterable, Optional, TypeAlias, Literal, cast

from pylatexenc.latexwalker import LatexWalker, LatexMathNode, LatexCommentNode, LatexSpecialsNode, LatexMacroNode, \
    LatexEnvironmentNode, LatexGroupNode, LatexCharsNode

from stextools.remote_repositories import get_mathhub_path, get_containing_archive
from stextools.stepper.html_support import MyHtmlParser
from stextools.stepper.interface import interface
from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import lang_from_path
from stextools.stex.stex_py_parsing import STEX_CONTEXT_DB, get_annotatable_plaintext, get_plaintext_approx, \
    PLAINTEXT_EXTRACTION_MACRO_RECURSION, PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES
from stextools.utils.json_iter import json_iter
from stextools.utils.linked_str import LinkedStr, string_to_lstr

logger = logging.getLogger(__name__)

MODE: TypeAlias = Literal['text', 'math']


@dataclasses.dataclass
class Document(abc.ABC):
    identifier: str
    format: str
    language: str

    @abc.abstractmethod
    def get_content(self) -> str:
        pass

    @abc.abstractmethod
    def set_content(self, content: str):
        pass

    def on_modified(self):
        pass

    def get_annotatable_plaintext(self) -> Iterable[LinkedStr[None]]:
        raise NotImplementedError(f'get_annotatable_plaintext not implemented for {self.format} documents.')

    def get_annotatable_formulae(self) -> Iterable[LinkedStr[None]]:
        raise NotImplementedError(f'{type(self)}.get_annotatable_formulae not implemented.')

    def get_all_annotatable(self) -> Iterable[tuple[MODE, LinkedStr[None]]]:
        l: list[tuple[MODE, LinkedStr[None]]] = list(itertools.chain(
            (( cast(MODE, 'text'), lstr) for lstr in self.get_annotatable_plaintext()),
            ((cast(MODE, 'math'), lstr) for lstr in self.get_annotatable_formulae())
        ))
        l.sort(key=lambda x: x[1].get_start_ref())
        return l

    def get_plaintext_approximation(self) -> LinkedStr:
        raise NotImplementedError(f'get_plaintext_approximation not implemented for {self.format} documents.')

    def get_inputted_documents(self) -> Iterable['Document']:
        r""" Returns the documents that were inputted to this document.
        (e.g. \input in LaTeX)
        """
        return []


class LocalFileDocument(Document, abc.ABC):
    _content: Optional[str] = None
    path: Path

    def __init__(self, path: Path, language: str, format: str):
        self.path = path
        super().__init__(
            identifier=str(path.resolve().absolute()),
            format=format,
            language=language
        )

    def get_content(self) -> str:
        if self._content is None:
            self._content = self.path.read_text()
        return self._content

    def set_content(self, content: str):
        self.write_content(content)
        self.on_modified(reset_content=False)

    def on_modified(self, reset_content: bool = True):
        if reset_content:
            self._content = None

    def write_content(self, content: str) -> None:
        """ Writes the content to the file. """
        self.path.write_text(content)
        self._content = content


class STeXDocument(LocalFileDocument):
    """ A local stex document. """
    _latex_walker: Optional[LatexWalker] = None

    def __init__(self, path: Path, language: str):
        super().__init__(path, language, 'sTeX')

    def on_modified(self, reset_content: bool = True):
        self._latex_walker = None
        FLAMS.load_file(self.identifier)
        LocalFileDocument.on_modified(self, reset_content=reset_content)

    def get_latex_walker(self) -> LatexWalker:
        """ Returns a LatexWalker for the document content. """
        if self._latex_walker is None:
            content = self.get_content()
            self._latex_walker = LatexWalker(content, latex_context=STEX_CONTEXT_DB)
        return self._latex_walker

    def get_annotatable_plaintext(self) -> Iterable[LinkedStr[None]]:
        return get_annotatable_plaintext(
            self.get_latex_walker()
        )

    def get_annotatable_formulae(self) -> Iterable[LinkedStr[None]]:
        walker = self.get_latex_walker()

        def _recurse(nodes):
            for node in nodes:
                if node is None or node.nodeType() in {LatexCommentNode, LatexCharsNode, LatexSpecialsNode}:
                    continue
                elif node.nodeType() == LatexMathNode:
                    yield string_to_lstr(self.get_content()[node.pos:node.pos+node.len], node.pos)
                elif node.nodeType() == LatexMacroNode:
                    # TODO: should we actually follow the plaintext extraction rules?
                    if node.macroname in PLAINTEXT_EXTRACTION_MACRO_RECURSION:
                        for arg_idx in PLAINTEXT_EXTRACTION_MACRO_RECURSION[node.macroname]:
                            yield from _recurse([node.nodeargd.argnlist[arg_idx]])
                elif node.nodeType() == LatexEnvironmentNode:
                    if node.envname in PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES:
                        recurse_content, recurse_args = PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES[node.envname]
                    else:
                        recurse_content, recurse_args = True, []
                    for arg_idx in recurse_args:
                        yield from _recurse([node.nodeargd.argnlist[arg_idx]])
                    if recurse_content:
                        yield from _recurse(node.nodelist)
                elif node.nodeType() == LatexGroupNode:
                    yield from _recurse(node.nodelist)
                else:
                    raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

        yield from _recurse(walker.get_latex_nodes()[0])

    def get_plaintext_approximation(self) -> LinkedStr:
        return get_plaintext_approx(self.get_latex_walker())

    def get_inputted_documents(self) -> Iterable['Document']:
        return self.get_dependencies(mode='inputs')

    def get_dependencies(self, mode: Literal['inputs', 'noninputs', 'both']) -> Iterable['Document']:
        """ not transitive """
        if mode == 'inputs':
            keys = {'IncludeProblem', 'Inputref'}
        elif mode == 'noninputs':
            keys = {'ImportModule', 'UseModule'}
        else:
            assert mode == 'both'
            keys = {'IncludeProblem', 'Inputref', 'ImportModule', 'UseModule'}

        annos = FLAMS.get_file_annotations(self.path)
        for e in json_iter(annos, {'full_range', 'val_range', 'key_range', 'Sig', 'smodule_range', 'Title',
                                   'path_range', 'archive_range'}):
            if not isinstance(e, dict):
                continue
            if all(k not in e for k in keys):
                continue

            if 'IncludeProblem' in e or 'Inputref' in e:
                key = 'IncludeProblem' if 'IncludeProblem' in e else 'Inputref'
                if e[key]['archive']:
                    repo = get_mathhub_path() / e[key]['archive'][0]
                else:
                    repo = get_containing_archive(self.path)
                    if repo is None:
                        interface.write_text(
                            f"Warning: {self.path} uses inputref without archive, but is not in a git repo.\n",
                            style='warning'
                        )
                        continue
                path = repo / 'source' / e[key]['filepath'][0]
                if not path.exists():
                    interface.write_text(f"Warning: {path} does not exist. (included by {self.path})\n", style='warning')
                    continue
                yield STeXDocument(path=path, language=lang_from_path(path))
            elif 'ImportModule' in e or 'UseModule' in e:
                key = 'ImportModule' if 'ImportModule' in e else 'UseModule'
                # uri = e[key]['module']['uri']
                path_val = e[key]['module']['full_path']
                if not path_val:
                    interface.write_text(
                        f'Warning: could not determine path for module included by {self.path}\n',
                        style='warning'
                    )
                    continue
                path = Path(path_val)
                yield STeXDocument(path=path, language=lang_from_path(path))
                # for v in get_transitive_imports([(uri, path)]).values():
                #     yield STeXDocument(path=Path(v), language=lang_from_path(Path(v)))


class WdAnnoTexDocument(LocalFileDocument):
    """ A local tex document that is supposed to be annotated with WikiData annotations (not sTeX). """

    _latex_walker: Optional[LatexWalker] = None

    def __init__(self, path: Path, language: str):
        super().__init__(path, language, 'wdTeX')

    def set_content(self, content: str):
        super().set_content(content)
        self._latex_walker = None

    def get_annotatable_formulae(self) -> Iterable[LinkedStr[None]]:
        result: list[LinkedStr] = []
        walker = self.get_latex_walker()
        # walker = LatexWalker(latex_text, latex_context=STEX_CONTEXT_DB)
        latex_text = walker.s

        def _recurse(nodes):
            for node in nodes:
                if node is None or node.nodeType() in {LatexCommentNode, LatexSpecialsNode}:
                    continue
                if node.nodeType() == LatexMathNode:
                    result.append(string_to_lstr(latex_text[node.pos:node.pos+node.len], node.pos))
                elif node.nodeType() == LatexMacroNode:
                    if node.macroname in PLAINTEXT_EXTRACTION_MACRO_RECURSION:
                        for arg_idx in PLAINTEXT_EXTRACTION_MACRO_RECURSION[node.macroname]:
                            _recurse([node.nodeargd.argnlist[arg_idx]])
                elif node.nodeType() == LatexEnvironmentNode:
                    if node.envname in PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES:
                        recurse_content, recurse_args = PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES[node.envname]
                    else:
                        recurse_content, recurse_args = True, []
                    for arg_idx in recurse_args:
                        _recurse([node.nodeargd.argnlist[arg_idx]])
                    if recurse_content:
                        _recurse(node.nodelist)
                elif node.nodeType() == LatexGroupNode:
                    _recurse(node.nodelist)
                elif node.nodeType() == LatexCharsNode:
                    result.append(string_to_lstr(node.chars, node.pos))
                else:
                    raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

        _recurse(walker.get_latex_nodes()[0])

        return result

    # copy everything else from STeXDocument (it's just a prototype, if successful, we can improve it)
    get_latex_walker = STeXDocument.get_latex_walker
    get_annotatable_plaintext = STeXDocument.get_annotatable_plaintext
    get_plaintext_approximation = STeXDocument.get_plaintext_approximation


class WdAnnoHtmlDocument(LocalFileDocument):
    """ A (local) HTML document that is supposed to be annotated with WikiData annotations (not sTeX/FLAMS). """
    def __init__(self, path: Path, language: str):
        super().__init__(path, language, 'wdHTML')

        self.html_parser: Optional[MyHtmlParser] = None

    def set_content(self, content: str):
        super().set_content(content)
        self.html_parser = None
        with open('/tmp/test2.html', 'w') as fp:
            fp.write(content)

    def _get_html_parser(self) -> MyHtmlParser:
        if self.html_parser is None:
            self.html_parser = MyHtmlParser(self.get_content())
            self.html_parser.feed(self.get_content())
        return self.html_parser

    def get_body_range(self) -> tuple[int, int]:
        html_parser = self._get_html_parser()
        return html_parser.body_start, html_parser.body_end

    def get_body_content(self) -> str:
        a, b = self.get_body_range()
        return self.get_content()[a:b]

    def get_annotatable_plaintext(self) -> Iterable[LinkedStr[None]]:
        return iter(self._get_html_parser().annotatable_plaintext_ranges)


    def get_annotatable_formulae(self) -> Iterable[LinkedStr[None]]:
        content = self.get_content()
        for start, end in self._get_html_parser().formula_ranges:
            yield string_to_lstr(content[start:end], start)


def documents_from_paths(
        paths: list[Path],
        annotation_format: Literal['stex', 'wikidata'] = 'stex',
        include_dependencies: bool = False,
) -> list[Document]:
    """
    Creates a list of Document objects from the given paths.

    ``annotation_format`` is relevant as the annotation format is (currently) also
    relevant for creating the document objects.
    This might not be the best design choice.

    ``include_dependencies`` indicates whether all dependencies should be added as well.
    If it is False (default) and documents input other documents, the user is asked whether to include them.
    "input" means that their content is included.
    There are also "non-input" dependencies, (importmodule, usemodule)
    which are only added if ``include_dependencies`` is True.

    TODO: This function needs cleanup and enhancements
    """

    # documents should be uniquely identified Document.identifier
    all_identifiers: set[str] = set()

    already_considered_file_paths: set[Path] = set()

    # Step 1: make a list of all relevant files
    file_paths: list[Path] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Path {path} does not exist.")
        if path.is_file():
            files = [path]
        else:
            files = list(path.rglob('*.tex'))
            if annotation_format == 'wikidata':
                for html_path in path.rglob('*.html'):
                    files.append(html_path)

        for path in files:
            path = path.resolve()
            if path not in already_considered_file_paths:
                file_paths.append(path)
                already_considered_file_paths.add(path)

    # Step 2: create Document objects for each file
    documents: list[Document] = []

    @functools.cache
    def log_once(msg: str):
        logger.info(msg)

    for path in file_paths:
        if annotation_format == 'stex' and path.suffix == '.tex':
            if path.parent.name == 'lib' and (path.parent.parent / '.git').exists():
                # skip lib files in archives (they crash FLAMS)
                log_once(f'Skipping files in {path.parent}.')
                continue
            if '/.flams/' in str(path):
                subpath = path
                while subpath and subpath.name != '.flams':
                    subpath = subpath.parent
                if subpath:
                    log_once(f'Skipping files in {subpath}.')
                    continue
            new_doc = STeXDocument(path=path, language=lang_from_path(path))
        elif annotation_format == 'wikidata' and path.suffix == '.tex':
            new_doc = WdAnnoTexDocument(path=path, language=lang_from_path(path))
        elif annotation_format == 'wikidata' and path.suffix == '.html':
            new_doc = WdAnnoHtmlDocument(path=path, language=lang_from_path(path))
        else:
            raise ValueError(f"Unsupported file format for path {path} with suffix {path.suffix}")

        documents.append(new_doc)
        all_identifiers.add(new_doc.identifier)

    include_inputted_files: Optional[bool] = None
    if include_dependencies:
        include_inputted_files = True

    for document in documents:
        if include_inputted_files is False:
            break

        # currently, only local files supported
        inputted = [
            doc for doc in document.get_inputted_documents()
            if isinstance(doc, LocalFileDocument) and doc.identifier not in all_identifiers
        ]
        if inputted:
            if include_inputted_files is None:
                include_inputted_files = interface.ask_yes_no(
                    'Some of the documents input other documents. Should these also be included?'
                )
            if include_inputted_files:
                for doc in inputted:
                    if doc.identifier not in all_identifiers:
                        documents.append(doc)
                        all_identifiers.add(doc.identifier)

    if include_dependencies:   # non-input dependencies should come after input dependencies
        documents.extend(get_missing_dependencies(documents, all_identifiers))

    return documents


def get_missing_dependencies(
        documents: list[Document],
        known_doc_ids: set[str],
) -> list[Document]:
    """
    Optimized helper function. Use with care!

    Ignores input dependencies.

    known_doc_ids should include the identifiers in the document list as well.
    It will be modified by this function!

    It works in a BFS manner, which may be desirable from a user perspective
    (first annotate the immediate dependencies)
    """

    result = documents[:]

    for document in result:
        if not isinstance(document, STeXDocument):  # currently, only STeX documents have non-input dependencies
            continue

        dependencies = [
            doc for doc in document.get_dependencies(mode='noninputs')
        ]

        for doc in dependencies:
            if isinstance(doc, LocalFileDocument):
                if doc.identifier not in known_doc_ids:
                    result.append(doc)
                    known_doc_ids.add(doc.identifier)

    return result[len(documents):]  # only return the newly added documents

