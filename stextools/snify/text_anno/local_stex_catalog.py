"""
This module contains code for creating a catalog based on local sTeX archives.
It is significantly optimized for performance (and hence unreadable).

The extraction is based on FLAMS.
FLAMS is slow enough that caching verbalizations is helpful.
"""

import dataclasses
import gzip
import logging
import os
from typing import TypeAlias, Iterable

import orjson

from stextools.config import CACHE_DIR
from stextools.snify.text_anno.catalog import Verbalization, Catalog, catalogs_from_stream
from stextools.stex.local_stex import OpenedStexFLAMSFile, lang_from_path
from stextools.stex.flams import FLAMS
from stextools.utils.timer import timelogger

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class LocalStexSymbol:
    uri: str
    path: str
    srefcount: int = 0   # simple heuristic: the more references, the more relevant

    # TODO: symbols have to be hashable... the following is not ideal though
    def __eq__(self, other):
        return (
                isinstance(other, LocalStexSymbol) and
                self.uri == other.uri and self.path == other.path
        )

    def __hash__(self):
        return hash((self.uri, self.path))


class LocalStexVerbalization(Verbalization):
    def __init__(self, verb: str, local_path: str, path_range: tuple[int, int]):
        super().__init__(verb)
        self.local_path = local_path
        self.path_range = path_range

    def __repr__(self):
        return f"LocalStexVerbalization(verb={self.verb!r}, local_path={self.local_path!r}, path_range={self.path_range!r})"


# very rudimentary representation for a verbalization
# used for efficient serialization and deserialization
# (language, symbol uri, symbol path, verb, verb start offset, verbend offset)
# verb path is ommitted as it is assumed to be known from the context
RawVerbEntry: TypeAlias = tuple[str, str, str, str, int, int]


def _verb_and_symb_extraction(j, opened_file: OpenedStexFLAMSFile) -> Iterable[RawVerbEntry | str]:
    """ recurse through the annotation json to find symrefs and co.
    It yields verbalizations (RawVerbEntry) and symbols (str) if they are defined/declared.
    """
    if isinstance(j, dict):
        for k, v in j.items():
            # TODO: add more keys to filter (optimization)
            if k in {'full_range', 'val_range', 'key_range', 'Sig', 'smodule_range', 'Title', 'path_range',
                     'archive_range', 'UseModule', 'ImportModule'}:
                continue
            if k in {'Symdef', 'Symdecl'}:
                yield v['uri']['uri']
            if k in {'MathStructure'}:
                yield v['uri']['uri']
            if k in {'Symref', 'SymName'}:
                # symbol = _get_symbol(v['uri'][0]['uri'], v['uri'][0]['filepath'])
                if k == 'Symref':
                    range_ = opened_file.flams_range_to_offsets(v['text'][0])
                    verb = opened_file.text[range_[0]:range_[1]]
                    verb = verb[1:-1]  # remove braces
                else:
                    range_ = opened_file.flams_range_to_offsets(v['name_range'])
                    verb = opened_file.text[range_[0]:range_[1]]
                    if '?' in verb:
                        verb = verb.split('?')[-1]
                    # TODO: For \Sn{edge}, we'd now have the verbalization "edge", not "Edge"
                    #  is this desirable?

                lang = lang_from_path(opened_file.path)
                symbol_uri: str = v['uri'][0]['uri']
                symbol_path: str = v['uri'][0]['filepath']
                yield (
                    lang,
                    symbol_uri,
                    symbol_path,
                    verb,
                    range_[0],
                    range_[1],
                )
                continue

            yield from _verb_and_symb_extraction(v, opened_file)

    elif isinstance(j, list):
        for item in j:
            yield from _verb_and_symb_extraction(item, opened_file)


CACHE_FILE = CACHE_DIR / 'local_stex_catalog.json.gz'
# cache file structure:
# filename -> { 'last_modified': timestamp, 'entries': [RawVerbEntry, ...] }


# def local_flams_stex_verbs() -> Iterable[RawVerbEntry]:
#     # The main extraction loop
#     FLAMS.require_all_files_loaded()
#     for path in FLAMS.get_loaded_files():
#
#         annos = FLAMS.get_file_annotations(path)
#
#         yield from _verb_extraction(annos, VerbExtractionCtx(path, OpenedFile(path)))

LocalFlamsCatalog: TypeAlias = Catalog[LocalStexSymbol, LocalStexVerbalization]


def local_flams_stex_catalogs() -> dict[str, LocalFlamsCatalog]:
    if CACHE_FILE.exists():
        # load json from cache
        with gzip.open(CACHE_FILE) as f:
            with timelogger(logger, f'Loading local sTeX catalog from {CACHE_FILE}'):
                cache = orjson.loads(f.read())
    else:
        cache = {}

    todo_list = []   # files that are not yet in the cache
    deletions = 0
    with timelogger(logger, 'Cleaning up cache'):
        all_files = FLAMS.get_all_files()
        all_files_set = set(all_files)
        for path, entry in list(cache.items()):
            # if modification time check is slow, it can be parallelized
            if path not in all_files_set or entry['last_modified'] < os.stat(path).st_mtime:
                deletions += 1
                del cache[path]

        todo_list = [path for path in all_files if path not in cache]

    logger.info(f'Kept {len(cache)} entries in cache ({deletions} entries deleted); {len(todo_list)} files to process')

    with timelogger(logger, 'Extracting local sTeX verbalizations with FLAMS'):
        for path in todo_list:
            annos = FLAMS.get_file_annotations(path)
            verbs_and_symbols = _verb_and_symb_extraction(annos, OpenedStexFLAMSFile(path))
            cache[path] = {
                'last_modified': os.stat(path).st_mtime,
                'verbs': [entry for entry in verbs_and_symbols if isinstance(entry, tuple)],
                'symbols': [symbol for symbol in verbs_and_symbols if isinstance(entry, str)],
            }

    if deletions + len(todo_list) > 100:
        with timelogger(logger, f'Saving local sTeX verbalizations to {CACHE_FILE}'):
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with gzip.open(CACHE_FILE, 'w') as f:
                f.write(orjson.dumps(cache))

    _symbols: dict[tuple[str, str], LocalStexSymbol] = {}
    def get_symbol(uri: str, path: str) -> LocalStexSymbol:
        key = (uri, path)
        if key not in _symbols:
            _symbols[key] = LocalStexSymbol(uri=uri, path=path)
        symbol = _symbols[key]
        symbol.srefcount += 1
        return symbol

    with timelogger(logger, 'Building catalogs'):
        return catalogs_from_stream(
            (
                (lang, get_symbol(uri, symb_path), LocalStexVerbalization(verb, path, (start, end)))
                for path, entry in cache.items()
                for lang, uri, symb_path, verb, start, end in entry['verbs']
            ),
            (
                symb
                for entry in cache.values()
                for symb in entry['symbols']
            )
        )


if __name__ == '__main__':
    # Example usage
    print('catalogs')
    catalogs = local_flams_stex_catalogs()
    for lang, catalog in catalogs.items():
        print(f'Catalog for language: {lang}')
        for symb, verbs in catalog.symb_to_verb.items():
            print(f'  Symbol: {symb.uri} ({symb.path}), References: {symb.srefcount}')
            for verb in verbs:
                print(f'    Verbalization: {verb.verb}, Path: {verb.local_path}, Range: {verb.path_range}')
