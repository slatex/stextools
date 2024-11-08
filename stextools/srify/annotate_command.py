import functools
from typing import Optional

import click
from pylatexenc.latexwalker import LatexMacroNode, LatexSpecialsNode, LatexMathNode, LatexGroupNode, \
    LatexEnvironmentNode, LatexCommentNode, LatexCharsNode, LatexWalker

from stextools.core.linker import Linker
from stextools.core.macros import STEX_CONTEXT_DB
from stextools.core.simple_api import SimpleSymbol, get_symbols
from stextools.srify.commands import Command, CommandInfo, CommandOutcome, SubstitutionOutcome, SetNewCursor, \
    ImportInsertionOutcome, ImportCommand, CommandCollection, show_current_selection, StatisticUpdateOutcome
from stextools.srify.state import State, SelectionCursor, PositionCursor
from stextools.utils.ui import standard_header, pale_color, option_string, color, latex_format

# This stores the keys to fix the order of the symbols within a session
# (note: cannot cache by SimpleSymbol object, because it changes when resetting the linker)
_already_determined: dict[tuple[str, str], tuple] = {}


def symbol_to_sorting_key(symbol: SimpleSymbol) -> tuple:
    k = (symbol.declaring_file.archive.name, symbol.path_rel_to_archive)
    if k in _already_determined:
        return _already_determined[k]
    primary = len(list(symbol.get_verbalizations()))
    print(symbol.name, primary)
    secondary = k
    _already_determined[k] = primary, secondary
    return primary, secondary


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
        self.candidate_symbols.sort(key=symbol_to_sorting_key, reverse=True)
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

        offset = 0
        if import_thing:
            outcomes.append(import_thing)
            # TODO: maybe the controller should be responsible for this
            offset += len(import_thing.inserted_str)

        outcomes.append(
            SubstitutionOutcome(sr, self.cursor.selection_start + offset, self.cursor.selection_end + offset)
        )
        outcomes.append(StatisticUpdateOutcome('annotation_inc'))
        offset += len(sr)
        outcomes.append(SetNewCursor(PositionCursor(self.cursor.file_index, self.cursor.selection_start + offset)))

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

        explain_loc = lambda loc: ' after ' + latex_format('\\begin{' + loc + '}') if loc else ' at the beginning of the file'

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
                if not node or node.nodeType() in {LatexSpecialsNode}:
                    continue
                elif node.nodeType() in {LatexMacroNode}:
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
        if not self.candidate_symbols:
            return click.style('  no candidate symbols found (possible reason: some symbols are filtered out)', italic=True)
        file = state.get_current_file_simple_api(self.linker)
        lines: list[str] = []
        for i, symbol in enumerate(self.candidate_symbols):
            symb_path = symbol.path_rel_to_archive.split('?')
            assert len(symb_path) == 3
            in_scope = file.symbol_is_in_scope_at(symbol, self.cursor.selection_start)
            if in_scope:
                marker = click.style('✓', bold=True, fg='green')
            else:
                marker = click.style('✗', bold=True, fg='red')
            line = option_string(
                str(i),
                ' ' + marker + ' ' + symbol.declaring_file.archive.name + ' ' +
                symb_path[0] + '?' +
                click.style(symb_path[1], bg=color('bright_cyan', (180, 180, 255))) + '?' +
                click.style(symb_path[2], bg=color('bright_green', (180, 255, 180))) +
                '\n      ' + click.style(symbol.declaring_file.path, italic=True, fg=pale_color())
            )
            lines.append(line)
        return '\n'.join(lines)
