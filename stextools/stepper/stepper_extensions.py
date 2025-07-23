from copy import deepcopy
from typing import Optional, Generic

from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Stepper, Modification, StateType, StopStepper, CursorType


#######################################################################
#   QUIT COMMAND
#######################################################################

class QuitOutcome(CommandOutcome):
    pass


class QuitCommand(Command):
    def __init__(self, long_description: Optional[str] = None):
        super().__init__(CommandInfo(
            pattern_presentation='q',
            description_short='uit',
            description_long=long_description or ''
        ))

    def execute(self, call: str) -> list[CommandOutcome]:
        return [QuitOutcome()]


class QuittableStepper(Stepper[StateType]):
    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification[StateType]]:
        if isinstance(outcome, QuitOutcome):
            raise StopStepper('quit')

        return super().handle_command_outcome(outcome)


#######################################################################
#   CURSOR SETTING
#######################################################################

class SetCursorOutcome(CommandOutcome, Generic[CursorType]):
    def __init__(self, new_cursor: CursorType):
        self.new_cursor = new_cursor


class CursorModification(Modification[StateType], Generic[StateType, CursorType]):
    def __init__(self, old_cursor: CursorType, new_cursor: CursorType):
        self.old_cursor = old_cursor
        self.new_cursor = new_cursor

    def apply(self, state: StateType):
        # print(f'CursorModification: changing cursor from {state.cursor} to {self.new_cursor}')
        state.cursor = self.new_cursor

    def unapply(self, state: StateType):
        # print(f'CursorModification: changing cursor from {state.cursor} to {self.old_cursor}')
        state.cursor = self.old_cursor


class CursorModifyingStepper(Stepper[StateType]):
    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification[StateType]]:
        if isinstance(outcome, SetCursorOutcome):
            return CursorModification(deepcopy(self.state.cursor), deepcopy(outcome.new_cursor))

        return super().handle_command_outcome(outcome)


#######################################################################
#   UNDO/REDO
#######################################################################

class UndoOutcome(CommandOutcome):
    ...


class RedoOutcome(CommandOutcome):
    ...



class UndoCommand(Command):
    def __init__(self, is_possible: bool):
        self.is_possible = is_possible
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='u',
            description_short='ndo' + ('' if is_possible else ' (currently nothing to undo)'),
            description_long='Undoes the most recent modification')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        if self.is_possible:
            return [UndoOutcome()]
        interface.admonition('Nothing to undo', 'error', confirm=True)
        return []


class RedoCommand(Command):
    def __init__(self, is_possible: bool):
        self.is_possible = is_possible
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='uu',
            description_short=' redo ("undo undo")' + ('' if is_possible else ' (currently nothing to redo)'),
            description_long='Redoes the most recently undone modification')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        if self.is_possible:
            return [RedoOutcome()]
        interface.admonition('Nothing to redo', 'error', confirm=True)
        return []


class UndoableStepper(Stepper[StateType]):
    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification[StateType]]:
        if isinstance(outcome, UndoOutcome):
            mods = self.modification_history.pop()
            for mod in reversed(mods):
                mod.unapply(self.state)
                self.reset_after_modification(mod)
                self.modification_future.append(mods)
        elif isinstance(outcome, RedoOutcome):
            mods = self.modification_future.pop()
            for mod in mods:
                mod.apply(self.state)
                self.reset_after_modification(mod)
            self.modification_history.append(mods)
        else:
            return super().handle_command_outcome(outcome)


#######################################################################
#   FOCUS
#######################################################################


class FocussableState:
    on_unfocus = None

    def is_focussed(self) -> bool:
        return self.on_unfocus is not None


class FocusOutcome(CommandOutcome, Modification):
    def __init__(self, new_state, stepper: Stepper):
        self.new_state = new_state
        self.stepper = stepper
        self.old_state = self.stepper.state

    def apply(self, state: StateType):
        self.new_state.on_unfocus = self.old_state
        self.stepper.state = self.new_state

    def unapply(self, state: StateType):
        self.stepper.state = state.on_unfocus


class UnfocusOutcome(CommandOutcome):
    def __init__(self, stepper: Stepper):
        self.stepper = stepper
        self.focus_state = self.stepper.state

    def apply(self, state: StateType):
        self.stepper.state = state.on_unfocus

    def unapply(self, state: StateType):
        self.stepper.state = self.focus_state


class UnfocusCommand(Command):
    def __init__(self, stepper: Stepper, long_description: Optional[str] = None):
        super().__init__(CommandInfo(
            pattern_presentation='q',
            description_short='uit (stop focussed mode)',
            description_long=long_description or ''
        ))
        self.stepper = stepper

    def execute(self, call: str) -> list[CommandOutcome]:
        return [UnfocusOutcome(self.stepper)]
