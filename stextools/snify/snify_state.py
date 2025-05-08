import dataclasses
from pathlib import Path
from typing import Optional

from stextools.core.linker import Linker
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

    lang: Optional[str]

    def __init__(self, files: list[Path], cursor: Cursor, filter_pattern: str, ignore_pattern: str,
                 lang: Optional[str] = None):
        super().__init__(files, cursor)
        self.filter_pattern = filter_pattern
        self.ignore_pattern = ignore_pattern

        self.skip_literal_by_file = {}
        self.skip_literal_all_session = {}
        self.skip_stem_by_file = {}
        self.skip_stem_all_session = {}

        self.lang = lang

    def get_current_lang(self, linker: Linker) -> str:
        if self.lang is None:
            self.lang = super().get_current_lang(linker)
        return self.lang

