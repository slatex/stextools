from pathlib import Path
from typing import Sequence, Any

from stextools.snify.snify_state import SnifyState, SnifyCursor, SetOngoingAnnoTypeModification
from stextools.snify.stex_dependency_addition import DependencyModificationOutcome
from stextools.snify.text_anno.catalog import Verbalization
from stextools.stepper.document import Document
from stextools.snify.text_anno.local_stex_catalog import LocalStexSymbol
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper_extensions import SetCursorOutcome


# If first edit is before cursor: set cursor to first edit position
# else: set to current position, to run reselection logic
def get_set_cursor_after_edit_function(state: SnifyState):
    def set_cursor_after_edit(pos) -> list[CommandOutcome]:
        if pos <= state.cursor.in_doc_pos:
            return [
                SetCursorOutcome(SnifyCursor(document_index=state.cursor.document_index, in_doc_pos=pos)),
                # dependencies may have changed...
                DependencyModificationOutcome(state.get_current_document())
            ]
        else:
            return [
                SetOngoingAnnoTypeModification(state.ongoing_annotype, None),
                DependencyModificationOutcome(state.get_current_document())
                # SetCursorOutcome(SnifyCursor(state.cursor.document_index, state.cursor.selection[0]))
            ]
    return set_cursor_after_edit


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
        return [
            SetOngoingAnnoTypeModification(self.state.ongoing_annotype, None),
            SetCursorOutcome(SnifyCursor(self.state.cursor.document_index + 1, 0, banned_annotypes=set()))
        ]


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


class SkipCommand(Command):
    def __init__(
            self,
            state: SnifyState,
            description_short: str = 'kip once',
            description_long: str = 'Skips to the next possible annotation'
    ):
        super().__init__(CommandInfo(
            pattern_presentation = 's',
            description_short = description_short,
            description_long = description_long)
        )
        self.state = state

    @classmethod
    def get_skip_outcome(cls, state: SnifyState) -> list[CommandOutcome]:
        c = state.cursor
        new_cursor = SnifyCursor(
            document_index=c.document_index,
            banned_annotypes=c.banned_annotypes | {state.ongoing_annotype},
            in_doc_pos=c.in_doc_pos
        )
        return [
            SetOngoingAnnoTypeModification(state.ongoing_annotype, None),
            SetCursorOutcome(new_cursor=new_cursor),
        ]


    def execute(self, call: str) -> list[CommandOutcome]:
        return self.get_skip_outcome(self.state)
