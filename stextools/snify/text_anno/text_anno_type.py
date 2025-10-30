import dataclasses
import functools
from typing import Optional, Literal

from stextools.snify.annotype import AnnoType, StateType
from stextools.snify.displaysupport import display_snify_header, display_text_selection
from stextools.snify.new_snify_state import NewSnifyState
from stextools.snify.snifystate import SnifyState
from stextools.snify.text_anno.catalog import Catalog
from stextools.snify.text_anno.local_stex_catalog import LocalFlamsCatalog, local_flams_stex_catalogs
from stextools.snify.wikidata import get_wd_catalog
from stextools.stepper.command import CommandCollection
from stextools.stepper.document import Document, STeXDocument, WdAnnoTexDocument, WdAnnoHtmlDocument
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification


@functools.cache
def _get_stex_catalogs() -> dict[str, LocalFlamsCatalog]:
    return local_flams_stex_catalogs()


@functools.cache
def get_catalog_for_lang(anno_format: str, lang: str) -> Optional[Catalog]:
    if anno_format == 'stex':
        catalogs = _get_stex_catalogs()
        if not catalogs:
            error_message = 'Error: No STeX catalogs available.'
        elif lang not in catalogs:
            error_message = f'Error: No STeX catalogs available for language {lang!r}.'
        else:
            return catalogs.get(lang)
        interface.write_text(error_message, 'error')
        interface.await_confirmation()
        return None
    elif anno_format == 'wikidata':
        return get_wd_catalog(lang)
    else:
        raise ValueError(f'Unknown annotation format: {anno_format}')


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


    def get_skip_words(self, lang: str, doc_index: Optional[int] = None, doc_content: Optional[str] = None):
        from stextools.snify.skip_and_ignore import get_srskipped_cached, IgnoreList

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
        from stextools.snify.skip_and_ignore import get_srskipped_cached

        tmp_skip = self.skip_stem.get(lang, set())
        tmp_doc_skip = self.skip_stem_by_docid.get((lang, doc_index), set()) if doc_index is not None else set()
        srskipped = get_srskipped_cached(doc_content).skipped_stems if doc_content is not None else set()
        return (
                tmp_skip
                | tmp_doc_skip
                | srskipped
        )

@dataclasses.dataclass
class TextAnnoSetSelectionModification(Modification):
    anno_type_name: str
    old_selection: tuple[int, int] | None = None
    new_selection: tuple[int, int] | None = None

    def apply(self, state: NewSnifyState):
        tas: TextAnnoState = state.annotype_states[self.anno_type_name]
        tas.selection = self.new_selection

    def unapply(self, state: NewSnifyState):
        tas: TextAnnoState = state.annotype_states[self.anno_type_name]
        tas.selection = self.old_selection




class TextAnnoType(AnnoType[TextAnnoState]):
    def __init__(self, anno_format: Literal['stex', 'wikidata']):
        self.anno_format = anno_format

    @property
    def name(self) -> str:
        return f'text-anno-{self.anno_format}'

    def get_initial_state(self) -> TextAnnoState:
        return TextAnnoState()

    def is_applicable(self, document: Document) -> bool:
        if 'text' not in self.snify_state.mode:
            return False
        if self.anno_format == 'stex':
            return isinstance(document, STeXDocument)
        elif self.anno_format == 'wikidata':
            return isinstance(document, WdAnnoTexDocument) or isinstance(document, WdAnnoHtmlDocument)
        raise ValueError(f'Unknown annotation format: {self.anno_format}')

    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        catalog = get_catalog_for_lang(self.anno_format, document.language)
        if catalog is None:
            return None

        for segment in document.get_annotatable_plaintext():
            if segment.get_end_ref() <= position:
                continue  # segment is before cursor

            # truncate segment to exclude everything before position
            if position >= segment.get_start_ref():
                segment = segment[segment.get_indices_from_ref_range(position, segment.get_end_ref())[0]:]

            first_match = catalog.find_first_match(
                string=str(segment),
                stems_to_ignore=self.state.get_skip_stems(document.language, self.snify_state.cursor.document_index,
                                                          document.get_content()),
                words_to_ignore=self.state.get_skip_words(document.language, self.snify_state.cursor.document_index,
                                                          document.get_content()),
                symbols_to_ignore=set(),
            )
            if first_match is not None:
                match_start_in_segment, match_end_in_segment, match_info = first_match
                sub_segment = segment[match_start_in_segment:match_end_in_segment]

                setup_modifications: list[Modification] = []

                # set selection
                setup_modifications.append(
                    TextAnnoSetSelectionModification(
                        anno_type_name=self.name,
                        old_selection=self.state.selection,
                        new_selection=(sub_segment.get_start_ref(), sub_segment.get_end_ref()),
                    )
                )

                return sub_segment.get_start_ref(), setup_modifications

    def rescan(self):
        _get_stex_catalogs.cache_clear()
        get_catalog_for_lang.cache_clear()

    def get_command_collection(self) -> CommandCollection:
        return CommandCollection(
            f'snify:{self.name}',
            [

            ],
            have_help=True
        )

    def show_current_state(self):
        interface.clear()
        display_snify_header(self.snify_state)
        display_text_selection(self.snify_state.get_current_document(), self.state.selection)
        interface.newline()
