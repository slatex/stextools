import abc
import dataclasses
import re
from typing import Optional

import click
from pylatexenc.latexwalker import LatexMacroNode, LatexMathNode, LatexSpecialsNode, LatexEnvironmentNode, \
    LatexGroupNode, LatexCommentNode, LatexCharsNode, LatexWalker

from stextools.core.linker import Linker
from stextools.core.macros import STEX_CONTEXT_DB
from stextools.core.simple_api import SimpleSymbol, get_symbols
from stextools.srify.state import State, SelectionCursor, Cursor
from stextools.utils.ui import option_string, standard_header, pale_color, color, get_lines_around, latex_format


def show_current_selection(state, with_header: bool = True):
    if with_header:
        standard_header(str(state.get_current_file()), bg='bright_green')

    cursor = state.cursor
    assert isinstance(cursor, SelectionCursor)

    a, b, c, line_no_start = get_lines_around(
        state.get_current_file_text(),
        cursor.selection_start,
        cursor.selection_end
    )
    doc = latex_format(a) + click.style(b, bg='bright_yellow', bold=True) + latex_format(c)

    for i, line in enumerate(doc.split('\n'), line_no_start):
        print(click.style(f'{i:4} ', fg=pale_color()) + line)


class CommandOutcome:
    pass


class Exit(CommandOutcome):
    pass


class ImportInsertionOutcome(CommandOutcome):
    def __init__(self, inserted_str: str, insert_pos: int):
        self.inserted_str = inserted_str
        self.insert_pos = insert_pos


class SubstitutionOutcome(CommandOutcome):
    def __init__(self, new_str: str, start_pos: int, end_pos: int):
        self.new_str = new_str
        self.start_pos = start_pos
        self.end_pos = end_pos


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


class AnnotateCommand(Command):
    """ Has to be re-instantiated for each state! """
    def __init__(self, candidate_symbols: list[SimpleSymbol], state: State, linker: Linker):
        super().__init__(CommandInfo(
            pattern_presentation='𝑖',
            pattern_regex='^[0-9]+$',
            description_short=' annotate with 𝑖',
            description_long='Annotates the current selection with option number 𝑖')
        )
        self.candidate_symbols = candidate_symbols
        self.state = state
        self.linker = linker
        if not isinstance(self.state.cursor, SelectionCursor):
            raise RuntimeError("AnnotateCommand can only be used with a SelectionCursor")
        self.cursor: SelectionCursor = self.state.cursor

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert state == self.state
        symbol = self.candidate_symbols[int(call)]

        outcomes: list[CommandOutcome] = []

        import_thing = self.get_import(symbol)
        sr = self.get_sr(symbol)

        if import_thing:
            outcomes.append(import_thing)
            # TODO: maybe the controller should be responsible for this
            offset = len(import_thing.inserted_str)
            outcomes.append(
                SubstitutionOutcome(sr, self.cursor.selection_start + offset, self.cursor.selection_end + offset)
            )
        else:
            outcomes.append(SubstitutionOutcome(sr, self.cursor.selection_start, self.cursor.selection_end))

        return outcomes

    def get_import(self, symbol: SimpleSymbol) -> Optional[ImportInsertionOutcome]:
        file = self.state.get_current_file_simple_api(self.linker)
        if file.symbol_is_in_scope_at(symbol, self.cursor.selection_start):
            return None

        import_locations = self.get_import_locations()
        import_impossible_reason: Optional[str] = None
        if import_locations[2] is None:
            import_impossible_reason = 'not in an smodule'
        else:
            # check for cycle (by checking if the file is in the transitive compilation dependencies)
            checked_dependencies = set()
            todo = [symbol.declaring_file]
            while todo:
                dep = todo.pop()
                if dep in checked_dependencies:
                    continue
                checked_dependencies.add(dep)
                if dep == file:
                    import_impossible_reason = 'would result in cyclic dependency'
                    break
                todo.extend(dep.get_compilation_dependencies())

        args = ''
        if symbol.declaring_file.archive != file.archive:
            args += f'[{symbol.declaring_file.archive.name}]'
        args += f'{{{symbol.declaring_module.path_rel_to_archive}}}'

        file_text = self.state.get_current_file_text()

        def _get_indentation(pos: int) -> str:
            indentation = '\n'
            for i in range(pos + 1, self.cursor.selection_start):
                if file_text[i] == ' ':
                    indentation += ' '
                else:
                    break
            return indentation

        explain_loc = lambda loc: ' after \\begin{' + loc + '}' if loc else ' at the beginning of the file'

        commands = [
            ImportCommand(
                'u', 'semodule' + explain_loc(import_locations[3]),
                    'Inserts \\usemodule' + explain_loc(import_locations[3]),
                ImportInsertionOutcome(
                    _get_indentation(import_locations[0]) + f'\\usemodule{args}',
                    import_locations[0]
                )
            ),
            ImportCommand(
                't',
                'op-level usemodule (i.e.' + explain_loc(import_locations[4]) + ')'
                    if import_locations[4] else
                    'op-level usemodule (in this case same as [u])',
                'Inserts \\usemodule at the top of the document (i.e.' + explain_loc(import_locations[4]) + ')'
                    if import_locations[4] else
                    'Inserts \\usemodule at the top of the document (in this case same as [u])',
                ImportInsertionOutcome(
                    _get_indentation(import_locations[1]) + f'\\usemodule{args}',
                    import_locations[1]
                )
            )
        ]

        if not import_impossible_reason:
            commands.append(ImportCommand(
                'i', 'mportmodule',
                'Inserts \\importmodule',
                ImportInsertionOutcome(
                    _get_indentation(import_locations[2]) + f'\\importmodule{args}',
                    import_locations[2]
                )
            ))

        cmd_collection = CommandCollection('Import options', commands, have_help=True)

        results = []
        while not results:
            click.clear()
            show_current_selection(self.state)
            print()
            standard_header('Import options', bg=pale_color())
            print('The symbol is not in scope.')
            if import_impossible_reason:
                print(f'\\importmodule is impossible: {import_impossible_reason}')
            print()
            results = cmd_collection.apply(state=self.state)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, ImportInsertionOutcome)
        return r

    def get_import_locations(self) -> tuple[int, int, Optional[int], Optional[str], Optional[str]]:
        use_pos: Optional[int] = None
        top_use_pos: Optional[int] = None
        import_pos: Optional[int] = None

        use_env: Optional[str] = None
        top_use_env: Optional[str] = None

        def _recurse(nodes):
            nonlocal use_pos, top_use_pos, import_pos, use_env, top_use_env
            for node in nodes:
                if node.nodeType() in {LatexMacroNode, LatexSpecialsNode}:
                    _recurse(node.nodeargs)
                elif node.nodeType() in {LatexMathNode, LatexGroupNode}:
                    _recurse(node.nodelist)
                elif node.nodeType() == LatexEnvironmentNode:
                    if node.environmentname in {
                        'sproblem', 'smodule', 'sdefinition', 'sparagraph', 'document', 'frame'
                    }:
                        use_pos = node.nodelist[0].pos
                        use_env = node.environmentname
                    if node.environmentname == 'smodule':
                        import_pos = node.nodelist[0].pos
                    if top_use_pos is None:
                        top_use_pos = node.nodelist[0].pos
                        top_use_env = node.environmentname
                    _recurse(node.nodelist)
                elif node.nodeType() in {LatexCommentNode, LatexCharsNode}:
                    pass
                else:
                    raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

        _recurse(LatexWalker(self.state.get_current_file_text(), latex_context=STEX_CONTEXT_DB).get_latex_nodes()[0])

        return use_pos or 0, top_use_pos or 0, import_pos, use_env, top_use_env


    def get_sr(self, symbol: SimpleSymbol) -> str:
        # check if symbol is uniquely identified by its name
        file = self.state.get_current_file_simple_api(self.linker)
        symbol_unique = True
        for _symbol in get_symbols(self.linker, name=symbol.name):
            if _symbol == symbol:
                continue
            # Note: for stronger disambiguation policy: omit the check
            if file.symbol_is_in_scope_at(_symbol, self.cursor.selection_start):
                symbol_unique = False
                break

        word = self.state.get_selected_text()
        symb_name = symbol.name
        if symbol_unique:
            symb_path = symb_name
        else:
            symb_path = symbol.path_rel_to_archive

        if word == symb_name:
            return '\\sn{' + symb_path + '}'
        elif word == symb_name + 's':
            return '\\sns{' + symb_path + '}'
        elif word[0] == symb_name[0].upper() and word[1:] == symb_name[1:]:
            return '\\Sn{' + symb_path + '}'
        elif word[0] == symb_name[0].upper() and word[1:] == symb_name[1:] + 's':
            return '\\Sns{' + symb_path + '}'
        elif word.startswith(symb_name):
            return f'\\sn[post={word[len(symb_name):]}]{{' + symb_path + '}'
        else:
            return '\\sr{' + symb_path + '}' + '{' + word + '}'

    def standard_display(self, *, state: State) -> str:
        assert state == self.state
        lines: list[str] = []
        for i, symbol in enumerate(self.candidate_symbols):
            symb_path = symbol.path_rel_to_archive.split('?')
            assert len(symb_path) == 3
            lines.append(option_string(
                str(i),
                ' ' + symbol.declaring_file.archive.name + ' ' +
                symb_path[0] + '?' +
                click.style(symb_path[1], bg=color('bright_cyan', (180, 180, 255))) + '?' +
                click.style(symb_path[2], bg=color('bright_green', (180, 255, 180))) +
                '\n      ' + click.style(symbol.declaring_file.path, italic=True, fg=pale_color())
            ))
        return '\n'.join(lines)


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
