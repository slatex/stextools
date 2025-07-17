import functools
import logging
import math
import pickle
from pathlib import Path
from typing import Optional

from stextools.core.mathhub import MathHub


logger = logging.getLogger(__name__)


CACHE_DIR = Path('~/.cache/stextools').expanduser()

MATHHUB_PICKLE_FILE = CACHE_DIR / 'mathhub.pickle'


class Cache:
    _mh: Optional[MathHub] = None
    _mh_uptodate: bool = False

    @classmethod
    @functools.cache
    def get_stextools_version(cls) -> str:
        """Returns the version number of the presently installed stextools"""
        from stextools import __version__
        return __version__

    @classmethod
    def get_mathhub(cls, update_all: bool = False) -> MathHub:
        """Returns the MathHub instance."""
        if cls._mh is not None:
            if update_all and not cls._mh_uptodate:
                cls._mh.load_all_doc_infos()
                cls._mh_uptodate = True
            return cls._mh

        cls.ensure_uptodate()
        if MATHHUB_PICKLE_FILE.exists():
            logger.info('Loading MathHub info from cache...')
            with open(MATHHUB_PICKLE_FILE, 'rb') as fp:
                cls._mh = pickle.load(fp)
                cls._mh.update()
        else:
            logger.info('No MathHub info found in cache - I will start from scratch.')
            cls._mh = MathHub()
        if update_all:
            if cls._mh.load_all_doc_infos() > 20:   # only update cache if enough documents have changed
                Cache.store_mathhub(cls._mh)
        return cls._mh

    @classmethod
    def store_mathhub(cls, mh: MathHub):
        cls.ensure_uptodate()
        logger.info('Writing MathHub info to cache...')
        with open(MATHHUB_PICKLE_FILE, 'wb') as fp:
            pickle.dump(mh, fp)

    @classmethod
    def clear(cls):
        MATHHUB_PICKLE_FILE.unlink(missing_ok=True)

    @classmethod
    def ensure_uptodate(cls):
        """Clears outdated data and ensures that the current stextools version is stored."""
        version_path = CACHE_DIR / 'version.txt'

        def _prepare_cache():
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(version_path, 'w') as fp:
                fp.write(cls.get_stextools_version())

        if not version_path.exists():
            cls.clear()
            _prepare_cache()
            return
        with open(version_path) as fp:
            version = fp.read().strip()
        if version != cls.get_stextools_version():
            logger.info('The cache appears to come from an older version of stextools. Clearing it...')
            cls.clear()
            _prepare_cache()
            return
