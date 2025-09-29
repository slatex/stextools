import dataclasses
import textwrap
from typing import Literal, Optional

from stextools.stepper.command import CommandCollection, Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Stepper, State, StopStepper, Modification


class AlignerState(State[int]):
    def __init__(self, cursor: int, alignments: dict[str, Optional[str]]):
        super().__init__(cursor)
        self.alignments = alignments


@dataclasses.dataclass
class ConceptDbEntry:
    identifier: str
    label: str
    description: str
    description_format: Literal['tex', 'plain']
    verbalizations: list[str]


class AnnotateModification(Modification[AlignerState], CommandOutcome):
    def __init__(self, concept_id: str, target_id: Optional[str]):
        self.concept_id = concept_id
        self.target_id = target_id

    def apply(self, state: AlignerState):
        state.alignments[self.concept_id] = self.target_id
        state.cursor += 1

    def unapply(self, state: AlignerState):
        if self.concept_id in state.alignments:
            del state.alignments[self.concept_id]
        state.cursor -= 1


class WdAnnotateCommand(Command):
    def __init__(
            self,
            concept_id: str,
            options: list[ConceptDbEntry],
    ):
        self.concept_id = concept_id
        self.options = options

        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖',
                pattern_regex='^[0-9]+$',
                description_short=' annotate with 𝑖',
                description_long='Annotates the current concept with option number 𝑖'
            )
        )

    def standard_display(self):
        for i, cde in enumerate(self.options):
            prevlen = len(cde.label) + len(cde.identifier) + 2
            description = '\n'.join(textwrap.wrap(
                ' ' * prevlen +
                cde.description or "no description",
                width=80, tabsize=6,
                ))
            interface.write_command_info(
                str(i), f'{cde.label} ({cde.identifier}): {description}'
            )

    def execute(self, call: str) -> list[CommandOutcome]:
        index = int(call)
        if index < 0 or index >= len(self.options):
            interface.write_text(f'Invalid option number: {index}\n', style='error')
            return []
        selected = self.options[index]
        return [AnnotateModification(self.concept_id, selected.identifier)]


class Aligner(Stepper):
    def __init__(self, sources: list[ConceptDbEntry], targets: list[ConceptDbEntry], current_alignments: dict[str, Optional[str]]):
        self.sources = sources
        self.targets = targets
        self.target_by_verb: dict[str, list[ConceptDbEntry]] = {}
        for t in targets:
            for v in t.verbalizations:
                self.target_by_verb.setdefault(v, []).append(t)
        self.alignments = current_alignments

        self.state = AlignerState(0, self.alignments)

        super(Aligner, self).__init__(self.state)

    def ensure_state_up_to_date(self):
        while self.state.cursor < len(self.sources) and self.sources[self.state.cursor].identifier in self.alignments:
            self.state.cursor += 1
        if self.state.cursor >= len(self.sources):
            raise StopStepper('done')

    def show_current_state(self):
        interface.write_header(f'Concept {self.state.cursor + 1}/{len(self.sources)}')
        cc = self.sources[self.state.cursor]  # current concept
        interface.write_text(cc.identifier, style='bold')
        interface.newline()
        interface.write_text(cc.label, style='highlight1')
        interface.newline()
        if cc.description_format == 'tex':
            interface.show_code(cc.description, 'tex')
        else:
            interface.write_text(cc.description)
        interface.newline()

    def get_current_command_collection(self) -> CommandCollection:
        options = list(
            {
                cde
                for v in self.sources[self.state.cursor].verbalizations
                for cde in self.target_by_verb.get(v, [])
            }
        )
        return CommandCollection(
            'aligner',
            [WdAnnotateCommand(
                concept_id=self.sources[self.state.cursor].identifier,
                options=options,
            ),
            ]
        )

if __name__ == '__main__':
    ...