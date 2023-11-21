import logging

import click
from stextools.cache import Cache

logger = logging.getLogger(__name__)


@click.group()
@click.option('--keep-cache', is_flag=True, default=False,
              help='Keep the cache despite changes to the stextools package (saves time when developing)')
def cli(keep_cache):
    if keep_cache:
        Cache.clear = lambda: None
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO)


@cli.command()
def clear_cache():
    Cache.clear()
    logger.info('Cleared cache.')


@cli.command()
@click.option('--mode', default='test',
              type=click.Choice(['test', 'ask', 'write'], case_sensitive=False),
              help='test: only print the changes, ask: ask before writing, write: write the changes without asking')
def update_dependencies(mode):
    from stextools.dependency_update import dependency_check
    dependency_check(mode)


@cli.command()
@click.option('--filter', default=None,
              help='Filter pattern to only show some archives (e.g. \'smglom/*,MiKoMH/*\')')
def show_graph(filter):
    from stextools.dependency_graph import show_graph
    show_graph(filter)


@cli.command()
@click.option('--filter', default=None,
              help='Filter pattern to only show some archives (e.g. \'smglom/*,MiKoMH/*\')')
def show_weak_dependencies(filter):
    from stextools.dependency_graph import show_weak_dependencies
    show_weak_dependencies(filter)


if __name__ == '__main__':
    cli()
