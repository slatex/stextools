import abc
import dataclasses
from pathlib import Path
from typing import Iterable, Optional

from pylatexenc.latexwalker import LatexWalker

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


class STeXDocument(Document):
    """ A local stex document. """
    _content: Optional[str] = None
    _latex_walker: Optional[LatexWalker] = None

    def __init__(self, path: Path, language: str):
        self.path = path
        super().__init__(
            identifier=str(path.resolve().absolute()),
            format='sTeX',
            language=language
        )

    def get_content(self) -> str:
        if self._content is None:
            self._content = self.path.read_text()
        return self._content

    def set_content(self, content: str):
        self.write_content(content)
        self._latex_walker = None
        FLAMS.load_file(self.identifier)


    def get_latex_walker(self) -> LatexWalker:
        """ Returns a LatexWalker for the document content. """
        if self._latex_walker is None:
            content = self.get_content()
            self._latex_walker = LatexWalker(content, latex_context=STEX_CONTEXT_DB)
        return self._latex_walker

    def write_content(self, content: str) -> None:
        """ Writes the content to the file. """
        self.path.write_text(content)
        self._content = content
        self._latex_walker = None

    def get_annotatable_plaintext(self) -> Iterable[LinkedStr[None]]:
        return get_annotatable_plaintext(
            self.get_latex_walker()
        )

    def get_plaintext_approximation(self) -> LinkedStr:
        return get_plaintext_approx(self.get_latex_walker())


def documents_from_paths(
        paths: list[Path]
) -> list[Document]:
    included_paths: set[Path] = set()

    # Step 1: make a list of all relevant files
    file_paths: list[Path] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Path {path} does not exist.")
        files = [path] if path.is_file() else path.rglob('*.tex')
        for path in files:
            if path not in included_paths:
                file_paths.append(path)
                included_paths.add(path)

    # Step 2: create Document objects for each file
    documents = [
        STeXDocument(path=path, language=lang_from_path(path))
        for path in file_paths
    ]

    return documents
