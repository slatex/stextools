import functools
import re
from typing import Optional

from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexMathNode, LatexCommentNode, LatexSpecialsNode, \
    LatexEnvironmentNode, LatexGroupNode, LatexCharsNode

from stextools.core.linker import Linker
from stextools.core.macros import STEX_CONTEXT_DB
from stextools.core.simple_api import get_symbols, SimpleSymbol
from stextools.srify.state import PositionCursor
from stextools.srify.state import SelectionCursor, State
from stextools.utils.linked_str import LinkedStr, string_to_lstr

# By default, macros are not searched for potential annotations.
# This is a list of exceptions to this rule.
# The keys are the names of the macros (note that they should be in the pylatexenc context).
# The values are the indices of the arguments that should be searched (-1 for last argument is a common choice).
MACRO_RECURSION_RULES: dict[str, list[int]] = {
    'emph': [0],
    'textbf': [0],
    'textit': [0],
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
}


@functools.cache   # note: caching results in a huge speedup
def mystem(word: str, lang: str) -> str:
    if word.isupper():  # acronym
        return word

    if lang == 'en':
        import nltk.stem.porter  # type: ignore
        if word and word[-1] == 's' and word[:-1].isupper():  # plural acronym
            return word[:-1]
        return ' '.join(nltk.stem.porter.PorterStemmer().stem(w) for w in word.split())
    elif lang == 'de':
        import nltk.stem.snowball.GermanStemmer
        return ' '.join(nltk.stem.snowball.GermanStemmer().stem(w) for w in word.split())
    else:
        raise ValueError(f"Unsupported language: {lang}")


def string_to_stemmed_word_sequence(string: str, lang: str) -> list[LinkedStr]:
    # TODO: Tokenization is too ad-hoc...
    # in particular, I think it does not cover diacritics...
    lstr: LinkedStr = string_to_lstr(string)
    lstr = lstr.normalize_spaces()
    replacements = []
    for match in re.finditer(r'\b\w+\b', str(lstr)):
        word = lstr[match]
        replacements.append((match.start(), match.end(), mystem(str(word), lang)))
    lstr = lstr.replacements_at_positions(replacements, positions_are_references=False)
    words: list[LinkedStr] = []
    for match in re.finditer(r'\b\w+\b', str(lstr)):
        words.append(lstr[match])
    return words


def string_to_stemmed_word_sequence_simplified(string: str, lang: str) -> list[str]:
    # same as above, but without linked strings (more efficient
    words: list[str] = []
    for match in re.finditer(r'\b\w+\b', string):
        words.append(mystem(match.group(), lang))
    return words


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
            for verb in symbol.get_verbalizations(lang):
                if len(verb.verb_str) < 3:
                    continue

                words = [str(w) for w in string_to_stemmed_word_sequence_simplified(verb.verb_str, lang)]
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

    def find_first_match(self, words: list[str]) -> Optional[tuple[int, int, list[SimpleSymbol]]]:
        """ Returns (start, end) where start is the earliest match start,
        and end (exclusive) is the latest end for a match from start. """

        match_start = 0
        while match_start < len(words):
            match_end: Optional[int] = None
            j = match_start
            trie = self.trie
            symbols: list[SimpleSymbol] = []
            while j < len(words) and words[j] in trie:
                if words[j][0]:   # corresponds to a symbol
                    match_end = j + 1
                    symbols = trie[words[j]][0]
                trie = trie[words[j]][1]
                j += 1
            if match_end is not None:
                assert symbols
                return match_start, match_end, symbols
            match_start += 1

        return None

    def find_next_selection(self, state: State) -> Optional[SelectionCursor]:
        _cursor: PositionCursor = state.cursor  # type: ignore
        if not isinstance(_cursor, PositionCursor):
            raise ValueError("Cursor must be a PositionCursor")

        class FoundMatch(BaseException):
            def __init__(self, start: int, end: int, symbols: list[SimpleSymbol]):
                self.start = start
                self.end = end
                self.symbols = symbols

        def _recurse(nodes, cursor: PositionCursor):
            for node in nodes:
                if node.pos + node.len < cursor.offset:   # anything before the cursor is irrelevant
                    continue
                if node.nodeType() in {LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                    # TODO: recurse into math nodes?
                    continue
                if node.nodeType() == LatexMacroNode:
                    if node.macroname in MACRO_RECURSION_RULES:
                        for arg_idx in MACRO_RECURSION_RULES[node.macroname]:
                            _recurse(node.nodeargs[arg_idx], cursor)
                elif node.nodeType() == LatexEnvironmentNode:
                    if node.envname in ENVIRONMENT_RECURSION_RULES:
                        recurse_content, recurse_args = ENVIRONMENT_RECURSION_RULES[node.envname]
                    else:
                        recurse_content, recurse_args = True, []
                    for arg_idx in recurse_args:
                        _recurse(node.nodeargs[arg_idx], cursor)
                    if recurse_content:
                        _recurse(node.nodelist, cursor)
                elif node.nodeType() == LatexGroupNode:
                    _recurse(node.nodelist, cursor)
                elif node.nodeType() == LatexCharsNode:
                    if node.pos + node.len < cursor.offset:   # anything before the cursor is irrelevant
                        continue

                    words_original = string_to_stemmed_word_sequence(node.chars, self.lang)
                    words_filtered: list[LinkedStr] = []
                    for word in words_original:
                        if word.get_end_ref() + node.pos < cursor.offset:
                            continue
                        words_filtered.append(word)

                    match = self.find_first_match([str(w) for w in words_filtered])
                    if match is not None:
                        raise FoundMatch(
                            node.pos + words_filtered[match[0]].get_start_ref(),
                            node.pos + words_filtered[match[1] - 1].get_end_ref(),
                            match[2]
                        )
                else:
                    raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

        while _cursor.file_index < len(state.files):
            text = state.files[_cursor.file_index].read_text()

            walker = LatexWalker(text, latex_context=STEX_CONTEXT_DB)
            try:
                _recurse(walker.get_latex_nodes()[0], _cursor)
            except FoundMatch as e:
                return SelectionCursor(_cursor.file_index, selection_start=e.start, selection_end=e.end)
            _cursor = PositionCursor(_cursor.file_index + 1, offset=0)
        return None

