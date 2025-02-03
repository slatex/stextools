""" Quick (hacky) script to generate statistics for the annotation choices in a document. """

# {1: 4936, 0: 197, 2: 1776, 6: 285, 3: 1016, 4: 978, 7: 284, 5: 316, 10: 79, 9: 305, 8: 263, 12: 41, 11: 47}
# {4: 2835, 2: 4551, 1: 8991, 10: 1230, 5: 1858, 3: 3656, 9: 748, 7: 795, 6: 1582, 8: 613, 14: 175, 16: 176, 0: 448, 19: 432, 11: 304, 12: 882, 13: 30, 18: 171, 17: 7, 15: 36}

import logging
from pathlib import Path

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.simple_api import file_from_path, get_symbols
from stextools.snify.controller import Controller
from stextools.stepper.state import State, PositionCursor
from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified

logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
logging.basicConfig(level=logging.INFO)

Cache.clear = lambda: None  # type: ignore


def simple_stem(word: str, lang: str) -> str:
    return ' '.join(string_to_stemmed_word_sequence_simplified(word, lang))


mh = Cache.get_mathhub(update_all=True)

linker1 = Linker(mh)

filter = '*'
ignore = 'sTeX/*'  # sTeX/* is typically ignored in annotation runs with snify
files = [Path(input('root file: ')).absolute().resolve()]
state = State(files=[], filter_pattern=filter,
              ignore_pattern=ignore, cursor=PositionCursor(file_index=0, offset=0))
controller = Controller(state, new_files=[Path(file).absolute().resolve() for file in files])

verbs_by_lang = {}  # from existing annotations

for file in state.files:
    sf = file_from_path(file, linker1)
    assert sf is not None
    for verb in sf.iter_verbalizations():
        if verb.is_defining:
            continue
        verbs_by_lang.setdefault(verb.lang, []).append(simple_stem(verb.verb_str, verb.lang))

verbs_by_lang_2 = {}  # from snify suggestions

lastprint = -1
while controller.ensure_cursor_selection():
    if controller.state.cursor.file_index % 10 == 0 and controller.state.cursor.file_index != lastprint:
        lastprint = controller.state.cursor.file_index
        print(controller.state.cursor.file_index, '/', len(controller.state.files))
    if controller.state.cursor.file_index > 50:
        break
    lang = controller.state.get_current_lang(linker1)
    verbs_by_lang_2.setdefault(lang, []).append(simple_stem(controller.state.get_selected_text(), lang))
    controller.state.cursor = PositionCursor(controller.state.cursor.file_index, controller.state.cursor.selection_start + 1)


histogram = {}
histogram2 = {}

def make_hist(vbl, h, onlycountsecond):
    for lang, verbs in vbl.items():
        print(f'{lang}: {len(verbs)} verbalizations')
        symb_to_verbs = {}

        for symbol in get_symbols(linker1):
            covered_verbs: set[str] = set()
            already_entered_verbs: set[str] = set()
            verbalizations = [simple_stem(v.verb_str, lang) for v in symbol.get_verbalizations(lang)]
            if not verbalizations:
                verbalizations = [symbol.name]
            for verb in verbalizations:
                if verb not in covered_verbs and onlycountsecond:
                    covered_verbs.add(verb)
                    continue
                if verb in already_entered_verbs:
                    continue
                already_entered_verbs.add(verb)
                symb_to_verbs.setdefault(verb, []).append(symbol)

        for verb in verbs:
            count = len(symb_to_verbs[verb]) if verb in symb_to_verbs else 0
            if count > 30:
                print(f'{verb}: {count} symbols')
            if count not in h:
                h[count] = 0
            h[count] += 1

make_hist(verbs_by_lang, histogram, True)
make_hist(verbs_by_lang_2, histogram2, False)

print('Histograms:')
print(histogram)
print(histogram2)


import matplotlib.pyplot as plt

max_ = max(max(histogram.keys()), max(histogram2.keys()))

plt.bar([x -0.2 for x in range(max_ + 1)], [histogram.get(i, 0) for i in range(max_ + 1)], color='b', width=0.4)
plt.bar([x +0.2 for x in range(max_ + 1)], [histogram2.get(i, 0) for i in range(max_ + 1)], color='r', width=0.4)
plt.show()
