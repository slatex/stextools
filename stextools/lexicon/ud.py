import functools
import typing
from typing import Iterator, Optional


if typing.TYPE_CHECKING or True:
    import stanza
    from stanza.models.common.doc import Word




T: typing.TypeAlias = typing.TypeVar('T')

def iter2list(f: typing.Callable[..., Iterator[T]]) -> typing.Callable[..., list[T]]:
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return list(f(*args, **kwargs))
    return wrapper


class NlpUnsuccessful(Exception):
    """
    NLP was not successful.
    This indicates that something went wrong in a way that cannot be prevented in general.
    For example, tokenization may not match the boundaries of concepts or an LLM may have produced
    unusable output.
    """

@functools.cache
def stanza_nlp(lang: str, processors: str) -> stanza.Pipeline:
    import stanza

    return stanza.Pipeline(lang=lang, processors=processors)


def token_start_end(token: Word) -> tuple[int, int]:
    if token.start_char is None or token.end_char is None:   # multi-word token
        return token.parent.start_char, token.parent.end_char
    return token.start_char, token.end_char


@iter2list
def sentence_tokenize(text: str, lang: str) -> Iterator[tuple[int, int]]:
    nlp = stanza_nlp(lang=lang, processors='tokenize')
    doc = nlp(text)
    for sent in doc.sentences:
        yield token_start_end(sent.words[0])[0], token_start_end(sent.words[-1])[1]


@functools.lru_cache(maxsize=2**13)
@iter2list
def word_tokenize(text: str, lang: str) -> Iterator[tuple[int, int]]:
    nlp = stanza_nlp(lang=lang, processors='tokenize')
    doc = nlp(text)
    for sent in doc.sentences:
        for word in sent.words:
            yield word.start_char, word.end_char


@functools.lru_cache(maxsize=2**13)
def process_up_to_lemma(text: str, lang: str) -> stanza.Document:
    nlp = stanza_nlp(lang=lang, processors='tokenize,mwt,pos,lemma')
    doc = nlp(text)
    return doc


@functools.lru_cache(maxsize=2**13)
def dep_parse(text: str, lang: str) -> stanza.Document:
    nlp = stanza_nlp(lang=lang, processors='tokenize,mwt,pos,lemma,depparse')
    doc = nlp(text)
    return doc


def feats_to_dict(feats: Optional[str]) -> dict[str, str]:
    if not feats:
        return {}
    return dict(pair.split('=') for pair in feats.split('|'))


# def get_word_dep(word_occurrence: 'WordOccurrence') -> tuple[str, str]:    # returns (dep_rel, head pos)
#     for sent in dep_parse(word_occurrence.sentence, 'en').sentences:
#         for word in sent.words:
#             if word.start_char == word_occurrence.start_offset and word.end_char == word_occurrence.end_offset:
#                 return word.deprel, sent.words[word.head - 1].upos


# returns (lemma, UPOS, FEATS)
# see https://universaldependencies.org/u/pos/ and https://universaldependencies.org/u/feat/index.html
def get_word_info(sentence: str, start_offset: int, end_offset: int, lang: str) -> tuple[str, str, dict[str, str]]:
    for sent in process_up_to_lemma(sentence, lang).sentences:
        for word in sent.words:
            if word.start_char == start_offset and word.end_char == end_offset:
                return word.lemma, word.upos, {e.partition('=')[0]: e.partition('=')[2] for e in word.feats.split('|')} if word.feats else {}
    raise NlpUnsuccessful(f'Could not find word {sentence[start_offset:end_offset]!r} at {start_offset}:{end_offset} in sentence: {sentence}')


# def get_phrase_head(sentence: str, lang: str, from_pos: int, to_pos: int) -> Optional[Word]:
#     relevant_words: list[Word] = []
#     for sent in dep_parse(sentence, lang).sentences:
#         for word in sent.words:
#             if from_pos <= word.start_char and word.end_char <= to_pos:
#                 relevant_words.append(word)
#
#     contained_indices = {word.id for word in relevant_words}
#     words_with_outside_deps = [word for word in relevant_words if word.head not in contained_indices]
#     if len(words_with_outside_deps) != 1:
#         return None
#     return words_with_outside_deps[0]
