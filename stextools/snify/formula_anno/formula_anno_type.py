from collections import defaultdict
from typing import Optional

from stextools.snify.annotype import AnnoType, StepperStatus
from stextools.snify.displaysupport import display_snify_header, display_text_selection
from stextools.snify.formula_anno.commands import SelectFormulaRangeCommand
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

        if self.state.level > 1:
            notations = get_notations(self.snify_state)
            string = self.get_doc_str()[self.state.sub_selection[0]:self.state.sub_selection[1]]
            notations_by_argument_ranges = defaultdict(list)
            for notation in notations:
                arg_ranges = get_notation_match(notation, string)
                if arg_ranges is None:
                    continue
                notations_by_argument_ranges[tuple(arg_ranges)].append(notation)

            if self.state.level == 2:
                interface.write_text('Possible notations:', style='bold')
                interface.newline()
                for i, arg_ranges in enumerate(sorted(notations_by_argument_ranges.keys())):
                    interface.write_text(f'{i + 1:>2}: ', style='info')
                    last_printed_index = 0
                    for arg_range in arg_ranges:
                        a, b = arg_range
                        interface.write_text(string[last_printed_index:a])
                        interface.write_text(string[a:b], style='highlight2')
                        last_printed_index = b
                    interface.write_text(string[last_printed_index:])
                    interface.newline()

                # interface.write_text(f'Notation match: {notation}', style='info')
                # interface.newline()


    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        """Return the commands applicable to the current state."""

        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                ExitFileCommand(self.snify_state),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),
                SkipCommand(self.snify_state),

                SelectFormulaRangeCommand(self.name, self.state),
            ],
            have_help=True,
        )
