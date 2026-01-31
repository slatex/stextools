from pathlib import Path
from typing import Optional

from click.exceptions import Exit

from stextools.snify.snify_stepper import SnifyStepper
from stextools.snify.snify_state import SnifyState, SnifyCursor
from stextools.stepper.document import documents_from_paths
from stextools.stepper.session_storage import SessionStorage, IgnoreSessions

import logging
logger = logging.getLogger(__name__)

def snify(
        files: list[Path],
        anno_format: str = 'stex',
        mode: str = 'text',  # 'text', 'math', 'both'
        deep: bool = False,
):
    if anno_format not in {'stex', 'wikidata'}:
        raise ValueError(f"Unknown annotation format: {anno_format}")

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
                in_doc_pos=0,
            ),
            documents=documents_from_paths(
                files,
                annotation_format=anno_format,
                include_dependencies=deep,
            ),
            anno_types=['text-anno-stex', 'formula-anno-stex', 'text-anno-wikidata', 'objective-anno'],
            deep_mode=deep,
        )
        assert mode in {'text', 'math', 'both'}
        if mode == 'both':
            state.mode = {'text', 'math'}
        else:
            state.mode = {mode}

        state.mode |= {'objectives'}  # TODO: this should be configurable (maybe via "+" suffix for mode?)

    stepper = SnifyStepper(state)

    try:
        stop_reason = stepper.run()
    except Exception as exc:
        try:
            doc = stepper.state.get_current_document()
            logger.exception(f'Unexpected error while processing {doc.identifier}')
        except ValueError:
            pass
        raise exc

    if stop_reason == 'quit':
        session_storage.store_session_dialog(state)
    else:
        session_storage.delete_session_if_loaded()
