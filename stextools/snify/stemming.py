import functools
import re

from stextools.utils.linked_str import LinkedStr


@functools.cache
def get_stem_fun(lang: str):
    if lang == 'en':
        import nltk.stem.porter  # type: ignore
        return nltk.stem.porter.PorterStemmer().stem
    elif lang == 'de':
        from nltk.stem import SnowballStemmer
        return SnowballStemmer('german').stem


@functools.cache  # note: caching results in a huge speedup
def mystem(word: str, lang: str) -> str:
    if word.isupper():  # acronym
        return word

    stem_fun = get_stem_fun(lang)

    if lang == 'en':
        if word and word[-1] == 's' and word[:-1].isupper():  # plural acronym
            return word[:-1]
        return ' '.join(stem_fun(w) for w in word.split())
    elif lang == 'de':
        return ' '.join(stem_fun(w) for w in word.split())
    else:
        raise ValueError(f"Unsupported language: {lang}")


def string_to_stemmed_word_sequence(lstr: LinkedStr, lang: str) -> list[LinkedStr]:
    # TODO: Tokenization is too ad-hoc...
    # in particular, I think it does not cover diacritics...
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
