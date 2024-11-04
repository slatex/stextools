from __future__ import annotations

import fnmatch
import functools
import logging
import multiprocessing
import os
import time
from pathlib import Path
from typing import Optional, Iterator, Literal, Callable

from stextools.core.manifest import Manifest
from stextools.core.stexdoc import STeXDocument, DocInfo

logger = logging.getLogger(__name__)


class MathHub:
    def __init__(self, root_path: Optional[Path] = None):
        self.root_path = root_path or get_mathhub_path()
        self.archive_lookup: dict[str, Repository] = {}
        self.update()

    def get_archive(self, archive_name: str) -> Optional[Repository]:
        return self.archive_lookup.get(archive_name)

    def iter_stex_archives(self) -> Iterator[Repository]:
        for repo in self.archive_lookup.values():
            if repo.is_stex_archive():
                yield repo

    def iter_stex_docs(self) -> Iterator[STeXDocument]:
        for repo in self.iter_stex_archives():
            yield from repo.stex_doc_iter()

    def get_archive_from_path(self, path: Path) -> Optional[Repository]:
        path = path.absolute().resolve()
        while not (path / '.git').is_dir():
            path = path.parent
            if path == Path('/'):
                raise FileNotFoundError(f'No parent of {path} has a .git directory')

        return self.get_archive(path.relative_to(self.root_path).as_posix())

    def update(self):
        """Updates the repo information"""
        logger.info('Scanning archives...')
        still_needed: set[str] = set()
        for repo in _get_mathhub_repos(self.root_path):
            if repo.get_archive_name() not in self.archive_lookup:
                self.archive_lookup[repo.get_archive_name()] = repo
            still_needed.add(repo.get_archive_name())

        for repo in list(self.archive_lookup.values()):
            if repo.get_archive_name() not in still_needed:
                del self.archive_lookup[repo.get_archive_name()]
            else:
                repo.update()

        logger.info(f'Found {len(self.archive_lookup)} MathHub archives')

    def load_all_doc_infos(self) -> int:
        """ loading all at once (instead of on demand) lets us parallelize the process """

        documents: list[STeXDocument] = [
            doc
            for repo in self.iter_stex_archives()
            for doc in repo.stex_doc_iter()
            if doc._doc_info is None
        ]

        if not documents:
            return 0

        logger.info(f'Updating the information for {len(documents)} files')
        last_printed = time.time()
        processed = 0

        if len(documents) < 50:
            for i, doc in enumerate(documents):
                doc.create_doc_info(self)
                processed += 1
            return len(documents)

        with multiprocessing.Pool(12) as pool:
            for i, doc_info in pool.imap(
                    _load_doc_info,
                    zip(range(len(documents)), documents, [self] * len(documents)),
                    chunksize=30
            ):
                documents[i]._doc_info = doc_info
                processed += 1
                if time.time() - last_printed > 1:
                    logger.info(f'Processed {processed}/{len(documents)} files')
                    last_printed = time.time()
        logger.info('Finished updating the information')
        return len(documents)


def _load_doc_info(arg) -> tuple[int, DocInfo]:
    i, document, mh = arg
    document.create_doc_info(mh)   # type: ignore
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

    def __init__(self, path: Path, mh_root_path: Path):
        self.path = path
        self.mh_root_path = mh_root_path
        self._manifest: Optional[Manifest] = None
        self._stex_documents: Optional[dict[str, STeXDocument]] = None  # rel. path -> document

    def update(self):
        """Updates the repo information (e.g. necessary when loading from pickle).

        Note: This is highly optimized as it has to iterate over a lot of data and has to
        be run when most stextools applications start."""
        self._manifest = None   # might have changed
        if self._stex_documents is None:
            return
        still_needed: set[str] = set()
        for rel_path, path in self._relevant_file_iterate():
            still_needed.add(rel_path)
            if rel_path not in self._stex_documents:
                self._stex_documents[rel_path] = STeXDocument(self, path)
            else:
                self._stex_documents[rel_path].delete_doc_info_if_outdated()

        for key in list(self._stex_documents):
            if key not in still_needed:
                del self._stex_documents[key]

    def _relevant_file_iterate(self) -> Iterator[tuple[str, Path]]:
        """yields relative paths as well (optimization) """
        base_path = self.path.absolute()
        path_len = len(base_path.as_posix()) + 1
        for p in (base_path / 'source').rglob('*.tex'):
            yield p.as_posix()[path_len:], p
        for p in (base_path / 'lib').rglob('*.tex'):
            yield p.as_posix()[path_len:], p

    def _relevant_file_iterate_simplified(self) -> Iterator[Path]:
        base_path = self.path.absolute()
        for p in (base_path / 'source').rglob('*.tex'):
            yield p
        for p in (base_path / 'lib').rglob('*.tex'):
            yield p

    def _ensure_stex_docs_loaded(self):
        if self._stex_documents:
            return
        self._stex_documents = {}
        for path in self._relevant_file_iterate_simplified():
            stex_doc = STeXDocument(self, path)
            self._stex_documents[stex_doc.get_rel_path()] = stex_doc

    def get_stex_doc(self, rel_path: str) -> Optional[STeXDocument]:
        self._ensure_stex_docs_loaded()
        assert self._stex_documents is not None
        return self._stex_documents.get(rel_path)

    def stex_doc_iter(self) -> Iterator[STeXDocument]:
        self._ensure_stex_docs_loaded()
        assert self._stex_documents is not None
        yield from self._stex_documents.values()

    def number_of_documents(self) -> int:
        self._ensure_stex_docs_loaded()
        assert self._stex_documents is not None
        return len(self._stex_documents)

    def get_manifest(self) -> Manifest:
        """Returns the manifest of the repository."""
        if self._manifest is None:
            self._manifest = Manifest(self.path / 'META-INF' / 'MANIFEST.MF')
        return self._manifest

    @functools.lru_cache(2 ** 16)
    def normalize_tex_file_ref(
            self, path: str, directory: Literal['source', 'lib'] = 'source', lang: str = '*'
    ) -> Optional[str]:
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
        options = list((self.path / directory / ('/'.join(split[:-1]))).glob(f'{split[-1]}.{lang}.tex'))
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
        name_guess = self.path.relative_to(self.mh_root_path).as_posix()
        try:
            return self.get_manifest()['id']
        except FileNotFoundError:
            return name_guess
        except KeyError:
            logger.warning(f'No id in manifest of {self.path} (using {name_guess})')
            return name_guess


def _get_mathhub_repos(mh_path: Path) -> Iterator[Repository]:
    """Returns an iterator over all MathHub repositories."""

    def get_git_repos(path: Path) -> Iterator[Path]:
        """ Much faster than path.glob('**/.git') as it does not traverse into repositories """
        for subdir in path.iterdir():
            if subdir.is_dir():
                if (subdir / '.git').is_dir():
                    yield subdir
                else:
                    yield from get_git_repos(subdir)

    paths = list(get_git_repos(mh_path))
    for path in paths:
        yield Repository(path, mh_path)


def make_filter_fun(filter: Optional[str], ignore: Optional[str] = None) -> Callable[[str], bool]:
    filter_fun: Callable[[str], bool]
    if filter or ignore:
        filter_patterns: list[str] = filter.split(',') if filter else ['*']
        ignore_patterns: list[str] = ignore.split(',') if ignore else []

        @functools.cache
        def filter_fun(filename: str) -> bool:
            for pattern in filter_patterns:
                if fnmatch.fnmatch(filename, pattern):
                    for ignore_pattern in ignore_patterns:
                        if fnmatch.fnmatch(filename, ignore_pattern):
                            return False
                    return True
            return False
    else:
        def filter_fun(filename: str) -> bool:
            return True
    return filter_fun
