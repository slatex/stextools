import dataclasses
import itertools
from pathlib import Path

from stextools.core.linker import Linker
from stextools.srify.commands import Command, CommandInfo, CommandOutcome, SetNewCursor, TextRewriteOutcome
from stextools.srify.state import State, SelectionCursor, PositionCursor
from stextools.srify.stemming import string_to_stemmed_word_sequence_simplified


class SkipOnceCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            pattern_presentation='s',
            pattern_regex='^s$',
            description_short='kip once',
            description_long='Skips to the next possible annotation')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        return [SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start + 1))]


class AddWordToSrSkip(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='S',
            pattern_regex='^S$',
            description_short='kip word in this file forever',
            description_long='Adds the selected word to the `% srskip` comments of this file\nthat list words that should always be skipped.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        srskipped = SrSkipped(state.files[state.cursor.file_index].read_text())
        srskipped.add_literal(state.get_selected_text())
        return [
            TextRewriteOutcome(srskipped.to_new_text()),
            # note: this is risky (position would change if there are, for weird reasons, early % srskip comments)
            SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start + 1))
        ]


class AddStemToSrSkip(Command):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='SS',
            pattern_regex='^SS$',
            description_short='kip stem (i.e. all words with the same stem) in this file forever',
            description_long='Adds the stem of the selected word to the `% srskip` comments of this file.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        srskipped = SrSkipped(state.files[state.cursor.file_index].read_text())
        word = state.get_selected_text()
        stem = ' '.join(string_to_stemmed_word_sequence_simplified(word, self.lang))
        srskipped.add_stem(stem)
        return [
            TextRewriteOutcome(srskipped.to_new_text()),
            SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start + 1))
        ]


@dataclasses.dataclass
class IgnoreWordOutcome(CommandOutcome):
    lang: str
    word: str


class IgnoreCommand(Command):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='i',
            pattern_regex='^i$',
            description_short='gnore the selected word forever',
            description_long=f'''
The word gets put into the ignore list and will never be proposed for annotation again,
unless removed from that list.
You can find the ignore list at {IgnoreList.file_path_string(lang)}.
'''.strip())
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        return [
            IgnoreWordOutcome(lang=self.lang, word=state.get_selected_text()),
            SetNewCursor(PositionCursor(state.cursor.file_index, state.cursor.selection_start + 1))
        ]


class _IgnoreList:
    def __init__(self, lang: str):
        self.lang = lang
        self.path = Path('~/.config/stextools/srify_ignore.en.txt').expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text('')

        self.word_list: list[str] = []
        for line in self.path.read_text().splitlines():
            word = line.strip()
            if word:
                self.word_list.append(word)
        self.word_set: set[str] = set(self.word_list)

    def add(self, word: str):
        if word not in self.word_set:
            self.word_list.append(word)
            self.word_set.add(word)
            self.path.write_text('\n'.join(self.word_list) + '\n')

    def remove(self, word: str):
        if word in self.word_set:
            self.word_list.remove(word)
            self.word_set.remove(word)
            self.path.write_text('\n'.join(self.word_list) + '\n')


class IgnoreList:
    _instances: dict[str, _IgnoreList] = {}

    @classmethod
    def _get(cls, lang: str) -> _IgnoreList:
        if lang not in cls._instances:
            cls._instances[lang] = _IgnoreList(lang)
        return cls._instances[lang]

    @classmethod
    def file_path_string(cls, lang: str) -> str:
        return str(cls._get(lang).path.absolute().resolve())

    @classmethod
    def add_word(cls, *, lang: str, word: str):
        cls._get(lang).add(word)

    @classmethod
    def remove_word(cls, *, lang: str, word: str):
        cls._get(lang).remove(word)

    @classmethod
    def contains(cls, *, lang: str, word: str) -> bool:
        return word in cls._get(lang).word_set


class SrSkipped:
    def __init__(self, text: str):
        self.text = text
        self.skipped_stems_ordered: list[str] = []
        self.skipped_stems: set[str] = set()
        self.skipped_literal_ordered: list[str] = []
        self.skipped_literal: set[str] = set()

        for line in text.splitlines():
            if line.startswith('% srskip '):
                for e in line[len('% srskip '):].split(','):
                    e = e.strip()
                    if e.startswith('s:'):
                        self.skipped_stems_ordered.append(e[2:])
                        self.skipped_stems.add(e[2:])
                    elif e.startswith('l:'):
                        self.skipped_literal_ordered.append(e[2:])
                        self.skipped_literal.add(e[2:])
                    else:   # legacy
                        self.skipped_stems_ordered.append(e)
                        self.skipped_stems.add(e)

    def add_stem(self, stem: str):
        self.skipped_stems_ordered.append(stem)
        self.skipped_stems.add(stem)

    def add_literal(self, literal: str):
        self.skipped_literal_ordered.append(literal)
        self.skipped_literal.add(literal)

    def to_new_text(self) -> str:
        have_added = False
        new_lines = []

        def _add_rskip():
            current_line = '% srskip'
            skips = itertools.chain(
                (f' s:{s}' for s in self.skipped_stems_ordered),
                (f' l:{l}' for l in self.skipped_literal_ordered)
            )
            for skip in skips:
                if len(current_line) + len(skip) > 80 and len(current_line) > 20:
                    new_lines.append(current_line + '\n')
                    current_line = '% srskip'
                current_line += skip + ','
            if current_line != '% srskip':
                new_lines.append(current_line[:-1] + '\n')

        for line in self.text.splitlines(keepends=True):
            if line.startswith('% srskip '):
                if have_added:
                    continue
                have_added = True
                _add_rskip()
            else:
                new_lines.append(line)

        if not have_added:
            _add_rskip()

        return ''.join(new_lines)
