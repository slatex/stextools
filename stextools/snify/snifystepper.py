import functools
from typing import Optional, Iterable, cast

from stextools.snify.annotate import STeXAnnotateCommand, STeXLookupCommand, AnnotationChoices, MathAnnotationChoices, \
    TextAnnotationChoices
from stextools.snify.text_anno.catalog import Catalog
from stextools.snify.text_anno.local_stex_catalog import local_flams_stex_catalogs, \
    LocalFlamsCatalog
from stextools.snify.math_catalog import MathCatalog
from stextools.snify.skip_and_ignore import SkipCommand, SkipUntilFileEnd, SkipForRestOfSession, IgnoreCommand, \
    AddWordToSrSkip, AddStemToSrSkip
from stextools.snify.snify_commands import View_i_Command, ViewCommand, ExitFileCommand, RescanOutcome, \
    StemFocusCommand, \
    StemFocusCommandPlus, PreviousWordShouldBeIncluded, FirstWordShouldntBeIncluded, NextWordShouldBeIncluded, \
    LastWordShouldntBeIncluded, RescanCommand
from stextools.snify.snifystate import SnifyState, SnifyCursor
from stextools.snify.wikidata import get_wd_catalog, WdAnnotateCommand, WikidataMathMLCatalog, WikidataMathTexCatalog
from stextools.stepper.command import CommandCollection, CommandSectionLabel, CommandOutcome
from stextools.stepper.document import STeXDocument, Document, WdAnnoTexDocument, WdAnnoHtmlDocument, MODE
from stextools.stepper.document_stepper import DocumentModifyingStepper, EditCommand
from stextools.stepper.interface import interface, BrowserInterface
from stextools.stepper.stepper import Stepper, StopStepper, Modification
from stextools.stepper.stepper_extensions import QuittableStepper, QuitCommand, CursorModifyingStepper, UndoCommand, \
    RedoCommand, UndoableStepper, SetCursorOutcome
from stextools.utils.linked_str import LinkedStr


class SnifyStepper(DocumentModifyingStepper, QuittableStepper, CursorModifyingStepper, UndoableStepper, Stepper[SnifyState]):
    def __init__(self, state: SnifyState):
        super().__init__(state)
        self.state = state
        self.current_annotation_choices: Optional[AnnotationChoices] = None

    @functools.cache
    def get_stex_catalogs(self) -> dict[str, LocalFlamsCatalog]:
        return local_flams_stex_catalogs()

    def get_catalog_for_document(self, doc: Document) -> Optional[Catalog]:
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
                    f'No STeX catalogs available for language {doc.language!r}.'
                )
            else:
                catalog = catalogs[doc.language]
        elif isinstance(doc, WdAnnoTexDocument) or isinstance(doc, WdAnnoHtmlDocument):
            return get_wd_catalog(doc.language)
        else:
            raise ValueError(f'Unsupported document type {type(doc)}')

        if error_message:
            interface.write_text(error_message, style='error')
            interface.await_confirmation()
        if self.state.stem_focus:
            catalog = catalog.sub_catalog_for_stem(self.state.stem_focus)
        return catalog

    def get_catalog_for_current_document(self) -> Optional[Catalog]:
        """ Get the catalog for the currently selected document."""
        doc = self.state.get_current_document()
        return self.get_catalog_for_document(doc)

    def get_math_catalog_for_document(self, doc: Document) -> Optional[MathCatalog]:
        if isinstance(doc, STeXDocument):
            raise NotImplementedError("Math catalog for STeX not implemented yet.")
        elif isinstance(doc, WdAnnoHtmlDocument):
            return WikidataMathMLCatalog()
        elif isinstance(doc, WdAnnoTexDocument):
            return WikidataMathTexCatalog()
        else:
            raise ValueError(f'Unsupported document type {type(doc)}')

    def ensure_state_up_to_date(self):
        """ If cursor is a position, rather than a range, we updated it to the next relevant range."""
        cursor = self.state.cursor

        if not isinstance(cursor.selection, int):   # already have a selection
            # The selection can be modified in lots of ways (e.g. undoing/redoing).
            # So we need to ensure that the annotation choices are up to date.
            # TODO: This is a bit annoying and repetitive - is there a better way?
            doc = self.state.documents[cursor.document_index]
            # catalog = self.get_catalog_for_document(doc) if isinstance(self.current_annotation_choices, TextAnnotationChoices) else self.get_catalog_for_document(doc)
            if isinstance(self.current_annotation_choices, TextAnnotationChoices):
                catalog = self.get_catalog_for_document(doc)
                first_match = catalog.find_first_match(
                    string=doc.get_content()[cursor.selection[0]:cursor.selection[1]],
                    stems_to_ignore=self.state.get_skip_stems(doc.language, cursor.document_index),
                    words_to_ignore=self.state.get_skip_words(doc.language, cursor.document_index),
                    symbols_to_ignore=set(),
                )
            else:
                assert isinstance(self.current_annotation_choices, MathAnnotationChoices)
                catalog = self.get_math_catalog_for_document(doc)
                first_match = catalog.find_first_match(
                    doc.get_content()[cursor.selection[0]:cursor.selection[1]],
                )
            if first_match is None:
                self.current_annotation_choices = TextAnnotationChoices([])
            else:
                start, stop, options = first_match
                if isinstance(catalog, MathCatalog):
                    self.current_annotation_choices = MathAnnotationChoices(options)
                else:
                    self.current_annotation_choices = TextAnnotationChoices(options)
            return

        while cursor.document_index < len(self.state.documents):
            doc = self.state.documents[cursor.document_index]
            if self.state.focus_lang is not None and doc.language != self.state.focus_lang:
                # document has wrong language
                cursor = SnifyCursor(cursor.document_index + 1, 0)
                continue

            print(f'Processing document {doc.identifier} at index {cursor.document_index}...')
            annotatable_segments: Iterable[tuple[MODE, LinkedStr[None]]]
            match self.state.mode:
                case 'text':
                    annotatable_segments = ((cast(MODE, 'text'), segment) for segment in doc.get_annotatable_plaintext())
                case 'math':
                    annotatable_segments = ((cast(MODE, 'math'), segment) for segment in doc.get_annotatable_formulae())
                case 'both':
                    annotatable_segments = doc.get_all_annotatable()
                case _:
                    raise RuntimeError(f'Unknown mode {self.state.mode!r}')

            # catalog = self.get_catalog_for_document(doc)
            # if catalog is None:
            #     cursor = SnifyCursor(cursor.document_index + 1, 0)
            #     continue

            for mode, segment in annotatable_segments:
                if segment.get_end_ref() <= cursor.selection:
                    continue  # segment is before cursor

                if cursor.selection >= segment.get_start_ref():
                    segment = segment[segment.get_indices_from_ref_range(cursor.selection, segment.get_end_ref())[0]:]


                if mode == 'text':
                    catalog = self.get_catalog_for_document(doc)
                    if catalog is None:
                        continue
                    first_match = catalog.find_first_match(
                        string=str(segment),
                        stems_to_ignore=self.state.get_skip_stems(doc.language, cursor.document_index),
                        words_to_ignore=self.state.get_skip_words(doc.language, cursor.document_index),
                        symbols_to_ignore=set(),
                    )
                else:
                    assert mode == 'math'
                    catalog = self.get_math_catalog_for_document(doc)
                    if catalog is None:
                        continue
                    first_match = catalog.find_first_match(
                        string=str(segment),
                    )


                if first_match is None:
                    continue

                start, stop, options = first_match
                subsegment = segment[start:stop]
                if isinstance(catalog, MathCatalog):
                    self.current_annotation_choices = MathAnnotationChoices(options)
                else:
                    self.current_annotation_choices = TextAnnotationChoices(options)
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
        if isinstance(interface.get_object(), BrowserInterface) and isinstance(doc, WdAnnoHtmlDocument):
            # render the HTML, rather than its source
            if isinstance(self.state.cursor.selection, tuple):
                a, b = self.state.cursor.selection
                content = (
                        doc.get_content()[doc.get_body_range()[0]:a] +
                        '<span class="highlight" id="snifyhighlight">' +  # TODO: in MathML, this works but is not ideal
                        doc.get_content()[a:b] +
                        '</span>' +
                        doc.get_content()[b:doc.get_body_range()[1]]
                )
            else:
                content = doc.get_body_content()
            interface.write_text(
                '<div style="border: 1px solid black; padding: 5px; margin: 5px; max-height: 40vh; overflow: auto;">' +
                 content +
                '</div>' + r'''
                ''',
                prestyled=True,
            )
        else:
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
        is_stex = isinstance(document, STeXDocument)
        is_wdanno = isinstance(document, WdAnnoTexDocument) or isinstance(document, WdAnnoHtmlDocument)

        # If first edit is before cursor: set cursor to first edit position
        # else: set to current position, to run reselection logic
        set_cursor_after_edit = lambda pos: [
            SetCursorOutcome(SnifyCursor(self.state.cursor.document_index, pos))
        ] if pos <= self.state.cursor.selection[0] else [
            SetCursorOutcome(SnifyCursor(self.state.cursor.document_index, self.state.cursor.selection[0]))
        ]

        # is_html = isinstance(document, WdAnnoHtmlDocument)
        # is_tex = isinstance(document, WdAnnoTexDocument) or isinstance(document, STeXDocument)
        return CommandCollection(
            'snify',
            [
                QuitCommand(),
                ExitFileCommand(self.state),
                UndoCommand(is_possible=bool(self.modification_history)),
                RedoCommand(is_possible=bool(self.modification_future)),

                CommandSectionLabel('\nAnnotation'),
                STeXAnnotateCommand(
                    self.state, cast(TextAnnotationChoices, self.current_annotation_choices), catalog, self
                ) if is_stex else None,
                WdAnnotateCommand(self.state, self.current_annotation_choices, catalog) if is_wdanno else None,
                STeXLookupCommand(self.state, catalog, self) if is_stex else None,


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
                View_i_Command(self.current_annotation_choices.choices) if isinstance(self.current_annotation_choices, TextAnnotationChoices) else None,
                EditCommand(1, document, set_cursor_after_edit),
                EditCommand(2, document, set_cursor_after_edit),
                RescanCommand() if is_stex else None,
            ],
            have_help=True
        )

    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification]:
        if isinstance(outcome, RescanOutcome):
            self.get_stex_catalogs.cache_clear()
            return None

        return super().handle_command_outcome(outcome)

