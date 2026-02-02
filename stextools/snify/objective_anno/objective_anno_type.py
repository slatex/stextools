from typing import Optional

from stextools.snify.annotype import AnnoType, StateType, StepperStatus
from stextools.snify.displaysupport import display_snify_header, stex_symbol_style
from stextools.snify.objective_anno.objective_anno_state import ObjectiveAnnoState, DIMENSIONS, ObjectiveStatus, \
    DIM_TO_LETTER
from stextools.snify.objective_anno.objectives_management import get_content_start, ObjectiveModificationCommand
from stextools.snify.snify_commands import ExitFileCommand, SkipCommand, ViewCommand, get_set_cursor_after_edit_function
from stextools.stepper.command import CommandCollection
from stextools.stepper.document import Document, STeXDocument, LocalFileDocument
from stextools.stepper.document_stepper import EditCommand
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import QuitCommand, UndoCommand, RedoCommand
from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import OpenedStexFLAMSFile, FlamsUri
from stextools.utils.json_iter import json_iter


class ObjectiveAnnoType(AnnoType[ObjectiveAnnoState]):
    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return f'objective-anno'

    def is_applicable(self, document: Document) -> bool:
        if 'objectives' not in self.snify_state.mode:
            return False
        return isinstance(document, STeXDocument)

    def get_initial_state(self) -> StateType:
        return ObjectiveAnnoState()

    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        flams_json, osff = self.get_flams_json()

        candidates = []
        for e in json_iter(flams_json):
            if (not isinstance(e, dict)) or 'Problem' not in e:
                continue
            range_ = osff.flams_range_to_offsets(e['Problem']['full_range'])
            if position <= range_[1]:
                candidates.append(range_[1])
        if candidates:
            return min(candidates), []
        return None


    def get_flams_json(self) -> tuple[dict, OpenedStexFLAMSFile]:
        document = self.snify_state.get_current_document()
        assert isinstance(document, STeXDocument)
        path = str(document.path)
        return FLAMS.get_file_annotations(path, load=True), OpenedStexFLAMSFile(path)

    def get_flams_problem_json(self) -> tuple[dict, OpenedStexFLAMSFile]:
        flams_json, osff = self.get_flams_json()
        candidates = []
        for e in json_iter(flams_json, ignore_keys={'full_range', 'parsed_args', 'name_range'}):
            if (not isinstance(e, dict)) or 'Problem' not in e:
                continue
            range_ = osff.flams_range_to_offsets(e['Problem']['full_range'])
            if range_[0] <= self.snify_state.cursor.in_doc_pos <= range_[1]:
                candidates.append((range_, e))

        if not candidates:
            raise RuntimeError('No problem found at current cursor position')

        range_, data = max(candidates)
        return data['Problem'], osff

    def show_current_state(self):
        flams_json, osff = self.get_flams_problem_json()
        content_start, lineno = get_content_start(flams_json, osff)

        wt = interface.write_text
        nl = interface.newline

        interface.clear()
        display_snify_header(self.snify_state)
        interface.show_code(
            ''.join(osff.text[content_start:].splitlines(keepends=True)[
                        :min(8, flams_json['full_range']['end']['line'] - lineno)])
            ,
            format='sTeX',
            show_line_numbers=True,
            first_line_number=lineno,
        )
        wt('Objectives: ')
        for i, dim in enumerate(DIMENSIONS):
            if i > 0:
                wt(', ')
            wt(dim[0].upper(), style='bold')
            wt(dim[1:])
        wt(':')
        nl()
        objs = ObjectiveStatus.from_flams_json(flams_json)
        for i, objective in enumerate(objs):
            dim_str = ''.join(
                DIM_TO_LETTER[dim] if dim in objective.dimension else '·'
                for dim in DIMENSIONS
            )
            wt(f' {i:<2} {dim_str}  ', style='bold')
            wt(stex_symbol_style(FlamsUri(objective.uri)))
            nl()
        nl()


    def get_command_collection(self, stepper_status: StepperStatus) -> CommandCollection:
        problem_json, osff = self.get_flams_problem_json()
        document = self.snify_state.get_current_document()
        assert isinstance(document, LocalFileDocument)
        return CommandCollection(
            f'snify:{self.name}',
            [
                QuitCommand(),
                ObjectiveModificationCommand(problem_json, osff, self.snify_state),
                ExitFileCommand(self.snify_state),
                ViewCommand(document),
                EditCommand(1, document, get_set_cursor_after_edit_function(self.snify_state)),
                EditCommand(2, document, get_set_cursor_after_edit_function(self.snify_state)),
                UndoCommand(is_possible=stepper_status.can_undo),
                RedoCommand(is_possible=stepper_status.can_redo),
                SkipCommand(self.snify_state, description_short='kip (stop annotating objectives)'),
            ],
            have_help=True,
        )

    def rescan(self):
        pass

