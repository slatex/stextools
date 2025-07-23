from pathlib import Path
from typing import Optional

from click.exceptions import Exit

from stextools.stepper.document import documents_from_paths
from stextools.snify.snifystate import SnifyState, SnifyCursor
from stextools.snify.snifystepper import SnifyStepper
from stextools.stepper.session_storage import SessionStorage, IgnoreSessions


def snify(files: list[Path]):
    session_storage = SessionStorage('snify2')
    result = session_storage.get_session_dialog()
    if isinstance(result, Exit):
        return
    assert isinstance(result, SnifyState) or isinstance(result, IgnoreSessions)
    state: Optional[SnifyState] = result if isinstance(result, SnifyState) else None

    if state is None:
        state = SnifyState(
            SnifyCursor(
                document_index=0,
                selection=0,
            ),
            documents=documents_from_paths(files)
        )

    stepper = SnifyStepper(state)

    stop_reason = stepper.run()

    if stop_reason == 'quit':
        session_storage.store_session_dialog(state)
    else:
        session_storage.delete_session_if_loaded()
