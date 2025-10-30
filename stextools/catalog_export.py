import json
from datetime import datetime
from pathlib import Path

from stextools.snify.text_anno.local_stex_catalog import local_flams_stex_catalogs


def catalog_export(path: Path):
    catalogs = local_flams_stex_catalogs()

    for lang, catalog in catalogs.items():
        with open(path / f'catalog-{lang}.json', 'w') as fp:
            catalog_data = {
                'entries': [
                    {
                        'verb': verb.verb,
                        'reference': symbol.uri,
                        'origin': {
                            'value': verb.local_path,
                            'type': 'localstexfile',
                        }
                    }
                    for symbol in catalog.symb_iter()
                    for verb in catalog.get_symb_verbs(symbol)
                ],
                'language': lang,
                'date': datetime.now().isoformat(),
                'creator': 'stextools catalog export',
            }
            json.dump(catalog_data, fp, indent=2)

if __name__ == '__main__':
    import sys
    catalog_export(Path(sys.argv[1]))
