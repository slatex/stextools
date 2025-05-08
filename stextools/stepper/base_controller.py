from __future__ import annotations

from pathlib import Path
from typing import TypeVar, Generic, Optional, Sequence

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.stepper.command_outcome import Exit, SubstitutionOutcome, TextRewriteOutcome, SetNewCursor, \
    StatisticUpdateOutcome, FocusOutcome, CommandOutcome
from stextools.stepper.commands import show_current_selection, UndoOutcome, RedoOutcome, RescanOutcome, \
    CommandCollection
from stextools.stepper.file_management import include_inputs
from stextools.stepper.modifications import Modification, FileModification, CursorModification, StatisticModification, \
    PushFocusModification
from stextools.stepper.state import State, FocusInfoType, PositionCursor, SelectionCursor

S = TypeVar('S', bound=State)


class BaseController(Generic[S]):
    def __init__(self, state: S, new_files: Optional[list[Path]] = None, initial_focus_info: Optional[FocusInfoType] = None):
        self.state: S = state
        self.mh = Cache.get_mathhub(update_all=True)
        self._linker: Optional[Linker] = None
        self._modification_history: list[list[Modification]] = []
        self._modification_future: list[list[Modification]] = []   # for re-doing

        if new_files:
            self.state.push_focus(
                new_files=include_inputs(self.mh, new_files),
                new_cursor=None,
                other_info=initial_focus_info   # type: ignore
            )


    @property
    def linker(self) -> Linker:
        if self._linker is None:
            self._linker = Linker(self.mh)
        return self._linker

    def reset_linker(self):
        self._linker = None
        self.post_reset_linker_hook()

    def post_reset_linker_hook(self):
        """ called every time after the linker is reset """
        pass

    def run(self) -> bool:
        """Returns True iff there are more files to annotate."""
        while True:
            if not self.state.focus_stack:
                return False

            if not self.ensure_cursor_selection():
                click.clear()
                self.state.pop_focus()
                if self.state.focus_stack:
                    print('Focus mode ended')
                else:
                    if self.state.statistic_annotations_added:
                        print(f'Congratulations! You have added {self.state.statistic_annotations_added} annotations.')
                    print('There are no more files to annotate.')
                click.pause()
                continue

            click.clear()
            show_current_selection(self.state, self.linker)
            outcomes = self._get_and_run_command()

            new_modifications: list[Modification] = []

            for outcome in outcomes:
                modification: Optional[Modification] = None

                if isinstance(outcome, Exit):
                    return True
                elif isinstance(outcome, SubstitutionOutcome):
                    text = self.state.get_current_file_text()
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=text,
                        new_text=text[:outcome.start_pos] + outcome.new_str + text[outcome.end_pos:]
                    )
                elif isinstance(outcome, TextRewriteOutcome):
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=self.state.get_current_file_text(),
                        new_text=outcome.new_text
                    )
                    if not outcome.requires_reparse:
                        modification.files_to_reparse = []
                elif isinstance(outcome, SetNewCursor):
                    modification = CursorModification(
                        old_cursor=self.state.cursor,
                        new_cursor=outcome.new_cursor
                    )
                elif isinstance(outcome, StatisticUpdateOutcome):
                    modification = StatisticModification(outcome)
                elif isinstance(outcome, FocusOutcome):
                    modification = PushFocusModification(
                        new_files=outcome.new_files,
                        new_cursor=outcome.new_cursor,
                        other_info=outcome.other_info
                    )
                elif isinstance(outcome, UndoOutcome):
                    mods = self._modification_history.pop()
                    for mod in reversed(mods):
                        mod.unapply(self.state)
                        self.reset_after_modification(mod)
                        self._modification_future.append(mods)
                elif isinstance(outcome, RedoOutcome):
                    mods = self._modification_future.pop()
                    for mod in mods:
                        mod.apply(self.state)
                        self.reset_after_modification(mod)
                    self._modification_history.append(mods)
                elif isinstance(outcome, RescanOutcome):
                    self.reset_linker()
                    self.mh.update()
                else:
                    modification = self.handle_custom_outcome(outcome)

                if modification is not None:
                    modification.apply(self.state)
                    new_modifications.append(modification)
                    self.reset_after_modification(modification)

            if new_modifications:
                self._modification_history.append(new_modifications)
                self._modification_future.clear()
                if len(self._modification_history) > 150:
                    self._modification_history = self._modification_history[-100:]

    def handle_custom_outcome(self, outcome) -> Optional[Modification]:
        raise ValueError(f'Unknown outcome: {outcome}')

    def reset_after_modification(self, modification: Modification):
        if modification.files_to_reparse:
            self.reset_linker()
            for file in modification.files_to_reparse:
                doc = self.mh.get_stex_doc(file)
                assert doc is not None
                doc.delete_doc_info_if_outdated()

    def _get_and_run_command(self) -> Sequence[CommandOutcome]:
        command_collection = self.get_current_command_collection()
        print()
        return command_collection.apply(state=self.state)

    def get_current_command_collection(self) -> CommandCollection:
        raise NotImplementedError()


    def ensure_cursor_selection(self) -> bool:
        """Returns False if nothing is left to select."""
        if self.state.cursor.file_index >= len(self.state.files):
            return False
        if isinstance(self.state.cursor, PositionCursor):
            # selection_cursor = self.get_verb_trie(self.get_current_lang()).find_next_selection(self.state)
            selection_cursor = self.find_next_selection()
            if selection_cursor is None:
                return False
            self.state.cursor = selection_cursor
        return True

    def find_next_selection(self) -> Optional[SelectionCursor]:
        raise NotImplementedError()

    def get_current_lang(self) -> str:
        return self.state.get_current_lang(self.linker)
