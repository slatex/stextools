import abc
import dataclasses
import re
from typing import Optional

import click

from stextools.core.simple_api import SimpleSymbol
from stextools.srify.state import State, SelectionCursor, Cursor, PositionCursor
from stextools.utils.ui import option_string, standard_header, pale_color, get_lines_around, latex_format, \
    standard_header_str


def show_current_selection(state, with_header: bool = True):
    if with_header:
        status = [
            f'File {state.cursor.file_index + 1}/{len(state.files)}'.ljust(15),
            f'Annotations added: {state.statistic_annotations_added}'.ljust(25)
        ]
        print(' | ' + ' | '.join(status) + ' |')
        standard_header(str(state.get_current_file()), bg='bright_green')

    cursor = state.cursor
    assert isinstance(cursor, SelectionCursor)

    a, b, c, line_no_start = get_lines_around(
        state.get_current_file_text(),
        cursor.selection_start,
        cursor.selection_end
    )
    doc = latex_format(a) + (
        '\n'.join(click.style(p, bg='bright_yellow', bold=True) for p in b.split('\n'))
    ) + latex_format(c)

    for i, line in enumerate(doc.split('\n'), line_no_start):
        print(click.style(f'{i:4} ', fg=pale_color()) + line)


class CommandOutcome:
    pass


class Exit(CommandOutcome):
    pass


class StatisticUpdateOutcome(CommandOutcome):
    def __init__(self, type_: str, value: Optional = None):
        self.type_ = type_
        self.value = value


class ImportInsertionOutcome(CommandOutcome):
    """Note: command is responsible for ensuring that the index is correct *after* the previous file modification outcomes."""
    def __init__(self, inserted_str: str, insert_pos: int):
        self.inserted_str = inserted_str
        self.insert_pos = insert_pos


class SubstitutionOutcome(CommandOutcome):
    """Note: command is responsible for ensuring that the index is correct *after* the previous file modification outcomes."""
    def __init__(self, new_str: str, start_pos: int, end_pos: int):
        self.new_str = new_str
        self.start_pos = start_pos
        self.end_pos = end_pos


class TextRewriteOutcome(CommandOutcome):
    def __init__(self, new_text: str):
        self.new_text = new_text


class SetNewCursor(CommandOutcome):
    def __init__(self, new_cursor: Cursor):
        self.new_cursor = new_cursor


@dataclasses.dataclass
class CommandInfo:
    pattern_presentation: str
    pattern_regex: str
    description_short: str
    description_long: str = ''

    show: bool = True


class Command(abc.ABC):
    def __init__(self, command_info: CommandInfo):
        self.command_info = command_info

    @abc.abstractmethod
    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        ...

    def standard_display(self, *, state: State) -> str:
        return option_string(self.command_info.pattern_presentation, self.command_info.description_short)

    def help_display(self) -> str:
        if self.command_info.description_long:
            indent = ' ' * (len(self.command_info.pattern_presentation) + 5)
            return option_string(
                self.command_info.pattern_presentation,
                self.command_info.description_short + '\n' + indent +
                self.command_info.description_long.replace('\n', '\n' + indent)
            )
        else:
            return option_string(self.command_info.pattern_presentation, self.command_info.description_short)


class QuitProgramCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            pattern_presentation='q',
            pattern_regex='^q$',
            description_short='uit',
            description_long='Quits the program')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [Exit()]


class RescanOutcome(CommandOutcome):
    pass


class RescanCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='R',
            pattern_regex='^R$',
            description_short='escan',
            description_long='Rescans all of MathHub')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [RescanOutcome()]


class ImportCommand(Command):
    def __init__(self, letter: str, description_short: str, description_long: str, outcome: ImportInsertionOutcome):
        super().__init__(CommandInfo(
            pattern_presentation=letter,
            pattern_regex=f'^{letter}$',
            description_short=description_short,
            description_long=description_long)
        )
        self.outcome = outcome

    def execute(self, *, state: State, call: str) -> list[ImportInsertionOutcome]:
        return [self.outcome]


class ExitFileCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='X',
            pattern_regex='^X$',
            description_short=' Exit file',
            description_long='Exits the current file (and continues with the next one)')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [SetNewCursor(PositionCursor(state.cursor.file_index + 1, 0))]


class UndoOutcome(CommandOutcome):
    ...


class UndoCommand(Command):
    def __init__(self, is_possible: bool):
        self.is_possible = is_possible
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='u',
            pattern_regex='^u$',
            description_short='ndo' + click.style('' if is_possible else ' (currently nothing to undo)', italic=True),
            description_long='Undoes the most recent modification')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        if self.is_possible:
            return [UndoOutcome()]
        print(click.style('Nothing to undo', fg='red'))
        click.pause()
        return []


class RedoOutcome(CommandOutcome):
    ...


class RedoCommand(Command):
    def __init__(self, is_possible: bool):
        self.is_possible = is_possible
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='uu',
            pattern_regex='^uu$',
            description_short=' redo ("undo undo")' + click.style('' if is_possible else ' (currently nothing to redo)', italic=True),
            description_long='Redoes the most recently undone modification')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        if self.is_possible:
            return [RedoOutcome()]
        print(click.style('Nothing to redo', fg='red'))
        click.pause()
        return []


class ReplaceCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='r',
            pattern_regex='^r$',
            description_short='eplace',
            description_long='Replace the selected word with a different one.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        new_word = click.prompt('Enter the new word: ', default=state.get_selected_text())
        return [
            SubstitutionOutcome(new_word, state.cursor.selection_start, state.cursor.selection_end),
            SetNewCursor(
                SelectionCursor(state.cursor.file_index, state.cursor.selection_start, state.cursor.selection_start + len(new_word))
            )
        ]


class ViewCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='v',
            pattern_regex='^v$',
            description_short='iew file',
            description_long='Show the current file in the pager')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        click.clear()
        click.echo_via_pager(
            standard_header_str(str(state.get_current_file()), bg='bright_green')
            + '\n\n' +
            latex_format(state.get_current_file_text())
        )
        return []


class View_i_Command(Command):
    def __init__(self, candidate_symbols: list[SimpleSymbol]):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='v𝑖',
            pattern_regex='^v[0-9]+$',
            description_short=' view document for 𝑖',
            description_long='Displays the document that introduces symbol no. 𝑖')
        )
        self.candidate_symbols = candidate_symbols

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        i = int(call[1:])
        if i >= len(self.candidate_symbols):
            print(click.style('Invalid symbol number', fg='red'))
            click.pause()
            return []
        symbol = self.candidate_symbols[i]
        click.echo_via_pager(
            standard_header_str(str(symbol.declaring_file.path), bg='bright_green')
            + '\n\n' +
            latex_format(symbol.declaring_file.path.read_text())
        )
        return []


class HelpCommand(Command):
    """ Should only be instantiated by CommandCollection. """
    def __init__(self, command_collection: 'CommandCollection'):
        super().__init__(CommandInfo(
            pattern_presentation='h',
            pattern_regex='^h$',
            description_short='elp',
            description_long='Displays this help message')
        )
        self.command_collection = command_collection

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        click.clear()
        standard_header(f'Help ({self.command_collection.name})')
        print()
        for command in self.command_collection.commands:
            print(command.help_display())
        print()
        click.pause()
        return []


@dataclasses.dataclass
class CommandCollection:
    name: str
    commands: list[Command]
    have_help: bool = True

    def __post_init__(self):
        if self.have_help:
            self.commands = [HelpCommand(self)] + self.commands

    def apply(self, *, state: State) -> list[CommandOutcome]:
        self._print_commands(state)
        call = input(click.style('>>>', bold=True) + ' ')
        for command in self.commands:
            if re.match(command.command_info.pattern_regex, call):
                return command.execute(state=state, call=call)
        print(click.style('Invalid command', fg='red'))
        click.pause()
        return []

    def _print_commands(self, state: State):
        show_all = all(c.command_info.show for c in self.commands)
        if not show_all and self.have_help:
            print('Commands:   ' + click.style('enter h (help) to see all available commands', fg=pale_color()))
        else:
            print('Commands:')

        for command in self.commands:
            if command.command_info.show:
                print(command.standard_display(state=state))
