import dataclasses
from pathlib import Path
from typing import Optional

from stextools.stepper.state import State, Cursor


@dataclasses.dataclass
class SnifyFocusInfo:
    select_only_stem: Optional[str] = None


class SnifyState(State[SnifyFocusInfo]):
    filter_pattern: str
    ignore_pattern: str

    skip_literal_by_file: dict[Path, set[str]]   # = dataclasses.field(default_factory=dict)
    skip_literal_all_session: dict[str, set[str]] # = dataclasses.field(default_factory=dict)  # lang -> set of words
    skip_stem_by_file: dict[Path, set[str]]  # = dataclasses.field(default_factory=dict)
    skip_stem_all_session: dict[str, set[str]] # = dataclasses.field(default_factory=dict)  # lang -> set of stems

    def __init__(self, files: list[Path], cursor: Cursor, filter_pattern: str, ignore_pattern: str):
        super().__init__(files, cursor)
        self.filter_pattern = filter_pattern
        self.ignore_pattern = ignore_pattern

        self.skip_literal_by_file = {}
        self.skip_literal_all_session = {}
        self.skip_stem_by_file = {}
        self.skip_stem_all_session = {}

