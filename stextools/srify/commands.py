import abc
import dataclasses
import re

import click

from stextools.core.linker import Linker
from stextools.core.simple_api import SimpleSymbol
from stextools.srify.state import State
from stextools.utils.ui import option_string, standard_header, pale_color, color


class CommandOutcome:
    pass


class Exit(CommandOutcome):
    pass


@dataclasses.dataclass
class CommandInfo:
    pattern_presentation: str
    pattern_regex: str
    description_short: str
    description_long: str = ''

    show: bool = True


class Command(abc.ABC):
    def __init__(self, command_info: CommandInfo):
        self.command_info = command_info

    @abc.abstractmethod
    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        ...

    def standard_display(self, *, state: State) -> str:
        return option_string(self.command_info.pattern_presentation, self.command_info.description_short)

    def help_display(self) -> str:
        if self.command_info.description_long:
            indent = ' ' * (len(self.command_info.pattern_presentation) + 5)
            return option_string(
                self.command_info.pattern_presentation,
                self.command_info.description_short + '\n' + indent +
                self.command_info.description_long.replace('\n', '\n' + indent)
            )
        else:
            return option_string(self.command_info.pattern_presentation, self.command_info.description_short)


class QuitProgramCommand(Command):
    def __init__(self):
        super().__init__(CommandInfo(
            pattern_presentation='q',
            pattern_regex='^q$',
            description_short='uit',
            description_long='Quits the program')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [Exit()]


class AnnotateCommand(Command):
    """ Has to be re-instantiated for each state! """
    def __init__(self, symbols: list[SimpleSymbol], state: State, linker: Linker):
        super().__init__(CommandInfo(
            pattern_presentation='𝑖',
            pattern_regex='^[0-9]+$',
            description_short=' annotate with 𝑖',
            description_long='Annotates the current selection with option number 𝑖')
        )
        self.symbols = symbols
        self.state = state
        self.linker = linker

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        assert state == self.state
        return []

    def standard_display(self, *, state: State) -> str:
        assert state == self.state
        lines: list[str] = []
        for i, symbol in enumerate(self.symbols):
            symb_path = symbol.path_rel_to_archive.split('?')
            assert len(symb_path) == 3
            lines.append(option_string(
                str(i),
                ' ' + symbol.declaring_file.archive.name + ' ' +
                symb_path[0] + '?' +
                click.style(symb_path[1], bg=color('bright_cyan', (180, 180, 255))) + '?' +
                click.style(symb_path[2], bg=color('bright_green', (180, 255, 180))) +
                '\n      ' + click.style(symbol.declaring_file.path, italic=True, fg=pale_color())
            ))
        return '\n'.join(lines)


class HelpCommand(Command):
    """ Should only be instantiated by CommandCollection. """
    def __init__(self, command_collection: 'CommandCollection'):
        super().__init__(CommandInfo(
            pattern_presentation='h',
            pattern_regex='^h$',
            description_short='elp',
            description_long='Displays this help message')
        )
        self.command_collection = command_collection

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        click.clear()
        standard_header(f'Help ({self.command_collection.name})')
        print()
        for command in self.command_collection.commands:
            print(command.help_display())
        print()
        click.pause()
        return []


@dataclasses.dataclass
class CommandCollection:
    name: str
    commands: list[Command]
    have_help: bool = True

    def __post_init__(self):
        if self.have_help:
            self.commands = [HelpCommand(self)] + self.commands

    def apply(self, *, state: State) -> list[CommandOutcome]:
        self._print_commands(state)
        call = input(click.style('>>>', bold=True) + ' ')
        for command in self.commands:
            if re.match(command.command_info.pattern_regex, call):
                return command.execute(state=state, call=call)
        print(click.style('Invalid command', fg='red'))
        click.pause()
        return []

    def _print_commands(self, state: State):
        show_all = all(c.command_info.show for c in self.commands)
        if not show_all and self.have_help:
            print('Commands:   ' + click.style('enter h (help) to see all available commands', fg=pale_color()))
        else:
            print('Commands:')

        for command in self.commands:
            if command.command_info.show:
                print(command.standard_display(state=state))
