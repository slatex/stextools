import dataclasses
from typing import Optional

from stextools.snify.snify_state import SnifyState
from stextools.stepper.command import CommandOutcome
from stextools.stepper.stepper import Modification


@dataclasses.dataclass
class TextAnnoState:
    selection: tuple[int, int] | None = None

    # *skipped temporarily in document/session*
    # (lang, doc_id) -> [word]
    skip_stem_by_docid: dict[tuple[str, int], set[str]] = dataclasses.field(default_factory=dict)
    skip_by_docid: dict[tuple[str, int], set[str]] = dataclasses.field(default_factory=dict)
    # lang -> [word]
    skip_stem: dict[str, set[str]] = dataclasses.field(default_factory=dict)
    skip: dict[str, set[str]] = dataclasses.field(default_factory=dict)

    # *focus details*
    stem_focus: Optional[str] = None  # only suggest annotations for this stem (used in focus mode)
    focus_lang: Optional[str] = None  # only annotate documents of this language (used in focus mode)

    def get_selected_text(self, snify_state: SnifyState) -> Optional[str]:
        if self.selection is None:
            return None
        start, end = self.selection
        document = snify_state.documents[snify_state.cursor.document_index]
        return document.get_content()[start:end]



    def get_skip_words(self, lang: str, doc_index: Optional[int] = None, doc_content: Optional[str] = None):
        from stextools.snify.text_anno.skip_and_ignore import get_srskipped_cached, IgnoreList

        tmp_skip = self.skip.get(lang, set())
        tmp_doc_skip = self.skip_by_docid.get((lang, doc_index), set()) if doc_index is not None else set()
        srskipped = get_srskipped_cached(doc_content).skipped_literal if doc_content is not None else set()
        return (
                tmp_skip
                | tmp_doc_skip
                | srskipped
                | IgnoreList.get_word_set(lang)
        )


    def get_skip_stems(self, lang: str, doc_index: Optional[int] = None, doc_content: Optional[str] = None):
        from stextools.snify.text_anno.skip_and_ignore import get_srskipped_cached

        tmp_skip = self.skip_stem.get(lang, set())
        tmp_doc_skip = self.skip_stem_by_docid.get((lang, doc_index), set()) if doc_index is not None else set()
        srskipped = get_srskipped_cached(doc_content).skipped_stems if doc_content is not None else set()
        return (
                tmp_skip
                | tmp_doc_skip
                | srskipped
        )


@dataclasses.dataclass
class TextAnnoSetSelectionModification(Modification, CommandOutcome):
    anno_type_name: str
    old_selection: tuple[int, int] | None = None
    new_selection: tuple[int, int] | None = None

    def apply(self, state: SnifyState):
        tas: TextAnnoState = state.annotype_states[self.anno_type_name]
        tas.selection = self.new_selection

    def unapply(self, state: SnifyState):
        tas: TextAnnoState = state.annotype_states[self.anno_type_name]
        tas.selection = self.old_selection
