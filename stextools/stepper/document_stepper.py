import dataclasses
import os
import subprocess
from copy import deepcopy
from typing import Optional, Sequence, Callable

from stextools.config import get_config
from stextools.stepper.command import CommandOutcome, Command, CommandInfo
from stextools.stepper.document import Document, LocalFileDocument
from stextools.stepper.interface import interface
from stextools.stepper.stepper import State, Modification, StateType, Stepper


@dataclasses.dataclass(frozen=True)
class DocumentCursor:
    document_index: int

    def with_document_index(self, new_index: int) -> 'DocumentCursor':
        new_cursor = deepcopy(self)
        object.__setattr__(new_cursor, 'document_index', new_index)
        return new_cursor


class DocumentStepperState(State[DocumentCursor]):
    def __init__(self, cursor: DocumentCursor, documents: list[Document]):
        super().__init__(cursor)
        self.documents = documents

    def get_current_document(self) -> Document:
        if not self.documents:
            raise ValueError("No documents available.")
        return self.documents[self.cursor.document_index]


class DocumentCollectionModification(Modification[DocumentStepperState]):
    def __init__(self, old_documents: list[Document], new_documents: list[Document],
                 old_document_index: int, new_document_index: int):
        self.old_documents = old_documents
        self.new_documents = new_documents
        self.old_document_index = old_document_index
        self.new_document_index = new_document_index

    def apply(self, state: DocumentStepperState):
        state.documents = self.new_documents
        state.cursor = state.cursor.with_document_index(self.new_document_index)

    def unapply(self, state: DocumentStepperState):
        state.documents = self.old_documents
        state.cursor = state.cursor.with_document_index(self.old_document_index)


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


#######################################################################
#   EDIT DOCUMENT
#######################################################################


def get_editor(number: int) -> str:
    if number == 1:
        return get_config().get('stextools.general', 'editor', fallback=os.getenv('EDITOR', 'nano'))
    elif number == 2:
        return get_config().get('stextools.general', f'editor2', fallback=os.getenv('EDITOR', 'nano'))
    else:
        raise ValueError('Invalid editor number')


class EditCommand(Command):
    def __init__(self, number: int, document: LocalFileDocument,
                 outcome_for_first_changed_pos: Optional[Callable[[int], Sequence[CommandOutcome]]] = None):
        self.document = document
        self.outcome_for_first_changed_pos = outcome_for_first_changed_pos
        self.editor = get_editor(number)
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='e' * number,
            pattern_regex='^' + 'e' * number + '$',
            description_short='dit file' + ('' if number == 1 else f' with editor {number}'),
            description_long=f'Edit the current file with {self.editor} (can be changed in the config file)')
        )

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        old_content = self.document.get_content()
        subprocess.Popen([self.editor, str(self.document.path)]).wait()
        new_content = self.document.get_content()
        self.document.on_modified()
        first_change_pos = 0
        while first_change_pos < len(old_content) and first_change_pos < len(new_content) and old_content[first_change_pos] == new_content[first_change_pos]:
            first_change_pos += 1

        if self.outcome_for_first_changed_pos is not None:
            return self.outcome_for_first_changed_pos(first_change_pos)
        return []
