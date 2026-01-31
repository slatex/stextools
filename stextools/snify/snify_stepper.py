from collections import namedtuple
from typing import Optional

from stextools.snify.annotype import AnnoType, StepperStatus
from stextools.snify.formula_anno.formula_anno_type import FormulaAnnoType
from stextools.snify.objective_anno.objective_anno_type import ObjectiveAnnoType
from stextools.snify.snify_commands import RescanOutcome
from stextools.snify.snify_state import SnifyState, SnifyCursor, SetOngoingAnnoTypeModification
from stextools.snify.stex_dependency_addition import DependencyModificationOutcome
from stextools.snify.text_anno.text_anno_type import TextAnnoType
from stextools.stepper.command import CommandCollection, CommandOutcome
from stextools.stepper.document_stepper import DocumentModifyingStepper
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Stepper, StopStepper, Modification
from stextools.stepper.stepper_extensions import QuittableStepper, CursorModifyingStepper, UndoableStepper, \
    CursorModification

ANNO_TYPES: list[AnnoType] = [
    TextAnnoType('stex'),
    TextAnnoType('wikidata'),
    FormulaAnnoType(),
    ObjectiveAnnoType(),
]

ANNO_TYPE_LOOKUP: dict[str, AnnoType] = {
    atype.name: atype for atype in ANNO_TYPES
}


class SnifyStepper(
    DocumentModifyingStepper, QuittableStepper, CursorModifyingStepper, UndoableStepper, Stepper[SnifyState]
):
    state: SnifyState

    def __init__(self, state: SnifyState):
        super().__init__(state)
        self.state = state

    def get_stepper_status(self) -> StepperStatus:
        return StepperStatus(
            can_undo=bool(self.modification_history),
            can_redo=bool(self.modification_future),
            stepper_ref=self,
        )

    def ensure_state_up_to_date(self):
        """ Regularly called by the stepper to ensure that we have an annotation to work on. """

        if self.state.ongoing_annotype is not None:
            return   # already up to date

        document_index = self.state.cursor.document_index
        in_doc_pos = self.state.cursor.in_doc_pos

        Suggestion = namedtuple('Suggestion', ['name', 'position', 'setup_modifications'])

        while document_index < len(self.state.documents):
            suggestions: list[Suggestion] = []
            doc = self.state.documents[document_index]
            for annotype_name in self.state.anno_types:
                anno_type = ANNO_TYPE_LOOKUP[annotype_name]
                anno_type.set_snify_state(self.state)
                if not anno_type.is_applicable(doc):
                    continue
                if annotype_name not in self.state:
                    self.state[annotype_name] = anno_type.get_initial_state()
                pos = in_doc_pos
                if annotype_name in self.state.cursor.banned_annotypes:
                    pos += 1   # only look for potential annotations after the current position
                r = anno_type.get_next_annotation_suggestion(
                    self.state.documents[document_index],
                    pos,
                )
                if r is not None:
                    suggestions.append(Suggestion(annotype_name, r[0], r[1]))

            if suggestions:
                next_anno = min(suggestions, key=lambda e: e.position)
                if next_anno.position < in_doc_pos:
                    raise RuntimeError(
                        f'{next_anno.name!r} returned an an annotation at position '
                        f'{next_anno.position}, which is not after the current cursor position '
                        f'{in_doc_pos}.'
                    )

                setup_modifications: list[Modification] = next_anno.setup_modifications
                if document_index != self.state.cursor.document_index or next_anno.position != self.state.cursor.in_doc_pos:
                    new_cursor = SnifyCursor(
                        document_index=document_index,
                        in_doc_pos=next_anno.position,
                        banned_annotypes=set(),   # reset banned endeavours on position change
                    )
                    setup_modifications = [
                        CursorModification(self.state.cursor, new_cursor)
                    ] + setup_modifications

                setup_modifications.append(
                    SetOngoingAnnoTypeModification(
                        old_annotype=self.state.ongoing_annotype,
                        new_annotype=next_anno.name
                    )
                )

                for modification in setup_modifications:
                    modification.apply(self.state)
                if self.modification_history:
                    self.modification_history[-1].extend(setup_modifications)
                else:
                    self.modification_history.append(setup_modifications)

                # TODO: Does this cause problems?
                # If undoing modifications automatically leads to this point,
                # it effectively breaks the redo functionality.
                # Resetting might not be necessary as we are (probably?) not doing modifications with long-term impact.
                self.modification_future = []

                return   # found something to annotate

            # nothing found in this document; move to the next one
            document_index += 1
            in_doc_pos = 0

        interface.clear()
        interface.write_text('There is nothing left to annotate.\n')
        if self.state.on_unfocus:
            interface.write_text('Ending focus mode.\n')
            interface.await_confirmation()
            self.state = self.state.on_unfocus
            # TODO: do we have to call ensure_state_up_to_date again here?
        else:
            interface.write_text('Quitting snify.\n')
            interface.await_confirmation()
            raise StopStepper('done')

    def get_current_anno_type(self) -> AnnoType:
        assert self.state.ongoing_annotype is not None
        return ANNO_TYPE_LOOKUP[self.state.ongoing_annotype]

    def show_current_state(self):
        self.get_current_anno_type().set_snify_state(self.state)
        self.get_current_anno_type().show_current_state()

    def get_current_command_collection(self) -> CommandCollection:
        return self.get_current_anno_type().get_command_collection(self.get_stepper_status())

    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification]:
        if isinstance(outcome, RescanOutcome):
            for anno_type in ANNO_TYPES:
                anno_type.rescan()
            return None
        elif isinstance(outcome, DependencyModificationOutcome):
            return outcome.get_modification(self.state)
        else:
            return super().handle_command_outcome(outcome)
