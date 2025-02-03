"""
This file introduces stepper commands and provides some general-purpose commands.
"""

import abc
import dataclasses
import os
import re
import subprocess
from pathlib import Path
from typing import Sequence, Union, Iterable

import click

from stextools.core.config import get_config
from stextools.stepper.command_outcome import CommandOutcome, Exit, SetNewCursor, SubstitutionOutcome
from stextools.stepper.state import State, SelectionCursor, PositionCursor
from stextools.utils.ui import option_string, standard_header, print_highlight_selection, standard_header_str, \
    latex_format, pale_color


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
    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
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


class QuitSubdialogCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=True,
            pattern_presentation='q',
            pattern_regex='^q$',
            description_short='uit subdialog',
            description_long='Quits current subdialog')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        return [Exit()]


class QuitProgramCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            pattern_presentation='q',
            pattern_regex='^q$',
            description_short='uit',
            description_long='Quits the program')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        return [Exit()]


def show_current_selection(state: State, with_header: bool = True):
    if with_header:
        status = [
            f'File {state.cursor.file_index + 1}/{len(state.files)}'.ljust(15),
            f'Annotations added: {state.statistic_annotations_added}'.ljust(25)
        ]
        print(' | ' + ' | '.join(status) + ' |')
        if state.get_current_file().is_relative_to(Path.cwd()):
            pathstr = str(state.get_current_file().relative_to(Path.cwd()))
        else:
            pathstr = str(state.get_current_file())
        standard_header(pathstr, bg='bright_green')

    cursor = state.cursor
    assert isinstance(cursor, SelectionCursor)

    print_highlight_selection(
        state.get_current_file_text(),
        cursor.selection_start,
        cursor.selection_end,
        n_lines=int(get_config().get('stextools.snify', 'context-lines', fallback='7'))

    )


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

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        return [RescanOutcome()]


class ExitFileCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='X',
            pattern_regex='^X$',
            description_short=' Exit file',
            description_long='Exits the current file (and continues with the next one)')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
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

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
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

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        if self.is_possible:
            return [RedoOutcome()]
        print(click.style('Nothing to redo', fg='red'))
        click.pause()
        return []


class ViewCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='v',
            pattern_regex='^v$',
            description_short='iew file',
            description_long='Show the current file in the pager')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        click.clear()
        click.echo_via_pager(
            standard_header_str(str(state.get_current_file()), bg='bright_green')
            + '\n\n' +
            latex_format(state.get_current_file_text())
        )
        return []


def get_editor(number: int) -> str:
    if number == 1:
        return get_config().get('stextools.snify', 'editor', fallback=os.getenv('EDITOR', 'nano'))
    elif number == 2:
        return get_config().get('stextools.snify', f'editor2', fallback=os.getenv('EDITOR', 'nano'))
    else:
        raise ValueError('Invalid editor number')


class EditCommand(Command):
    def __init__(self, number: int):
        self.editor = get_editor(number)
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='e' * number,
            pattern_regex='^' + 'e' * number + '$',
            description_short='dit file' + ('' if number == 1 else f' with editor {number}'),
            description_long=f'Edit the current file with {self.editor} (can be changed in the config file)')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        old_content = state.get_current_file_text()
        subprocess.Popen([self.editor, str(state.get_current_file())]).wait()
        new_content = state.get_current_file_text()
        first_change_pos = 0
        while first_change_pos < len(old_content) and first_change_pos < len(new_content) and old_content[first_change_pos] == new_content[first_change_pos]:
            first_change_pos += 1

        outcomes: list[CommandOutcome] = [RescanOutcome()]
        assert isinstance(state.cursor, SelectionCursor)
        if first_change_pos <= state.cursor.selection_end + 5:   # some buffer in case a suffix was appended
            outcomes.append(SetNewCursor(PositionCursor(state.cursor.file_index, min(first_change_pos, state.cursor.selection_start))))

        return outcomes


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

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        click.clear()
        lines: list[str] = []
        lines.append(standard_header_str(f'Help ({self.command_collection.name})'))
        lines.append('')
        for command in self.command_collection.commands:
            if isinstance(command, Command):
                lines.append(command.help_display())
            else:
                lines.append(click.style(command.message, fg=pale_color()))
        lines.append('')
        click.echo_via_pager('\n'.join(lines))
        return []


@dataclasses.dataclass
class CommandSectionLabel:
    message: str


@dataclasses.dataclass
class CommandCollection:
    name: str
    commands: list[Union[Command, CommandSectionLabel]]
    have_help: bool = True

    def __post_init__(self):
        if self.have_help:
            self.commands = [HelpCommand(self)] + self.commands

    def apply(self, *, state: State) -> Sequence[CommandOutcome]:
        self._print_commands(state)
        call = input(click.style('>>>', bold=True) + ' ')
        for command in self._pure_commands():
            if re.match(command.command_info.pattern_regex, call):
                return command.execute(state=state, call=call)
        print(click.style('Invalid command', fg='red'))
        click.pause()
        return []

    def _pure_commands(self) -> Iterable[Command]:
        for c in self.commands:
            if isinstance(c, Command):
                yield c

    def _print_commands(self, state: State):
        show_all = all(c.command_info.show for c in self._pure_commands())
        if not show_all and self.have_help:
            print('Commands:   ' + click.style('enter h (help) to see all available commands', fg=pale_color()))
        else:
            print('Commands:')

        for command in self._pure_commands():
            if command.command_info.show:
                print(command.standard_display(state=state))


class ReplaceCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='r',
            pattern_regex='^r$',
            description_short='eplace',
            description_long='Replace the selected word with a different one.')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        new_word = click.prompt('Enter the new word: ', default=state.get_selected_text())
        return [
            SubstitutionOutcome(new_word, state.cursor.selection_start, state.cursor.selection_end),
            SetNewCursor(
                SelectionCursor(state.cursor.file_index, state.cursor.selection_start, state.cursor.selection_start + len(new_word))
            )
        ]
