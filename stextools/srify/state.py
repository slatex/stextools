import abc
import dataclasses
from pathlib import Path


@dataclasses.dataclass
class Cursor:
    file_index: int


@dataclasses.dataclass
class SelectionCursor(Cursor):
    file_index: int

    selection_start: int
    selection_end: int


@dataclasses.dataclass
class PositionCursor(Cursor):
    file_index: int

    offset: int


class Focus(abc.ABC):
    cursor_on_unfocus: Cursor


@dataclasses.dataclass
class State:
    """ Editing state for srify. This can be saved to a file and reloaded. """
    files: list[Path]

    filter_pattern: str
    ignore_pattern: str

    cursor: Cursor

    focus_stack: list[Focus] = dataclasses.field(default_factory=list)

    def get_current_file(self) -> Path:
        return self.files[self.cursor.file_index]

    def get_current_file_text(self) -> str:
        return self.get_current_file().read_text()


