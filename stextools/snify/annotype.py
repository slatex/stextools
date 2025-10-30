"""
There are different types of annotations: concept references in text, notations in formulae, problem objectives, ...
These need to be handled very differently.

The Stepper code becomes too convoluted if it has to deal with all these different types of annotations at once.
The idea of the AnnoType is to have a separate class that provides the functionality for each type of annotation.
Essentially, the stepper delegates functionality to the AnnoType.

A central challenge when implementing an AnnoType is that we need to be able to
undo/redo any modifications.
Furthermore, we need to be able to store an annotation session and restore it later.
The stepper therefore maintains a state that can be pickled/unpickled
as well as a modification history that allows undoing/redoing modifications.

Therefore, AnnoType has to
a) keep all relevant state (i.e. everything that has to be recovered from resuming a session or undoing changes)
   in the stepper state
b) make all changes to that state (or to files for that matter) via Modification objects

This is annoying, but it's the best way I've come up with so far.

Performance remarks:
- Every AnnoType is instantiated when snify starts, even if it is not used.
  Therefore, initialization should and expensive setup should be deferred until the AnnoType is actually used.
"""
import abc
from typing import TypeVar, Generic, Optional

from stextools.snify.new_snify_state import NewSnifyState
from stextools.stepper.command import CommandCollection
from stextools.stepper.document import Document
from stextools.stepper.stepper import Modification

StateType = TypeVar('StateType')


class AnnoType(Generic[StateType], abc.ABC):
    snify_state: NewSnifyState

    def set_snify_state(self, state: NewSnifyState):
        self.snify_state = state

    @property
    def state(self) -> StateType:
        return self.snify_state[self.name]

    # -------------------------------------------------
    # The following can/should be overridden by subclasses
    # -------------------------------------------------

    def get_initial_state(self) -> StateType:
        """Return the initial state for this AnnoType. The stepper will insert it into the snify_state."""
        return None

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The name of the AnnoType (acts as an identifier in various places)"""

    @abc.abstractmethod
    def is_applicable(self, document: Document) -> bool:
        """Whether this AnnoType is applicable to the given document in the current state."""

    @abc.abstractmethod
    def get_next_annotation_suggestion(
            self, document: Document, position: int
    ) -> Optional[tuple[int, list[Modification]]]:
        """
        Looks for the next possible annotation in the given document after the given position.

        Returns (i, m) where i is the position of the next annotation
        and m is a list of modifications needed set up the state for that annotation.
        Returns None if there are no more annotations.
        """

    @abc.abstractmethod
    def show_current_state(self):
        """Show the current state to the user (e.g. print the document fragment and highlight selected segment)."""

    @abc.abstractmethod
    def get_command_collection(self) -> CommandCollection:
        """Return the commands applicable to the current state."""

    def rescan(self):
        """
        Called when some assumptions may be outdated.
        For example, if some sTeX files have been edited and the catalog has to be updated.
        """
