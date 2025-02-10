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
from stextools.stepper.session_storage import SessionStorage
from stextools.snify.skip_and_ignore import SkipOnceCommand, IgnoreWordOutcome, IgnoreCommand, IgnoreList, \
    AddWordToSrSkip, AddStemToSrSkip, SrSkipped, SkipUntilFileEnd, SkipForRestOfSession
from stextools.snify.snify_state import SnifyState
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


class Controller:
    def __init__(self, state: SnifyState, new_files: Optional[list[Path]] = None, stem_focus: Optional[str] = None):
        self.state: SnifyState = state
        self.mh = Cache.get_mathhub(update_all=True)
        self._linker: Optional[Linker] = None
        self._verb_trie_by_lang: dict[str, VerbTrie] = {}
        self._modification_history: list[list[Modification]] = []
        self._modification_future: list[list[Modification]] = []   # for re-doing

        if new_files:
            self.state.push_focus(new_files=include_inputs(self.mh, new_files), select_only_stem=stem_focus)


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
            if not self.state.focus_stack:
                return False

            if not self.ensure_cursor_selection():
                click.clear()
                self.state.pop_focus()
                if self.state.focus_stack:
                    print('Focus mode ended')
                else:
                    if self.state.statistic_annotations_added:
                        print(f'Congratulations! You have added {self.state.statistic_annotations_added} annotations.')
                    print('There are no more files to annotate.')
                click.pause()
                continue

            click.clear()
            show_current_selection(self.state)
            outcomes = self._get_and_run_command()

            new_modifications: list[Modification] = []

            for outcome in outcomes:
                modification: Optional[Modification] = None

                if isinstance(outcome, Exit):
                    return True
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
                    if not outcome.requires_reparse:
                        modification.files_to_reparse = []
                elif isinstance(outcome, SetNewCursor):
                    modification = CursorModification(
                        old_cursor=self.state.cursor,
                        new_cursor=outcome.new_cursor
                    )
                elif isinstance(outcome, StatisticUpdateOutcome):
                    modification = StatisticModification(outcome)
                elif isinstance(outcome, FocusOutcome):
                    modification = PushFocusModification(
                        new_files=outcome.new_files,
                        new_cursor=outcome.new_cursor,
                        select_only_stem=outcome.select_only_stem
                    )
                elif isinstance(outcome, StateSkipOutcome):
                    modification = StateSkipModification(
                        file=None if outcome.session_wide else self.state.get_current_file(),
                        lang=self.get_current_lang() if outcome.session_wide else None,
                        word=outcome.word,
                        is_stem=outcome.is_stem
                    )
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
                doc = self.mh.get_stex_doc(file)
                assert doc is not None
                doc.delete_doc_info_if_outdated()

    def _get_and_run_command(self) -> Sequence[CommandOutcome]:
        command_collection = self._get_current_command_collection()
        print()
        return command_collection.apply(state=self.state)

    def _get_current_command_collection(self) -> CommandCollection:
        vt = self.get_verb_trie(self.get_current_lang())
        match_info = vt.find_first_match(
            string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang())
        )
        # sos = self.state.focus_stack[-1].select_only_stem
        # if sos is None:
        #     match_info = vt.find_first_match(
        #         string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang())
        #     )
        # else:
        #     match_info = vt.find_first_match_restricted(
        #         string_to_stemmed_word_sequence_simplified(self.state.get_selected_text(), self.get_current_lang()),
        #         string_to_stemmed_word_sequence_simplified(sos, self.get_current_lang()),
        #     )
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

                sos = self.state.focus_stack[-1].select_only_stem
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

    def get_current_lang(self) -> str:
        return self.state.get_current_lang(self.linker)


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

