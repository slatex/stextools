import json
import math
import pickle
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from stextools.config import CONFIG_DIR
from stextools.stepper.command import CommandOutcome, Command, CommandInfo, CommandCollection
from stextools.stepper.interface import interface
from stextools.stepper.stepper import State
from stextools.stepper.stepper_extensions import QuitOutcome, QuitCommand

# TODO: move this somewhere else?
PATH = CONFIG_DIR / 'sessions'


def format_past_timestamp(time: datetime) -> str:
    """ recent timestamps skip unnecessary information """
    now = datetime.now()
    if time.year == now.year:
        if time.date() == now.date():
            return time.strftime('%H:%M')
        return time.strftime('%b %d %H:%M')
    return time.strftime('%Y-%m-%d %H:%M')


class Session:
    def __init__(self, identifier: str, metadata: dict, tool_id: str):
        self.identifier = identifier
        self.metadata = metadata
        self.tool_id = tool_id

    def write(self, state: State):
        with open(PATH / (self.identifier + f'.{self.tool_id}.json'), 'w') as fp:
            fp.write(json.dumps(self.metadata))
        with open(PATH / (self.identifier + f'.{self.tool_id}.dmp'), 'wb') as fp:
            pickle.dump(state, fp)

    def get_state(self) -> State:
        with open(PATH / (self.identifier + f'.{self.tool_id}.dmp'), 'rb') as fp:
            return pickle.load(fp)

    @classmethod
    def from_identifier(cls, identifier: str, tool_id: str):
        with open(PATH / (identifier + f'.{tool_id}.json'), 'r') as fp:
            metadata = json.loads(fp.read())
        return cls(identifier, metadata, tool_id)

    def delete(self):
        (PATH / (self.identifier + f'.{self.tool_id}.json')).unlink()
        (PATH / (self.identifier + f'.{self.tool_id}.dmp')).unlink()


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

    def standard_display(self):
        interface.write_text('Resume an existing session:\n')
        for i, session in enumerate(self.sessions):
            interface.write_command_info(
                str(i),
                '  ' + format_past_timestamp(datetime.fromtimestamp(session.metadata['timestamp'])) + \
                ' – ' + session.metadata['description']
            )

    def execute(self, call: str) -> list[CommandOutcome]:
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

    def execute(self, call: str) -> list[CommandOutcome]:
        return [SessionChoiceOutcome(int(call[1:]), 'delete')]


class DeleteAllSessionsCommand(Command):
    def __init__(self, sessions: list[Session]):
        self.sessions = sessions
        super().__init__(CommandInfo(
            show=True,
            pattern_presentation='D',
            description_short='elete all sessions',
            description_long='Delete all existing sessions')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        return [SessionChoiceOutcome(0, 'delete') for _ in range(len(self.sessions))]


class IgnoreSessions(CommandOutcome):
    pass


class ContinueWithoutSession(Command):
    def __init__(self, sessions: list[Session]):
        self.sessions = sessions
        super().__init__(CommandInfo(
            show=True,
            pattern_presentation='c',
            description_short='ontinue (ignore old sessions)',
            description_long='Continue and do not resume any session')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        return [IgnoreSessions()]


class SessionStorage:
    def __init__(self, tool_id: str):
        self.tool_id = tool_id
        PATH.mkdir(parents=True, exist_ok=True)
        self.sessions: list[Session] = []
        for file in PATH.glob(f'*.{self.tool_id}.json'):
            identifier = str(file.name)[:-len(f'.{self.tool_id}.json')]
            self.sessions.append(Session.from_identifier(identifier, self.tool_id))

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

    def get_session_dialog(self) -> State | QuitOutcome | IgnoreSessions:
        if not self.have_ongoing_session():
            return IgnoreSessions()

        while self.sessions:
            interface.clear()
            interface.write_header('Session management')
            interface.newline()
            interface.write_text('You have multiple existing sessions. What would you like to do?')
            outcomes = CommandCollection(
                name='session management',
                commands=[
                    ContinueWithoutSession(self.sessions),
                    QuitCommand('quit the program'),
                    DeleteSessionCommand(self.sessions),
                    DeleteAllSessionsCommand(self.sessions),
                    PickSessionCommand(self.sessions),
                ],
                have_help=True,
            ).apply()

            for outcome in outcomes:
                if isinstance(outcome, IgnoreSessions):
                    return outcome
                elif isinstance(outcome, QuitOutcome):
                    return outcome
                elif isinstance(outcome, SessionChoiceOutcome):
                    if outcome.action == 'resume':
                        session = self.sessions[outcome.session_number]
                        if session.metadata['srifytimestamp'] < self.srify_timestamp:
                            if not interface.ask_yes_no(
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

        return IgnoreSessions()

    def store_session_dialog(self, state: State):
        interface.write_text('\n\n')
        if not interface.ask_yes_no('Would you like to save the current session?'):
            return
        if self.loaded_session:
            interface.write_text('You are in a session that was loaded from a file.\n')
            interface.write_text('  Description: ' + self.loaded_session.metadata['description'] + '\n')
            interface.write_text('  Timestamp: ' + self.loaded_session.metadata['timestamp'] + '\n')
            if interface.ask_yes_no('Would you like to overwrite this session?'):
                self.loaded_session.write(state)
                return

        interface.write_text('Brief description of the session (optional): ')
        description = interface.get_input() or 'no description'
        session = Session(
            identifier=str(uuid.uuid4()),
            metadata={
                'description': description,
                'timestamp': time.time(),
                'srifytimestamp': self.srify_timestamp,
            },
            tool_id=self.tool_id
        )
        session.write(state)
