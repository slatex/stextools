import subprocess
from typing import Optional, Sequence, Union

import click

from stextools.core.linker import Linker
from stextools.core.mathhub import make_filter_fun
from stextools.core.simple_api import SimpleSymbol, get_files, SimpleVerbalization
from stextools.snify.snify_state import SnifyState
from stextools.stepper.command_outcome import CommandOutcome, SubstitutionOutcome, SetNewCursor, FocusOutcome
from stextools.stepper.commands import CommandInfo, Command, RescanOutcome, get_editor
from stextools.stepper.state import State, SelectionCursor, PositionCursor
from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified
from stextools.utils.ui import pale_color, latex_format, \
    standard_header_str, print_highlight_selection


class StateSkipOutcome(CommandOutcome):
    def __init__(self, word: str, is_stem: bool, session_wide: bool):
        self.word = word
        self.is_stem = is_stem
        self.session_wide = session_wide


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
            print(click.style('The symbol is in scope due to the following import chain:', bg='bright_cyan'))
            import_path = file.explain_symbol_in_scope_at(symbol, offset)
            assert import_path is not None, 'Symbol is in scope, but no import path found'
            for file, range_ in import_path:
                print(click.style(f'  {file.path}', fg='black'))
                print_highlight_selection(
                    file.path.read_text(),
                    range_[0],
                    range_[1],
                    n_lines=0,
                )

        click.pause()

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
        assert isinstance(state, SnifyState)
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


