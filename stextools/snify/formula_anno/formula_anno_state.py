import dataclasses
from typing import TypeVar, Generic

from stextools.snify.snify_state import SnifyState
from stextools.stepper.command import CommandOutcome
from stextools.stepper.stepper import Modification


@dataclasses.dataclass
class FormulaAnnoState:
    # the formula that is currently being annotated
    formula_selection: tuple[int, int] | None = None

    # the range in the formula that is currently being annotated
    sub_selection: tuple[int, int] | None = None

    # the arguments in the sub_selection
    args_in_sub_selection: list[tuple[int, int]] | None = None

    @property
    def level(self) -> int:
        """
        The "level" indicates how deep in the annotation process we are.
        "level" is a bad name for this, but I can't think of anything better right now.

        0: no formula selected
        1: formula selected, but no range to annotate has been selected
        2: range selected, but no arguments selected
        3: arguments selected - ready to select and create an annotation
        """
        if self.formula_selection is None:
            return 0
        if self.sub_selection is None:
            return 1
        if self.args_in_sub_selection is None:
            return 2
        return 3



_V = TypeVar('_V')

@dataclasses.dataclass
class SetStateAttributeModification(Modification, CommandOutcome, Generic[_V]):
    anno_type_name: str
    attribute_name: str
    old_value: _V
    new_value: _V

    def apply(self, state: SnifyState):
        s = state.annotype_states[self.anno_type_name]
        setattr(s, self.attribute_name, self.new_value)

    def unapply(self, state: SnifyState):
        s = state.annotype_states[self.anno_type_name]
        setattr(s, self.attribute_name, self.old_value)

class SetFormulaSelectionModification(SetStateAttributeModification[tuple[int, int] | None]):
    def __init__(self, anno_type_name: str,
                 old_selection: tuple[int, int] | None,
                 new_selection: tuple[int, int] | None):
        super().__init__(anno_type_name, 'formula_selection', old_selection, new_selection)

class SetSubSelectionModification(SetStateAttributeModification[tuple[int, int] | None]):
    def __init__(self, anno_type_name: str,
                 old_selection: tuple[int, int] | None,
                 new_selection: tuple[int, int] | None):
        super().__init__(anno_type_name, 'sub_selection', old_selection, new_selection)

class SetArgsInSubSelectionModification(SetStateAttributeModification[list[tuple[int, int]] | None]):
    def __init__(self, anno_type_name: str,
                 old_args: list[tuple[int, int]] | None,
                 new_args: list[tuple[int, int]] | None):
        super().__init__(anno_type_name, 'args_in_sub_selection', old_args, new_args)