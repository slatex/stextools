import abc
import dataclasses
import itertools
from pathlib import Path
from typing import Iterable, Optional, TypeAlias, Literal, cast

from pylatexenc.latexwalker import LatexWalker, LatexMathNode, LatexCommentNode, LatexSpecialsNode, LatexMacroNode, \
    LatexEnvironmentNode, LatexGroupNode, LatexCharsNode

from stextools.remote_repositories import get_mathhub_path, get_containing_archive
from stextools.stepper.html_support import MyHtmlParser
from stextools.stepper.interface import interface
from stextools.stex.local_stex import lang_from_path
from stextools.stex.stex_py_parsing import STEX_CONTEXT_DB, get_annotatable_plaintext, get_plaintext_approx, \
    PLAINTEXT_EXTRACTION_MACRO_RECURSION, PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES
from stextools.stex.flams import FLAMS
from stextools.utils.json_iter import json_iter
from stextools.utils.linked_str import LinkedStr, string_to_lstr

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

    def write_content(self, content: str) -> None:
        """ Writes the content to the file. """
        self.path.write_text(content)
        self._content = content


class STeXDocument(LocalFileDocument):
    """ A local stex document. """
    _latex_walker: Optional[LatexWalker] = None

    def __init__(self, path: Path, language: str):
        super().__init__(path, language, 'sTeX')

    def set_content(self, content: str):
        super().set_content(content)
        self._latex_walker = None
        FLAMS.load_file(self.identifier)


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

    def get_plaintext_approximation(self) -> LinkedStr:
        return get_plaintext_approx(self.get_latex_walker())

    def get_inputted_documents(self) -> Iterable['Document']:
        annos = FLAMS.get_file_annotations(self.path)
        for e in json_iter(annos, {'full_range', 'val_range', 'key_range', 'Sig', 'smodule_range', 'Title',
                                   'path_range', 'archive_range', 'UseModule', 'ImportModule'}):
            if not isinstance(e, dict):
                continue
            if not ('IncludeProblem' in e or 'Inputref' in e):
                continue
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
        tex_format: str = 'sTeX',    # or 'wdTeX' to use wikidata annotation format
        html_format: Optional[str] = None,  # 'wdHTML' to use wikidata annotation format for HTML files
) -> list[Document]:
    included_paths: set[Path] = set()

    # Step 1: make a list of all relevant files
    file_paths: list[Path] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Path {path} does not exist.")
        if path.is_file():
            files = [path]
        else:
            files = list(path.rglob('*.tex'))
            if html_format is not None:
                for html_path in path.rglob('*.html'):
                    files.append(html_path)

        for path in files:
            path = path.resolve()
            if path not in included_paths:
                file_paths.append(path)
                included_paths.add(path)

    # Step 2: create Document objects for each file
    documents: list[Document] = []

    for path in file_paths:
        if tex_format == 'sTeX' and path.suffix == '.tex':
            new_doc = STeXDocument(path=path, language=lang_from_path(path))
        elif tex_format == 'wdTeX' and path.suffix == '.tex':
            new_doc = WdAnnoTexDocument(path=path, language=lang_from_path(path))
        elif html_format == 'wdHTML' and path.suffix == '.html':
            new_doc = WdAnnoHtmlDocument(path=path, language=lang_from_path(path))
        else:
            raise ValueError(f"Unsupported file format for path {path} with suffix {path.suffix}")

        documents.append(new_doc)

    include_inputted_files: Optional[bool] = None

    for document in documents:
        if include_inputted_files is False:
            break

        # currently, only local files supported
        inputted = [
            doc for doc in document.get_inputted_documents()
            if isinstance(doc, LocalFileDocument) and doc.path.resolve not in included_paths
        ]
        if inputted:
            if include_inputted_files is None:
                include_inputted_files = interface.ask_yes_no('Some of the documents input other documents. Should these also be included?')
            if include_inputted_files:
                for doc in inputted:
                    rp = doc.path.resolve()
                    if rp not in included_paths:
                        documents.append(doc)
                        included_paths.add(rp)

    return documents
