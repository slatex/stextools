import abc
import dataclasses
from pathlib import Path
from typing import Optional

from stextools.core.linker import Linker
from stextools.core.simple_api import file_from_path, SimpleFile


@dataclasses.dataclass(frozen=True)
class Cursor:
    file_index: int


@dataclasses.dataclass(frozen=True)
class SelectionCursor(Cursor):
    file_index: int

    selection_start: int
    selection_end: int


@dataclasses.dataclass(frozen=True)
class PositionCursor(Cursor):
    file_index: int

    offset: int


@dataclasses.dataclass
class Focus:
    cursor_on_unfocus: Cursor
    files_on_unfocus: list[Path]
    select_only_stem: Optional[str] = None


@dataclasses.dataclass
class State:
    """ Editing state for srify. This can be saved to a file and reloaded. """
    files: list[Path]

    filter_pattern: str
    ignore_pattern: str

    cursor: Cursor

    statistic_annotations_added: int = 0

    skip_literal_by_file: dict[Path, set[str]] = dataclasses.field(default_factory=dict)
    skip_literal_all_session: dict[str, set[str]] = dataclasses.field(default_factory=dict)  # lang -> set of words
    skip_stem_by_file: dict[Path, set[str]] = dataclasses.field(default_factory=dict)
    skip_stem_all_session: dict[str, set[str]] = dataclasses.field(default_factory=dict)  # lang -> set of stems

    focus_stack: list[Focus] = dataclasses.field(default_factory=list)

    def push_focus(
            self,
            new_files: Optional[list[Path]] = None,
            new_cursor: Optional[Cursor] = None,
            select_only_stem: Optional[str] = None
    ):
        if new_files is not None:
            self.files = new_files
        if new_cursor is not None:
            self.cursor = new_cursor
        self.focus_stack.append(
            Focus(cursor_on_unfocus=self.cursor, files_on_unfocus=self.files, select_only_stem=select_only_stem)
        )

    def pop_focus(self):
        focus = self.focus_stack.pop()
        self.cursor = focus.cursor_on_unfocus
        self.files = focus.files_on_unfocus

    def get_current_file(self) -> Path:
        return self.files[self.cursor.file_index]

    def get_current_file_simple_api(self, linker: Linker) -> SimpleFile:
        file = file_from_path(self.get_current_file(), linker)
        if file is None:
            raise RuntimeError(f"File {self.get_current_file()} does not seem to be loaded")
        return file

    def get_current_file_text(self) -> str:
        return self.get_current_file().read_text()

    def get_selected_text(self) -> str:
        assert isinstance(self.cursor, SelectionCursor)
        return self.get_current_file_text()[self.cursor.selection_start:self.cursor.selection_end]

    def get_current_lang(self, linker: Linker) -> str:
        lang = file_from_path(self.get_current_file(), linker).lang
        if lang == '*':
            return 'unknownlang'
        return lang
