from __future__ import annotations

import functools
import itertools
import logging
import multiprocessing
import os
from pathlib import Path
from typing import Optional, Iterator, Literal

from stextools.manifest import Manifest
from stextools.stexdoc import STeXDocument, DocInfo

logger = logging.getLogger(__name__)


class MathHub:
    def __init__(self):
        self.archive_lookup: dict[str, Repository] = {
            repo.get_archive_name(): repo for repo in get_mathhub_repos()
        }
        logger.info(f'Found {len(self.archive_lookup)} archives, {len(self.archive_lookup)} of which are stex archives')

    def get_archive(self, archive_name: str) -> Optional[Repository]:
        return self.archive_lookup.get(archive_name)

    def iter_stex_archives(self) -> Iterator[Repository]:
        for repo in self.archive_lookup.values():
            if repo.is_stex_archive():
                yield repo

    def load_all_doc_infos(self):
        """ quick hack for parallel loading """
        def doc_iter():
            for repo in self.iter_stex_archives():
                yield from repo.stex_doc_iter()
        documents: list[STeXDocument] = list(doc_iter())

        _load_doc_info.mh = self   # type: ignore
        with multiprocessing.Pool(8) as pool:
            for i, doc_info in pool.imap(_load_doc_info, zip(range(len(documents)), documents), chunksize=30):
                documents[i]._doc_info = doc_info


def _load_doc_info(arg) -> tuple[int, DocInfo]:
    i, document = arg
    document.create_doc_info(_load_doc_info.mh)   # type: ignore
    return i, document._doc_info


class MathhubNotFoundException(Exception):
    pass


@functools.cache
def get_mathhub_path() -> Path:
    """Returns the path to the MathHub directory."""
    mathhub_val = os.environ['MATHHUB']
    if mathhub_val is None:
        raise MathhubNotFoundException("MATHHUB environment variable not set")
    path = Path(mathhub_val)
    if not path.is_dir():
        raise MathhubNotFoundException(f'{path} (inferred from MATHHUB env. variable) is not a directory')
    return path


class Repository:
    """A MathHub repository."""

    def __init__(self, path: Path):
        self.path = path
        self._manifest: Optional[Manifest] = None
        self._stex_documents: Optional[dict[str, STeXDocument]] = None  # rel. path -> document

    def load_stex_documents(self):
        if self._stex_documents:
            return
        self._stex_documents = {}
        for file in itertools.chain(
                (self.path / 'source').rglob('**/*.tex'),
                (self.path / 'lib').rglob('**/*.tex')
        ):
            stex_doc = STeXDocument(self, file)
            self._stex_documents[stex_doc.get_rel_path()] = stex_doc

    def get_stex_doc(self, rel_path: str) -> Optional[STeXDocument]:
        if self._stex_documents is None:
            self.load_stex_documents()
        assert self._stex_documents is not None
        return self._stex_documents.get(rel_path)

    def stex_doc_iter(self) -> Iterator[STeXDocument]:
        if self._stex_documents is None:
            self.load_stex_documents()
        assert self._stex_documents is not None
        yield from self._stex_documents.values()

    def get_manifest(self) -> Manifest:
        """Returns the manifest of the repository."""
        if self._manifest is None:
            self._manifest = Manifest(self.path / 'META-INF' / 'MANIFEST.MF')
        return self._manifest

    @functools.lru_cache(2 ** 16)
    def normalize_tex_file_ref(self, path: str, directory: Literal['source', 'lib'] = 'source') -> Optional[str]:
        """ Tries to normalize a file reference (e.g. by appending .tex or .en.tex).
            Returns None if the file does not exist.
            TODO: Currently any language is accepted - should it be restricted to the language of the source document?
        """
        if (self.path / directory / path).is_file():
            return path
        if (self.path / directory / (path + '.tex')).is_file():
            return path + '.tex'

        split = path.split('/')
        # try for .[lang].tex (at least that's how I understand the sTeX manual)
        options = list((self.path / directory / ('/'.join(split[:-1]))).glob(f'{split[-1]}.*.tex'))
        if options:
            return str(options[0].relative_to(self.path / directory).as_posix())
        return None

    @functools.cache
    def is_stex_archive(self) -> bool:
        try:
            mf = self.get_manifest()
        except FileNotFoundError:
            return False  # no manifest -> no stex archive
        if 'format' not in mf:
            return False
        return mf['format'] == 'stex'

    def try_get_manifest(self) -> Optional[Manifest]:
        """Returns the manifest of the repository, if it exists."""
        try:
            return self.get_manifest()
        except FileNotFoundError:
            return None

    @functools.cache
    def get_archive_name(self) -> str:
        name_guess = self.path.relative_to(get_mathhub_path()).as_posix()
        try:
            return self.get_manifest()['id']
        except FileNotFoundError:
            return name_guess
        except KeyError:
            logger.warning(f'No id in manifest of {self.path} (using {name_guess})')
            return name_guess


def get_mathhub_repos() -> Iterator[Repository]:
    """Returns an iterator over all MathHub repositories."""
    mathhub = get_mathhub_path()
    for path in mathhub.glob('*/*'):
        if (path / '.git').is_dir():
            yield Repository(path)
