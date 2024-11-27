import re
from pathlib import Path
from typing import Optional

import click
from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexMathNode, LatexCommentNode, LatexSpecialsNode, \
    LatexEnvironmentNode, LatexGroupNode, LatexCharsNode

from stextools.core.linker import Linker
from stextools.core.macros import STEX_CONTEXT_DB
from stextools.core.simple_api import get_symbols, SimpleSymbol
from stextools.snify.commands import Command, CommandInfo, CommandOutcome, SetNewCursor
from stextools.snify.skip_and_ignore import IgnoreList, SrSkipped
from stextools.snify.state import SelectionCursor, State
from stextools.snify.stemming import string_to_stemmed_word_sequence, string_to_stemmed_word_sequence_simplified
from stextools.utils.linked_str import LinkedStr, string_to_lstr
from stextools.utils.ui import standard_header

# By default, macros are not searched for potential annotations.
# This is a list of exceptions to this rule.
# The keys are the names of the macros (note that they should be in the pylatexenc context).
# The values are the indices of the arguments that should be searched (-1 for last argument is a common choice).
MACRO_RECURSION_RULES: dict[str, list[int]] = {
    'emph': [0],
    'textbf': [0],
    'textit': [0],
    'inlinedef': [1],
    'definiens': [1],
}

# By default, the content of environment is searched for potential annotations,
# but the arguments are not.
# This is a list of exceptions to this rule.
# The keys are the names of the environments (note that they should be in the pylatexenc context).
# The values are pairs (a, b), where
#   - a is a boolean indicating whether the environment content should be searched
#   - b is a list of indices of the arguments that should be searched
ENVIRONMENT_RECURSION_RULES: dict[str, tuple[bool, list[int]]] = {
    'lstlisting': (False, []),
    'tikzpicture': (False, []),
}


def get_linked_strings(latex_text: str) -> list[LinkedStr]:
    result: list[LinkedStr] = []

    def _recurse(nodes):
        for node in nodes:
            if node is None or node.nodeType() in {LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                # TODO: recurse into math nodes?
                continue
            if node.nodeType() == LatexMacroNode:
                if node.macroname in MACRO_RECURSION_RULES:
                    for arg_idx in MACRO_RECURSION_RULES[node.macroname]:
                        if arg_idx >= len(node.nodeargd.argnlist):
                            click.clear()
                            standard_header('Error', bg='red')
                            print(f"Macro {node.macroname} does not have argument {arg_idx}")
                            print('Context:')
                            print(latex_text[max(node.pos - 100, 0):min(len(latex_text) - 1, node.pos + 300)])
                            print()
                            print('Please report this error')
                            click.pause()
                            continue
                        _recurse([node.nodeargd.argnlist[arg_idx]])
            elif node.nodeType() == LatexEnvironmentNode:
                if node.envname in ENVIRONMENT_RECURSION_RULES:
                    recurse_content, recurse_args = ENVIRONMENT_RECURSION_RULES[node.envname]
                else:
                    recurse_content, recurse_args = True, []
                for arg_idx in recurse_args:
                    _recurse([node.nodeargd.argnlist[arg_idx]])
                if recurse_content:
                    _recurse(node.nodelist)
            elif node.nodeType() == LatexGroupNode:
                _recurse(node.nodelist)
            elif node.nodeType() == LatexCharsNode:
                result.append(string_to_lstr(node.chars, node.pos))
            else:
                raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

    walker = LatexWalker(latex_text, latex_context=STEX_CONTEXT_DB)
    _recurse(walker.get_latex_nodes()[0])

    return result


class PreviousWordShouldBeIncluded(Command):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='p',
            pattern_regex='^p$',
            description_short='revious token should be included',
            description_long='Extends the selection to include the previous token.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        for lstr in get_linked_strings(state.get_current_file_text()):
            if lstr.get_end_ref() >= state.cursor.selection_start:
                words = string_to_stemmed_word_sequence(lstr, self.lang)
                i = 0
                while i < len(words) and words[i].get_end_ref() <= state.cursor.selection_start:
                    i += 1
                if i == 0:
                    print(click.style('Already at beginning of possible selection range.', fg='red'))
                    click.pause()
                    return []
                return [SetNewCursor(SelectionCursor(
                    state.cursor.file_index,
                    words[i - 1].get_start_ref(),
                    state.cursor.selection_end,
                ))]
        raise RuntimeError('Somehow I did not find the previous word.')


class FirstWordShouldntBeIncluded(Command):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='P',
            pattern_regex='^P$',
            description_short=' exclude first selected token',
            description_long='Opposite of [p]. Excludes the first token from the selection.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        for lstr in get_linked_strings(state.get_current_file_text()):
            if lstr.get_end_ref() >= state.cursor.selection_start:
                words = string_to_stemmed_word_sequence(lstr, self.lang)
                i = 0
                while i < len(words) and words[i].get_end_ref() <= state.cursor.selection_start:
                    i += 1
                new_start = words[i + 1].get_start_ref()
                if new_start >= state.cursor.selection_end:
                    print(click.style('Selection is getting too small', fg='red'))
                    click.pause()
                    return []
                return [SetNewCursor(SelectionCursor(
                    state.cursor.file_index,
                    new_start,
                    state.cursor.selection_end,
                ))]
        raise RuntimeError('I could not find the first word.')


class NextWordShouldBeIncluded(Command):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='n',
            pattern_regex='^n$',
            description_short='ext token should be included',
            description_long='Extends the selection to include the next token.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        for lstr in get_linked_strings(state.get_current_file_text()):
            if lstr.get_end_ref() >= state.cursor.selection_start:
                words = string_to_stemmed_word_sequence(lstr, self.lang)
                i = 0
                while i < len(words) and words[i].get_start_ref() < state.cursor.selection_end:
                    i += 1
                if i == len(words):
                    print(click.style('Already at end of possible selection range.', fg='red'))
                    click.pause()
                    return []
                return [SetNewCursor(SelectionCursor(
                    state.cursor.file_index,
                    state.cursor.selection_start,
                    words[i].get_end_ref(),
                ))]
        raise RuntimeError('Somehow I did not find the next word.')


class LastWordShouldntBeIncluded(Command):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='N',
            pattern_regex='^N$',
            description_short=' exclude last selected token',
            description_long='Opposite of [n]. Excludes the last token from the selection.')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert isinstance(state.cursor, SelectionCursor)
        for lstr in get_linked_strings(state.get_current_file_text()):
            if lstr.get_end_ref() >= state.cursor.selection_start:
                words = string_to_stemmed_word_sequence(lstr, self.lang)
                i = 0
                while i < len(words) and words[i].get_start_ref() < state.cursor.selection_end:
                    i += 1
                new_end = words[i - 2].get_end_ref()
                if new_end <= state.cursor.selection_start:
                    print(click.style('Selection is getting too small', fg='red'))
                    click.pause()
                    return []
                return [SetNewCursor(SelectionCursor(
                    state.cursor.file_index,
                    state.cursor.selection_start,
                    new_end,
                ))]
        raise RuntimeError('I could not find the last word.')


class VerbTrie:
    def __init__(self, lang: str, linker: Linker):
        self.lang = lang
        self.linker = linker

        # keys are words, values are pairs (a, b), where
        #   - a is a list of all symbols that correspond to this node
        #   - b is a trie for the continuations
        self.trie: dict = {}

        for symbol in get_symbols(linker):
            covered_verbs: set[str] = set()
            verbalizations = [v.verb_str for v in symbol.get_verbalizations(lang)]
            if not verbalizations:
                verbalizations = [symbol.name]
            for verb in verbalizations:
                if len(verb) < 3:
                    continue

                words = [str(w) for w in string_to_stemmed_word_sequence_simplified(verb, lang)]
                if repr(words) in covered_verbs:
                    continue
                covered_verbs.add(repr(words))

                current = self.trie
                for i in range(len(words) - 1):
                    w = words[i]
                    if w not in current:
                        current[w] = ([], {})
                    current = current[w][1]
                w = words[-1]
                if w not in current:
                    current[w] = ([symbol], {})
                else:
                    current[w][0].append(symbol)

    def find_first_match_restricted(
            self,
            words_stemmed: list[str],
            restriction: list[str],
    ) -> Optional[tuple[int, int, list[SimpleSymbol]]]:
        """like find_first_match, but only considers matches that correspond to the restriction"""
        match_start = 0
        while match_start < len(words_stemmed):
            is_match = True
            for j in range(len(restriction)):
                if match_start + j >= len(words_stemmed) or words_stemmed[match_start + j] != restriction[j]:
                    is_match = False
                    break
            if is_match:
                found_symbols = True
                trie = self.trie
                for r in restriction[:-1]:
                    if r not in trie:
                        found_symbols = False
                        break
                    trie = trie[r][1]
                if found_symbols:
                    return match_start, match_start + len(restriction), trie[restriction[-1]][0]
            match_start += 1
        return None

    def find_first_match(
            self,
            words_stemmed: list[str],
            # words are only ignored if the next two arguments are provided (necessary for skipping literal (i.e. unstemmed) words)
            word_lstrs: Optional[list[LinkedStr]] = None,
            original_string: Optional[str] = None,
            # the temporarily skipped words are only considered if the next two arguments are provided
            state: Optional[State] = None,
            file: Optional[Path] = None,
            shift: Optional[int] = None,
            srskipped: Optional[SrSkipped] = None,
    ) -> Optional[tuple[int, int, list[SimpleSymbol]]]:
        """ Returns (start, end) where start is the earliest match start,
        and end (exclusive) is the latest end for a match from start. """

        match_start = 0
        while match_start < len(words_stemmed):
            match_end: Optional[int] = None
            j = match_start
            trie = self.trie
            symbols: list[SimpleSymbol] = []
            while j < len(words_stemmed) and words_stemmed[j] in trie:
                if trie[words_stemmed[j]][0]:  # corresponds to a symbol
                    skip = False
                    if word_lstrs is not None and original_string is not None:
                        original_word = original_string[word_lstrs[j].get_start_ref()-shift:word_lstrs[j].get_end_ref()-shift]
                        original_word = re.sub(r'\s+', ' ', original_word)
                        if IgnoreList.contains(lang=self.lang, word=original_word):
                            skip = True
                        if srskipped is not None and srskipped.should_skip_literal(original_word):
                            skip = True
                        if state is not None:
                            if file is not None:
                                if original_word in state.skip_literal_by_file.get(file, set()):
                                    skip = True
                            if original_word in state.skip_literal_all_session.get(self.lang, set()):
                                skip = True

                    stemmed_word = ' '.join(words_stemmed[match_start:j + 1])
                    if srskipped and stemmed_word in srskipped.skipped_stems:
                        skip = True
                    if state is not None:
                        if file is not None:
                            if stemmed_word in state.skip_stem_by_file.get(file, set()):
                                skip = True
                        if stemmed_word in state.skip_stem_all_session.get(self.lang, set()):
                            skip = True

                    if not skip:
                        match_end = j + 1
                        symbols = trie[words_stemmed[j]][0]
                trie = trie[words_stemmed[j]][1]
                j += 1
            if match_end is not None:
                assert symbols
                return match_start, match_end, symbols
            match_start += 1

        return None

