from copy import deepcopy
from pathlib import Path
from typing import Sequence, Any

from stextools.snify.catalog import Verbalization
from stextools.snify.snifystate import SnifyCursor, SnifyState
from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified, mystem, string_to_stemmed_word_sequence
from stextools.stepper.document import Document
from stextools.snify.local_stex_catalog import LocalStexSymbol
from stextools.stepper.command import CommandOutcome, Command, CommandInfo
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Stepper
from stextools.stepper.stepper_extensions import SetCursorOutcome, FocusOutcome


class ImportCommand(Command):
    def __init__(self, letter: str, description_short: str, description_long: str, outcome: SubstitutionOutcome,
                 redundancies: list[SubstitutionOutcome]):
        super().__init__(CommandInfo(
            pattern_presentation=letter,
            description_short=description_short,
            description_long=description_long)
        )
        self.outcome = outcome
        self.redundancies = redundancies

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        cmds: list[SubstitutionOutcome] = self.redundancies + [self.outcome]
        cmds.sort(key=lambda x: x.start_pos, reverse=True)
        return cmds


class View_i_Command(Command):
    def __init__(self, options: list[tuple[Any, Verbalization]]):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='v𝑖',
            pattern_regex='^v[0-9]+$',
            description_short=' view document for 𝑖',
            description_long='Displays the document that introduces symbol no. 𝑖')
        )
        self.options = options

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        i = int(call[1:])
        if i >= len(self.options):
            interface.admonition('Invalid number', 'error', True)
            return []

        symbol = self.options[i][0]
        if not isinstance(symbol, LocalStexSymbol):
            interface.admonition(f'Unsupported symbol type {type(symbol)}', 'error', True)
            return []

        with interface.big_infopage():
            interface.write_header(symbol.path)
            interface.show_code(
                Path(symbol.path).read_text(),
                format='sTeX',
                show_line_numbers=True,
            )
        return []


class ViewCommand(Command):
    def __init__(self, current_document: Document):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='v',
            description_short='iew file',
            description_long='Show the current file fully')
        )
        self.current_document = current_document

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        with interface.big_infopage():
            interface.write_header(self.current_document.identifier)
            interface.show_code(
                self.current_document.get_content(),
                self.current_document.format,  # type: ignore
                show_line_numbers=True,
            )
        return []


class ExitFileCommand(Command):
    def __init__(self, state: SnifyState):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='X',
            description_short=' Exit file',
            description_long='Exits the current file (and continues with the next one)')
        )
        self.state = state

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        return [SetCursorOutcome(SnifyCursor(self.state.cursor.document_index + 1, 0))]


class RescanOutcome(CommandOutcome):
    pass


class RescanCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='R',
            description_short='escan',
            description_long='Rescans some local files (useful if files were modified externally)\n' +
                             'For a more complete reset, quit the program and clear the cache.'
        ))

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        return [RescanOutcome()]


class StemFocusCommand(Command):
    def __init__(self, stepper: Stepper):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='f',
            description_short='ocus on stem',
            description_long='Look for other occurrences of the current stem in the current file')
        )
        self.stepper = stepper

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        state = self.stepper.state
        assert isinstance(state, SnifyState)
        new_state = deepcopy(state)   # TODO: This is inefficient (copies and then discards entire stack)
        new_state.on_unfocus = None
        new_state.documents = [state.get_current_document()]
        new_state.stem_focus = mystem(state.get_selected_text(), state.get_current_document().language)
        new_state.focus_lang = state.get_current_document().language

        return [
            # do not want to return to old selection
            FocusOutcome(new_state, self.stepper),
            SetCursorOutcome(SnifyCursor(state.cursor.document_index, state.cursor.selection[0])),
        ]


class StemFocusCommandPlus(Command):
    # TODO: Merge this with StemFocusCommand
    def __init__(self, stepper: Stepper):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='f!',
            description_short='ocus on stem in all remaining files',
            description_long='Look for other occurrences of the current stem in the remaining files')
        )
        self.stepper = stepper

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        state = self.stepper.state
        assert isinstance(state, SnifyState)
        new_state = deepcopy(state)   # TODO: This is inefficient (copies and then discards entire stack)
        new_state.on_unfocus = None
        new_state.stem_focus = mystem(state.get_selected_text(), state.get_current_document().language)
        new_state.focus_lang = state.get_current_document().language

        return [
            FocusOutcome(new_state, self.stepper),
            SetCursorOutcome(SnifyCursor(state.cursor.document_index, state.cursor.selection[0])),
        ]


class PreviousWordShouldBeIncluded(Command):
    def __init__(self, state: SnifyState):
        self.state = state
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='p',
            description_short='revious token should be included',
            description_long='Extends the selection to include the previous token.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.state
        doc = state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.cursor.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_end_ref() <= state.cursor.selection[0]:
                    i += 1
                if i == 0:
                    interface.admonition(
                        'Already at beginning of possible selection range.',
                        'error',
                        confirm=True
                    )
                    return []
                return [SetCursorOutcome(SnifyCursor(
                    state.cursor.document_index,
                    (words[i - 1].get_start_ref(), state.cursor.selection[1]),
                ))]
        raise RuntimeError('Somehow I did not find the previous word.')


class FirstWordShouldntBeIncluded(Command):
    def __init__(self, state: SnifyState):
        self.state = state
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='P',
            description_short=' exclude first selected token',
            description_long='Opposite of [p]. Excludes the first token from the selection.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.state
        doc = state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.cursor.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_end_ref() <= state.cursor.selection[0]:
                    i += 1
                new_start = words[i + 1].get_start_ref()
                if new_start >= state.cursor.selection[1]:
                    interface.admonition('Selection is getting too small', 'error', confirm=True)
                    return []
                return [SetCursorOutcome(SnifyCursor(
                    state.cursor.document_index,
                    (new_start, state.cursor.selection[1]),
                ))]
        raise RuntimeError('I could not find the first word.')


class NextWordShouldBeIncluded(Command):
    def __init__(self, state: SnifyState):
        self.state = state
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='n',
            description_short='ext token should be included',
            description_long='Extends the selection to include the next token.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.state
        doc = state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.cursor.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_start_ref() < state.cursor.selection[1]:
                    i += 1
                if i == len(words):
                    interface.admonition('Already at end of possible selection range.', 'error', confirm=True)
                    return []
                return [SetCursorOutcome(SnifyCursor(
                    state.cursor.document_index,
                    (state.cursor.selection[0], words[i].get_end_ref()),
                ))]
        raise RuntimeError('Somehow I did not find the next word.')


class LastWordShouldntBeIncluded(Command):
    def __init__(self, state: SnifyState):
        self.state = state
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='N',
            description_short=' exclude last selected token',
            description_long='Opposite of [n]. Excludes the last token from the selection.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.state
        doc = state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.cursor.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_start_ref() < state.cursor.selection[1]:
                    i += 1
                new_end = words[i - 2].get_end_ref()
                if new_end <= state.cursor.selection[0]:
                    interface.admonition('Selection is getting too small', 'error', confirm=True)
                    return []
                return [SetCursorOutcome(SnifyCursor(
                    state.cursor.document_index,
                    (state.cursor.selection[0], new_end),
                ))]
        raise RuntimeError('I could not find the last word.')
