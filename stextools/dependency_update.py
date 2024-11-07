import logging
from typing import Literal

from stextools import stexmmtquery
from stextools.core.cache import Cache

logger = logging.getLogger(__name__)


def always_keep_dependency_check(dep: str) -> bool:
    """Some dependencies should be kept even if we do not detect them"""
    #     if dep == 'sTeX/meta-inf':
    #         return True
    if dep.endswith('/meta-inf'):
        return True
    if dep.startswith('MMT/'):
        return True
    return False


def dependency_check(mode: Literal['test', 'ask', 'write'] = 'test'):
    mh = Cache.get_mathhub()
    if mh.load_all_doc_infos():
        Cache.store_mathhub(mh)

    logger.info('Getting dependencies from server...')
    server_dependencies = stexmmtquery.get_dependencies()
    logger.info(f'Found dependencies for {len(server_dependencies)} archives on the server, '
                'but I will only update dependencies of locally installed archives.')

    for archive in mh.iter_stex_archives():
        needed_dependencies_my_data = set(
            dep.archive for doc in archive.stex_doc_iter() for dep in doc.get_doc_info(mh).flattened_dependencies()
        )
        needed_dependencies_server = set(server_dependencies.get(archive.get_archive_name(), []))
        # TODO: Why are there discrepancies?
        print('X', needed_dependencies_server - needed_dependencies_my_data)
        print('Y', needed_dependencies_my_data - needed_dependencies_server)
        needed_dependencies = needed_dependencies_my_data | needed_dependencies_server
        new_dependencies: list[str] = []
        manifest = archive.get_manifest()
        for dependency in manifest.get_dependencies():
            if always_keep_dependency_check(dependency):
                new_dependencies.append(dependency)
        for dependency in needed_dependencies:
            if dependency == archive.get_archive_name():  # no self-dependencies
                continue
            if dependency not in new_dependencies:
                new_dependencies.append(dependency)

        print()
        if deps_only_on_server := needed_dependencies_server - needed_dependencies_my_data:
            print(f'WARNING - the following dependencies were not found locally: {deps_only_on_server}')
            # Note: it is expected that some dependencies are missing on the server (e.g. from \cmhtikzinput)
        if set(new_dependencies) == set(manifest.get_dependencies()):
            print('No changes needed for', manifest.path)
            continue

        print(f'Updating {manifest.path}:')
        print(f'Old dependencies: {manifest["dependencies"]}')
        print(f'New dependencies: {",".join(new_dependencies)}')
        if mode == 'test':
            pass
        elif mode == 'write':
            manifest['dependencies'] = ','.join(new_dependencies)
            manifest.write()
        else:
            assert mode == 'ask'
            answer = input('Should I do it? [y/n] ')
            if answer in {'y', 'Y', 'yes', 'Yes'}:
                manifest['dependencies'] = ','.join(new_dependencies)
                manifest.write()
            else:
                print('Skipping...')
