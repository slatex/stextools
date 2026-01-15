from stextools.snify.formula_anno.formula_anno_state import SetSubSelectionModification, FormulaAnnoState
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface


class SelectFormulaRangeCommand(Command):
    def __init__(
            self,
            anno_type_name: str,
            formula_anno_state: FormulaAnnoState,
    ):
        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖-𝑗',
                pattern_regex='^[0-9]+-[0-9]+$',
                description_short=' select the formula range 𝑖 to 𝑗',
            )
        )
        self.anno_type_name = anno_type_name
        self.formula_anno_state = formula_anno_state

    def execute(self, call: str) -> list[CommandOutcome]:
        a, b = map(int, call.split('-'))
        if a >= b:
            interface.admonition(f'Invalid range: {a} is not less than {b}', type='error', confirm=True)
            return []
        # TODO: more error checking (out of bounds)
        assert self.formula_anno_state.formula_selection is not None
        a += self.formula_anno_state.formula_selection[0]
        b += self.formula_anno_state.formula_selection[0] + 1
        return [
            SetSubSelectionModification(self.anno_type_name, self.formula_anno_state.sub_selection, (a, b))
        ]
