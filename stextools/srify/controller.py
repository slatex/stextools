import abc
from pathlib import Path
from typing import Optional

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.mathhub import make_filter_fun
from stextools.core.simple_api import file_from_path
from stextools.core.stexdoc import Dependency
from stextools.srify.annotate_command import AnnotateCommand
from stextools.srify.commands import CommandCollection, QuitProgramCommand, Exit, CommandOutcome, \
    show_current_selection, ImportInsertionOutcome, SubstitutionOutcome, SetNewCursor, \
    ExitFileCommand, UndoOutcome, RedoOutcome, UndoCommand, RedoCommand, ViewCommand, View_i_Command, \
    TextRewriteOutcome, StatisticUpdateOutcome, ReplaceCommand, RescanCommand, RescanOutcome
from stextools.srify.selection import VerbTrie, PreviousWordShouldBeIncluded, NextWordShouldBeIncluded, \
    get_linked_strings
from stextools.srify.session_storage import SessionStorage
from stextools.srify.skip_and_ignore import SkipOnceCommand, IgnoreWordOutcome, IgnoreCommand, IgnoreList, \
    AddWordToSrSkip, AddStemToSrSkip, SrSkipped
from stextools.srify.state import PositionCursor, Cursor, SelectionCursor
from stextools.srify.state import State
from stextools.srify.stemming import string_to_stemmed_word_sequence_simplified, string_to_stemmed_word_sequence
from stextools.utils.linked_str import LinkedStr


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


class Controller:
    def __init__(self, state: State, is_new: bool):
        self.state: State = state
        self.mh = Cache.get_mathhub(update_all=True)
        self._linker: Optional[Linker] = None
        self._verb_trie_by_lang: dict[str, VerbTrie] = {}
        self._modification_history: list[list[Modification]] = []
        self._modification_future: list[list[Modification]] = []   # for re-doing

        if is_new:
            self.load_includes_dialog()

    def load_includes_dialog(self):
        have_inputs = False
        for file in self.state.files:
            stexdoc = self.mh.get_stex_doc(file)
            if not stexdoc:
                continue
            for dep in stexdoc.get_doc_info(self.mh).dependencies:
                if dep.is_input:
                    have_inputs = True
                    break
            if have_inputs:
                break
        if have_inputs and click.confirm(
            'The selected files input other files. Should I include those as well?'
        ):
            all_files: list[Path] = []
            all_files_set: set[Path] = set()
            todo_list = list(reversed(self.state.files))
            while todo_list:
                file = todo_list.pop()
                path = file.absolute().resolve()
                if path in all_files_set:
                    continue
                stexdoc = self.mh.get_stex_doc(path)
                if stexdoc:
                    all_files.append(path)
                    all_files_set.add(path)
                    dependencies: list[Dependency] = [
                        dep
                        for dep in stexdoc.get_doc_info(self.mh).dependencies
                        if dep.is_input and dep.file
                    ]
                    # reverse as todo_list is a stack
                    dependencies.sort(key=lambda dep: dep.intro_range[0], reverse=True)
                    for dep in dependencies:
                        if dep.is_input and dep.file:
                            archive = self.mh.get_archive(dep.archive)
                            if not archive:
                                continue
                            todo_list.append(archive.path / 'source' / dep.file)
                else:
                    print(f'File {path} is not loaded')

            self.state.files = all_files

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

    def run(self) -> bool:
        """Returns True iff there are more files to annotate."""
        while True:
            if not self.ensure_cursor_selection():
                return False  # nothing left to annotate

            click.clear()
            show_current_selection(self.state)
            outcomes = self._get_and_run_command()

            new_modifications: list[Modification] = []

            for outcome in outcomes:
                modification: Optional[Modification] = None

                if isinstance(outcome, Exit):
                    return True
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
                elif isinstance(outcome, TextRewriteOutcome):
                    modification = FileModification(
                        file=self.state.get_current_file(),
                        old_text=self.state.get_current_file_text(),
                        new_text=outcome.new_text
                    )
                elif isinstance(outcome, SetNewCursor):
                    modification = CursorModification(
                        old_cursor=self.state.cursor,
                        new_cursor=outcome.new_cursor
                    )
                elif isinstance(outcome, StatisticUpdateOutcome):
                    modification = StatisticModification(outcome)
                elif isinstance(outcome, IgnoreWordOutcome):
                    modification = IgnoreListAddition(lang=outcome.lang, word=outcome.word)
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
                    raise RuntimeError(f"Unexpected outcome {outcome}")

                if modification is not None:
                    modification.apply(self.state)
                    new_modifications.append(modification)
                    self.reset_after_modification(modification)

            if new_modifications:
                self._modification_history.append(new_modifications)
                self._modification_future.clear()
                if len(self._modification_history) > 150:
                    self._modification_history = self._modification_history[-100:]

    def reset_after_modification(self, modification: Modification):
        if modification.files_to_reparse:
            self.reset_linker()
            for file in modification.files_to_reparse:
                self.mh.get_stex_doc(file).delete_doc_info_if_outdated()

    def _get_and_run_command(self) -> list[CommandOutcome]:
        command_collection = self._get_current_command_collection()
        print()
        return command_collection.apply(state=self.state)

    def _get_current_command_collection(self) -> CommandCollection:
        candidate_symbols = self.get_verb_trie(self.get_current_lang()).find_first_match(
            string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang())
        )[2]
        filter_fun = make_filter_fun(self.state.filter_pattern, self.state.ignore_pattern)
        candidate_symbols = [s for s in candidate_symbols if filter_fun(s.declaring_file.archive.name)]
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
                ReplaceCommand(),
                PreviousWordShouldBeIncluded(self.get_current_lang()),
                NextWordShouldBeIncluded(self.get_current_lang()),
                SkipOnceCommand(),
                IgnoreCommand(self.get_current_lang()),
                AddWordToSrSkip(),
                AddStemToSrSkip(self.get_current_lang()),
                UndoCommand(is_possible=bool(self._modification_history)),
                RedoCommand(is_possible=bool(self._modification_future)),
                RescanCommand(),
                annotate_command,
                ViewCommand(),
                View_i_Command(candidate_symbols=candidate_symbols),
            ],
            have_help=True
        )

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
        _cursor: PositionCursor = self.state.cursor  # type: ignore
        if not isinstance(_cursor, PositionCursor):
            raise ValueError("Cursor must be a PositionCursor")

        while _cursor.file_index < len(self.state.files):
            if not self.state.get_current_file().exists():
                print(click.style(f"File {self.state.get_current_file()} does not exist", fg='red'))
                click.pause()
                _cursor = PositionCursor(_cursor.file_index + 1, offset=0)
                self.state.cursor = _cursor
                continue
            if not file_from_path(self.state.get_current_file(), self.linker):
                print(click.style(f"File {self.state.get_current_file()} is not loaded. Skipping it.", fg='red'))
                click.pause()
                _cursor = PositionCursor(_cursor.file_index + 1, offset=0)
                self.state.cursor = _cursor
                continue

            text = self.state.files[_cursor.file_index].read_text()
            srskipped = SrSkipped(text)

            lstrs = get_linked_strings(text)
            for lstr in lstrs:
                if lstr.get_end_ref() < _cursor.offset:
                    continue
                words_original = string_to_stemmed_word_sequence(lstr, self.get_current_lang())
                words_filtered: list[LinkedStr] = []
                for word in words_original:
                    if word.get_start_ref() < _cursor.offset:
                        continue
                    words_filtered.append(word)

                match = self.get_verb_trie(self.get_current_lang()).find_first_match(
                    [str(w) for w in words_filtered],
                    words_filtered,
                    str(lstr),
                    lstr.get_start_ref(),
                    srskipped,
                )
                if match is not None:
                    return SelectionCursor(
                        _cursor.file_index,
                        words_filtered[match[0]].get_start_ref(),
                        words_filtered[match[1] - 1].get_end_ref(),
                    )
            _cursor = PositionCursor(_cursor.file_index + 1, offset=0)
            self.state.cursor = _cursor
        return None

    def get_current_lang(self) -> str:
        return self.state.get_current_lang(self.linker)


def srify(files: list[str], filter: str, ignore: str):
    session_storage = SessionStorage()
    state = session_storage.get_session_dialog()
    if state is None:
        state = State(files=[Path(file) for file in files], filter_pattern=filter, ignore_pattern=ignore,
                      cursor=PositionCursor(file_index=0, offset=0))
    controller = Controller(state, is_new=True)
    unfinished = controller.run()
    if unfinished:
        session_storage.store_session_dialog(state)
    else:
        session_storage.delete_session_if_loaded()
