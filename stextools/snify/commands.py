import abc
import dataclasses
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Any, Sequence, Union

import click

from stextools.core.config import get_config
from stextools.core.linker import Linker
from stextools.core.mathhub import make_filter_fun
from stextools.core.simple_api import SimpleSymbol, get_files, SimpleVerbalization
from stextools.snify.state import State, SelectionCursor, Cursor, PositionCursor
from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified
from stextools.utils.ui import option_string, standard_header, pale_color, get_lines_around, latex_format, \
    standard_header_str, print_highlight_selection


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


class CommandOutcome:
    pass


class Exit(CommandOutcome):
    pass


class StatisticUpdateOutcome(CommandOutcome):
    def __init__(self, type_: str, value: Optional[Any] = None):
        self.type_ = type_
        self.value = value


class SubstitutionOutcome(CommandOutcome):
    """Note: command is responsible for ensuring that the index is correct *after* the previous file modification outcomes."""
    def __init__(self, new_str: str, start_pos: int, end_pos: int):
        self.new_str = new_str
        self.start_pos = start_pos
        self.end_pos = end_pos


class TextRewriteOutcome(CommandOutcome):
    def __init__(self, new_text: str, requires_reparse: bool = True):
        self.new_text = new_text
        self.requires_reparse = requires_reparse


class SetNewCursor(CommandOutcome):
    def __init__(self, new_cursor: Cursor):
        self.new_cursor = new_cursor


class StateSkipOutcome(CommandOutcome):
    def __init__(self, word: str, is_stem: bool, session_wide: bool):
        self.word = word
        self.is_stem = is_stem
        self.session_wide = session_wide


class FocusOutcome(CommandOutcome):
    def __init__(self, new_files: Optional[list[Path]] = None, new_cursor: Optional[Cursor] = None, select_only_stem: Optional[str] = None):
        self.new_files = new_files
        self.new_cursor = new_cursor
        self.select_only_stem = select_only_stem


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


class ImportCommand(Command):
    def __init__(self, letter: str, description_short: str, description_long: str, outcome: SubstitutionOutcome,
                 redundancies: list[SubstitutionOutcome]):
        super().__init__(CommandInfo(
            pattern_presentation=letter,
            pattern_regex=f'^{letter}$',
            description_short=description_short,
            description_long=description_long)
        )
        self.outcome = outcome
        self.redundancies = redundancies

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        cmds: list[SubstitutionOutcome] = self.redundancies + [self.outcome]
        cmds.sort(key=lambda x: x.start_pos, reverse=True)
        return cmds


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

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
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

        outcomes = [RescanOutcome()]
        assert isinstance(state.cursor, SelectionCursor)
        if first_change_pos <= state.cursor.selection_end + 5:   # some buffer in case a suffix was appended
            outcomes.append(SetNewCursor(PositionCursor(state.cursor.file_index, min(first_change_pos, state.cursor.selection_start))))

        return outcomes


class Edit_i_Command(Command):
    def __init__(self, number: int, candidate_symbols: list[SimpleSymbol]):
        self.editor = get_editor(number)
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='e' * number + '𝑖',
            pattern_regex='^' + 'e' * number + '[0-9]+$',
            description_short=' edit document for 𝑖' + ('' if number == 1 else f' with editor {number}'),
            description_long=f'Edit the document that introduces symbol no. 𝑖 with {self.editor} (can be changed in the config file)')
        )
        self.candidate_symbols = candidate_symbols

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        i = int(call[call.count('e'):])
        if i >= len(self.candidate_symbols):
            print(click.style('Invalid symbol number', fg='red'))
            click.pause()
            return []
        symbol = self.candidate_symbols[i]
        subprocess.Popen([self.editor, str(symbol.declaring_file.path)]).wait()
        return [RescanOutcome()]


class Explain_i_Command(Command):
    def __init__(self, candidate_symbols: list[SimpleSymbol]):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='x𝑖',
            pattern_regex='^x[0-9]+$',
            description_short=' explain 𝑖',
            description_long='Explains why symbol no. 𝑖 is listed')
        )
        self.candidate_symbols = candidate_symbols

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        i = int(call[1:])
        if i >= len(self.candidate_symbols):
            print(click.style('Invalid symbol number', fg='red'))
            click.pause()
            return []
        symbol = self.candidate_symbols[i]
        print(click.style(f'Explanation for symbol {i}:', bold=True))
        print(click.style(f'{symbol.declaring_file.path}', fg=pale_color()))
        print()
        verb: Optional[Union[SimpleVerbalization, SimpleSymbol]] = None
        linker = symbol._linker
        lang = state.get_current_lang(linker)
        stem = string_to_stemmed_word_sequence_simplified(symbol.name, lang)
        for v in symbol.get_verbalizations(lang=lang):
            if string_to_stemmed_word_sequence_simplified(v.verb_str, lang) == stem:
                verb = v
                break

        if verb is None and string_to_stemmed_word_sequence_simplified(symbol.name, lang) == stem:
            verb = symbol

        if verb is None:
            print(click.style('No matching verbalization found... this might be a bug...', bg='black', fg='bright_red'))
        elif isinstance(verb, SimpleSymbol):
            print('There was no matchinb verbalization, but the symbol name matches:')
            print_highlight_selection(
                verb.declaring_file.path.read_text(),
                verb.macro_range[0],
                verb.macro_range[1],
                n_lines=2,
            )
        elif isinstance(verb, SimpleVerbalization):
            print('Matching verbalization found in:')
            print(click.style(f'  {verb.declaring_file.path}', fg='black', bg='bright_green'))
            print_highlight_selection(
                verb.declaring_file.path.read_text(),
                verb.macro_range[0],
                verb.macro_range[1],
                n_lines=2,
            )
            print()
        else:
            raise RuntimeError(f'Unexpected type {type(verb)}')

        assert isinstance(state.cursor, SelectionCursor)
        file = state.get_current_file_simple_api(linker)
        offset = state.cursor.selection_start
        in_scope = file.symbol_is_in_scope_at(symbol, offset)

        if in_scope:
            ...     # TODO

        click.pause()

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
        click.echo_via_pager('\n'.join(lines), color=True)
        return []


class StemFocusCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='f',
            pattern_regex='^f$',
            description_short='ocus on stem',
            description_long='Look for other occurrences of the current stem in the current file')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        return [
            # do not want to return to old selection
            SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start)),
            FocusOutcome([state.get_current_file()], select_only_stem=state.get_selected_text())
        ]


class StemFocusCommandPlus(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='f!',
            pattern_regex='^f!$',
            description_short='ocus on stem in all remaining files',
            description_long='Look for other occurrences of the current stem in the remaining files')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        return [
            SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start)),
            FocusOutcome(select_only_stem=state.get_selected_text())
        ]


class StemFocusCommandPlusPlus(Command):
    def __init__(self, linker: Linker):
        self.linker = linker
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='f!!',
            pattern_regex='^f!!$',
            description_short='ocus on stem in all files',
            description_long='Look for other occurrences of the current stem in all files')
        )

    def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        filter_fun = make_filter_fun(state.filter_pattern, state.ignore_pattern)
        return [
            SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start)),
            FocusOutcome(
                new_files=[
                    f.path
                    for f in get_files(self.linker)
                    if filter_fun(f.archive.name) and f.lang == state.get_current_lang(self.linker)
                ],
                select_only_stem=state.get_selected_text()
            )
        ]


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

    def _pure_commands(self) -> Sequence[Command]:
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
