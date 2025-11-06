import re

from stextools.snify.snify_state import SnifyState
from stextools.snify.text_anno.text_anno_state import TextAnnoSetSelectionModification
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.stepper.interface import interface


class ReplaceCommand(Command):
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name

        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='r',
            pattern_regex='^r$',
            description_short='eplace',
            description_long='Replace the selected word with a different one.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.snify_state[self.anno_type_name]
        old_word = self.snify_state.get_current_document().get_content()[state.selection[0]:state.selection[1]]
        new_word = interface.editable_string_field(
            'Enter the new word: ',
            re.sub(r'\s+', ' ', old_word.strip())
        )

        return [
            SubstitutionOutcome(new_word, state.selection[0], state.selection[1]),
            TextAnnoSetSelectionModification(
                anno_type_name=self.anno_type_name,
                old_selection=state.selection,
                new_selection=(state.selection[0], state.selection[0] + len(new_word)),
            )
        ]

    # def execute(self, *, state: State, call: str) -> Sequence[CommandOutcome]:
    #     assert isinstance(state.cursor, SelectionCursor)
    #     new_word = click.prompt('Enter the new word: ', default=state.get_selected_text())
    #     return [
    #         SubstitutionOutcome(new_word, state.cursor.selection_start, state.cursor.selection_end),
    #         SetNewCursor(
    #             SelectionCursor(state.cursor.file_index, state.cursor.selection_start, state.cursor.selection_start + len(new_word))
    #         )
    #     ]

