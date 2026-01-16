import math
from copy import deepcopy
from typing import Callable

from stextools.snify.formula_anno.formula_anno_state import SetSubSelectionModification, FormulaAnnoState, \
    SetArgsInSubSelectionModification, SetFormulaSelectionModification
from stextools.snify.snify_state import SnifyState, SnifyCursor
from stextools.snify.stex_dependency_addition import get_modules_in_scope_and_import_locations, get_import, \
    AnnotationAborted
from stextools.snify.text_anno.annotate import stex_symbol_style
from stextools.snify.text_anno.local_stex_catalog import LocalStexSymbol
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document import STeXDocument
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper_extensions import SetCursorOutcome
from stextools.stex.local_stex import FlamsUri


class SelectFormulaRangeCommand(Command):
    def __init__(
            self,
            anno_type_name: str,
            formula_anno_state: FormulaAnnoState,
    ):
        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖-𝑗',
                pattern_regex='^[0-9]+-[0-9]+$',
                description_short=' select the formula range 𝑖 to 𝑗',
            )
        )
        self.anno_type_name = anno_type_name
        self.formula_anno_state = formula_anno_state

    def execute(self, call: str) -> list[CommandOutcome]:
        a, b = map(int, call.split('-'))
        if a > b:
            interface.admonition(f'Invalid range: {a} is greater than {b}', type='error', confirm=True)
            return []
        # TODO: more error checking (out of bounds)
        assert self.formula_anno_state.formula_selection is not None
        a += self.formula_anno_state.formula_selection[0]
        b += self.formula_anno_state.formula_selection[0] + 1
        return [
            SetSubSelectionModification(self.anno_type_name, self.formula_anno_state.sub_selection, (a, b))
        ]

class SelectArgumentPatternCommand(Command):
    def __init__(self, anno_type_name: str, formula_anno_state: FormulaAnnoState,
                 patterns: list[tuple[tuple[int, int], ...]], string: str):
        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖',
                pattern_regex='^[0-9]+$',
                description_short=' select the argument pattern 𝑖',
            )
        )
        self.anno_type_name = anno_type_name
        self.formula_anno_state = formula_anno_state
        self.patterns = patterns
        self.string = string

    def execute(self, call: str) -> list[CommandOutcome]:
        i = int(call)
        if i < 0 or i >= len(self.patterns):
            interface.admonition(f'Invalid argument pattern index: {i}', type='error', confirm=True)
            return []
        selected_pattern = self.patterns[i]
        return [
            SetArgsInSubSelectionModification(
                self.anno_type_name,
                self.formula_anno_state.args_in_sub_selection,
                selected_pattern
            )
        ]

    def standard_display(self):
        string = self.string
        for i, arg_ranges in enumerate(self.patterns):
            last_added_index = 0
            parts = []
            for arg_range in arg_ranges:
                a, b = arg_range
                parts.append(string[last_added_index:a])
                parts.append('·')
                parts.append(interface.apply_style(string[a:b], style='highlight2'))
                parts.append('·')
                last_added_index = b
            parts.append(string[last_added_index:])
            interface.write_command_info(
                str(i),
                ' pattern: ' + ''.join(parts)
            )

class MakeAnnotationCommand(Command):
    def __init__(
            self,
            anno_type_name: str,
            symbols: list[LocalStexSymbol],
            substitutions: list[str],
            snify_state: SnifyState,
            show_state_fun: Callable[[], None],
    ):
        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖',
                pattern_regex='^[0-9]+$',
                description_short=' annotation with selected symbol',
                description_long='Creates an annotation for the selected range with the selected symbol'
            )
        )
        self.anno_type_name = anno_type_name
        self.symbols = symbols
        self.substitutions = substitutions
        self.snify_state = snify_state
        document = snify_state.get_current_document()
        assert isinstance(document, STeXDocument)
        self.document = document
        self.importinfo = get_modules_in_scope_and_import_locations(document, snify_state.cursor.in_doc_pos)
        self.show_state_fun = show_state_fun

    def standard_display(self):
        """ largely copied from STeXAnnotateCommand - TODO: refactor """
        style = interface.apply_style
        for i, symbol in enumerate(self.symbols):
            module_uri_f = FlamsUri(symbol.uri)
            if '/' in module_uri_f.module:  # TODO: better way to identify structures
                structure = deepcopy(module_uri_f)
                structure.module, _, structure.symbol = module_uri_f.module.rpartition('/')
                is_available = str(structure) in self.importinfo.structs_in_scope
            else:
                module_uri_f.symbol = None
                is_available = str(module_uri_f) in self.importinfo.modules_in_scope
            symbol_display = ' '
            symbol_display += (
                style('✓', 'correct-weak') if is_available else style('✗', 'error-weak')
            )
            symbol_display += ' ' + self.substitutions[i].split('{')[0].ljust(10)
            symbol_display += ' ' + stex_symbol_style(FlamsUri(symbol.uri))

            interface.write_command_info(
                str(i),
                symbol_display
            )

    def execute(self, call: str) -> list[CommandOutcome]:
        # Adapted from STeXAnnotateBase.annotate_symbol
        # todo: can we do some refactoring to avoid code duplication?
        i = int(call)
        if i < 0 or i >= len(self.symbols):
            interface.admonition(f'Invalid annotation index: {i}', type='error', confirm=True)
            return []
        symbol, substitution = self.symbols[i], self.substitutions[i]
        try:
            import_thing = get_import(self.document, self.importinfo, symbol, self.show_state_fun)
        except AnnotationAborted:
            return []

        outcomes: list[CommandOutcome] = []

        if import_thing:
            outcomes.extend(import_thing)

        state: FormulaAnnoState = self.snify_state.annotype_states[self.anno_type_name]
        main_subst = SubstitutionOutcome(substitution, state.sub_selection[0], state.sub_selection[1])
        outcomes.append(main_subst)

        # at this point, we only have substitutions
        # -> sort them and update the offsets
        # TODO: maybe the controller should be responsible for this
        offset = 0
        outcomes.sort(key=lambda o: o.start_pos if isinstance(o, SubstitutionOutcome) else math.inf)
        for o in outcomes:
            if isinstance(o, SubstitutionOutcome):
                o.start_pos += offset
                o.end_pos += offset
                if o is not main_subst:
                    offset += len(o.new_str) - (o.end_pos - o.start_pos)

        outcomes.extend([
            SetArgsInSubSelectionModification(self.anno_type_name, state.args_in_sub_selection, None),
            SetSubSelectionModification(self.anno_type_name, state.sub_selection, None),
            SetFormulaSelectionModification(
                self.anno_type_name, state.formula_selection,
                (
                    state.formula_selection[0] + offset,
                    state.formula_selection[1] - (state.sub_selection[1] - state.sub_selection[0]) + len(substitution)
                )
            ),
        ])

        c = self.snify_state.cursor
        new_cursor = SnifyCursor(
            document_index=c.document_index,
            banned_annotypes=c.banned_annotypes,
            in_doc_pos=c.in_doc_pos + offset,
        )
        outcomes.extend([
            SetCursorOutcome(new_cursor=new_cursor),
        ])

        return outcomes

