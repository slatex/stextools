import dataclasses
import functools
import itertools
import re
from copy import deepcopy
from typing import Sequence, Literal

from stextools.config import CONFIG_DIR
from stextools.snify.snify_state import SnifyState, SetOngoingAnnoTypeModification
from stextools.snify.snify_commands import SkipCommand
from stextools.snify.text_anno.stemming import mystem
from stextools.snify.text_anno.text_anno_state import TextAnnoState
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document_stepper import TextRewriteOutcome
from stextools.stepper.stepper import Modification, Stepper
from stextools.stepper.stepper_extensions import FocusOutcome


class StateSkipOutcome(CommandOutcome, Modification[SnifyState]):
    """
    Command outcome that writes into the state that a certain word (or stem) should be skipped
    either for the rest of the session or for the rest of the current document.
    It does not update the cursor; that has to be done separately.
    """
    def __init__(
            self, word: str, is_stem: bool, session_wide: bool, lang: str, current_document_index: int,
            anno_type_name: str,
    ):
        self.word = word
        self.is_stem = is_stem
        self.session_wide = session_wide
        self.lang = lang
        self.current_document_index = current_document_index
        self.anno_type_name = anno_type_name

    def _get_key_and_dict(self, snify_state: SnifyState):
        state = snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
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
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='s!',
            description_short='kip until end of file',
            description_long='Skip all occurrences of the selected phrase in this file (until end of session).')
        )
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        return [
            StateSkipOutcome(
                word=state.get_selected_text(self.snify_state),
                is_stem=False,
                session_wide=False,
                lang=self.snify_state.get_current_document().language,
                current_document_index=self.snify_state.cursor.document_index,
                anno_type_name=self.anno_type_name
            )
        ] + SkipCommand.get_skip_outcome(self.snify_state)

class SkipForRestOfSession(Command):
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='s!!',
            description_short='kip until end of session',
            description_long='Skip all occurrences of the selected phrase in this session.')
        )
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        return [
            StateSkipOutcome(
                word=state.get_selected_text(self.snify_state),
                is_stem=False,
                session_wide=True,
                lang=self.snify_state.get_current_document().language,
                current_document_index=self.snify_state.cursor.document_index,
                anno_type_name=self.anno_type_name
            )
        ] + SkipCommand.get_skip_outcome(self.snify_state)




@dataclasses.dataclass
class IgnoreWordOutcome(CommandOutcome, Modification[SnifyState]):
    lang: str
    word: str

    def apply(self, state: SnifyState):
        IgnoreList.add_word(lang=self.lang, word=self.word)

    def unapply(self, state: SnifyState):
        IgnoreList.remove_word(lang=self.lang, word=self.word)


class IgnoreCommand(Command):
    def __init__(self, state: SnifyState, anno_type_name: str):
        self.snify_state = state
        self.anno_type_name = anno_type_name
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='i',
            pattern_regex='^i$',
            description_short='gnore the selected word forever',
            description_long=f'''
The word gets put into the ignore list and will never be proposed for annotation again,
unless removed from that list.
You can find the ignore list at {IgnoreList.file_path_string(self.snify_state.get_current_document().language)}.
'''.strip())
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        return [
            IgnoreWordOutcome(
                lang=self.snify_state.get_current_document().language,
                word=re.sub(r'\s+', ' ', state.get_selected_text(self.snify_state)).strip()
            )
        ] + SkipCommand.get_skip_outcome(self.snify_state)


class AddWordToSrSkip(Command):
    def __init__(self, state: SnifyState, anno_type_name: str):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='S',
            description_short='kip word in this file forever',
            description_long='Adds the selected word to the `% srskip` comments of this file\nthat list words that should always be skipped.')
        )
        self.snify_state = state
        self.anno_type_name = anno_type_name

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        srskipped = SrSkipped(self.snify_state.get_current_document().get_content())
        srskipped.add_literal(state.get_selected_text(self.snify_state))
        return [TextRewriteOutcome(srskipped.to_new_text())] + SkipCommand.get_skip_outcome(self.snify_state)


class AddStemToSrSkip(Command):
    def __init__(self, state: SnifyState, anno_type_name: str):
        self.snify_state = state
        self.anno_type_name = anno_type_name
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='SS',
            description_short='kip stem (i.e. all words with the same stem) in this file forever',
            description_long='Adds the stem of the selected word to the `% srskip` comments of this file.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        state = self.snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        srskipped = SrSkipped(self.snify_state.get_current_document().get_content())
        word = state.get_selected_text(self.snify_state)
        stem = mystem(word, self.snify_state.get_current_document().language)
        srskipped.add_stem(stem)
        return [TextRewriteOutcome(srskipped.to_new_text())] + SkipCommand.get_skip_outcome(self.snify_state)


class _IgnoreList:
    def __init__(self, lang: str):
        self.lang = lang
        self.path = CONFIG_DIR / f'srify_ignore.{self.lang}.txt'
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


class StemFocusCommand(Command):
    def __init__(
            self, stepper: Stepper, scope: Literal['file', 'remaining_files'], anno_type_name: str
    ):
        if scope == 'file':
            super().__init__(CommandInfo(
                show=False,
                pattern_presentation='f',
                description_short='ocus on stem',
                description_long='Look for other occurrences of the current stem in the current file')
            )
        elif scope == 'remaining_files':
            super().__init__(CommandInfo(
                show=False,
                pattern_presentation='f!',
                description_short='ocus on stem in all remaining files',
                description_long='Look for other occurrences of the current stem in the remaining files')
            )
        else:
            raise ValueError(f'Invalid scope: {scope}')
        self.anno_type_name = anno_type_name
        self.scope = scope
        self.stepper = stepper

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        snify_state = self.stepper.state
        assert isinstance(snify_state, SnifyState)
        new_snify_state = deepcopy(snify_state)   # TODO: This is inefficient (copies and then discards entire stack)
        new_snify_state.on_unfocus = None
        if self.scope == 'file':
            new_snify_state.documents = [snify_state.get_current_document()]
        new_state = new_snify_state[self.anno_type_name]
        assert isinstance(new_state, TextAnnoState)
        new_state.stem_focus = mystem(new_state.get_selected_text(snify_state), snify_state.get_current_document().language)
        new_state.focus_lang = snify_state.get_current_document().language

        return [
            # do not want to return to old selection
            FocusOutcome(new_snify_state, self.stepper),
            SetOngoingAnnoTypeModification(snify_state.ongoing_annotype, None),
        ]
