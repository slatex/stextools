import logging
from pathlib import Path

import click
from stextools.cache import Cache

logger = logging.getLogger(__name__)


@click.group()
@click.option('--keep-cache', is_flag=True, default=False,
              help='Keep the cache despite changes to the stextools package.'
                   'This can be useful for stextools development, but may lead to errors.')
def cli(keep_cache):
    if keep_cache:
        Cache.clear = lambda: None  # type: ignore
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO)


@cli.command(help='Clear the cache. You should not have to do this '
                  'as the cache is automatically cleared whenever stextools is updated.')
def clear_cache():
    Cache.clear()
    logger.info('Cleared cache.')


@cli.command(help='Update the archive dependencies.')
@click.option('--mode', default='test',
              type=click.Choice(['test', 'ask', 'write'], case_sensitive=False),
              help='test: only print the changes, ask: ask before writing, write: write the changes without asking')
def update_dependencies(mode):
    from stextools.dependency_update import dependency_check
    dependency_check(mode)


@cli.command(help='Visualize the archive dependency graph (requires networkx and matplotlib).')
@click.option('--filter', default=None,
              help='Filter pattern to only show some archives (e.g. \'smglom/*,MiKoMH/*\')')
def show_dependency_graph(filter):
    from stextools.dependency_graph import show_graph
    show_graph(filter)


@cli.command(help='List archive dependencies that may be candidates for removal.')
@click.option('--filter', default=None,
              help='Filter pattern to only show some archives (e.g. \'smglom/*,MiKoMH/*\')')
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


if __name__ == '__main__':
    cli()
