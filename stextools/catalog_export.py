import functools
import gzip
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import orjson

from stextools.snify.text_anno.local_stex_catalog import local_flams_stex_catalogs
from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import get_imports_from_module_annotation
from stextools.utils.json_iter import json_iter


@functools.cache
def archive_path_to_archive_id(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    mf_path = path / 'META-INF' / 'MANIFEST.MF'
    if not mf_path.is_file():
        return None
    for line in mf_path.read_text().splitlines():
        parts = line.split(':')
        if len(parts) == 2 and parts[0].strip() == 'id':
            return parts[1].strip()
    return None


@functools.cache
def get_containing_archive(path: Path) -> Optional[Path]:
    """recursive re-implementation - caching makes this much more efficient """
    if (path / '.git').exists():
        return path
    parent = path.parent
    if parent and parent != path:
        return get_containing_archive(parent)
    return None


@functools.cache
def file_path_to_archive_id(path: str) -> Optional[str]:
    return archive_path_to_archive_id(get_containing_archive(Path(path).parent))



def get_catalog_by_archive():
    collection = defaultdict(set)

    catalogs = local_flams_stex_catalogs()
    for lang, catalog in catalogs.items():
        for symbol in catalog.symb_iter():
            for verb in catalog.get_symb_verbs(symbol):
                collection[file_path_to_archive_id(verb.local_path) or '?'].add((verb.verb, lang, symbol.uri))

    return {
        archive: [
            {'verb': verb, 'lang': lang, 'symbol': symbol}
            for verb, lang, symbol in triples
        ]
        for archive, triples in collection.items()
    }


def dependency_info():
    struct_dependencies = defaultdict(list)
    module_dependencies = defaultdict(list)

    for path in FLAMS.get_all_files():
        annos = FLAMS.get_file_annotations(path)

        for j in json_iter(annos):
            if not isinstance(j, dict):
                continue
            if 'MathStructure' in j:
                s = j['MathStructure']
                uri = s['uri']['uri']
                for ext0 in s.get('extends', []):
                    for ext1 in ext0:
                        if 'uri' in ext1:
                            struct_dependencies[uri].append(ext1['uri'])
            if 'Module' in j:
                s = j['Module']
                uri = s['uri']
                for import_uri, _ in get_imports_from_module_annotation(s):
                    module_dependencies[uri].append(import_uri)

    return module_dependencies, struct_dependencies


def main():
    if len(sys.argv) != 2:
        print('Expected the target filename as argument')
    out_file = sys.argv[1]    # '/tmp/stextools_catalog_export.json.gz'
    module_dependencies, struct_dependencies = dependency_info()
    result: dict[str, Any] = {
        'catalog_by_archive': get_catalog_by_archive(),
        'module_dependencies': module_dependencies,
        'struct_dependencies': struct_dependencies,
    }

    with gzip.open(out_file, 'wb') as f:
        f.write(orjson.dumps(result))


if __name__ == "__main__":
    main()
