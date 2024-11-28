from stextools.core.cache import Cache
import logging
from pathlib import Path

from stextools.core.linker import Linker

logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
logging.basicConfig(level=logging.INFO)

Cache.clear = lambda: None  # type: ignore

mh = Cache.get_mathhub(update_all=True)

linker1 = Linker(mh)

import stextools.core.simple_api as sa

# sa.file_from_path(Path('/home/jfs/MMT/MMT-content/smglom/computing/source/mod/termination.en.tex'), linker1)
symbs = list(sa.get_symbols(linker1, name='termination'))

for doc in sa.get_files(linker1):
    for verb in doc._stex_doc.get_doc_info(linker1.mh).verbalizations:
        if verb.symbol_name == 'termination':
            print(doc.path)
