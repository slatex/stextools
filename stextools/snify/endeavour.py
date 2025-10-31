"""
There are different types of annotations:
concept references in text, notations in formulae, problem objectives, ...

These need to be handled very differently.
Endeavours were developed to avoid overly convoluted code.

An Endeavour is the attempt to make a new annotation,
e.g. to annotate the word "natural number".
This typically involves a user selecting an annotation target,
but other interactions are also possible (e.g. adjusting the range).

The Endeavour code can therefore be specialized towards a specific type of annotation.

An EndeavourSource suggests the next Endeavour for a particular type of annotation.
In its main loop, snify queries all applicable EndeavourSources to find the next
annotation Endeavour.


Remarks on the state:
The SnifyState has a dictionary to track the state of each endeavour source individually.
Using it is optional.
It should be noted that the state should only be modified via Modification objects.
This is annoying, but ensures that undo/redo works correctly.
"""

from __future__ import annotations

import abc
from typing import Optional

from stextools.snify.snify_state import SnifyState
from stextools.stepper.command import CommandCollection, CommandOutcome
from stextools.stepper.document import Document
from stextools.stepper.stepper import Modification


class EndeavourSource(abc.ABC):
    """
    Note: instantiation should be cheap (will always be instantiated when snify starts, even if they are not used).

    Costly initialization should be deferred until ``get_next_endeavour`` is called the first time.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    @abc.abstractmethod
    def is_applicable(self, document: Document, snify_state: SnifyState) -> bool:
        # Note: Document may be different in snify state cursor
        # snify_state should only be used for general session information (mode, annotation format, ...)
        pass

    @abc.abstractmethod
    def get_next_endeavour(
            self,
            document: Document,   # document and position may be different in state cursor
            position: int,
            snify_state: SnifyState
    ) -> Optional[Endeavour]:
        pass

    def rescan(self):
        """
        Called when some assumptions may be outdated.
        For example, if some sTeX files have been edited and the catalog has to be updated.
        """


class EndOfEndeavour(CommandOutcome):
    pass


class Endeavour(abc.ABC):
    def __init__(self, name: str, document: Document, position: int, snify_state: SnifyState,
                 setup_modifications: list[Modification[SnifyState]]):
        # Important: Both document and position could be wrong in snify_state's cursor
        # That's because at this point the endeavour is just a proposal.
        # That's why document and position are passed explicitly.

        # The setup_modifications are applied to the snify_state to prepare for the endeavour
        # (if the endeavour gets selected).
        # This is done by the stepper.
        # The primary purpose is to update endeavour-specific state in snify_state.

        self.name = name   # name of the endeavour source that created this endeavour
        self.snify_state = snify_state
        self.document = document
        self.position = position
        self.setup_modifications = setup_modifications
        self.post_init()

    def post_init(self):
        """ can be overridden by subclasses to do additional initialization """
        pass

    def show_current_state(self):
        pass

    def get_command_collection(self) -> CommandCollection:
        pass

    def rescan(self):
        """
        Called when some assumptions may be outdated.
        For example, if some sTeX files have been edited and the catalog and annotation candidates have to be updated.
        """
