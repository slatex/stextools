"""
User interfaces for the stepper module.
"""
import dataclasses
import functools
import shutil
import subprocess
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Literal, Optional, TypeAlias, Callable, Any

import click
from pygments import highlight
from pygments.formatters.terminal import TerminalFormatter
from pygments.formatters.terminal256 import TerminalTrueColorFormatter
from pygments.lexers.markup import TexLexer, MarkdownLexer

from stextools.config import get_config

_Color: TypeAlias = str | tuple[int, int, int]


def _get_lines_around(text: str, start: int, end: int, n_lines: int = 7) -> tuple[str, str, str, int]:
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


class interface:
    """
    This is a hack because I messed up the design of this module.

    It has to stay synchronized with the abstract Interface class.
    An alternative would be to use __getattr__,
    but that would prevent static type checking.
    """
    @staticmethod
    def clear():
        actual_interface.clear()

    @staticmethod
    def big_infopage():
        return actual_interface.big_infopage()

    @staticmethod
    def write_text(text: str, style: str = 'default', *, prestyled: bool = False):
        actual_interface.write_text(text, style=style, prestyled=prestyled)

    @staticmethod
    def apply_style(text: str, style: str) -> str:
        return actual_interface.apply_style(text, style=style)

    @staticmethod
    def get_input() -> str:
        return actual_interface.get_input()

    @staticmethod
    def newline():
        actual_interface.newline()

    @staticmethod
    def write_header(text: str, style: Literal['default', 'error', 'warning', 'subdialog', 'section'] = 'default'):
        actual_interface.write_header(text, style=style)

    @staticmethod
    def write_command_info(key: str, description: str):
        actual_interface.write_command_info(key, description)

    @staticmethod
    def write_statistics(text: str):
        actual_interface.write_statistics(text)

    @staticmethod
    def await_confirmation():
        actual_interface.await_confirmation()

    @staticmethod
    def admonition(text: str, type: Literal['error', 'warning', 'info'], confirm: bool):
        actual_interface.admonition(text, type=type, confirm=confirm)

    @staticmethod
    def list_search(items: dict[str, Any] | list[str]) -> Optional[Any]:
        return actual_interface.list_search(items)

    @staticmethod
    def ask_yes_no(message: Optional[str] = None) -> bool:
        return actual_interface.ask_yes_no(message)

    @staticmethod
    def show_code(
            code: str,
            format: Optional[Literal['tex', 'sTeX', 'myst']] = None,
            *,
            highlight_range: Optional[tuple[int, int]] = None,
            limit_range: Optional[int] = None,    # only shows this many lines before/after the highlight_range
            show_line_numbers: bool = True,
    ) -> None:
        actual_interface.show_code(
            code, format=format, highlight_range=highlight_range, limit_range=limit_range,
            show_line_numbers=show_line_numbers
        )


class Interface(ABC):
    """Base class for all interfaces in the stepper module."""

    @abstractmethod
    def clear(self) -> None:
        """Clears/resets the screen."""

    @abstractmethod
    @contextmanager
    def big_infopage(self):
        pass

    @abstractmethod
    def write_text(self, text: str, style: str = 'default', *, prestyled: bool = False):
        pass


    def list_search(self, items: dict[str, Any] | list[str]) -> Optional[Any]:
        """
        Displays the items in a searchable list and returns the selected item.
        If the items are a dictionary, the keys are displayed,
        and the value corresponding to the selected key is returned.
        """
        # simple default implementation

        if isinstance(items, list):
            items = {s: s for s in items}

        self.clear()
        self.write_header('Search')
        for i, key in enumerate(items):
            self.write_text(f'[{i}] {key}\n', style='bold')
            self.newline()
        while True:
            self.write_text('Enter the number of the item you want to select (empty string to abort): ',
                            style='default')
            number = self.get_input().strip()
            if not number:
                return None
            if number.isdigit() and int(number) in range(len(items)):
                return items[list(items.keys())[int(number)]]
            self.write_text(f'Invalid number: {number!r}. Please try again.\n', style='error')


    def apply_style(self, text: str, style: str) -> str:
        return text

    @abstractmethod
    def get_input(self) -> str:
        pass

    def admonition(self, text: str, type: Literal['error', 'warning', 'info'], confirm: bool):
        style = {
            'error': 'error',
            'warning': 'warning',
            'info': 'default',
        }[type]
        self.write_header(
            type.capitalize(),
            style=style,   # type: ignore
        )
        if not text.endswith('\n'):
            text += '\n'
        self.write_text(text, style=style + ('-weak' if style in {'error', 'warning'} else ''))
        if confirm:
            self.await_confirmation()

    def newline(self):
        self.write_text('\n')

    def write_header(
            self, text: str, style: Literal['default', 'error', 'warning', 'subdialog', 'section'] = 'default'
    ):
        del style   # default implementation ignores style
        self.write_text(text, style='bold')
        self.newline()

    def write_command_info(self, key: str, description: str):
        self.write_text('  ')
        self.write_text(f'[{key}]', style='bold')
        self.write_text(description.replace('\n', '\n' + ' ' * (len(key) + 4)), prestyled=True)
        self.newline()

    def write_statistics(self, text: str):
        self.write_text(text, style='pale')
        self.newline()

    def ask_yes_no(self, message: Optional[str] = None) -> bool:
        if message:
            self.write_text(message, style='default')
        self.write_text(' (y/n): ', style='bold')
        result = self.get_input().strip().lower()
        while result not in {'y', 'n'}:
            self.write_text('Please answer with "y" or "n": ', style='error')
            result = self.get_input().strip().lower()
        return result == 'y'

    def await_confirmation(self):
        self.write_text('Press Enter to continue...', style='default')
        self.get_input()

    def _code_highlight_prep(
            self, code: str, highlight_range: Optional[tuple[int, int]] = None, limit_range: Optional[int] = None
    ) -> tuple[str, str, str, int]:
        """
        returns (
            relevant code before highlight,
            highlighted code,
            relevant code after highlight,
            line number at the start of the relevant code
        )
        """
        if limit_range is not None:
            if highlight_range is None:
                raise ValueError("highlight_range must be provided if limit_range is specified.")
            a, b, c, line_no_start = _get_lines_around(
                code, highlight_range[0], highlight_range[1], n_lines=limit_range or 7
            )
        elif highlight_range:
            a = code[:highlight_range[0]]
            b = code[highlight_range[0]:highlight_range[1]]
            c = code[highlight_range[1]:]
            line_no_start = 1
        else:
            a = code
            b = ''
            c = ''
            line_no_start = 1

        return a, b, c, line_no_start


    def show_code(
            self,
            code: str,
            format: Optional[Literal['tex', 'sTeX', 'myst']] = None,
            *,
            highlight_range: Optional[tuple[int, int]] = None,
            limit_range: Optional[int] = None,    # only shows this many lines before/after the highlight_range
            show_line_numbers: bool = True,
    ):
        del format   # default implementation does no syntax highlighting

        a, b, c, line_no = self._code_highlight_prep(code, highlight_range, limit_range)
        last_printed_line_no = None

        for source, style in [(a, 'default'), (b, 'highlight'), (c, 'default')]:
            for line_no, line in enumerate(source.splitlines(keepends=True), line_no):
                if show_line_numbers and last_printed_line_no != line_no:
                    self.write_text(f'{line_no:4} ', style='pale')
                    last_printed_line_no = line_no
                self.write_text(line, style=style)

            if source.endswith('\n'):
                line_no += 1

        if not code.endswith('\n'):
            self.newline()

class MinimalInterface(Interface):
    """A minimal interface that only prints text to the console."""

    def clear(self) -> None:
        self.write_text('\n' + '=' * 80 + '\n')

    @contextmanager
    def big_infopage(self):
        self.clear()
        yield
        self.await_confirmation()
        self.clear()

    def write_text(self, text: str, style: str = 'default', *, prestyled: bool = False):
        print(text, end='')

    def get_input(self) -> str:
        return input()


@dataclasses.dataclass
class ConsoleInterface(Interface):
    light_mode: bool = False
    true_color: bool = False

    def __post_init__(self):
        self._in_big_infopage: bool = False
        self._big_infopage_content: str = ''

    def clear(self) -> None:
        click.clear()

    def list_search(self, items: dict[str, Any] | list[str]) -> Optional[Any]:
        fzf_path = get_fzf_path()

        if not fzf_path:
            return super().list_search(items)

        if isinstance(items, list):
            items = {s: s for s in items}


        proc = subprocess.Popen([fzf_path, '--ansi'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert proc.stdin is not None
        proc.stdin.write('\n'.join(items.keys()))
        proc.stdin.close()
        assert proc.stdout is not None
        selected = proc.stdout.read().strip()
        proc.wait()
        if not selected:
            return None
        lookup = {
            click.unstyle(key): value
            for key, value in items.items()
        }  # ansi codes are apparently stripped in the fzf output
        return lookup[selected]




    def width(self):
        return shutil.get_terminal_size().columns

    @contextmanager
    def big_infopage(self):
        if self._in_big_infopage:
            raise RuntimeError("Already in a big infopage context.")
        self._in_big_infopage = True
        self._big_infopage_content = ''
        yield
        self._in_big_infopage = False
        click.echo_via_pager(self._big_infopage_content)

    def _write_styled(self, text: str):
        if self._in_big_infopage:
            self._big_infopage_content += text
        else:
            click.echo(text, nl=False)

    def write_text(self, text: str, style: str = 'default', *, prestyled: bool = False):
        if not prestyled:
            text = self.apply_style(text, style)
        self._write_styled(text)

    def write_header(
            self, text: str, style: Literal['default', 'error', 'warning', 'subdialog', 'section'] = 'default'
    ):
        style = {
            'default': 'highlight1',
            'error': 'error',
            'warning': 'warning',
            'subdialog': 'bold',
            'section': 'bold',
        }[style]
        self.write_text(f'{text:^{self.width()}}', style=style)
        self.newline()

    def apply_style(self, text: str, style: str) -> str:
        def c(
                simple: str | None,
                full: tuple[int, int, int],
                simple_light: str | None,
                full_light: tuple[int, int, int],
        ) -> _Color | None:
            if self.light_mode:
                return full_light if self.true_color else simple_light
            return full if self.true_color else simple

        bold = False
        italics = False
        strikethrough = False
        default_bg = c(None, (0, 0, 0), None, (255, 255, 255))
        default_fg = c(None, (255, 255, 255), None, (0, 0, 0))
        bg = default_bg
        fg = default_fg

        if style == 'bold':
            bold = True
        elif style == 'error':
            bg = c('red', (255, 0, 0), 'bright_red', (255, 128, 128))
        elif style == 'error-weak':
            fg = c('bright_red', (255, 128, 128), 'red', (255, 0, 0))
        elif style == 'success-weak':
            fg = c('bright_green', (128, 255, 128), 'green', (0, 255, 0))
        elif style == 'warning':
            bg = c('yellow', (255, 255, 0), 'bright_yellow', (255, 255, 128))
        elif style == 'highlight':
            bg = c('yellow', (255, 255, 0), 'bright_yellow', (255, 255, 128))
        elif style == 'pale':
            fg = c('bright_black', (128, 128, 128), 'bright_black', (128, 128, 128))
        elif style == 'highlight1':
            bg = c('bright_green', (0, 255, 0), 'bright_green', (128, 255, 128))
        elif style == 'highlight2':
            bg = c('bright_cyan', (0, 255, 255), 'bright_cyan', (128, 255, 255))
        elif style == 'highlight3':
            bg = c('bright_blue', (0, 0, 255), 'bright_blue', (128, 128, 255))
        else:
            pass

        return click.style(text, bg=bg, fg=fg, bold=bold, italic=italics, strikethrough=strikethrough) + \
            click.style('', bg=default_bg, fg=default_fg, reset=False)


    def get_input(self) -> str:
        return click.prompt('', show_default=False, prompt_suffix='')

    def show_code(
            self,
            code: str,
            format: Optional[Literal['tex', 'sTeX', 'myst']] = None,
            *,
            highlight_range: Optional[tuple[int, int]] = None,
            limit_range: Optional[int] = None,    # only shows this many lines before/after the highlight_range
            show_line_numbers: bool = True,
    ):
        a, b, c, line_no = self._code_highlight_prep(code, highlight_range, limit_range)

        def code_format(string: str) -> str:
            style = 'vs' if self.light_mode else 'monokai'

            if self.true_color:
                formatter = TerminalTrueColorFormatter(style=style)
            else:
                formatter = TerminalFormatter(style=style)

            if format in {'tex', 'sTeX'}:
                lexer = TexLexer(stripnl=False, stripall=False, ensurenl=False)
            elif format == 'myst':
                lexer = MarkdownLexer(stripnl=False, stripall=False, ensurenl=False)
            else:
                raise ValueError(f"Unknown format: {format!r}. Supported formats are 'tex', 'sTeX', and 'myst'.")

            return highlight(string, lexer, formatter)

        formatted_code = code_format(a) + self.apply_style(b, 'highlight') + code_format(c)

        for i, line in enumerate(formatted_code.splitlines(keepends=True), line_no):
            self.write_text(f'{i:4} ', style='pale')
            self.write_text(line, prestyled=True)

        interface.newline()

    def await_confirmation(self):
        self.write_text('Press Enter to continue...', style='default')
        input()   # get_input doesn't work for empty input

@functools.cache
def get_fzf_path() -> Optional[str]:
    fzf_path = get_config().get('stextools', 'fzf_path', fallback=shutil.which('fzf'))
    if fzf_path is None:
        interface.admonition('fzf not found', 'error', confirm=False)
        interface.write_text('''
This feature works best with the fzf tool.
You install it via your package manager, e.g.:
sudo apt install fzf
sudo pacman -S fzf
brew install fzf
For more information, see https://github.com/junegunn/fzf?tab=readme-ov-file#installation

You can also place the fzf binary in your PATH.
Download: https://github.com/junegunn/fzf/releases

For now, I'll continue without fzf.
''')
        interface.await_confirmation()
    return fzf_path



actual_interface: Interface = MinimalInterface()

DEFAULT_INTERFACES: dict[str, Callable[[], Interface]] = {
    'console-debug': lambda: MinimalInterface(),
    'console-dark': lambda: ConsoleInterface(light_mode=False, true_color=False),
    'console-light': lambda: ConsoleInterface(light_mode=True, true_color=False),
    'console-true-dark': lambda: ConsoleInterface(light_mode=True, true_color=True),
    'console-true-light': lambda: ConsoleInterface(light_mode=True, true_color=True),
}

def set_interface(new_interface: Interface | str):
    global actual_interface

    if isinstance(new_interface, str):
        if new_interface not in DEFAULT_INTERFACES:
            raise ValueError(f'Unknown interface name: {new_interface!r}')
        new_interface = DEFAULT_INTERFACES[new_interface]()

    if not isinstance(new_interface, Interface):
        raise TypeError(f"Expected an instance of Interface, got {type(new_interface)}")

    actual_interface = new_interface
