import shutil
import subprocess
from typing import Optional, Callable

import click

from stextools.core.config import get_config
from stextools.core.simple_api import SimpleSymbol


def get_fzf_path() -> Optional[str]:
    fzf_path = get_config().get('stextools', 'fzf_path', fallback=shutil.which('fzf'))
    if fzf_path is None:
        print(click.style('fzf not found', fg='red'))
        print('Please install fzf to use this feature.')
        print('You install it via your package manager, e.g.:')
        print('  sudo apt install fzf')
        print('  sudo pacman -S fzf')
        print('  brew install fzf')
        print('For more information, see https://github.com/junegunn/fzf?tab=readme-ov-file#installation')
        print()
        print('You can also place the fzf binary in your PATH.')
        print('Download: https://github.com/junegunn/fzf/releases')
        print()
        click.pause()

    return fzf_path


def get_symbol_from_fzf(symbols: list[SimpleSymbol], display_fun: Callable[[SimpleSymbol], str]) -> Optional[SimpleSymbol]:
    # note: display_fun must be injective
    lookup = {}
    lines = []
    for symbol in symbols:
        display = display_fun(symbol)
        lookup[display] = symbol
        lines.append(display)

    fzf_path = get_fzf_path()
    if not fzf_path:
        return None

    proc = subprocess.Popen([fzf_path, '--ansi'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin is not None
    proc.stdin.write('\n'.join(lines))
    proc.stdin.close()
    assert proc.stdout is not None
    selected = proc.stdout.read().strip()
    proc.wait()
    if not selected:
        return None
    return lookup[selected]

