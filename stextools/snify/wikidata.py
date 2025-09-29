import dataclasses
import functools
import gzip
import html
import itertools
import logging
import re
import textwrap
from typing import Sequence, Optional

import orjson
import requests


from stextools.config import CACHE_DIR
from stextools.snify.annotate import AnnotationChoices, TextAnnotationChoices, MathAnnotationChoices
from stextools.snify.catalog import Catalog, Verbalization, Symb
from stextools.snify.math_catalog import MathCatalog
from stextools.snify.snifystate import SnifyState, SnifyCursor
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document import WdAnnoTexDocument, WdAnnoHtmlDocument
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
    item_is_math_concept_small = r'''
      { ?item wdt:P2579/wdt:P31 wd:Q20026918 . } UNION
      { ?item wdt:P2579/wdt:P31 wd:Q1936384 . } UNION
      { ?item wdt:P279/wdt:P2579/wdt:P31 wd:Q1936384 . } UNION
      { ?item wdt:P2579 wd:Q395 . }.
    '''
    item_is_math_concept = r'''
    { ?item wdt:P6104 wd:Q8487137 .
        FILTER NOT EXISTS {?item wdt:P31 wd:Q28920044. } .
        FILTER NOT EXISTS {?item wdt:P31 wd:Q5 }.
        FILTER NOT EXISTS {?item wdt:P31 wd:Q10376408 }.
    } UNION {VALUES ?item { wd:Q204 wd:Q199 wd:Q200 }}. 
    '''
    # item_has_description = r'?item schema:description ?description . FILTER(LANG(?description) = "en")'
    item_has_description = r'''
    SERVICE wikibase:label {
        bd:serviceParam wikibase:language "en".
        ?item schema:description ?description .
    }
    '''
    item_has_unicode_notation = r'?item wdt:P913?/wdt:P487 ?notation'
    item_has_tex_notation = r'?item wdt:P913?/wdt:P1993 ?notation'

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
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f'wd_labels_{lang}.json.gz'
    if cache_file.exists():
        with gzip.open(cache_file, 'rb') as fp:
            return orjson.loads(fp.read())

    logger.info(f'Downloading wikidata verbalizations for language {lang!r}')

    labels = send_query(f'''
    SELECT DISTINCT ?item ?itemLabel WHERE {{
      {{ {QueryFragments.item_is_math_concept} }} UNION {{ {QueryFragments.item_is_math_concept_small} }} .
      {QueryFragments.item_label_in_lang(lang)}
    }}
    ''')
    akas = send_query(f'''
    SELECT DISTINCT ?item ?aka WHERE {{
      {QueryFragments.item_is_math_concept_small}   # bigger set of items result in timeout
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

def _get_cached_symbols(format: str):
    assert format in {'tex', 'unicode'}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f'wd_notations_{format}.json.gz'
    if cache_file.exists():
        with gzip.open(cache_file, 'rb') as fp:
            return orjson.loads(fp.read())

    logger.info(f'Downloading {format} notations from wikidata')
    notations = send_query(f'''
    SELECT DISTINCT ?item ?notation WHERE {{
      {QueryFragments.item_is_math_concept}
      { {'unicode': QueryFragments.item_has_unicode_notation, 'tex': QueryFragments.item_has_tex_notation}[format] }
    }}
    ''')
    notation_data = {}
    for binding in notations['results']['bindings']:
        notation_data.setdefault(binding['item']['value'], []).append(binding['notation']['value'])

    with gzip.open(cache_file, 'wb') as fp:
        fp.write(orjson.dumps(notation_data))

    return notation_data

def _get_descriptions() -> dict[str, str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f'wd_descriptions_en.json.gz'
    if cache_file.exists():
        with gzip.open(cache_file, 'rb') as fp:
            return orjson.loads(fp.read())

    logger.info(f'Downloading wikidata descriptions')

    descriptions = send_query(f'''
    SELECT DISTINCT ?item ?description WHERE {{
      {{ {QueryFragments.item_is_math_concept} }} UNION {{ {QueryFragments.item_is_math_concept_small} }} .
      {QueryFragments.item_has_description}
    }}
    ''')

    description_data = {}
    for binding in descriptions['results']['bindings']:
        if not 'description' in binding:
            continue
        description_data[binding['item']['value'].split('/')[-1]] = binding['description']['value']

    with gzip.open(cache_file, 'wb') as fp:
        fp.write(orjson.dumps(description_data))

    return description_data

@functools.cache
def get_wd_descriptions() -> dict[str, str]:
    return _get_descriptions()


@functools.cache
def get_wd_catalog(lang: str) -> Catalog[WdSymbol, Verbalization]:
    catalog = Catalog[WdSymbol, Verbalization](lang=lang)
    for uri, verbs in _get_cached_verbs(lang).items():
        symbol = WdSymbol(identifier=uri.split('/')[-1])
        for verb in verbs:
            catalog.add_symbverb(symbol, Verbalization(verb))

    return catalog


@functools.cache
def get_notation_table(format: str) -> dict[str, list[str]]:
    notation_data = _get_cached_symbols(format)
    notation_table: dict[str, list[str]] = {}
    for uri, notations in notation_data.items():
        for notation in notations:
            symbol_id = uri.split('/')[-1]
            if notation not in notation_table:
                notation_table[notation] = []
            notation_table[notation].append(symbol_id)
    return notation_table


class WdAnnotateCommand(Command):
    def __init__(
            self,
            state: SnifyState,
            options: AnnotationChoices,
            catalog: Catalog[WdSymbol, Verbalization] | MathCatalog,
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
        symbols = [o[0] for o in self.options.choices] if isinstance(self.options, TextAnnotationChoices) else self.options.choices
        for i, symb in enumerate(symbols):
            label = interface.apply_style(get_wd_catalog("en").get_symb_verbs(symb)[0].verb, "highlight1")
            id = interface.apply_style(f"({symb.identifier})", "pale")
            prevlen = len(label) + len(id) + 3
            description = '\n'.join(textwrap.wrap(
                ' ' * prevlen +
                get_wd_descriptions().get(symb.identifier) or "no description",
                width=80, tabsize=6,
            ))
            description = description.strip()
            interface.write_command_info(
                str(i),
                f' {label} {id}: {description}',
                # f' {symb.uri}: {", ".join(v.verb for v in get_wd_catalog("en").get_symb_verbs(symb))}'
            )

    def annotate_symbol(self, symbol: WdSymbol) -> Sequence[CommandOutcome]:
        cursor = self.state.cursor
        if isinstance(self.state.get_current_document(), WdAnnoTexDocument):
            if isinstance(self.options, TextAnnotationChoices):
                new_string = f'\\wdalign{{{symbol.identifier}}}{{{self.state.get_selected_text()}}}'
            else:
                new_string = f'\\mwdalign{{{symbol.identifier}}}{{{self.state.get_selected_text()}}}'
        elif isinstance(self.state.get_current_document(), WdAnnoHtmlDocument):
            if isinstance(self.options, TextAnnotationChoices):
                new_string = f'<span data-wd-align="{symbol.identifier}">{self.state.get_selected_text()}</span>'
            else:
                st = self.state.get_selected_text()
                gtpos = st.find('>')
                assert gtpos != -1
                new_string = st[:gtpos] + f' data-wd-align="{symbol.identifier}"' + st[gtpos:]
        else:
            raise ValueError("Document type not supported for Wikidata annotation.")
        return [
            SubstitutionOutcome(
                new_string,
                cursor.selection[0], cursor.selection[1]
            ),
            SetCursorOutcome(SnifyCursor(cursor.document_index, cursor.selection[0] + len(new_string)))
        ]

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        if int(call) >= len(self.options.choices):
            interface.write_text('Invalid annotation number', style='error')
            interface.await_confirmation()
            return []

        if isinstance(self.options, TextAnnotationChoices):
            symbol, _ = self.options.choices[int(call)]
        else:
            assert isinstance(self.options, MathAnnotationChoices)
            symbol = self.options.choices[int(call)]
        return self.annotate_symbol(symbol)


class WikidataMathMLCatalog(MathCatalog):
    def __init__(self):
        self.lookup: dict[str, list[str]] = get_notation_table('unicode')

    def find_first_match(
            self,
            string: str,
    ) -> Optional[tuple[int, int, list[Symb]]]:
        for match in re.finditer(r'<m[ino][^>]*>(?P<symbol>[^<]*)</m[ino]>', string):
            if 'data-wd-align' in match.group():
                continue
            identifiers = self.lookup.get(html.unescape(match.group('symbol')), [])
            if identifiers:
                return match.start(), match.end(), [WdSymbol(identifier) for identifier in identifiers]
        return None


class WikidataMathTexCatalog(MathCatalog):
    def __init__(self):
        self.lookup: dict[str, list[str]] = get_notation_table('tex')

    def find_first_match(
            self,
            string: str,
    ) -> Optional[tuple[int, int, list[Symb]]]:
        # TODO: this won't scale - use trie
        order = sorted(self.lookup.keys(), key=len, reverse=True)
        i = 0
        while i < len(string):
            s = string[i:]
            if s.startswith('\\mwdalign{'):
                # continue after next two closing braces
                brace_count = 0
                while brace_count < 2 and i < len(string):
                    if string[i] == '}':
                        brace_count += 1
                    i += 1
            for notation in order:
                if s.startswith(notation):
                    identifiers = self.lookup[notation]
                    return i, i + len(notation), [WdSymbol(identifier) for identifier in identifiers]
            i += 1
        return None
