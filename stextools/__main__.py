import importlib.metadata
import logging
import shutil
from pathlib import Path
from platform import python_version

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
@click.option('--mode', default='text,objectives',
              help='Annotation mode. Possible entries: text, objectives. Under development: math, verbalizations')
@click.option('--deep', is_flag=True,
              help='Also include dependencies of the specified files (transitively).')
@click.argument(
    'files', nargs=-1, type=click.Path(exists=True, path_type=Path),
)
@interface_option
def snify_command(anno_format, mode, deep, files, interface):
    from stextools.snify.snify import snify
    set_interface(interface)
    if not files:
        click.echo('No files specified. Please provide paths to files or directories to snify.')
        return
    snify(files, anno_format=anno_format, mode=mode, deep=deep)


@cli.command(name='trans', help='Create a target-language translation template from an English sTeX file, auto-filling known term translations.')
@click.argument('file', type=click.Path(exists=True, path_type=Path))
@click.option('--lang', '-l', 'lang', default=None, help='Target language code or alias (e.g. de, german, zhs, fr).')
@click.option('--out', '-o', default=None, type=click.Path(path_type=Path), help='Output path (default: <stem>.<lang>.tex next to the input).')
@click.option('--non-interactive', '--auto', 'non_interactive', is_flag=True,
              help='Do not prompt on ambiguous terms; take the top-ranked translation.')
@click.option('--no-fill', 'no_fill', is_flag=True, help='Do not fill translations via FLAMS; only insert placeholders.')
@click.option('--no-report', 'no_report', is_flag=True, help='Do not write the .json report.')
def trans_command(file, lang, out, non_interactive, no_fill, no_report):
    """Click entry point for `stextools trans`.
    args:
        file: Path to the input English (annotated) sTeX file.
        lang: Target language code or alias; required (errors if None).
        out: Optional output path (default <stem>.<lang>.tex next to the input).
        non_interactive: If set, take the top-ranked translation without prompting.
        no_fill: If set, only insert placeholders (skip the FLAMS fill step).
        no_report: If set, do not write the .json report.
    returns:
        None. Delegates to run_trans(), which writes the output files.
    """
    from stextools.trans.patterns import lang_flag_tokens
    if lang is None:
        raise click.UsageError(
            'Target language not specified. Use --lang <code>, e.g. one of: '
            + ', '.join(lang_flag_tokens())
        )
    from stextools.trans.trans import run_trans
    run_trans(file, lang, out=out, interactive=not non_interactive,
              fill=not no_fill, write_report=not no_report)


@cli.command(name='lexgen', help='lexicon generation (experimental and work-in-progress)')
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
@click.option('--use-https', is_flag=True, help='Use https instead of ssh')
@click.argument('groups', nargs=-1)
def clone_groups(use_https, groups):
    from stextools.remote_repositories import clone_group
    for group in groups:
        clone_group(group, use_ssh=not use_https)

@cli.command(name='version', help='Print the version of stextools.')
def version():
    print('stextools:', importlib.metadata.version('stextools'))
    print('python:', python_version())

if __name__ == '__main__':
    cli(
        standalone_mode=False,   # helps with debugging if stuck
    )
