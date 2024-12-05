import shutil
from typing import Optional

import click


USE_24_BIT_COLORS: bool = True


def width():
    return shutil.get_terminal_size().columns


def print_options(intro: Optional[str], options: list[tuple[str, str]]):
    if intro:
        print(intro)
    for key, description in options:
        print(option_string(key, description))


def option_string(key: str, description: str):
    return '  ' + click.style(f'[{key}', bold=True) + click.style(']', bold=True) + description


def color(simple: str, full: tuple[int, int, int]):
    if USE_24_BIT_COLORS:
        return full
    else:
        return simple


def standard_header(title, bg: str = 'bright_green'):
    print(standard_header_str(title, bg))


def standard_header_str(title, bg: str = 'bright_green') -> str:
    return click.style(f'{title:^{width()}}', bold=True, fg='black', bg=bg)


def pale_color():
    return color('bright_black', (128, 128, 128))


def simple_choice_prompt(options: list[str]):
    return click.prompt(
        click.style('>>>', bold=True),
        type=click.Choice(options),
        show_choices=False, prompt_suffix=''
    )


def print_highlight_selection(doc_text: str, start: int, end: int, n_lines: int = 7, *, bold: bool = True):
    a, b, c, line_no_start = get_lines_around(doc_text, start, end, n_lines)
    doc = latex_format(a) + (
        '\n'.join(click.style(p, fg='black', bg='bright_yellow', bold=bold) for p in b.split('\n'))
    ) + latex_format(c)

    for i, line in enumerate(doc.split('\n'), line_no_start):
        print(click.style(f'{i:4} ', fg=pale_color()) + line)


def latex_format(code: str) -> str:
    from pygments import highlight
    from pygments.lexers import TexLexer

    if USE_24_BIT_COLORS:
        from pygments.formatters import TerminalTrueColorFormatter as TerminalFormatter
    else:
        from pygments.formatters import TerminalFormatter  # type: ignore

    return highlight(code, TexLexer(stripnl=False, stripall=False, ensurenl=False), TerminalFormatter(style='vs'))


def get_lines_around(text: str, start: int, end: int, n_lines: int = 7) -> tuple[str, str, str, int]:
    """
    returns
      - the n_lines lines before the start index
      - the text between the start and end index
      - the n_lines lines after the end index
      - the line number of the start index
    """
    start_index = start
    for _ in range(n_lines):
        if start_index > 0:
            start_index -= 1
        while start_index > 0 and text[start_index - 1] != '\n':
            start_index -= 1

    end_index = end
    for _ in range(n_lines):
        if end_index + 1 < len(text):
            end_index += 1
        while end_index + 1 < len(text) and text[end_index + 1] != '\n':
            end_index += 1
    end_index += 1

    return text[start_index:start], text[start:end], text[end:end_index], text[:start_index].count('\n') + 1
