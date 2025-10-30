import logging
import shutil
from pathlib import Path

import click

from stextools.config import get_config, CACHE_DIR
from stextools.stepper.interface import set_interface, DEFAULT_INTERFACES

logger = logging.getLogger(__name__)


interface_option = click.option(
    '--interface',
    default=lambda: get_config().get('stextools.general', 'interface', fallback='console-light'),
    type=click.Choice(DEFAULT_INTERFACES.keys(), case_sensitive=False),
    help='Sets the interface (true refers to true color, which is not supported by all terminals).'
)


@click.group()
@click.option('--log-file', default=None, type=click.Path(),
              help='Log file path. If not set, logs to stdout.')
def cli(log_file):
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, filename=log_file)


@cli.command(name='snify', help='\\sn-ify sTeX documents')
@click.option('--anno-format', default='stex', type=click.Choice(['stex', 'wikidata']),
              help='Annotation type (wikidata support is prototypical only).')
@click.option('--mode', default='text', type=click.Choice(['text', 'math', 'both']),
              help='Annotation mode: text, math, or both (default: text). Note that math is experimental.')
@click.argument(
    'files', nargs=-1, type=click.Path(exists=True, path_type=Path),
)
@interface_option
def snify_command(anno_format, mode, files, interface):
    from stextools.snify.snify import snify
    set_interface(interface)
    if not files:
        click.echo('No files specified. Please provide paths to files or directories to snify.')
        return
    snify(files, anno_format=anno_format, mode=mode)

@cli.command(name='snify3', help='\\sn-ify sTeX documents')
@click.option('--anno-format', default='stex', type=click.Choice(['stex', 'wikidata']),
              help='Annotation type (wikidata support is prototypical only).')
@click.option('--mode', default='text', type=click.Choice(['text', 'math', 'both']),
              help='Annotation mode: text, math, or both (default: text). Note that math is experimental.')
@click.argument(
    'files', nargs=-1, type=click.Path(exists=True, path_type=Path),
)
@interface_option
def snify3_command(anno_format, mode, files, interface):
    from stextools.snify.snify import snify3
    set_interface(interface)
    if not files:
        click.echo('No files specified. Please provide paths to files or directories to snify.')
        return
    snify3(files, anno_format=anno_format, mode=mode)

@cli.command(name='lexgen', help='lexicong generation')
@click.argument(
    'files', nargs=-1, type=click.Path(exists=True, path_type=Path),
)
@interface_option
def lexgen_command(files, interface):
    from stextools.lexicon.lexgen import lexgen
    set_interface(interface)
    if not files:
        click.echo('No files specified. Please provide paths to files or directories to snify.')
        return
    lexgen(files)

@cli.command(help='Clear the cache. The cache is automatically cleared whenever stextools is updated.')
def clear_cache():
    shutil.rmtree(CACHE_DIR)
    click.echo('Cache cleared.')


@cli.command(help='Recursively clone all public repositories in the specified MathHub groups.')
@click.argument('groups', nargs=-1)
def clone_groups(groups):
    from stextools.remote_repositories import clone_group
    for group in groups:
        clone_group(group)


if __name__ == '__main__':
    cli(
        standalone_mode=False,   # helps with debugging if stuck
    )
