import dataclasses
import functools
import gzip
import itertools
import logging
from typing import Sequence

import orjson
import requests


from stextools.config import CACHE_DIR
from stextools.snify.catalog import Catalog, Verbalization
from stextools.snify.snifystate import SnifyState, SnifyCursor
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper_extensions import SetCursorOutcome

logger = logging.getLogger(__name__)

def send_query(query: str):
    r = requests.get(
        'https://query.wikidata.org/sparql',
        params={'query': query},
        headers={'Accept': 'application/json'}
    )
    try:
        r.raise_for_status()
    except Exception as e:
        message = '\n' + r.text
        if len(message) > 2000:
            message = message[:2000] + '...'
        message = message.replace('\n', '\n    ')
        logger.error(f'Response with error code has following message: {message}')
        raise e
    return r.json()

class QueryFragments:
    item_is_math_concept = r'''
      {?item wdt:P2579/wdt:P31 wd:Q20026918 . } UNION
      { ?item wdt:P2579/wdt:P31 wd:Q1936384 . } UNION
      {  ?item wdt:P279/wdt:P2579/wdt:P31 wd:Q1936384 . } UNION
      {?item wdt:P2579 wd:Q395 .}.
    '''

    @classmethod
    def item_label_in_lang(cls, lang: str) -> str:
        return r'SERVICE wikibase:label { bd:serviceParam wikibase:language "' + lang + r'". }'

    @classmethod
    def aka_in_lang(cls, lang: str) -> str:
        return f'''
          ?item skos:altLabel ?aka .
          FILTER (LANG(?aka) = "{lang}")
        '''

@dataclasses.dataclass(frozen=True)
class WdSymbol:
    """ Wikidata item. Identifier is the Q... identifier, not the full URI."""
    identifier: str

    @property
    def uri(self):
        return 'http://www.wikidata.org/entity/' + self.identifier


def _get_cached_verbs(lang: str):
    cache_file = CACHE_DIR / f'wd_labels_{lang}.json.gz'
    if cache_file.exists():
        with gzip.open(cache_file, 'rb') as fp:
            return orjson.loads(fp.read())

    logger.info(f'Downloading wikidata verbalizations for language {lang!r}')

    labels = send_query(f'''
    SELECT DISTINCT ?item ?itemLabel WHERE {{
      {QueryFragments.item_is_math_concept}
      {QueryFragments.item_label_in_lang(lang)}
    }}
    ''')
    akas = send_query(f'''
    SELECT DISTINCT ?item ?aka WHERE {{
      {QueryFragments.item_is_math_concept}
      {QueryFragments.aka_in_lang(lang)}
    }}
    ''')

    verb_data = {}

    for binding in itertools.chain(labels['results']['bindings'], akas['results']['bindings']):
        item = binding['item']['value']
        if item not in verb_data:
            verb_data[item] = []
        if 'itemLabel' in binding:
            verb_data[item].append(binding['itemLabel']['value'])
        elif 'aka' in binding:
            verb_data[item].append(binding['aka']['value'])

    with gzip.open(cache_file, 'w') as fp:
        fp.write(orjson.dumps(verb_data))

    return verb_data


@functools.cache
def get_wd_catalog(lang: str) -> Catalog[WdSymbol, Verbalization]:
    catalog = Catalog[WdSymbol, Verbalization](lang=lang)
    for uri, verbs in _get_cached_verbs(lang).items():
        symbol = WdSymbol(identifier=uri.split('/')[-1])
        for verb in verbs:
            catalog.add_symbverb(symbol, Verbalization(verb))

    return catalog



class WdAnnotateCommand(Command):
    def __init__(
            self,
            state: SnifyState,
            options: list[tuple[WdSymbol, Verbalization]],
            catalog: Catalog[WdSymbol, Verbalization]
    ):
        self.state = state
        self.options = options
        self.catalog = catalog

        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖',
                pattern_regex='^[0-9]+$',
                description_short=' annotate with 𝑖',
                description_long='Annotates the current selection with option number 𝑖'
            )
        )

    def standard_display(self):
        for i, (symb, verb) in enumerate(self.options):
            interface.write_command_info(
                str(i),
                f' {symb.uri}: {", ".join(v.verb for v in self.catalog.get_symb_verbs(symb))}'
            )

    def annotate_symbol(self, symbol: WdSymbol) -> Sequence[CommandOutcome]:
        cursor = self.state.cursor
        return [
            SubstitutionOutcome(
                f'\\wdalign{{{symbol.identifier}}}{{{self.state.get_selected_text()}}}',
                cursor.selection[0], cursor.selection[1]
            ),
            SetCursorOutcome(SnifyCursor(cursor.document_index, cursor.selection[1]))
        ]

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        if int(call) >= len(self.options):
            interface.write_text('Invalid annotation number', style='error')
            interface.await_confirmation()
            return []

        symbol, _ = self.options[int(call)]
        return self.annotate_symbol(symbol)
