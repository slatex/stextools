from collections import defaultdict
from typing import Optional

from stextools.snify.annotype import AnnoType, StepperStatus
from stextools.snify.displaysupport import display_snify_header, display_text_selection
from stextools.snify.formula_anno.commands import SelectFormulaRangeCommand, SelectArgumentPatternCommand, \
    MakeAnnotationCommand
from stextools.snify.formula_anno.formula_anno_state import FormulaAnnoState, SetFormulaSelectionModification
from stextools.snify.formula_anno.notations import get_notations, get_notation_match
from stextools.snify.snify_commands import SkipCommand, ExitFileCommand
from stextools.stepper.command import CommandCollection
from stextools.stepper.document import Document, STeXDocument
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import QuitCommand, UndoCommand, RedoCommand


class FormulaAnnoType(AnnoType[FormulaAnnoState]):
    _candidate_sorting_keys = {}    # we store them to ensure consistent ordering

    @property
    def name(self) -> str:
        return f'formula-anno-stex'

    def get_initial_state(self) -> FormulaAnnoState:
        return FormulaAnnoState()

    def is_applicable(self, document: Document) -> bool:
        if 'math' not in self.snify_state.mode:
            return False
        return isinstance(document, STeXDocument)

    def get_next_annotation_suggestion(
                self, document: Document, position: int
        ) -> Optional[tuple[int, list[Modification]]]:
        for formula in document.get_annotatable_formulae():
            if formula.get_start_ref() >= position:
                # found a candidate
                range_ = (formula.get_start_ref(), formula.get_end_ref())
                return formula.get_start_ref(), [
                    SetFormulaSelectionModification(self.name, self.state.formula_selection, range_)
                ]
        return None  # no more formulae

    def get_doc_str(self) -> str:
        """ returns the string content of the current document"""
        return self.snify_state.get_current_document().get_content()

    def _compute_notation_info(self):
        # notations = get_notations(self.snify_state)
        notations = get_notations()
        string = self.get_doc_str()[self.state.sub_selection[0]:self.state.sub_selection[1]]
        notations_by_argument_ranges = defaultdict(list)
        for notation in notations:
            arg_ranges = get_notation_match(notation, string)
            if arg_ranges is None:
                continue
            notations_by_argument_ranges[tuple(arg_ranges)].append(notation)

        # for level 2, argument order is irrelevant
        arg_ranges_sorted = sorted(set(tuple(sorted(ar)) for ar in notations_by_argument_ranges.keys()))

        return notations_by_argument_ranges, arg_ranges_sorted

    def show_current_state(self):
        # TODO: make sure flams data (e.g. the formula notation catalog) is loaded
        # otherwise (e.g. when resuming a session), the interface can be polluted with flams logs
        interface.clear()
        display_snify_header(self.snify_state)
        display_text_selection(self.snify_state.get_current_document(), self.state.formula_selection)
        interface.newline()
        formula_str = self.get_doc_str()[self.state.formula_selection[0]:self.state.formula_selection[1]]

        def write_with_subsel_hl(string: str):
            if self.state.sub_selection is None:
                interface.write_text(string)
            else:
                f0 = self.state.formula_selection[0]
                a, b = self.state.sub_selection
                a -= f0
                b -= f0
                interface.write_text(string[:a])
                interface.write_text(string[a:b], style='highlight')
                interface.write_text(string[b:])
            interface.newline()

        write_with_subsel_hl(formula_str)
        write_with_subsel_hl(('|^^^^' * (len(formula_str) // 5 + 1))[:len(formula_str)])
        write_with_subsel_hl(''.join(f'{i:<5}' for i in range(0, len(formula_str), 5)))
        interface.newline()


    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        """Return the commands applicable to the current state."""
        select_arg_pattern_cmd = None
        make_annotation_cmd = None

        if self.state.level > 1:
            string = self.get_doc_str()[self.state.sub_selection[0]:self.state.sub_selection[1]]
            notations_by_argument_ranges, arg_ranges_sorted = self._compute_notation_info()
            if self.state.level == 2:
                select_arg_pattern_cmd = SelectArgumentPatternCommand(
                    self.name,
                    self.state,
                    arg_ranges_sorted,
                    string
                )
            elif self.state.level == 3:
                notations = get_notations()
                symbols = []
                substitutions = []
                for arg_range in notations_by_argument_ranges:
                    if tuple(sorted(arg_range)) == self.state.args_in_sub_selection:
                        for n in notations_by_argument_ranges[arg_range]:
                            for symbol, macroname in notations[n]:
                                symbols.append(symbol)
                                substitutions.append(f'\\{macroname}' + ''.join('{' + string[a:b] + '}' for a, b in arg_range))
                make_annotation_cmd = MakeAnnotationCommand(self.name, symbols, substitutions, self.snify_state, self.show_current_state)

        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                ExitFileCommand(self.snify_state),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),
                SkipCommand(self.snify_state, description_short='kip (stop annotating this formula)'),
                select_arg_pattern_cmd,
                make_annotation_cmd,
                SelectFormulaRangeCommand(self.name, self.state),
            ],
            have_help=True,
        )
