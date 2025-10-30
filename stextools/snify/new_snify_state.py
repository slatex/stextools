import dataclasses
from typing import Any, Optional

from stextools.stepper.document import Document
from stextools.stepper.document_stepper import DocumentCursor, DocumentStepperState
from stextools.stepper.stepper import State
from stextools.stepper.stepper_extensions import FocussableState


@dataclasses.dataclass(frozen=True)
class NewSnifyCursor(DocumentCursor):
    in_doc_pos: int
    # set of anno types that should not be suggested for this specific cursor position anymore
    banned_annotypes: set[str] = dataclasses.field(default_factory=set)


class NewSnifyState(DocumentStepperState, FocussableState, State[NewSnifyCursor]):
    """
    This state should hold all relevant information for snify.
    It can be stored (pickled) and restored to continue an annotation session.

    Before a session is stored, changes of an unfinished endeavour are rolled back.
    """
    def __init__(self, cursor: NewSnifyCursor, documents: list[Document], anno_types: list[str]):
        super().__init__(cursor, documents)

        self.mode: set[str] = set()         # what should be annotated (text/formulae/...)
        # list of anno types that can generally be used
        self.anno_types: list[str] = anno_types
        # states for individual anno types (by anno type name)
        self.annotype_states: dict[str, Any] = {}

        self.ongoing_annotype: Optional[str] = None  # which anno type is currently being annotated

    def __getitem__(self, key: str) -> Any:
        return self.annotype_states.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.annotype_states[key] = value

    def __contains__(self, item):
        return item in self.annotype_states
