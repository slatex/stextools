import gzip
from datetime import datetime
import functools

import requests

from stextools.config import CACHE_DIR
from stextools.stepper.interface import interface

URL = 'https://nc.kwarc.info/s/9taC9nL5egAgPLk'   # TODO: this should come from mathhub.info



@functools.cache
def get_remote_mathhub_data():
    path = CACHE_DIR / 'remote_stex_catalog_data.json.gz'

    def download():
        response = requests.get(URL)
        response.raise_for_status()
        with gzip.open(path, 'wt') as fout:
            fout.write(response.text)

    if path.exists():
        time_since_last_update = datetime.fromtimestamp(path.stat().st_mtime) - datetime.now()
        if (time_since_last_update.days > 1 and    # is this a reasonable frequency?
            interface.ask_yes_no(
                f'The catalog from mathhub.info is outdated. Should I update it?'
            )
        ):
            download()
    else:
        interface.write_text(f'No cached catalog from mathhub.info found. Downloading...', 'info')
        download()

