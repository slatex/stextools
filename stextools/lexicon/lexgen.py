from pathlib import Path
from typing import Optional

from click.exceptions import Exit

from stextools.lexicon.lexgenstepper import LexGenState, LexGenStepper
from stextools.snify.snifystate import SnifyCursor
from stextools.stepper.document import documents_from_paths
from stextools.stepper.session_storage import SessionStorage, IgnoreSessions


def lexgen(files: list[Path]):
    session_storage = SessionStorage('lexgen')
    result = session_storage.get_session_dialog()
    if isinstance(result, Exit):
        return
    assert isinstance(result, LexGenState) or isinstance(result, IgnoreSessions)
    state: Optional[LexGenState] = result if isinstance(result, LexGenState) else None

    if state is None:
        state = LexGenState(
            SnifyCursor(
                document_index=0,
                selection=0,
            ),
            documents=documents_from_paths(files)
        )

    stepper = LexGenStepper(state)

    stop_reason = stepper.run()

    if stop_reason == 'quit':
        session_storage.store_session_dialog(state)
    else:
        session_storage.delete_session_if_loaded()
