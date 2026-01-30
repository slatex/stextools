from typing import Optional

from stextools.snify.annotype import AnnoType, StateType, StepperStatus
from stextools.snify.displaysupport import display_snify_header
from stextools.snify.objective_anno.objective_anno_state import ObjectiveAnnoState
from stextools.stepper.command import CommandCollection
from stextools.stepper.document import Document, STeXDocument
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification


class ObjectiveAnnoType(AnnoType[ObjectiveAnnoState]):
    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return f'objective-anno'

    def is_applicable(self, document: Document) -> bool:
        if 'objectives' not in self.snify_state.mode:
            return False
        return isinstance(document, STeXDocument)

    def get_initial_state(self) -> StateType:
        return ObjectiveAnnoState()

    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        s = document.get_content()[position:]
        end_problem_idx = s.find(r'\end{sproblem}')
        end_subproblem_idx = s.find(r'\end{subproblem}')
        position: Optional[int] = None
        if end_problem_idx == -1 and end_subproblem_idx == -1:
            return None
        if end_problem_idx == -1:
            position = end_subproblem_idx + position
        else:
            position = end_problem_idx + position

        return position, []


    def show_current_state(self):
        interface.clear()
        display_snify_header(self.snify_state)


    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        ...

    def rescan(self):
        pass

