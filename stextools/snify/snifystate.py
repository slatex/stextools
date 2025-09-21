import dataclasses
from typing import Optional, Literal

from stextools.stepper.document import Document, MODE
from stextools.stepper.document_stepper import DocumentStepperState, DocumentCursor
from stextools.stepper.stepper import State
from stextools.stepper.stepper_extensions import FocussableState


@dataclasses.dataclass(frozen=True)
class SnifyCursor(DocumentCursor):
    selection: int | tuple[int, int]


class SnifyState(DocumentStepperState, FocussableState, State[SnifyCursor]):
    def __init__(self, cursor: SnifyCursor, documents: list[Document]):
        super().__init__(cursor, documents)

        # (lang, doc_id) -> [word]
        self.skip_stem_by_docid: dict[tuple[str, int], set[str]] = {}
        self.skip_by_docid: dict[tuple[str, int], set[str]] = {}
        # lang -> [word]
        self.skip_stem: dict[str, set[str]] = {}
        self.skip: dict[str, set[str]] = {}

        self.stem_focus: Optional[str] = None   # only suggest annotations for this stem (used in focus mode)
        self.focus_lang: Optional[str] = None  # only annotate documents of this language (used in focus mode)

        self.mode: MODE | Literal['both'] = 'text'   # by default, only annotate text, not formulae

    def get_skip_words(self, lang: str, doc_index: Optional[int] = None):
        from stextools.snify.skip_and_ignore import get_srskipped_cached, IgnoreList

        tmp_skip = self.skip.get(lang, set())
        tmp_doc_skip = self.skip_by_docid.get((lang, doc_index), set()) if doc_index is not None else set()
        srskipped = get_srskipped_cached(self.get_current_document().get_content()).skipped_literal
        return (
            tmp_skip
            | tmp_doc_skip
            | srskipped
            | IgnoreList.get_word_set(lang)
        )


    def get_skip_stems(self, lang: str, doc_index: Optional[int] = None):
        from stextools.snify.skip_and_ignore import get_srskipped_cached

        tmp_skip = self.skip_stem.get(lang, set())
        tmp_doc_skip = self.skip_stem_by_docid.get((lang, doc_index), set()) if doc_index is not None else set()
        srskipped = get_srskipped_cached(self.get_current_document().get_content()).skipped_stems
        return (
            tmp_skip
            | tmp_doc_skip
            | srskipped
        )


    def get_current_document(self) -> Document:
        if not self.documents:
            raise ValueError("No documents available.")
        return self.documents[self.cursor.document_index]

    def get_selected_text(self) -> str:
        document = self.get_current_document()
        selection = self.cursor.selection
        if isinstance(selection, tuple):
            start, end = selection
            return document.get_content()[start:end]
        else:
            raise Exception("Selection is not a range; cannot get selected text.")
