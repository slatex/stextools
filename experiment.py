from stextools.core.cache import Cache
import logging

from stextools.core.linker import Linker

logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
# logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
logging.basicConfig(level=logging.INFO)

Cache.clear = lambda: None  # type: ignore

mh = Cache.get_mathhub(update_all=True)

linker1 = Linker(mh)


