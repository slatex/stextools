import dataclasses
from pathlib import Path
from typing import Optional, TypeVar, Generic

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



FocusInfoType = TypeVar('FocusInfoType')

@dataclasses.dataclass
class Focus(Generic[FocusInfoType]):
    cursor_on_unfocus: Cursor
    files_on_unfocus: list[Path]
    other_info: FocusInfoType
    # select_only_stem: Optional[str] = None


@dataclasses.dataclass
class State(Generic[FocusInfoType]):
    """ Editing state for snify. This can be saved to a file and reloaded. """
    files: list[Path]
    cursor: Cursor

    statistic_annotations_added: int = 0
    focus_stack: list[Focus[FocusInfoType]] = dataclasses.field(default_factory=list)

    def push_focus(
            self,
            new_files: Optional[list[Path]],
            new_cursor: Optional[Cursor],
            other_info: FocusInfoType,
    ):
        self.focus_stack.append(
            Focus(cursor_on_unfocus=self.cursor, files_on_unfocus=self.files, other_info=other_info)
        )
        if new_files is not None:
            self.files = new_files
        if new_cursor is not None:
            self.cursor = new_cursor

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
        file = file_from_path(self.get_current_file(), linker)
        assert file is not None
        lang = file.lang
        if lang == '*':
            return 'unknownlang'
        return lang
