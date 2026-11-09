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


@cli.command(name='trans', help='Create translation templates of sTeX files (or whole directories) for another language, from any language into any other (the source language is read from the file name, set.de.tex is German), auto-filling known term translations.')
@click.argument('paths', nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option('--lang', '-l', 'lang', default=None, help='Target language code or alias (e.g. de, german, en, zhs, fr).')
@click.option('--from', 'from_lang', default=None,
              help='Source language for directories (they expand to *.<from>.tex) and for files whose name has no language code (default: en).')
@click.option('--out', '-o', default=None, type=click.Path(path_type=Path), help='Output path (single input only; default: <module>.<lang>.tex next to the input).')
@click.option('--non-interactive', '--auto', 'non_interactive', is_flag=True,
              help='Do not prompt on ambiguous terms; take the top-ranked translation.')
@click.option('--no-fill', 'no_fill', is_flag=True, help='Do not fill translations via FLAMS; only insert placeholders.')
@click.option('--no-report', 'no_report', is_flag=True, help='Do not write the .json report.')
@click.option('--closure', 'closure', is_flag=True,
              help='Large-scale mode: translate the (reference) closure of the input documents — the '
                   'definitions of everything they reference that lacks a target-language version.')
@click.option('--out-dir', 'out_dir', default='trans-staging', type=click.Path(path_type=Path),
              help='Staging directory for --closure output (default: ./trans-staging).')
@click.option('--depth', 'depth', default=1, type=int,
              help='--closure: how far to follow references (1 = only directly referenced defs).')
def trans_command(paths, lang, from_lang, out, non_interactive, no_fill, no_report,
                  closure, out_dir, depth):
    """Click entry point for `stextools trans`.
    args:
        paths: One or more input paths. In normal mode a file is translated directly and a
            directory is expanded to its `*.<from>.tex` files. In --closure mode these are the
            seed documents whose references drive the closure.
        lang: Target language code or alias; required (errors if None).
        from_lang: Source language for directories and for file names without a language
            code (default: en).
        out: Optional output path; only allowed with a single input file (normal mode).
        non_interactive: If set, take the top-ranked translation without prompting.
        no_fill: If set, only insert placeholders (skip the FLAMS fill step).
        no_report: If set, do not write the .json report.
        closure: Large-scale reference-closure mode (see run_closure).
        out_dir: Staging directory for --closure output.
        depth: how far the closure follows references (1 = only directly referenced definitions).
    returns:
        None. Delegates to run_closure() (large-scale) or run_batch() (normal).
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

    if closure:
        # seeds: files as given; a directory expands to all sTeX sources under it
        seeds = []
        for p in paths:
            if p.is_dir():
                seeds.extend(sorted(f for f in p.rglob('*.tex')))
            else:
                seeds.append(p)
        if not seeds:
            raise click.UsageError('No seed documents. Provide file(s) or a directory of sTeX sources.')
        from stextools.trans.trans import run_closure
        run_closure(seeds, lang, out_dir=out_dir, depth=depth,
                    interactive=not non_interactive, write_report=not no_report)
        return

    # normal mode: translate the given files (a directory expands to its *.<from>.tex sources)
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

    from stextools.trans.trans import run_batch
    run_batch(files, lang, out=out, interactive=not non_interactive,
              fill=not no_fill, write_report=not no_report, from_lang=from_lang)


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
