from pathlib import Path
from typing import Optional, Any, Sequence

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.mathhub import make_filter_fun
from stextools.core.simple_api import file_from_path
from stextools.snify.annotate_command import AnnotateCommand, LookupCommand
from stextools.snify.commands import View_i_Command, \
    StateSkipOutcome, \
    StemFocusCommand, StemFocusCommandPlus, StemFocusCommandPlusPlus, Edit_i_Command, \
    Explain_i_Command
from stextools.snify.selection import VerbTrie, PreviousWordShouldBeIncluded, NextWordShouldBeIncluded, \
    get_linked_strings, FirstWordShouldntBeIncluded, LastWordShouldntBeIncluded
from stextools.stepper.base_controller import BaseController
from stextools.stepper.session_storage import SessionStorage
from stextools.snify.skip_and_ignore import SkipOnceCommand, IgnoreWordOutcome, IgnoreCommand, IgnoreList, \
    AddWordToSrSkip, AddStemToSrSkip, SrSkipped, SkipUntilFileEnd, SkipForRestOfSession
from stextools.snify.snify_state import SnifyState, SnifyFocusInfo
from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified, string_to_stemmed_word_sequence
from stextools.stepper.command_outcome import CommandOutcome, Exit, StatisticUpdateOutcome, SubstitutionOutcome, \
    TextRewriteOutcome, SetNewCursor, FocusOutcome
from stextools.stepper.commands import QuitProgramCommand, show_current_selection, RescanOutcome, RescanCommand, \
    ExitFileCommand, UndoOutcome, UndoCommand, RedoOutcome, RedoCommand, ViewCommand, EditCommand, CommandSectionLabel, \
    CommandCollection, ReplaceCommand
from stextools.stepper.file_management import include_inputs
from stextools.stepper.modifications import Modification, FileModification, CursorModification, PushFocusModification, \
    StatisticModification
from stextools.stepper.state import PositionCursor, SelectionCursor
from stextools.stepper.state import State
from stextools.utils.linked_str import LinkedStr


class IgnoreListAddition(Modification):
    def __init__(self, lang: str, word: str):
        self.files_to_reparse = []
        self.lang = lang
        self.word = word

    def apply(self, state: State):
        IgnoreList.add_word(lang=self.lang, word=self.word)

    def unapply(self, state: State):
        IgnoreList.remove_word(lang=self.lang, word=self.word)


class StateSkipModification(Modification):
    def __init__(self, file: Optional[Path], lang: Optional[str], word: str, is_stem: bool):
        self.files_to_reparse = []
        self.file = file
        self.lang = lang
        self.word = word
        self.is_stem = is_stem

    def apply(self, state: State):
        assert isinstance(state, SnifyState)
        if self.file is None:
            assert self.lang is not None
            if self.is_stem:
                state.skip_stem_all_session.setdefault(self.lang, set()).add(self.word)
            else:
                state.skip_literal_all_session.setdefault(self.lang, set()).add(self.word)
        else:
            if self.is_stem:
                state.skip_stem_by_file.setdefault(self.file, set()).add(self.word)
            else:
                state.skip_literal_by_file.setdefault(self.file, set()).add(self.word)

    def unapply(self, state: State):
        assert isinstance(state, SnifyState)
        if self.file is None:
            assert self.lang is not None
            if self.is_stem:
                state.skip_stem_all_session[self.lang].remove(self.word)
            else:
                state.skip_literal_all_session[self.lang].remove(self.word)
        else:
            if self.is_stem:
                state.skip_stem_by_file[self.file].remove(self.word)
            else:
                state.skip_literal_by_file[self.file].remove(self.word)


class Controller(BaseController):
    def __init__(self, state: SnifyState, new_files: Optional[list[Path]] = None, stem_focus: Optional[str] = None):
        super().__init__(state, new_files, SnifyFocusInfo(select_only_stem=stem_focus))
        self._verb_trie_by_lang: dict[str, VerbTrie] = {}

    def post_reset_linker_hook(self):
        self._verb_trie_by_lang = {}

    def get_verb_trie(self, lang: str) -> VerbTrie:
        if lang not in self._verb_trie_by_lang:
            self._verb_trie_by_lang[lang] = VerbTrie(lang, self.linker)
        return self._verb_trie_by_lang[lang]

    def get_current_command_collection(self) -> CommandCollection:
        vt = self.get_verb_trie(self.get_current_lang())
        match_info = vt.find_first_match(
            string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang())
        )

        candidate_symbols = match_info[2] if match_info is not None else []
        filter_fun = make_filter_fun(self.state.filter_pattern, self.state.ignore_pattern)
        candidate_symbols = [s for s in candidate_symbols if filter_fun(s.declaring_file.archive.name)]
        annotate_command = AnnotateCommand(
            candidate_symbols=candidate_symbols,
            state=self.state,
            linker=self.linker,
        )
        return CommandCollection(
            name='snify standard commands',
            commands=[
                QuitProgramCommand(),
                ExitFileCommand(),
                UndoCommand(is_possible=bool(self._modification_history)),
                RedoCommand(is_possible=bool(self._modification_future)),
                RescanCommand(),

                CommandSectionLabel('\nAnnotation'),
                annotate_command,
                LookupCommand(self.linker, self.state),
                Explain_i_Command(candidate_symbols),

                CommandSectionLabel('\nSelection modification'),
                PreviousWordShouldBeIncluded(self.get_current_lang()),
                FirstWordShouldntBeIncluded(self.get_current_lang()),
                NextWordShouldBeIncluded(self.get_current_lang()),
                LastWordShouldntBeIncluded(self.get_current_lang()),

                CommandSectionLabel('\nSkipping'),
                SkipOnceCommand(),
                SkipUntilFileEnd(),
                SkipForRestOfSession(),
                IgnoreCommand(self.get_current_lang()),
                AddWordToSrSkip(),
                AddStemToSrSkip(self.get_current_lang()),

                CommandSectionLabel('\nFocussing'),
                StemFocusCommand(),
                StemFocusCommandPlus(),
                StemFocusCommandPlusPlus(self.linker),

                CommandSectionLabel('\nViewing and editing'),
                ReplaceCommand(),
                ViewCommand(),
                View_i_Command(candidate_symbols=candidate_symbols),
                EditCommand(1),
                Edit_i_Command(1, candidate_symbols=candidate_symbols),
                EditCommand(2),
                Edit_i_Command(2, candidate_symbols=candidate_symbols),
            ],
            have_help=True
        )

    def find_next_selection(self) -> Optional[SelectionCursor]:
        _cursor: PositionCursor = self.state.cursor  # type: ignore
        if not isinstance(_cursor, PositionCursor):
            raise ValueError("Cursor must be a PositionCursor")

        start_index = _cursor.file_index
        progress_bar: Optional[Any] = None

        while _cursor.file_index < len(self.state.files):
            if progress_bar is None and _cursor.file_index > start_index + 10:
                print('It seems to take a while to find the next selection.')
                progress_bar = click.progressbar(length=len(self.state.files) - start_index - 10, label='documents', item_show_func=lambda s: s).__enter__()
            if progress_bar is not None:
                progress_bar.update(1, str(self.state.get_current_file()))
            if not self.state.get_current_file().exists():
                print(click.style(f"File {self.state.get_current_file()} does not exist", fg='red'))
                click.pause()
                _cursor = PositionCursor(_cursor.file_index + 1, offset=0)
                self.state.cursor = _cursor
                continue
            if not file_from_path(self.state.get_current_file(), self.linker):
                print(click.style(f"File {self.state.get_current_file()} is not loaded. Skipping it.\nPotential causes:\n * One archive is cloned multiple times\n * The file is not in an archive\n * The file is in an archive outside the MATHHUB path", fg='red'))
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
                if not len(lstr):
                    continue
                words_original = string_to_stemmed_word_sequence(lstr, self.get_current_lang())
                words_filtered: list[LinkedStr] = []
                for word in words_original:
                    if word.get_start_ref() < _cursor.offset:
                        continue
                    words_filtered.append(word)

                sos = self.state.focus_stack[-1].other_info.select_only_stem
                if sos is None:
                    match = self.get_verb_trie(self.get_current_lang()).find_first_match(
                        [str(w) for w in words_filtered],
                        words_filtered,
                        str(lstr),
                        self.state,
                        self.state.files[_cursor.file_index],
                        lstr.get_start_ref(),
                        srskipped,
                    )
                else:
                    match = self.get_verb_trie(self.get_current_lang()).find_first_match_restricted(
                        [str(w) for w in words_filtered],
                        string_to_stemmed_word_sequence_simplified(sos, self.get_current_lang()),
                    )
                if match is not None:
                    if progress_bar is not None:
                        progress_bar.render_finish()
                    return SelectionCursor(
                        _cursor.file_index,
                        words_filtered[match[0]].get_start_ref(),
                        words_filtered[match[1] - 1].get_end_ref(),
                    )
            _cursor = PositionCursor(_cursor.file_index + 1, offset=0)
            self.state.cursor = _cursor
        if progress_bar is not None:
            progress_bar.render_finish()
        return None


def snify(files: list[str], filter: str, ignore: str, focus: Optional[str]):
    session_storage = SessionStorage('snify')
    state: Optional[SnifyState] = None
    if state is None and focus is None:
        _state = session_storage.get_session_dialog()
        assert isinstance(_state, SnifyState) or _state is None
        state = _state
    if state is None:
        state = SnifyState(files=[], cursor=PositionCursor(file_index=0, offset=0), filter_pattern=filter,
                           ignore_pattern=ignore)
        paths: list[Path] = []
        for file in files:
            path = Path(file).absolute().resolve()
            if path.is_dir():
                paths.extend(path.rglob('*.tex'))
            else:
                paths.append(path)
        controller = Controller(state, new_files=paths, stem_focus=focus)
    else:
        controller = Controller(state)
    unfinished = controller.run()
    if unfinished:
        session_storage.store_session_dialog(state)
    else:
        session_storage.delete_session_if_loaded()

