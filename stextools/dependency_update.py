import logging
from typing import Literal, Optional

import click

from stextools import stexmmtquery
from stextools.core.cache import Cache
from stextools.core.mathhub import make_filter_fun

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


def dependency_check(mode: Literal['test', 'ask', 'write'] = 'test', filter: Optional[str] = None):
    filter_fun = make_filter_fun(filter)
    mh = Cache.get_mathhub()
    if mh.load_all_doc_infos():
        Cache.store_mathhub(mh)

    logger.info('Getting dependencies from server...')
    server_dependencies = stexmmtquery.get_dependencies()
    logger.info(f'Found dependencies for {len(server_dependencies)} archives on the server, '
                'but I will only update dependencies of locally installed archives.')

    for archive in mh.iter_stex_archives():
        if not filter_fun(archive.get_archive_name()):
            continue
        print('\n\n')
        print(click.style(archive.get_archive_name(), fg='blue', bold=True))
        needed_dependencies_my_data = set(
            dep.archive for doc in archive.stex_doc_iter() for dep in doc.get_doc_info(mh).flattened_dependencies()
        )
        # print('Dependencies from my data:', needed_dependencies_my_data)
        needed_dependencies_server = set(server_dependencies.get(archive.get_archive_name(), []))
        # TODO: Why are there discrepancies?
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
        # if deps_only_on_server := needed_dependencies_server - needed_dependencies_my_data:
        #     print(f'WARNING - the following dependencies were not found locally: {deps_only_on_server}')
        #     # Note: it is expected that some dependencies are missing on the server (e.g. from \cmhtikzinput)
        if set(new_dependencies) == set(manifest.get_dependencies()):
            print('No changes needed for', manifest.path)
            continue

        if needed_dependencies_my_data != needed_dependencies_server:
            print(f'WARNING')
            print('The dependencies from the server and locally obtained data do not match:')
            print('The following dependencies are only in the server data:')
            print(needed_dependencies_server - needed_dependencies_my_data)
            print('The following dependencies are only in the locally obtained data:')
            print(needed_dependencies_my_data - needed_dependencies_server)
            print('I will take the union of both sets as the new dependencies.')

        print(click.style('Manifest is outdated', bold=True))
        print(f'Old dependencies: {manifest}')
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
