from stextools.lexicon.lexgenstate import LexGenState
from stextools.snify.snifystate import SnifyCursor
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.stepper_extensions import SetCursorOutcome


class SkipCommand(Command):
    def __init__(self, state: LexGenState):
        super().__init__(CommandInfo(
            pattern_presentation = 's',
            description_short = 'kip to next definiendum')
        )
        self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        assert isinstance(self.state.cursor.selection, tuple)
        return [
            SetCursorOutcome(
                new_cursor=SnifyCursor(self.state.cursor.document_index, self.state.cursor.selection[-1] + 1)
            )
        ]
