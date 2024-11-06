import abc
from pathlib import Path
from typing import Optional

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.simple_api import file_from_path
from stextools.srify.commands import CommandCollection, QuitProgramCommand, Exit, CommandOutcome, AnnotateCommand, \
    show_current_selection, ImportInsertionOutcome, SubstitutionOutcome
from stextools.srify.selection import VerbTrie, string_to_stemmed_word_sequence_simplified
from stextools.srify.state import PositionCursor, Cursor
from stextools.srify.state import State


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
            raise RuntimeError(f"File {self.file} has been modified since the last time it was read")
        self.file.write_text(self.new_text)

    def unapply(self, state: State):
        current_text = self.file.read_text()
        if current_text != self.new_text:
            raise RuntimeError(f"File {self.file} has been modified since the last time it was written")
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


class Controller:
    def __init__(self, state: State):
        self.state: State = state
        self.mh = Cache.get_mathhub(update_all=True)
        self._linker: Optional[Linker] = None
        self._verb_trie_by_lang: dict[str, VerbTrie] = {}
        self._modification_history: list[list[Modification]] = []

    @property
    def linker(self) -> Linker:
        if self._linker is None:
            self._linker = Linker(self.mh)
        return self._linker

    def reset_linker(self):
        self._linker = None
        self._verb_trie_by_lang = {}

    def get_verb_trie(self, lang: str) -> VerbTrie:
        if lang not in self._verb_trie_by_lang:
            self._verb_trie_by_lang[lang] = VerbTrie(lang, self.linker)
        return self._verb_trie_by_lang[lang]

    def run(self):
        while True:
            if not self.ensure_cursor_selection():
                return   # nothing left to annotate

            click.clear()
            show_current_selection(self.state)
            outcomes = self._get_and_run_command()

            new_modifications: list[Modification] = []

            for outcome in outcomes:
                if isinstance(outcome, Exit):
                    return
                elif isinstance(outcome, ImportInsertionOutcome):
                    text = self.state.get_current_file_text()
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=text,
                        new_text=text[:outcome.insert_pos] + outcome.inserted_str + text[outcome.insert_pos:]
                    )
                    modification.apply(self.state)
                    new_modifications.append(modification)
                elif isinstance(outcome, SubstitutionOutcome):
                    text = self.state.get_current_file_text()
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=text,
                        new_text=text[:outcome.start_pos] + outcome.new_str + text[outcome.end_pos:]
                    )
                    modification.apply(self.state)
                    new_modifications.append(modification)
                elif isinstance(outcome, CursorModification):
                    modification = CursorModification(
                        old_cursor=self.state.cursor,
                        new_cursor=outcome.new_cursor
                    )
                    modification.apply(self.state)
                    new_modifications.append(modification)
                else:
                    raise RuntimeError(f"Unexpected outcome {outcome}")

            self._modification_history.append(new_modifications)

    def _get_and_run_command(self) -> list[CommandOutcome]:
        command_collection = self._get_current_command_collection()
        return command_collection.apply(state=self.state)

    def _get_current_command_collection(self) -> CommandCollection:
        annotate_command = AnnotateCommand(
            candidate_symbols=self.get_verb_trie(self.get_current_lang()).find_first_match(
                string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang())
            )[2],
            state=self.state,
            linker=self.linker,
        )
        return CommandCollection(
            name='srify standard commands',
            commands=[
                QuitProgramCommand(),
                annotate_command,
            ],
            have_help=True
        )

    def ensure_cursor_selection(self) -> bool:
        """Returns False if nothing is left to select."""
        if isinstance(self.state.cursor, PositionCursor):
            selection_cursor = self.get_verb_trie(self.get_current_lang()).find_next_selection(self.state)
            if selection_cursor is None:
                return False
            self.state.cursor = selection_cursor
        return True

    def get_current_lang(self) -> str:
        return file_from_path(self.state.get_current_file(), self.linker).lang


def srify(files: list[str], filter: str, ignore: str):
    state = State(files=[Path(file) for file in files], filter_pattern=filter, ignore_pattern=ignore,
                  cursor=PositionCursor(file_index=0, offset=0))
    controller = Controller(state)
    controller.run()
