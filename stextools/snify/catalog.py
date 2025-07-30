import re
from typing import TypeVar, Generic, Iterable, Optional, Hashable

from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified, string_to_stemmed_word_sequence
from stextools.utils.linked_str import LinkedStr, string_to_lstr


class Verbalization:
    def __init__(self, verb: str):
        self.verb = verb


Symb = TypeVar('Symb', bound=Hashable)
Verb = TypeVar('Verb', bound=Verbalization)


class Trie(Generic[Symb, Verb]):
    __slots__ = 'verbs', 'children'
    def __init__(self):
        self.children: dict[str, 'Trie[Symb, Verb]'] = {}
        self.verbs: dict[Symb, list[Verb]] = {}

    def insert(self, key: Iterable[str], symb: Symb, verb: Verb):
        node = self
        for k in key:
            if k not in node.children:
                node.children[k] = Trie[Symb, Verb]()
            node = node.children[k]
        node.verbs.setdefault(symb, []).append(verb)

    def get(self, key: Iterable[str]) -> dict[Symb, list[Verb]]:
        node = self
        for k in key:
            if k not in node.children:
                return {}
            node = node.children[k]
        return node.verbs

    def __contains__(self, item):
        return item in self.verbs


class Catalog(Generic[Symb, Verb]):
    lang: str
    trie: Trie[Symb, Verb]
    symb_to_verb: dict[Symb, list[Verb]]
    symbols: set[Symb]

    def __init__(self, lang: str, symbverbs: Optional[Iterable[tuple[Symb, Verb]]] = None):
        self.lang = lang
        self.trie = Trie[Symb, Verb]()
        self.symb_to_verb = {}
        if symbverbs is not None:
            for symb, verb in symbverbs:
                self.add_symbverb(symb, verb)

    def symb_iter(self) -> Iterable[Symb]:
        yield from self.symb_to_verb.keys()

    def get_symb_verbs(self, symb: Symb) -> list[Verb]:
        return self.symb_to_verb.get(symb, [])

    def add_symbverb(self, symb: Symb, verb: Verb):
        self.symb_to_verb.setdefault(symb, []).append(verb)
        key = string_to_stemmed_word_sequence_simplified(verb.verb, self.lang)
        self.trie.insert(key, symb, verb)

    def add_symb(self, symb: Symb):
        """ Add a symbol, that may not have a verbalization. """
        self.symb_to_verb.setdefault(symb, [])

    def sub_catalog_for_stem(self, stem: str) -> 'Catalog[Symb, Verb]':
        """ Returns a sub-catalog that only contains verbalizations for the given stem. """
        stem_seq = string_to_stemmed_word_sequence_simplified(stem, self.lang)
        remaining: list[tuple[str, Symb, Verb]] = []
        result = self.trie.get(stem_seq)
        for symb, verbs in result.items():
            for verb in verbs:
                remaining.append((self.lang, symb, verb))
        return catalogs_from_stream(remaining).get(self.lang, Catalog(self.lang))

    def find_first_match(
            self,
            string: str,
            stems_to_ignore: Optional[set[str]] = None,
            words_to_ignore: Optional[set[str]] = None,
            symbols_to_ignore: Optional[set[Symb]] = None,
    ) -> Optional[tuple[int, int, list[tuple[Symb, Verb]]]]:
        """ returns (start_index, end_index, [(symbol, example verb), ...])
        for the match with the lowest start_index and highest end_index
        (i.e. first, but longest match).

        The code could theoretically be optimized (if verbalizations have very many words),
        but in practice verbalizations are short.
        """

        lstr = string_to_lstr(string)
        seq: list[LinkedStr] = string_to_stemmed_word_sequence(lstr, self.lang)
        match_start = 0

        while match_start < len(seq):
            j = match_start
            trie = self.trie

            # the result will be set whenever a match is found
            # longer matches will overwrite previous ones
            result: Optional[tuple[int, int, list[tuple[Symb, Verb]]]] = None
            while j < len(seq) and str(seq[j]) in trie.children:
                trie = trie.children[str(seq[j])]
                if trie.verbs:      # potential match
                    is_valid_match = True
                    original_word = string[seq[match_start].get_start_ref():seq[j].get_end_ref()]
                    original_word = re.sub(r'\s+', ' ', original_word)
                    if original_word in (words_to_ignore or ()):
                        is_valid_match = False
                    elif ' '.join(str(w) for w in seq[match_start:j + 1]) in (stems_to_ignore or ()):
                        is_valid_match = False

                    if is_valid_match:
                        symbols = [
                            (symb, verbs[0])
                            for symb, verbs in trie.verbs.items()
                            if symb not in (symbols_to_ignore or ())
                        ]
                        if symbols:
                            result = (
                                seq[match_start].get_start_ref(),
                                seq[j].get_end_ref(),
                                symbols
                            )
                j += 1

            if result is not None:
                return result

            match_start += 1

        return None    # no match found


def catalogs_from_stream(
        stream: Iterable[tuple[str, Symb, Verb]],
        symbols: Iterable[Symb] = (),
    ) -> dict[str, Catalog[Symb, Verb]]:
    catalogs: dict[str, Catalog[Symb, Verb]] = {}
    for lang, symb, verb in stream:
        if lang not in catalogs:
            catalogs[lang] = Catalog[Symb, Verb](lang)
            for symbol in symbols:
                catalogs[lang].add_symb(symbol)
        catalogs[lang].add_symbverb(symb, verb)
    return catalogs