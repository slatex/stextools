import dataclasses
import functools
import itertools
import re

from stextools.config import CONFIG_DIR
from stextools.snify.snifystate import SnifyCursor, SnifyState
from stextools.snify.text_anno.stemming import mystem
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document_stepper import TextRewriteOutcome
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import SetCursorOutcome


class SkipCommand(Command):
    def __init__(self, state: SnifyState):
        super().__init__(CommandInfo(
            pattern_presentation = 's',
            description_short = 'kip once',
            description_long = 'Skips to the next possible annotation')
        )
        self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        assert isinstance(self.state.cursor.selection, tuple)
        return [
            SetCursorOutcome(
                new_cursor=SnifyCursor(self.state.cursor.document_index, self.state.cursor.selection[-1] + 1)
            )
        ]


class StateSkipOutcome(CommandOutcome, Modification[SnifyState]):
    def __init__(self, word: str, is_stem: bool, session_wide: bool, lang: str, current_document_index: int):
        self.word = word
        self.is_stem = is_stem
        self.session_wide = session_wide
        self.lang = lang
        self.current_document_index = current_document_index

    def _get_key_and_dict(self, state: SnifyState):
        if self.session_wide:
            return self.lang, state.skip_stem if self.is_stem else state.skip
        else:
            return (self.lang, self.current_document_index), \
                state.skip_stem_by_docid if self.is_stem else state.skip_by_docid

    def apply(self, state: SnifyState):
        k, d = self._get_key_and_dict(state)
        if k not in d:
            d[k] = set()
        d[k].add(self.word)

    def unapply(self, state: SnifyState):
        k, d = self._get_key_and_dict(state)
        assert k in d, f"Key {k} not found in dictionary {d}"
        d[k].remove(self.word)


class SkipUntilFileEnd(Command):
    def __init__(self, state: SnifyState):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='s!',
            description_short='kip until end of file',
            description_long='Skip all occurrences of the selected phrase in this file (until end of session).')
        )
        self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        return [
            StateSkipOutcome(
                word=self.state.get_selected_text(),
                is_stem=False,
                session_wide=False,
                lang=self.state.get_current_document().language,
                current_document_index=self.state.cursor.document_index
            ),
            SetCursorOutcome(SnifyCursor(self.state.cursor.document_index, self.state.cursor.selection[0])),
        ]

class SkipForRestOfSession(Command):
    def __init__(self, state: SnifyState):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='s!!',
            description_short='kip until end of session',
            description_long='Skip all occurrences of the selected phrase in this session.')
        )
        self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        return [
            StateSkipOutcome(
                word=self.state.get_selected_text(),
                is_stem=False,
                session_wide=True,
                lang=self.state.get_current_document().language,
                current_document_index=self.state.cursor.document_index
            ),
            SetCursorOutcome(SnifyCursor(self.state.cursor.document_index, self.state.cursor.selection[0])),
        ]




@dataclasses.dataclass
class IgnoreWordOutcome(CommandOutcome, Modification[SnifyState]):
    lang: str
    word: str

    def apply(self, state: SnifyState):
        IgnoreList.add_word(lang=self.lang, word=self.word)

    def unapply(self, state: SnifyState):
        IgnoreList.remove_word(lang=self.lang, word=self.word)


class IgnoreCommand(Command):
    def __init__(self, state: SnifyState):
        self.state = state
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='i',
            pattern_regex='^i$',
            description_short='gnore the selected word forever',
            description_long=f'''
The word gets put into the ignore list and will never be proposed for annotation again,
unless removed from that list.
You can find the ignore list at {IgnoreList.file_path_string(self.state.get_current_document().language)}.
'''.strip())
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.state
        return [
            IgnoreWordOutcome(lang=state.get_current_document().language,
                              word=re.sub(r'\s+', ' ', state.get_selected_text()).strip()),
            SetCursorOutcome(SnifyCursor(state.cursor.document_index, state.cursor.selection[0] + 1))
        ]


class AddWordToSrSkip(Command):
    def __init__(self, state: SnifyState):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='S',
            description_short='kip word in this file forever',
            description_long='Adds the selected word to the `% srskip` comments of this file\nthat list words that should always be skipped.')
        )
        self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        srskipped = SrSkipped(self.state.get_current_document().get_content())
        srskipped.add_literal(self.state.get_selected_text())
        return [
            TextRewriteOutcome(srskipped.to_new_text()),
            SetCursorOutcome(SnifyCursor(self.state.cursor.document_index, self.state.cursor.selection[0] + 1))
        ]


class AddStemToSrSkip(Command):
    def __init__(self, state: SnifyState):
        self.state = state
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='SS',
            description_short='kip stem (i.e. all words with the same stem) in this file forever',
            description_long='Adds the stem of the selected word to the `% srskip` comments of this file.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.state
        srskipped = SrSkipped(self.state.get_current_document().get_content())
        word = state.get_selected_text()
        stem = mystem(word, self.state.get_current_document().language)
        srskipped.add_stem(stem)
        return [
            TextRewriteOutcome(srskipped.to_new_text()),
            SetCursorOutcome(SnifyCursor(state.cursor.document_index, state.cursor.selection[0] + 1))
        ]


class _IgnoreList:
    def __init__(self, lang: str):
        self.lang = lang
        self.path = CONFIG_DIR / 'srify_ignore.{self.lang}.txt'
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

    @classmethod
    def get_word_set(cls, lang: str) -> set[str]:
        if lang not in cls._instances:
            cls._get(lang)
        return cls._get(lang).word_set


class SrSkipped:
    """
    class for managing the `% srskip` comment lines in STeX documents.
    (they keep track of stems and literal phrases that should not be suggested for annotation in the file)
    """
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
                        if e[2:] in self.skipped_stems or not e[2:]:
                            continue
                        self.skipped_stems_ordered.append(e[2:])
                        self.skipped_stems.add(e[2:])
                    elif e.startswith('l:'):
                        if e[2:] in self.skipped_literal or not e[2:]:
                            continue
                        self.skipped_literal_ordered.append(e[2:])
                        self.skipped_literal.add(e[2:])
                    else:   # legacy
                        if e in self.skipped_stems or not e:
                            continue
                        self.skipped_stems_ordered.append(e)
                        self.skipped_stems.add(e)

    def add_stem(self, stem: str):
        self.skipped_stems_ordered.append(stem)
        self.skipped_stems.add(stem)

    def add_literal(self, literal: str):
        literal = re.sub(r'\s+', ' ', literal)
        self.skipped_literal_ordered.append(literal)
        self.skipped_literal.add(literal)

    def should_skip_literal(self, literal: str) -> bool:
        return re.sub(r'\s+', ' ', literal) in self.skipped_literal

    def to_new_text(self) -> str:
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
                continue    # easier to put them in the end (no need to update offsets etc.)
                # if have_added:
                #     continue
                # have_added = True
                # _add_rskip()
            else:
                new_lines.append(line)

        # if not have_added:
        _add_rskip()

        return ''.join(new_lines)


@functools.lru_cache(maxsize=1)
def get_srskipped_cached(text: str) -> SrSkipped:
    """ typically, we repeatedly check for the same file """
    return SrSkipped(text)
