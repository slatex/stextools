import dataclasses
import logging
from collections import defaultdict

from stextools.core.cache import Cache
from stextools.core.simple_api import get_linker, get_repos, get_symbols


def prepare():
    Cache.clear = lambda: None  # type: ignore
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    # TODO: the linker indicates both real sTeX issues and missing features – we should not suppress them in general
    logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
    logging.basicConfig(level=logging.INFO)


prepare()
linker = get_linker()


@dataclasses.dataclass
class Stat:
    symbols: int = 0   # number of declared symbols
    defined_by_lang: dict[str, int] = dataclasses.field(default_factory=lambda: defaultdict(int))
    annotated_refs: int = 0
    alt_annotated_refs: int = 0


def repo_to_category(repo):
    if repo.name.startswith('smglom'):
        return 'smglom'
    if (
            repo.name.endswith('course') or repo.name.endswith('ComSem') or repo.name.endswith('ComLog') or
            repo.name.endswith('TheoCS') or repo.name.endswith('eida') or repo.name.endswith('WebEng') or
            repo.name.endswith('lecture-notes')
    ):
        return 'courses'
    if repo.name.endswith('problems'):
        return 'problems'
    elif 'talks' in repo.name:
        return 'talks'
    return 'other'


stats = defaultdict(Stat)

for repo in get_repos(linker):
    category = repo_to_category(repo)
    if category == 'other':
        print('Unknown category:', repo.name)

    for file in repo.files:
        for symbol in file.declared_symbols:
            stats[category].symbols += 1
            for verb in symbol.get_verbalizations():
                if verb.is_defining:
                    stats[category].defined_by_lang[verb.lang] += 1
        for verb in file.iter_verbalizations():
            if verb.is_defining:
                continue
            stats[category].alt_annotated_refs += 1

for symbol in get_symbols(linker):
    for verb in symbol.get_verbalizations():
        if verb.is_defining:
            continue
        stats[repo_to_category(verb.declaring_file.archive)].annotated_refs += 1

print(stats)
