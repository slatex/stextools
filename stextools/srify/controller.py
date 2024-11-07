import abc
from pathlib import Path
from typing import Optional

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.simple_api import file_from_path
from stextools.srify.commands import CommandCollection, QuitProgramCommand, Exit, CommandOutcome, AnnotateCommand, \
    show_current_selection, ImportInsertionOutcome, SubstitutionOutcome, SetNewCursor, SkipOnceCommand, IgnoreCommand, \
    IgnoreWordOutcome, ExitFileCommand, UndoOutcome, RedoOutcome, UndoCommand, RedoCommand, ViewCommand, View_i_Command
from stextools.srify.selection import VerbTrie, string_to_stemmed_word_sequence_simplified, IgnoreList
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


class IgnoreListAddition(Modification):
    def __init__(self, lang: str, word: str):
        self.files_to_reparse = []
        self.lang = lang
        self.word = word

    def apply(self, state: State):
        IgnoreList.add_word(lang=self.lang, word=self.word)

    def unapply(self, state: State):
        IgnoreList.remove_word(lang=self.lang, word=self.word)


class Controller:
    def __init__(self, state: State):
        self.state: State = state
        self.mh = Cache.get_mathhub(update_all=True)
        self._linker: Optional[Linker] = None
        self._verb_trie_by_lang: dict[str, VerbTrie] = {}
        self._modification_history: list[list[Modification]] = []
        self._modification_future: list[list[Modification]] = []   # for re-doing

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
                modification: Optional[Modification] = None

                if isinstance(outcome, Exit):
                    return
                elif isinstance(outcome, ImportInsertionOutcome):
                    text = self.state.get_current_file_text()
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=text,
                        new_text=text[:outcome.insert_pos] + outcome.inserted_str + text[outcome.insert_pos:]
                    )
                elif isinstance(outcome, SubstitutionOutcome):
                    text = self.state.get_current_file_text()
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=text,
                        new_text=text[:outcome.start_pos] + outcome.new_str + text[outcome.end_pos:]
                    )
                elif isinstance(outcome, SetNewCursor):
                    modification = CursorModification(
                        old_cursor=self.state.cursor,
                        new_cursor=outcome.new_cursor
                    )
                elif isinstance(outcome, IgnoreWordOutcome):
                    modification = IgnoreListAddition(lang=outcome.lang, word=outcome.word)
                elif isinstance(outcome, UndoOutcome):
                    mods = self._modification_history.pop()
                    for mod in reversed(mods):
                        mod.unapply(self.state)
                    self._modification_future.append(mods)
                elif isinstance(outcome, RedoOutcome):
                    mods = self._modification_future.pop()
                    for mod in mods:
                        mod.apply(self.state)
                    self._modification_history.append(mods)
                else:
                    raise RuntimeError(f"Unexpected outcome {outcome}")

                if modification is not None:
                    modification.apply(self.state)
                    new_modifications.append(modification)

                    if modification.files_to_reparse:
                        self.reset_linker()
                        for file in modification.files_to_reparse:
                            self.mh.get_stex_doc(file).delete_doc_info_if_outdated()

            if new_modifications:
                self._modification_history.append(new_modifications)
                self._modification_future.clear()
                if len(self._modification_history) > 150:
                    self._modification_history = self._modification_history[-100:]

    def _get_and_run_command(self) -> list[CommandOutcome]:
        command_collection = self._get_current_command_collection()
        print()
        return command_collection.apply(state=self.state)

    def _get_current_command_collection(self) -> CommandCollection:
        candidate_symbols = self.get_verb_trie(self.get_current_lang()).find_first_match(
            string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang())
        )[2]
        annotate_command = AnnotateCommand(
            candidate_symbols=candidate_symbols,
            state=self.state,
            linker=self.linker,
        )
        return CommandCollection(
            name='srify standard commands',
            commands=[
                QuitProgramCommand(),
                ExitFileCommand(),
                SkipOnceCommand(),
                IgnoreCommand(self.get_current_lang()),
                UndoCommand(is_possible=bool(self._modification_history)),
                RedoCommand(is_possible=bool(self._modification_future)),
                annotate_command,
                ViewCommand(),
                View_i_Command(candidate_symbols=candidate_symbols),
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
        lang = file_from_path(self.state.get_current_file(), self.linker).lang
        if lang == '*':
            return 'unknownlang'
        return lang


def srify(files: list[str], filter: str, ignore: str):
    state = State(files=[Path(file) for file in files], filter_pattern=filter, ignore_pattern=ignore,
                  cursor=PositionCursor(file_index=0, offset=0))
    controller = Controller(state)
    controller.run()
