import json
import math
import pickle
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from stextools.stepper.command_outcome import CommandOutcome
from stextools.stepper.commands import CommandInfo, Command, CommandCollection
from stextools.stepper.state import State
from stextools.utils.ui import option_string, standard_header

# TODO: move this somewhere else?
PATH = Path('~/.config/stextools/sessions').expanduser()


def format_past_timestamp(time: datetime) -> str:
    """ recent timestamps skip unnecessary information """
    now = datetime.now()
    if time.year == now.year:
        if time.date() == now.date():
            return time.strftime('%H:%M')
        return time.strftime('%b %d %H:%M')
    return time.strftime('%Y-%m-%d %H:%M')


class Session:
    def __init__(self, identifier: str, metadata: dict):
        self.identifier = identifier
        self.metadata = metadata

    def write(self, state: State):
        with open(PATH / (self.identifier + '.json'), 'w') as fp:
            fp.write(json.dumps(self.metadata))
        with open(PATH / (self.identifier + '.dmp'), 'wb') as fp:
            pickle.dump(state, fp)

    def get_state(self) -> State:
        with open(PATH / (self.identifier + '.dmp'), 'rb') as fp:
            return pickle.load(fp)

    @classmethod
    def from_identifier(cls, identifier: str):
        with open(PATH / (identifier + '.json'), 'r') as fp:
            metadata = json.loads(fp.read())
        return cls(identifier, metadata)

    def delete(self):
        (PATH / (self.identifier + '.json')).unlink()
        (PATH / (self.identifier + '.dmp')).unlink()


class SessionChoiceOutcome(CommandOutcome):
    def __init__(self, session_number: int, action: str):
        self.session_number = session_number
        self.action = action


class PickSessionCommand(Command):
    # instance_count = 0

    def __init__(self, sessions: list[Session]):
        # PickSessionCommand.instance_count += 1
        # assert PickSessionCommand.instance_count == 1, 'Only one PickSessionCommand instance allowed'
        self.sessions = sessions
        super().__init__(CommandInfo(
            pattern_presentation='𝑖',
            pattern_regex='^[0-9]+$',
            description_short=' resume session 𝑖',
            description_long='Resume the existing session 𝑖')
        )

    def standard_display(self, *, state: State) -> str:
        lines: list[str] = ['Resume an existing session:']
        for i, session in enumerate(self.sessions):
            line = option_string(
                str(i),
                '  ' + format_past_timestamp(datetime.fromtimestamp(session.metadata['timestamp'])) + ' – ' + session.metadata['description']
            )
            lines.append(line)
        return '\n'.join(lines)

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [SessionChoiceOutcome(int(call), 'resume')]


class DeleteSessionCommand(Command):
    def __init__(self, sessions: list[Session]):
        self.sessions = sessions
        super().__init__(CommandInfo(
            show=True,
            pattern_presentation='d𝑖',
            pattern_regex='^d[0-9]+$',
            description_short=' delete session 𝑖',
            description_long='Delete the existing session 𝑖')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [SessionChoiceOutcome(int(call[1:]), 'delete')]


class DeleteAllSessionsCommand(Command):
    def __init__(self, sessions: list[Session]):
        self.sessions = sessions
        super().__init__(CommandInfo(
            show=True,
            pattern_presentation='D',
            pattern_regex='^D$',
            description_short='elete all sessions',
            description_long='Delete all existing sessions')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [SessionChoiceOutcome(0, 'delete') for _ in range(len(self.sessions))]


class IgnoreSessions(CommandOutcome):
    pass


class ContinueWithoutSession(Command):
    def __init__(self, sessions: list[Session]):
        self.sessions = sessions
        super().__init__(CommandInfo(
            show=True,
            pattern_presentation='c',
            pattern_regex='^c$',
            description_short='ontinue',
            description_long='Continue and do not resume any session')
        )

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        return [IgnoreSessions()]


class SessionStorage:
    def __init__(self):
        self.path = PATH
        self.path.mkdir(parents=True, exist_ok=True)
        self.sessions: list[Session] = []
        for file in PATH.glob('*.json'):
            self.sessions.append(Session.from_identifier(file.stem))

        last_modified = -math.inf
        for file in Path(__file__).parent.rglob('**/*.py'):
            last_modified = max(last_modified, file.stat().st_mtime)
        self.srify_timestamp = last_modified
        self.loaded_session: Optional[Session] = None

    def have_ongoing_session(self) -> bool:
        return bool(self.sessions)

    def delete_session_if_loaded(self):
        if self.loaded_session:
            self.sessions.remove(self.loaded_session)
            self.loaded_session.delete()

    def get_session_dialog(self) -> Optional[State]:
        if not self.have_ongoing_session():
            return None

        while self.sessions:
            click.clear()
            standard_header('Session management', bg='bright_cyan')
            print()
            print('You have multiple existing sessions. What would you like to do?')
            outcomes = CommandCollection(
                name='session management',
                commands=[
                    ContinueWithoutSession(self.sessions),
                    DeleteSessionCommand(self.sessions),
                    DeleteAllSessionsCommand(self.sessions),
                    PickSessionCommand(self.sessions),
                ],
                have_help=True,
            ).apply(state=None)    # type: ignore

            for outcome in outcomes:
                if isinstance(outcome, IgnoreSessions):
                    return None
                elif isinstance(outcome, SessionChoiceOutcome):
                    if outcome.action == 'resume':
                        session = self.sessions[outcome.session_number]
                        if session.metadata['srifytimestamp'] < self.srify_timestamp:
                            if not click.confirm(
                                'This session was created with an older version of snify. '
                                'Resuming it may lead to unexpected behavior. '
                                'Are you sure you want to resume it?'
                            ):
                                continue
                        self.loaded_session = session
                        return session.get_state()
                    elif outcome.action == 'delete':
                        self.sessions[outcome.session_number].delete()
                        self.sessions.pop(outcome.session_number)
                    else:
                        raise RuntimeError(f'Unexpected action: {outcome.action}')
                else:
                    raise RuntimeError(f'Unexpected outcome: {outcome}')

        return None   # no sessions left

    def store_session_dialog(self, state: State):
        print('\n\n')
        if not click.confirm('Would you like to save the current session?'):
            return
        if self.loaded_session:
            print('You are in a session that was loaded from a file.')
            print('  Description:', self.loaded_session.metadata['description'])
            print('  Timestamp:', self.loaded_session.metadata['timestamp'])
            if click.confirm('Would you like to overwrite this session?'):
                self.loaded_session.write(state)
                return

        description = click.prompt('Brief description of the session (optional)', default='no description')
        session = Session(
            identifier=str(uuid.uuid4()),
            metadata={
                'description': description,
                'timestamp': time.time(),
                'srifytimestamp': self.srify_timestamp,
            }
        )
        session.write(state)
