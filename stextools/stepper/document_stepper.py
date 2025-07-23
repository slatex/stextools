import dataclasses
from typing import Optional

from stextools.stepper.command import CommandOutcome
from stextools.stepper.document import Document
from stextools.stepper.interface import interface
from stextools.stepper.stepper import State, Modification, StateType, Stepper


@dataclasses.dataclass(frozen=True)
class DocumentCursor:
    document_index: int


class DocumentStepperState(State[DocumentCursor]):
    def __init__(self, cursor: DocumentCursor, documents: list[Document]):
        super().__init__(cursor)
        self.documents = documents

    def get_current_document(self) -> Document:
        if not self.documents:
            raise ValueError("No documents available.")
        return self.documents[self.cursor.document_index]


#######################################################################
#   MODIFY DOCUMENT
#######################################################################

class SubstitutionOutcome(CommandOutcome):
    """Note: command is responsible for ensuring that the index is correct *after* the previous file modification outcomes."""
    def __init__(self, new_str: str, start_pos: int, end_pos: int):
        self.new_str = new_str
        self.start_pos = start_pos
        self.end_pos = end_pos


class TextRewriteOutcome(CommandOutcome):
    def __init__(self, new_text: str):
        self.new_text = new_text


class DocumentModification(Modification):
    def __init__(self, document: Document, old_text: str, new_text: str):
        self.document = document
        self.old_text = old_text
        self.new_text = new_text

    def apply(self, state: StateType):
        current_text = self.document.get_content()
        if current_text != self.old_text:
            interface.write_text(
                (f"\n{self.document.identifier} has been modified since the last time it was read.\n"
                 f"I will not change the file\n"),
                style='warning'
            )
            interface.await_confirmation()
            return

        self.document.set_content(self.new_text)

    def unapply(self, state: StateType):
        current_text = self.document.get_content()
        if current_text != self.new_text:
            interface.write_text(
                (f"\n{self.document.identifier} has been modified since the last time it was written to.\n"
                 f"I will not change the file\n"),
                style='warning'
            )
            interface.await_confirmation()
            return
        self.document.set_content(self.old_text)


class DocumentModifyingStepper(Stepper[DocumentStepperState]):
    def handle_command_outcome(self, outcome: CommandOutcome) -> Optional[Modification]:
        doc = self.state.get_current_document()

        if isinstance(outcome, SubstitutionOutcome):
            return DocumentModification(
                doc,
                old_text=doc.get_content(),
                new_text=doc.get_content()[:outcome.start_pos] + outcome.new_str + doc.get_content()[outcome.end_pos:]
            )
        elif isinstance(outcome, TextRewriteOutcome):
            return DocumentModification(
                doc,
                old_text=doc.get_content(),
                new_text=outcome.new_text
            )

        return super().handle_command_outcome(outcome)


