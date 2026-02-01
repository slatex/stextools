from typing import Sequence

from stextools.snify.objective_anno.objective_anno_state import ObjectiveStatus, DIM_TO_LETTER, DIMENSIONS, \
    DIM_BY_LETTER
from stextools.snify.snify_state import SnifyState, SnifyCursor
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper_extensions import SetCursorOutcome
from stextools.stex.local_stex import OpenedStexFLAMSFile, FlamsUri
from stextools.utils.json_iter import json_iter


def get_content_start(flams_json: dict, osff: OpenedStexFLAMSFile) -> tuple[int, int]:
    lineno = flams_json['full_range']['start']['line']
    lineno += 1  # move to the line after \begin{sproblem}
    lines = osff.text.splitlines(keepends=True)
    for i, line in enumerate(lines[lineno:], start=lineno):
        line = line.strip()
        # this is a somewhat crude way, but should work reasonably well in practice...
        if (not line) or any(line.startswith(prefix) for prefix in (
                '%', r'\usemodule', r'\objective', r'\importmodule', r'\usestructure'
        )):
            lineno = i + 1
        else:
            break

    return osff.line_col_to_offset(lineno, 0), lineno


class ObjectiveModificationCommand(Command):
    def __init__(self, flams_problem_json: dict, osff: OpenedStexFLAMSFile, snify_state: SnifyState):
        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖' + ''.join('{' + DIM_TO_LETTER[d].lower() + '}' for d in DIMENSIONS),
                pattern_regex='^[0-9]+' + '[' + ''.join(DIM_BY_LETTER.keys()) + ']*' + '$',
                description_short=' sets the dimensions for objective 𝑖 (e.g. "0ra").',
                description_long='For example, "0ra" sets objective 0 to "remember" and "apply", while "0" clears all dimensions of objective 0.'
            )
        )

        self.flams_problem_json = flams_problem_json
        self.osff = osff
        self.snify_state = snify_state

    def execute(self, command_str: str) -> Sequence[CommandOutcome]:
        # note: must already have been matched against pattern_regex
        digits = int(''.join(d for d in command_str if d.isdigit()))
        objss = ObjectiveStatus.from_flams_json(self.flams_problem_json)
        if digits >= len(objss):
            interface.admonition(f'Invalid objective index {digits}', 'error', confirm=True)
            return []
        objs = objss[digits]
        dims = {DIM_BY_LETTER[d] for d in command_str if not d.isdigit()}

        substitutions: list[SubstitutionOutcome] = []

        insert_pos, insert_lineno = get_content_start(self.flams_problem_json, self.osff)
        lines = self.osff.text.splitlines(keepends=True)
        indent = ''
        for c in lines[insert_lineno-1]:
            if c.isspace():
                indent += c
            else:
                break

        for dim in DIMENSIONS:
            if dim in dims and dim not in objs.dimension:
                # have to add objective
                flamsuri = FlamsUri(objs.uri)
                substitutions.append(
                    SubstitutionOutcome(
                        # TODO: only prefix module if symbol is not globally unique? (cf. annotate.py)
                        indent + r'\objective{' + dim + '}{' + flamsuri.module + '?' + flamsuri.symbol  + '}' + '\n',
                        insert_pos,
                        insert_pos,
                    )
                )
            elif dim not in dims and dim in objs.dimension:
                # have to find and remove objective
                for e in json_iter(self.flams_problem_json, ignore_keys={'full_range', 'parsed_args', 'name_range'}):
                    if (not isinstance(e, dict)) or 'Objective' not in e:
                        continue
                    e = e['Objective']
                    if e['uri'] and e['uri'][0]['uri'] == objs.uri and e.get('dim').lower() == dim:
                        range_ = self.osff.flams_range_to_offsets(e['full_range'])
                        start, end = range_
                        can_remove_whole_line = True
                        t = self.osff.text
                        while start > 0 and t[start - 1].isspace() and t[start - 1] != '\n':
                            start -= 1
                        if not (start > 0 and t[start - 1] == '\n'):
                            can_remove_whole_line = False
                        end -= 1
                        while end < len(t) - 1 and t[end + 1].isspace() and t[end + 1] != '\n':
                            end += 1
                        if not (end < len(t) - 1 and t[end + 1] == '\n'):
                            can_remove_whole_line = False
                            print('CANNOT REMOVE WHOLE LINE', end < len(t) - 1, repr(t[end + 1]))
                            input()

                        end += 2  # include line break
                        if not can_remove_whole_line:
                            start, end = range_

                        substitutions.append(
                            SubstitutionOutcome('', start, end)
                        )
                        break

        offset = 0
        substitutions.sort(key=lambda o: o.start_pos)
        for o in substitutions:
            if isinstance(o, SubstitutionOutcome):
                o.start_pos += offset
                o.end_pos += offset
                offset += len(o.new_str) - (o.end_pos - o.start_pos)

        c = self.snify_state.cursor
        new_cursor = SnifyCursor(
            document_index=c.document_index,
            banned_annotypes=c.banned_annotypes,
            in_doc_pos=c.in_doc_pos + offset,
        )

        return substitutions + [SetCursorOutcome(new_cursor)]