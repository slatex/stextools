from stextools.snify.snifystate import SnifyCursor
from stextools.stepper.document_stepper import DocumentStepperState
from stextools.stepper.stepper import State


class LexGenState(DocumentStepperState, State[SnifyCursor]):
    pass
