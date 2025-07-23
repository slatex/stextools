"""
This module provides the command infrastructure for the stepper.

Instances of (subclasses of) the `Command` class represent concrete commands
that can be executed in the current context and their instatiation
may depend on the current state.

If applied, they return a list of ``CommandOutcome``s that describe the
changes to be made.

``Command``s should be grouped into a ``CommandCollection``.
A ``CommandCollection`` can then be "applied", which displays the available commands
and asks the user for a command that will be executed.
"""

import dataclasses
import re
from typing import Sequence, Iterable

from stextools.stepper.interface import interface


@dataclasses.dataclass
class CommandInfo:
    """
    Essentially metadata for a command.

    It describes how the command can be invoked and how the command should be presented to the user.
    """
    pattern_presentation: str
    description_short: str
    pattern_regex: str = ''         # if not set, will be derived from pattern_presentation
    description_long: str = ''      # if not set, will be derived from description_short

    show: bool = True   # set to False if the command should only be shown in the help text

    def __post_init__(self):
        if not self.pattern_regex:
            self.pattern_regex = '^' + self.pattern_presentation + '$'

        if not self.description_long:
            self.description_long = self.description_short


class CommandOutcome:
    """Result of executing a command."""


@dataclasses.dataclass
class SimpleCommandOutcome(CommandOutcome):
    """For simple implementations, it suffices to just return the call."""
    call: str


@dataclasses.dataclass
class Command:
    """Instances represent a command that can be executed in the current context.

    Usually, you should create a custom subclass for each command you want to implement.
    """
    command_info: CommandInfo

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        del self   # Intentionally unused in the base class.
        return [SimpleCommandOutcome(call=call)]

    def standard_display(self):
        interface.write_command_info(
            self.command_info.pattern_presentation,
            self.command_info.description_short,
        )

    def help_display(self):
        interface.write_command_info(
            self.command_info.pattern_presentation,
            self.command_info.description_long,
        )


class _HelpCommand(Command):
    """ Should only be instantiated by CommandCollection! """
    def __init__(self, command_collection: 'CommandCollection'):
        super().__init__(CommandInfo(
            pattern_presentation='h',
            pattern_regex='^h$',
            description_short='elp',
            description_long='Displays this help message')
        )
        self.command_collection = command_collection

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        with interface.big_infopage():
            interface.write_header(f'Help ({self.command_collection.name})', style='subdialog')
            interface.newline()
            for command in self.command_collection.commands:
                if isinstance(command, Command):
                    command.help_display()
                else:
                    interface.newline()
                    interface.write_header(command.message, style='section')
        return []


@dataclasses.dataclass
class CommandSectionLabel:
    message: str


@dataclasses.dataclass
class CommandCollection:
    name: str
    commands: list[Command | CommandSectionLabel]
    have_help: bool = True

    def __post_init__(self):
        if self.have_help:
            self.commands = [_HelpCommand(self)] + self.commands

    def apply(self) -> Sequence[CommandOutcome]:
        self._print_commands()
        interface.write_text('>>>', style='bold')
        call = interface.get_input()

        for command in self._pure_commands():
            if re.match(command.command_info.pattern_regex, call):
                return command.execute(call)

        interface.admonition(f'Invalid command {call!r}', 'error', confirm=True)
        return []

    def _pure_commands(self) -> Iterable[Command]:
        for c in self.commands:
            if isinstance(c, Command):
                yield c

    def _print_commands(self):
        show_all = all(c.command_info.show for c in self._pure_commands())
        interface.write_text('Commands:')
        if not show_all and self.have_help:
            interface.write_text(' ')
            interface.write_text('enter h (help) to see all available commands', style='pale')
        interface.newline()

        for command in self._pure_commands():
            if command.command_info.show:
                command.standard_display()
