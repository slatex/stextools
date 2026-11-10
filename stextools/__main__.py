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


def _trans_depth(ctx, param, value):
    """--depth for `stextools trans`: a number >= 0, or 'all' (no limit) -> None."""
    if str(value).strip().lower() == 'all':
        return None
    try:
        n = int(value)
    except ValueError:
        n = -1
    if n < 0:
        raise click.BadParameter(f"expected a number >= 0 or 'all', got {value!r}")
    return n


@cli.command(name='trans', help='Create translation templates of sTeX files (or whole directories) for another language, from any language into any other (the source language is read from the file name, set.de.tex is German), auto-filling known term translations.')
@click.argument('paths', nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option('--lang', '-l', 'lang', default=None, help='Target language code or alias (e.g. de, german, en, zhs, fr).')
@click.option('--from', 'from_lang', default=None,
              help='Source language for directories (they expand to *.<from>.tex) and for files whose name has no language code (default: en).')
@click.option('--out', '-o', default=None, type=click.Path(path_type=Path), help='Output path (single input only; default: <module>.<lang>.tex next to the input).')
@click.option('--non-interactive', '--auto', 'non_interactive', is_flag=True,
              help='Never stop to ask: take the top-ranked translation, leave missing words as placeholders.')
@click.option('--ask-new', 'ask_new', is_flag=True,
              help='With --auto: still stop to ask for a word when a defined term has no translation yet.')
@click.option('--no-fill', 'no_fill', is_flag=True, help='Do not fill translations via FLAMS; only insert placeholders.')
@click.option('--no-report', 'no_report', is_flag=True, help='Do not write the .json report.')
@click.option('--depth', 'depth', default='0', metavar='N|all', callback=_trans_depth,
              help='Also translate the definitions the inputs are missing, first, following references '
                   'N steps (all = no limit). 0 = only the inputs (default).')
@click.option('--out-dir', 'out_dir', default='trans-staging', type=click.Path(path_type=Path),
              help='Where --depth 1 or more writes (default: ./trans-staging).')
def trans_command(paths, lang, from_lang, out, non_interactive, ask_new, no_fill, no_report,
                  depth, out_dir):
    """Click entry point for `stextools trans`.
    args:
        paths: One or more input paths. A file is translated directly and a directory is
            expanded to its `*.<from>.tex` files.
        lang: Target language code or alias; required (errors if None).
        from_lang: Source language for directories and for file names without a language
            code (default: en).
        out: Optional output path; only allowed with a single input file and --depth 0.
        non_interactive: If set, never prompt: take the top-ranked translation.
        ask_new: With non_interactive, still ask for a word when a defined term has none.
        no_fill: If set, only insert placeholders (skip the FLAMS fill step).
        no_report: If set, do not write the .json report.
        depth: 0 = only the inputs; N >= 1 or None (all) = first translate the definitions
            the inputs are missing, following references N steps (see run_closure).
        out_dir: Staging directory for --depth 1 or more.
    returns:
        None. Delegates to run_batch() (depth 0) or run_closure() (deeper).
    """
    from stextools.trans.trans import ensure_utf8_stdout
    ensure_utf8_stdout()   # tolerate non-ASCII (e.g. CJK) verbalizations on a legacy code page

    from stextools.trans.patterns import lang_flag_tokens, resolve_lang_alias
    if lang is None:
        raise click.UsageError(
            'Target language not specified. Use --lang <code>, e.g. one of: '
            + ', '.join(lang_flag_tokens())
        )
    from_lang = resolve_lang_alias(from_lang) if from_lang else 'en'

    # a directory expands to its *.<from>.tex sources
    files = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob(f'*.{from_lang}.tex')))
        else:
            files.append(p)
    if not files:
        raise click.UsageError(f'No input files. Provide sTeX file(s), or a directory containing '
                               f'*.{from_lang}.tex files (choose the language with --from).')
    if out is not None and len(files) > 1:
        raise click.UsageError('--out can only be used with a single input file.')

    if depth != 0:
        # translate the missing definitions first, then the inputs, all into the staging dir
        if out is not None:
            raise click.UsageError('--out only works with --depth 0 (deeper runs write into --out-dir).')
        if no_fill:
            raise click.UsageError('--depth needs the fill (FLAMS); drop --no-fill.')
        from stextools.trans.trans import run_closure
        run_closure(files, lang, out_dir=out_dir, depth=depth, interactive=not non_interactive,
                    write_report=not no_report, ask_new=ask_new, from_lang=from_lang)
        return

    from stextools.trans.trans import run_batch
    run_batch(files, lang, out=out, interactive=not non_interactive,
              fill=not no_fill, write_report=not no_report, from_lang=from_lang,
              ask_new=ask_new)


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
