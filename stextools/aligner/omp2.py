# quick and dirty hack
import textwrap

from stextools.snify.wikidata import get_wd_catalog, WdSymbol, _get_cached_verbs, get_wd_descriptions
from stextools.stepper.command import CommandCollection, Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface, set_interface
from stextools.stepper.stepper import Stepper, State, StopStepper, Modification
from stextools.stepper.stepper_extensions import CursorModifyingStepper, SetCursorOutcome


class SkipCommand(Command):
    def __init__(self, state: State):
        super().__init__(CommandInfo(
            pattern_presentation = 's',
            description_short = 'kip once',
            description_long = 'Skips to the next possible annotation')
        )
        self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        return [
            SetCursorOutcome(
                new_cursor=self.state.cursor + 1
            )
        ]

class Omp2AnnotateCommand(Command):
    def __init__(
            self,
            concept_id: str,
            options: list[WdSymbol],
            data
    ):
        self.concept_id = concept_id
        self.options = options
        self.data = data

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
            label = _get_cached_verbs('en')[cde.uri][0]
            prevlen = len(label) + len(cde.identifier) + 2
            raw_description = get_wd_descriptions()[cde.identifier].strip() if cde.identifier in get_wd_descriptions() else '<no description>'
            description = '\n'.join(textwrap.wrap(
                ' ' * prevlen +
                raw_description or "no description",
                width=80, tabsize=6,
                )).lstrip()
            interface.write_command_info(
                str(i), f' {label} ({cde.identifier}): {description}'
            )

    def execute(self, call: str) -> list[CommandOutcome]:
        index = int(call)
        if index < 0 or index >= len(self.options):
            interface.write_text(f'Invalid option number: {index}\n', style='error')
            return []
        selected = self.options[index]
        return [AnnotateModification(self.concept_id, selected.identifier, self.data)]


class AnnotateModification(Modification[State], CommandOutcome):
    def __init__(self, omp2id: str, wdid: str, data):
        self.omp2id = omp2id
        self.wdid = wdid
        self.data = data

    def apply(self, state: State):
        self.data[self.omp2id]['alignment'] = self.wdid
        with open('/tmp/omp2.json', 'w') as fp:
            import json
            json.dump(self.data, fp, indent=2)
    def unapply(self, state: State):
        if 'alignment' in self.data[self.omp2id]:
            del self.data[self.omp2id]['alignment']
        with open('/tmp/omp2.json', 'w') as fp:
            import json
            json.dump(self.data, fp, indent=2)


class Omp2Aligner(CursorModifyingStepper, Stepper):
    def __init__(self):
        super().__init__(State(0))

        with open('/tmp/omp2.json', 'r') as fp:
            import json
            self.data = json.load(fp)
            self.keys = sorted(list(self.data.keys()))

    def show_current_state(self):
        interface.clear()
        interface.write_header(f'Concept {self.state.cursor + 1}/{len(self.keys)}')
        key = self.keys[self.state.cursor]
        entry = self.data[key]
        interface.write_text(key + '\n\n')

        labels = ', '.join(sorted(entry['labels']))
        interface.write_text(labels + '\n')
        if 'comments' in entry:
            interface.write_text('\n'.join(entry['comments']) + '\n')
        interface.newline()


    def ensure_state_up_to_date(self):
        self.annotation_choices = []
        while not self.annotation_choices:
            while self.state.cursor < len(self.data) and 'alignment' in self.data[self.keys[self.state.cursor]]:
                self.state.cursor += 1
            if self.state.cursor >= len(self.data):
                raise StopStepper('done')

            element = self.data[self.keys[self.state.cursor]]


            catalog = get_wd_catalog('en')
            for verb in element['labels']:
                if r := catalog.find_first_match(verb):
                    if r[0]:
                        continue
                    for rr in r[2]:
                        rr = rr[0]
                        if rr not in self.annotation_choices:
                            self.annotation_choices.append(rr)
            if not self.annotation_choices:
                self.state.cursor += 1

    def get_current_command_collection(self) -> CommandCollection:
        return CommandCollection(
        'aligner',
        [Omp2AnnotateCommand(
            concept_id=self.keys[self.state.cursor],
            options=self.annotation_choices,
            data=self.data,
        ),
            SkipCommand(self.state),
        ]
    )

if __name__ == '__main__':
    set_interface('console-true-light')
    aligner = Omp2Aligner()
    aligner.run()


