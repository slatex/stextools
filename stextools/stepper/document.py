import abc
import dataclasses
from pathlib import Path
from typing import Iterable, Optional

from pylatexenc.latexwalker import LatexWalker

from stextools.stepper.html_support import MyHtmlParser
from stextools.stex.local_stex import lang_from_path
from stextools.stex.stex_py_parsing import STEX_CONTEXT_DB, get_annotatable_plaintext, get_plaintext_approx
from stextools.stex.flams import FLAMS
from stextools.utils.linked_str import LinkedStr


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
        raise NotImplementedError()

    def get_plaintext_approximation(self) -> LinkedStr:
        raise NotImplementedError()

    def get_inputted_documents(self) -> Iterable['Document']:
        r""" Returns the documents that were inputted to this document.
        (e.g. \input in LaTeX)
        """
        return []


class LocalFileDocument(Document, abc.ABC):
    _content: Optional[str] = None

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


class WdAnnoTexDocument(LocalFileDocument):
    """ A local tex document that is supposed to be annotated with WikiData annotations (not sTeX). """

    _latex_walker: Optional[LatexWalker] = None

    def __init__(self, path: Path, language: str):
        super().__init__(path, language, 'wdTeX')

    def set_content(self, content: str):
        super().set_content(content)
        self._latex_walker = None

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
            if path not in included_paths:
                file_paths.append(path)
                included_paths.add(path)

    # Step 2: create Document objects for each file
    documents: list[Document] = []

    for path in file_paths:
        if tex_format == 'sTeX' and path.suffix == '.tex':
            documents.append(STeXDocument(path=path, language=lang_from_path(path)))
        elif tex_format == 'wdTeX' and path.suffix == '.tex':
            documents.append(WdAnnoTexDocument(path=path, language=lang_from_path(path)))
        elif html_format == 'wdHTML' and path.suffix == '.html':
            documents.append(WdAnnoHtmlDocument(path=path, language=lang_from_path(path)))
        else:
            raise ValueError(f"Unsupported file format for path {path} with suffix {path.suffix}")

    return documents
