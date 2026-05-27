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


class VerbalizationAnnoState:
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


class VerbalizationAnnoType(AnnoType[VerbalizationAnnoState]):
    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return f'verbalization-anno'

    def is_applicable(self, document: Document) -> bool:
        if 'verbalizations' not in self.snify_state.mode:
            return False
        if isinstance(document, STeXDocument):
            return True
        else:
            return False

    def get_initial_state(self) -> StateType:
        return ObjectiveAnnoState()

    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        # a string with the content of the file
        document_content = document.get_content()
        # we only care about stuff after the current position
        document_content = document_content[position:]

        our_position = document_content.find('\\symdef')
        if our_position == -1:    # we did not find anything
            return None
        else:
            return our_position + position, []

    def show_current_state(self):
        interface.clear()
        interface.write_text('HELLO, I AM THE VERBALIZATION ASSISTANT\n')

        document_content = self.snify_state.get_current_document().get_content()
        position = self.snify_state.cursor.in_doc_pos

        string = document_content[position:]
        line = string.splitlines()[0]

        interface.write_text('Current \\symdef:\n')
        interface.show_code(line, format='sTeX')



    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        position = self.snify_state.cursor.in_doc_pos
        document_content = self.snify_state.get_current_document().get_content()
        string = document_content[position:]
        position = position + 1 + string.find('\n')

        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),
                SkipCommand(self.snify_state, description_short='kip'),
                AddVerbalizationCommand(position),
            ],
            have_help=True,
        )
