import fnmatch
import functools
from typing import Optional, Literal, cast

from stextools.config import get_config
from stextools.snify.annotype import AnnoType, StepperStatus
from stextools.snify.displaysupport import display_snify_header, display_text_selection
from stextools.snify.text_anno.annotate import AnnotationCandidates, TextAnnotationCandidates, STeXAnnotateCommand, \
    STeXLookupCommand
from stextools.snify.text_anno.change_selection_commands import PreviousWordShouldBeIncluded, \
    FirstWordShouldntBeIncluded, NextWordShouldBeIncluded, LastWordShouldntBeIncluded
from stextools.snify.text_anno.replace_command import ReplaceCommand
from stextools.snify.text_anno.skip_and_ignore import SkipUntilFileEnd, SkipForRestOfSession, IgnoreCommand, \
    AddWordToSrSkip, AddStemToSrSkip, StemFocusCommand
from stextools.snify.snify_commands import ExitFileCommand, SkipCommand, ViewCommand, RescanCommand, \
    get_set_cursor_after_edit_function, View_i_Command
from stextools.snify.text_anno.catalog import Catalog
from stextools.snify.text_anno.local_stex_catalog import LocalFlamsCatalog, local_flams_stex_catalogs, LocalStexSymbol
from stextools.snify.text_anno.text_anno_state import TextAnnoState, TextAnnoSetSelectionModification
from stextools.snify.wikidata import get_wd_catalog, WdAnnotateCommand
from stextools.stepper.command import CommandCollection, CommandSectionLabel
from stextools.stepper.document import Document, STeXDocument, WdAnnoTexDocument, WdAnnoHtmlDocument, LocalFileDocument
from stextools.stepper.document_stepper import EditCommand
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import QuitCommand, UndoCommand, RedoCommand
from stextools.stex.local_stex import FlamsUri
from stextools.utils.timer import timelogger


@functools.cache
def _get_stex_catalogs() -> dict[str, LocalFlamsCatalog]:
    return local_flams_stex_catalogs()


@functools.cache
def _get_catalog_for_lang(anno_format: str, lang: str) -> Optional[Catalog]:
    if anno_format == 'stex':
        catalogs = _get_stex_catalogs()
        if not catalogs:
            error_message = 'Error: No STeX catalogs available.'
        elif lang not in catalogs:
            error_message = f'Error: No STeX catalogs available for language {lang!r}.'
        else:
            return catalogs[lang]

        interface.write_text(error_message, 'error')
        interface.await_confirmation()
        return None
    elif anno_format == 'wikidata':
        return get_wd_catalog(lang)
    else:
        raise ValueError(f'Unknown annotation format: {anno_format}')


def get_catalog_for_lang(anno_format: str, lang: str, stem_focus: Optional[str]) -> Optional[Catalog]:
    catalog = _get_catalog_for_lang(anno_format, lang)
    if catalog is not None and stem_focus is not None:
        catalog = catalog.sub_catalog_for_stem(stem_focus)
    return catalog


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
        catalog = get_catalog_for_lang(self.anno_format, document.language, self.state.stem_focus)
        if catalog is None:
            return None

        for segment in document.get_annotatable_plaintext():
            if segment.get_end_ref() <= position:
                continue  # segment is before cursor

            # truncate segment to exclude everything before position
            if position >= segment.get_start_ref():
                cutoff = segment.get_indices_from_ref_range(position, segment.get_end_ref())[0]
                # Idea: do not cut in the middle of a word.
                # Otherwise, we might get matches that start in the middle of a word.
                if cutoff > 0:
                    while cutoff < len(segment) and str(segment[cutoff - 1]).isalnum():
                        cutoff += 1
                segment = segment[cutoff:]

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
        _get_catalog_for_lang.cache_clear()
        self.get_annotation_candidates_actual.cache_clear()
    
    @functools.lru_cache(1)
    def get_annotation_candidates_actual(self, doc_id: int, doc_content: str, position: int) -> AnnotationCandidates:
        """
        Basic idea:
        The annotation candidates should not be re-computed too often.
        For example, if the selection is modified, we still want to display the original candidates.
        Nevertheless, re-computation is sometimes necessary.
        The hope is that this (not too carefully designed) caching mechanism strikes a good balance.
        """
        assert position >= 0
        document = self.snify_state.documents[doc_id]
        catalog = get_catalog_for_lang(self.anno_format, document.language, self.state.stem_focus)
        assert catalog is not None
        _, _, candidates = catalog.find_first_match(
            string=str(doc_content[self.state.selection[0]:self.state.selection[1]]),
            stems_to_ignore=self.state.get_skip_stems(document.language, self.snify_state.cursor.document_index,
                                                      document.get_content()),
            words_to_ignore=self.state.get_skip_words(document.language, self.snify_state.cursor.document_index,
                                                      document.get_content()),
            symbols_to_ignore=set(),
        ) or (-1, -1, [])
        return TextAnnotationCandidates(candidates)


    def get_annotation_candidates(self) -> AnnotationCandidates:
        return self.get_annotation_candidates_actual(
            doc_id=self.snify_state.cursor.document_index,
            doc_content=self.snify_state.get_current_document().get_content(),
            position=self.snify_state.cursor.in_doc_pos,
        )

    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        document = self.snify_state.get_current_document()
        # no stem focus (commands may need full catalog)
        catalog = get_catalog_for_lang(self.anno_format, document.language, None)

        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                ExitFileCommand(self.snify_state),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),

                CommandSectionLabel('\nAnnotation'),
                STeXAnnotateCommand(
                    self.snify_state, cast(TextAnnotationCandidates, self.get_annotation_candidates()), catalog,
                    self.show_current_state, self.name
                ) if self.anno_format == 'stex' else None,
                WdAnnotateCommand(
                    self.snify_state, self.get_annotation_candidates(), catalog, self.name
                ) if self.anno_format == 'wikidata' else None,
                STeXLookupCommand(self.snify_state, catalog, self.show_current_state, self.name) if self.anno_format == 'stex' else None,

                CommandSectionLabel('\nSelection modification'),
                PreviousWordShouldBeIncluded(self.snify_state, self.name),
                FirstWordShouldntBeIncluded(self.snify_state, self.name),
                NextWordShouldBeIncluded(self.snify_state, self.name),
                LastWordShouldntBeIncluded(self.snify_state, self.name),

                CommandSectionLabel('\nSkipping'),
                SkipCommand(self.snify_state),
                SkipUntilFileEnd(self.snify_state, self.name),
                SkipForRestOfSession(self.snify_state, self.name),
                IgnoreCommand(self.snify_state, self.name),
                AddWordToSrSkip(self.snify_state, self.name),
                AddStemToSrSkip(self.snify_state, self.name),

                CommandSectionLabel('\nFocussing'),
                StemFocusCommand(stepper_status.stepper_ref, scope='file', anno_type_name=self.name),
                StemFocusCommand(stepper_status.stepper_ref, scope='remaining_files', anno_type_name=self.name),

                CommandSectionLabel('\nViewing and editing'),
                ViewCommand(document),
                View_i_Command(self.get_annotation_candidates().candidates)
                    if isinstance(self.get_annotation_candidates(), TextAnnotationCandidates)
                    else None,
                ReplaceCommand(self.snify_state, self.name) if isinstance(document, LocalFileDocument) else None,
                EditCommand(
                    1, document, get_set_cursor_after_edit_function(self.snify_state)
                ) if isinstance(document, LocalFileDocument) else None,
                EditCommand(
                    2, document, get_set_cursor_after_edit_function(self.snify_state)
                ) if isinstance(document, LocalFileDocument) else None,
                RescanCommand(),
            ],
            have_help=True
        )

    def show_current_state(self):
        # if stex catalogs are not loaded (e.g. when resuming a session),
        # the interface would be polluted with flams logs
        _get_stex_catalogs()
        interface.clear()
        display_snify_header(self.snify_state)
        display_text_selection(self.snify_state.get_current_document(), self.state.selection)
        interface.newline()
