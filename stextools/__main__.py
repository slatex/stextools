import importlib.metadata
import logging
from pathlib import Path
from platform import python_version

import click

from stextools.utils import ui
from stextools.core.cache import Cache
from stextools.core.config import get_config

logger = logging.getLogger(__name__)


filter_option = click.option('--filter', default=None,
                             help='Filter pattern to only include some archives (e.g. \'smglom/*,courses/*\')')


@click.group()
@click.option('--keep-cache', is_flag=True, default=False,
              help='Keep the cache despite changes to the stextools package.'
                   'This can be useful for stextools development, but may lead to errors.')
@click.option('--use-true-color',
              default=lambda: get_config().getboolean('stextools', 'use_true_color', fallback=True),
              type=bool,
              help='Use 24-bit ("true") colors. Not all terminals support this.')
def cli(keep_cache, use_true_color):
    ui.USE_24_BIT_COLORS = use_true_color
    if keep_cache:
        Cache.clear = lambda: None  # type: ignore
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    # TODO: the linker indicates both real sTeX issues and missing features – we should not suppress them in general
    logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
    logging.basicConfig(level=logging.INFO)


@cli.command(help='Clear the cache. You should not have to do this '
                  'as the cache is automatically cleared whenever stextools is updated.')
def clear_cache():
    Cache.clear()
    logger.info('Cleared cache.')


@cli.command(help='Looks for a cycle (that is imported by a particular file).')
@click.argument('file')
def cycle_finder(file):
    from stextools.cycle_finder import cycle_finder
    cycle_finder(file)


@cli.command(help='Update the archive dependencies.')
@click.option('--mode', default='test',
              type=click.Choice(['test', 'ask', 'write'], case_sensitive=False),
              help='test: only print the changes, ask: ask before writing, write: write the changes without asking')
@filter_option
def update_dependencies(mode, filter):
    from stextools.dependency_update import dependency_check
    dependency_check(mode, filter)


@cli.command(help='Visualize the archive dependency graph (requires networkx and matplotlib).')
@click.option('--filter', default=None,
              help='Filter pattern to only show some archives (e.g. \'smglom/*,MiKoMH/*\')')
def show_dependency_graph(filter):
    from stextools.dependency_graph import show_graph
    show_graph(filter)


@cli.command(help='List archive dependencies that may be candidates for removal.')
@click.option('--filter', default=None,
              help='Filter pattern to only show some archives (e.g. \'smglom/*,courses/*\')')
def show_weak_dependencies(filter):
    from stextools.dependency_graph import show_weak_dependencies
    show_weak_dependencies(filter)


@cli.command(help='Recursively clone all public repositories in the specified MathHub groups.')
@click.argument('groups', nargs=-1)
def clone_groups(groups):
    from stextools.remote_repositories import clone_group
    for group in groups:
        clone_group(group)


@cli.command(help='Translate an sTeX document (experimental).')
@click.argument('path')
def translate(path):
    from stextools.translation import translate
    print(translate(Path(path)))


@cli.command(name='snify', help='\\sn-ify sTeX documents')
@click.argument('files', nargs=-1)  # Path to files or directories to snify
@click.option('--filter',
              default=lambda: get_config().get('stextools.snify', 'filter', fallback=None),
              help='Filter pattern to only include some archives (e.g. \'smglom/*,courses/*\')')
@click.option('--ignore',
              default=lambda: get_config().get('stextools.snify', 'ignore', fallback=None),
              help='Pattern to exclude some archives (e.g. \'Papers/*,smglom/mv\')')
@click.option('--focus',
              help='Immediately focus on a specific word')
def snify_actual(files, filter, ignore, focus):
    from stextools.snify.controller import snify
    snify(files, filter, ignore, focus)


@cli.command(name='version', help='Print the version of stextools.')
def version():
    print('stextools:', importlib.metadata.version('stextools'))
    print('python:', python_version())


if __name__ == '__main__':
    cli()
