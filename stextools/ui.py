from typing import Optional

import click


USE_24_BIT_COLORS: bool = True


def print_options(intro: Optional[str], options: list[tuple[str, str]]):
    if intro:
        print(intro)
    for key, description in options:
        print(' ', click.style(f'[{key}]', bold=True) + description)


def color(simple: str, full: tuple[int, int, int]):
    if USE_24_BIT_COLORS:
        return full
    else:
        return simple


def pale_color():
    return color('bright_black', (128, 128, 128))


def simple_choice_prompt(options: list[str]):
    return click.prompt(
        click.style('>>> ', reverse=True, bold=True),
        type=click.Choice(options),
        show_choices=False, prompt_suffix=''
    )
