"""
This file introduces the ``CommandOutcome`` class and provides a few
general-purpose subclasses of it.
Other ``CommandOutcome``s are defined wherever they are needed.
"""

from pathlib import Path
from typing import Optional, Any

from stextools.stepper.state import Cursor


class CommandOutcome:
    pass


class Exit(CommandOutcome):
    pass


class StatisticUpdateOutcome(CommandOutcome):
    def __init__(self, type_: str, value: Optional[Any] = None):
        self.type_ = type_
        self.value = value


class SubstitutionOutcome(CommandOutcome):
    """Note: command is responsible for ensuring that the index is correct *after* the previous file modification outcomes."""
    def __init__(self, new_str: str, start_pos: int, end_pos: int):
        self.new_str = new_str
        self.start_pos = start_pos
        self.end_pos = end_pos


class TextRewriteOutcome(CommandOutcome):
    def __init__(self, new_text: str, requires_reparse: bool = True):
        self.new_text = new_text
        self.requires_reparse = requires_reparse


class SetNewCursor(CommandOutcome):
    def __init__(self, new_cursor: Cursor):
        self.new_cursor = new_cursor


class FocusOutcome(CommandOutcome):
    def __init__(self, new_files: Optional[list[Path]] = None, new_cursor: Optional[Cursor] = None, select_only_stem: Optional[str] = None):
        self.new_files = new_files
        self.new_cursor = new_cursor
        self.select_only_stem = select_only_stem
