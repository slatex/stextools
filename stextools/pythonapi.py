import functools
import logging
from typing import Optional

import click

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.simple_api import get_linker, SimpleSymbol
from stextools.snify.selection import VerbTrie
from stextools.snify.stemming import string_to_stemmed_word_sequence_simplified
from stextools.utils.ui import latex_format


@functools.cache
def get_linker() -> Linker:
    mh = Cache.get_mathhub(update_all=True)
    return Linker(mh)


@functools.cache
def get_verb_trie(lang: str) -> VerbTrie:
    return VerbTrie(lang, get_linker())


def setup_logging():
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    # TODO: the linker indicates both real sTeX issues and missing features – we should not suppress them in general
    logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
    logging.basicConfig(level=logging.INFO)


def serialize_symbol(symbol: SimpleSymbol) -> str:
    symb_path = symbol.path_rel_to_archive
    archive = symbol.declaring_file.archive.name
    return f'[{archive}]{symb_path}'

def interactive_symbol_search(verbalization: str, lang: str = 'en') -> Optional[str]:
    vt = get_verb_trie(lang)
    stemmed = string_to_stemmed_word_sequence_simplified(verbalization, lang)

    subtrie = ([], vt.trie)
    for word in stemmed:
        if word not in subtrie[1]:
            return None
        subtrie = subtrie[1][word]

    options: list[SimpleSymbol] = subtrie[0]

    if not options:
        return None

    for i, symbol in enumerate(options):
        print(f'[{i}]', serialize_symbol(symbol))
    print()
    print('Available commands:')
    print('  [q] - quit')
    print('  [𝑖] - choose symbol 𝑖')
    print('  [v𝑖] - view document for symbol 𝑖')
    print()

    while True:
        command: str = input('>>> ').strip()
        if command.isnumeric() and (i := int(command)) in range(len(options)):
            return serialize_symbol(options[i])
        elif command.startswith('v') and command[1:].isnumeric() and (i := int(command[1:])) in range(len(options)):
            symbol = options[i]
            click.echo_via_pager(
                click.style(symbol.declaring_file.path, bold=True)
                + '\n\n' +
                latex_format(symbol.declaring_file.path.read_text())
            )
        elif command == 'q':
            return None
        else:
            print(f'Invalid command: {command!r}.')
            continue
