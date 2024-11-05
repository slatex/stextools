from pathlib import Path
from typing import Optional

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.srify.state import PositionCursor
from stextools.srify.commands import CommandCollection, QuitProgramCommand
from stextools.srify.selection import VerbTrie
from stextools.srify.state import State, SelectionCursor
from stextools.utils import ui
from stextools.utils.ui import get_lines_around, latex_format, pale_color

STANDARD_COMMANDS = CommandCollection(
    name='srify standard commands',
    commands=[
        QuitProgramCommand()
    ],
    have_help=True
)


class Controller:
    def __init__(self, state: State):
        self.state: State = state
        self.mh = Cache.get_mathhub(update_all=True)
        self._linker: Optional[Linker] = None
        self._verb_trie_by_lang: dict[str, VerbTrie] = {}

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
            self._show_current_selection()
            STANDARD_COMMANDS.apply(state=self.state)

    def _show_current_selection(self, with_header: bool = True):
        if with_header:
            ui.standard_header(str(self.state.get_current_file()), bg='bright_green')

        cursor = self.state.cursor
        assert isinstance(cursor, SelectionCursor)

        a, b, c, line_no_start = get_lines_around(
            self.state.get_current_file_text(),
            cursor.selection_start,
            cursor.selection_end
        )
        doc = latex_format(a) + click.style(b, bg='bright_yellow', bold=True) + latex_format(c)

        for i, line in enumerate(doc.split('\n'), line_no_start):
            print(click.style(f'{i:4} ', fg=pale_color()) + line)

    def ensure_cursor_selection(self) -> bool:
        """Returns False if nothing is left to select."""
        if isinstance(self.state.cursor, PositionCursor):
            selection_cursor = self.get_verb_trie('en').find_next_selection(self.state)
            if selection_cursor is None:
                return False
            self.state.cursor = selection_cursor
        return True


def srify(files: list[str], filter: str, ignore: str):
    state = State(files=[Path(file) for file in files], filter_pattern=filter, ignore_pattern=ignore,
                  cursor=PositionCursor(file_index=0, offset=0))
    controller = Controller(state)
    controller.run()
