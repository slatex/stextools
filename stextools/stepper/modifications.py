import abc
from pathlib import Path
from typing import Optional

import click

from stextools.stepper.command_outcome import StatisticUpdateOutcome
from stextools.stepper.state import State, Cursor


class Modification(abc.ABC):
    files_to_reparse: list[Path]

    @abc.abstractmethod
    def apply(self, state: State):
        pass

    @abc.abstractmethod
    def unapply(self, state: State):
        pass


class FileModification(Modification):
    def __init__(self, file: Path, old_text: str, new_text: str):
        self.files_to_reparse = [file]
        self.file = file
        self.old_text = old_text
        self.new_text = new_text

    def apply(self, state: State):
        current_text = self.file.read_text()
        if current_text != self.old_text:
            print(click.style(f"File {self.file} has been modified since the last time it was read", fg='black', bg='bright_yellow'))
            print(click.style(f"I will not change the file", fg='black', bg='bright_yellow'))
            click.pause()
            return

        self.file.write_text(self.new_text)

    def unapply(self, state: State):
        current_text = self.file.read_text()
        if current_text != self.new_text:
            print(click.style(f"File {self.file} has been modified since the last time it was written", fg='black', bg='bright_yellow'))
            print(click.style(f"I will not change the file", fg='black', bg='bright_yellow'))
            click.pause()
            return
        self.file.write_text(self.old_text)


class CursorModification(Modification):
    def __init__(self, old_cursor: Cursor, new_cursor: Cursor):
        self.files_to_reparse = []
        self.old_cursor = old_cursor
        self.new_cursor = new_cursor

    def apply(self, state: State):
        state.cursor = self.new_cursor

    def unapply(self, state: State):
        state.cursor = self.old_cursor


class PushFocusModification(Modification):
    def __init__(self, new_files: Optional[list[Path]], new_cursor: Optional[Cursor], select_only_stem: Optional[str]):
        self.files_to_reparse = []
        self.new_files = new_files
        self.new_cursor = new_cursor
        self.select_only_stem = select_only_stem

    def apply(self, state: State):
        state.push_focus(new_files=self.new_files, new_cursor=self.new_cursor, select_only_stem=self.select_only_stem)

    def unapply(self, state: State):
        state.pop_focus()


class StatisticModification(Modification):
    def __init__(self, statistic_update_outcome: StatisticUpdateOutcome):
        self.files_to_reparse = []
        self.type_ = statistic_update_outcome.type_
        self.value = statistic_update_outcome.value

    def apply(self, state: State):
        if self.type_ == 'annotation_inc':
            state.statistic_annotations_added += 1
        else:
            raise RuntimeError(f"Unexpected type {self.type_}")

    def unapply(self, state: State):
        if self.type_ == 'annotation_inc':
            state.statistic_annotations_added -= 1
        else:
            raise RuntimeError(f"Unexpected type {self.type_}")
