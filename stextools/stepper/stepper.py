from abc import abstractmethod, ABC
from typing import Optional, TypeVar, Generic, Sequence, Literal, TypeAlias

from stextools.stepper.command import CommandCollection, CommandOutcome


CursorType = TypeVar('CursorType')


class State(Generic[CursorType]):
    """
    The state of the stepper.
    It may be pickled to restore the stepper's state in a future session.
    It may therefore be necessary that the stepper keeps an additional state for ephemeral data.
    """
    def __init__(self, cursor: CursorType):
        self.cursor = cursor


StateType = TypeVar('StateType', bound=State)

class Modification(ABC, Generic[StateType]):
    """A change that can be undone. E.g. a file modification."""
    @abstractmethod
    def apply(self, state: StateType):
        pass

    @abstractmethod
    def unapply(self, state: StateType):
        pass


StopReason: TypeAlias = Literal['done', 'quit', 'fatal_error']

class StopStepper(Exception):
    """Raised to stop the stepper loop."""
    def __init__(self, reason: StopReason):
        super().__init__(f'StopStepper: {reason}')
        self.reason = reason


class Stepper(ABC, Generic[StateType]):
    """
    The base class for "ispell-like" functionality.
    """
    def __init__(self, state: StateType):
        self.state = state

        # a single undoing/redoing may undo/redo multiple modifications
        # (e.g. modify a file and change the cursor position)
        self.modification_history: list[list[Modification[StateType]]] = []
        self.modification_future: list[list[Modification[StateType]]] = []

    def run(self) -> StopReason:
        """Run the stepper until it is stopped."""
        try:
            while True:
                self._single_iteration()
        except StopStepper as e:
            return e.reason

    def _single_iteration(self):
        self.ensure_state_up_to_date()
        self.show_current_state()
        outcomes: Sequence[CommandOutcome] = self.get_current_command_collection().apply()
        new_modifications: list[Modification[StateType]] = []
        for outcome in outcomes:
            assert isinstance(outcome, CommandOutcome)
            modification = self.handle_command_outcome(outcome)
            if modification:
                new_modifications.append(modification)
                modification.apply(self.state)
                self.reset_after_modification(modification)

        if new_modifications:
            self.modification_history.append(new_modifications)
            self.modification_future.clear()

    def ensure_state_up_to_date(self):
        """May do nothing, but could, e.g., update the cursor."""

    def reset_after_modification(self, modification: Modification[StateType], is_undone: bool = False):
        """Sometimes modifications require resetting something (e.g. invalidating caches after file modifications)."""
        pass

    @abstractmethod
    def show_current_state(self):
        """display the current state/task in the user interface"""

    @abstractmethod
    def get_current_command_collection(self) -> CommandCollection:
        """Should return the commands currently applicable to the current state."""

    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification[StateType]]:
        """Handle the outcome of a command execution."""
        if isinstance(outcome, Modification):   # some command outcomes are also modifications
            return outcome
        raise NotImplementedError(f"No handler implemented for {type(outcome)}")
