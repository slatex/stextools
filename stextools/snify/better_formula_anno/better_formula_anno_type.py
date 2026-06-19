from typing import Optional

from stextools.snify.annotype import AnnoType, StateType, StepperStatus
from stextools.snify.objective_anno.objective_anno_state import ObjectiveAnnoState
from stextools.snify.snify_commands import SkipCommand
from stextools.stepper.command import CommandCollection, Command, CommandInfo, CommandOutcome
from stextools.stepper.document import Document, STeXDocument
from stextools.stepper.document_stepper import TextRewriteOutcome, SubstitutionOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import QuitCommand, UndoCommand, RedoCommand


class FormulaAnnoState:
    pass


class AddVerbalizationCommand(Command):
    def __init__(self, position: int):
        self.position = position
        super().__init__(CommandInfo(
            pattern_presentation='a',
            description_short='dd verbalization',
            description_long='Add a verbalization for the current \\symdef.'
        ))

    def execute(self, call: str) -> list[CommandOutcome]:
        """ this is called when the user presses 'a' """

        interface.write_text('Please enter the annotation type: ')
        annotation_type = interface.get_input()

        return [
            SubstitutionOutcome(
                '\\verbalization{...}{' + annotation_type + '}{...}\n',
                self.position, self.position
            )
        ]


class BetterFormulaAnnoType(AnnoType[FormulaAnnoState]):
    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return f'formula-anno-stex'

    def is_applicable(self, document: Document) -> bool:
        if 'math' not in self.snify_state.mode:
            return False
        return isinstance(document, STeXDocument)

    def get_initial_state(self) -> StateType:
        return FormulaAnnoState()

    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        for formula in document.get_annotatable_formulae():
            if formula.get_start_ref() >= position:
                # found a candidate
                return formula.get_start_ref(), []

    def show_current_state(self):
        interface.clear()
        interface.write_text('HELLO, I AM THE FORMULA ANNOTATION ASSISTANT\n')

        document_content = self.snify_state.get_current_document().get_content()
        position = self.snify_state.cursor.in_doc_pos

        string = document_content[position:]
        line = string.splitlines()[0]

        interface.write_text('Current line:\n')
        interface.show_code(line, format='sTeX')



    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        position = self.snify_state.cursor.in_doc_pos

        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),
                SkipCommand(self.snify_state, description_short='kip'),
            ],
            have_help=True,
        )
