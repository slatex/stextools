import functools
from typing import Optional, Any

from stextools.snify.annotate import STeXAnnotateCommand, STeXLookupCommand
from stextools.snify.catalog import Catalog, Verbalization
from stextools.snify.local_stex_catalog import local_flams_stex_catalogs, \
    LocalFlamsCatalog
from stextools.snify.skip_and_ignore import SkipCommand, SkipUntilFileEnd, SkipForRestOfSession, IgnoreCommand, \
    AddWordToSrSkip, AddStemToSrSkip
from stextools.snify.snify_commands import View_i_Command, ViewCommand, ExitFileCommand, RescanOutcome, StemFocusCommand, \
    StemFocusCommandPlus, PreviousWordShouldBeIncluded, FirstWordShouldntBeIncluded, NextWordShouldBeIncluded, \
    LastWordShouldntBeIncluded
from stextools.snify.snifystate import SnifyState, SnifyCursor
from stextools.stepper.command import CommandCollection, CommandSectionLabel, CommandOutcome
from stextools.stepper.document import STeXDocument, Document
from stextools.stepper.document_stepper import DocumentModifyingStepper
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Stepper, StopStepper, Modification
from stextools.stepper.stepper_extensions import QuittableStepper, QuitCommand, CursorModifyingStepper, UndoCommand, \
    RedoCommand, UndoableStepper


class SnifyStepper(DocumentModifyingStepper, QuittableStepper, CursorModifyingStepper, UndoableStepper, Stepper[SnifyState]):
    def __init__(self, state: SnifyState):
        super().__init__(state)
        self.state = state
        self.current_annotation_choices: Optional[list[tuple[Any, Verbalization]]] = None

    @functools.cache
    def get_stex_catalogs(self) -> dict[str, LocalFlamsCatalog]:
        return local_flams_stex_catalogs()

    def get_catalog_for_document(self, doc: Document) -> Optional[LocalFlamsCatalog]:
        error_message: Optional[str] = None
        catalog: Optional[Catalog] = None

        if isinstance(doc, STeXDocument):
            catalogs = self.get_stex_catalogs()
            if not catalogs:
                error_message = (
                    f'Error when processing {doc.identifier}:\n'
                    'No STeX catalogs available.'
                )
            elif doc.language not in catalogs:
                error_message = (
                    f'Error when processing {doc.identifier}:\n'
                    'No STeX catalogs available for language {doc.language}.'
                )
            else:
                catalog = catalogs[doc.language]
        else:
            raise ValueError(f'Unsupported document type {type(doc)}')

        if error_message:
            interface.write_text(error_message, style='error')
            interface.await_confirmation()
        if self.state.stem_focus:
            catalog = catalog.sub_catalog_for_stem(self.state.stem_focus)
        return catalog

    def get_catalog_for_current_document(self) -> Optional[LocalFlamsCatalog]:
        """ Get the catalog for the currently selected document."""
        doc = self.state.get_current_document()
        return self.get_catalog_for_document(doc)

    def ensure_state_up_to_date(self):
        """ If cursor is a position, rather than a range, we updated it to the next relevant range."""
        cursor = self.state.cursor

        if not isinstance(cursor.selection, int):   # already have a selection
            # The selection can be modified in lots of ways (e.g. undoing/redoing).
            # So we need to ensure that the annotation choices are up to date.
            # TODO: This is a bit annoying and repetitive - is there a better way?
            doc = self.state.documents[cursor.document_index]
            catalog = self.get_catalog_for_document(doc)
            first_match = catalog.find_first_match(
                string=doc.get_content()[cursor.selection[0]:cursor.selection[1]],
                stems_to_ignore=self.state.get_skip_stems(doc.language, cursor.document_index),
                words_to_ignore=self.state.get_skip_words(doc.language, cursor.document_index),
                symbols_to_ignore=set(),
            )
            if first_match is None:
                self.current_annotation_choices = []
            else:
                start, stop, options = first_match
                self.current_annotation_choices = options
            return

        while cursor.document_index < len(self.state.documents):
            doc = self.state.documents[cursor.document_index]
            if self.state.focus_lang is not None and doc.language != self.state.focus_lang:
                # document has wrong language
                cursor = SnifyCursor(cursor.document_index + 1, 0)
                continue

            print(f'Processing document {doc.identifier} at index {cursor.document_index}...')
            annotatable_segments = doc.get_annotatable_plaintext()

            catalog = self.get_catalog_for_document(doc)
            if catalog is None:
                cursor = SnifyCursor(cursor.document_index + 1, 0)
                continue

            for segment in annotatable_segments:
                if segment.get_end_ref() <= cursor.selection:
                    continue  # segment is before cursor

                if cursor.selection >= segment.get_start_ref():
                    segment = segment[segment.get_indices_from_ref_range(cursor.selection, segment.get_end_ref())[0]:]

                first_match = catalog.find_first_match(
                    string=str(segment),
                    stems_to_ignore=self.state.get_skip_stems(doc.language, cursor.document_index),
                    words_to_ignore=self.state.get_skip_words(doc.language, cursor.document_index),
                    symbols_to_ignore=set(),
                )

                if first_match is None:
                    continue

                start, stop, options = first_match
                subsegment = segment[start:stop]
                self.current_annotation_choices = options
                self.state.cursor = SnifyCursor(
                    cursor.document_index,
                    selection=(subsegment.get_start_ref(), subsegment.get_end_ref())
                )
                return

            # nothing found in this document; move to the next one
            cursor = SnifyCursor(cursor.document_index + 1, 0)

        interface.clear()
        interface.write_text('There is nothing left to annotate.\n')
        if self.state.on_unfocus:
            interface.write_text('Ending focus mode.\n')
            interface.await_confirmation()
            self.state = self.state.on_unfocus
        else:
            interface.write_text('Quitting snify.\n')
            interface.await_confirmation()
            raise StopStepper('done')


    def show_current_state(self):
        doc = self.state.get_current_document()
        interface.clear()
        interface.write_header(
            doc.identifier
        )
        interface.show_code(
            doc.get_content(),
            doc.format,  # type: ignore
            highlight_range=self.state.cursor.selection if isinstance(self.state.cursor.selection, tuple) else None,
            limit_range=5,
        )
        interface.newline()

    def get_current_command_collection(self) -> CommandCollection:
        catalog = self.get_catalog_for_current_document()
        document = self.state.get_current_document()
        assert catalog is not None
        return CommandCollection(
            'snify',
            [
                QuitCommand(),
                ExitFileCommand(self.state),
                UndoCommand(is_possible=bool(self.modification_history)),
                RedoCommand(is_possible=bool(self.modification_future)),

                CommandSectionLabel('\nAnnotation'),
                STeXAnnotateCommand(self.state, self.current_annotation_choices, catalog, self),
                STeXLookupCommand(self.state, catalog, self),

                CommandSectionLabel('\nSelection modification'),
                PreviousWordShouldBeIncluded(self.state),
                FirstWordShouldntBeIncluded(self.state),
                NextWordShouldBeIncluded(self.state),
                LastWordShouldntBeIncluded(self.state),

                CommandSectionLabel('\nSkipping'),
                SkipCommand(self.state),
                SkipUntilFileEnd(self.state),
                SkipForRestOfSession(self.state),
                IgnoreCommand(self.state),
                AddWordToSrSkip(self.state),
                AddStemToSrSkip(self.state),

                CommandSectionLabel('\nFocussing'),
                StemFocusCommand(self),
                StemFocusCommandPlus(self),

                CommandSectionLabel('\nViewing and editing'),
                ViewCommand(document),
                View_i_Command(self.current_annotation_choices),
            ],
            have_help=True
        )

    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification]:
        if isinstance(outcome, RescanOutcome):
            self.get_stex_catalogs.cache_clear()
            return None

        return super().handle_command_outcome(outcome)

