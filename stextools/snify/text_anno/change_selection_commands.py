from stextools.snify.snify_state import SnifyState
from stextools.snify.text_anno.stemming import string_to_stemmed_word_sequence
from stextools.snify.text_anno.text_anno_state import TextAnnoSetSelectionModification, TextAnnoState
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface


class PreviousWordShouldBeIncluded(Command):
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='p',
            description_short='revious token should be included',
            description_long='Extends the selection to include the previous token.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        snify_state = self.snify_state
        state = snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        assert state.selection is not None
        doc = snify_state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_end_ref() <= state.selection[0]:
                    i += 1
                if i == 0:
                    interface.admonition(
                        'Already at beginning of possible selection range.',
                        'error',
                        confirm=True
                    )
                    return []
                return [
                    TextAnnoSetSelectionModification(
                        anno_type_name=self.anno_type_name,
                        old_selection=state.selection,
                        new_selection=(words[i - 1].get_start_ref(), state.selection[1]),
                    )
                ]
                # return [SetCursorOutcome(SnifyCursor(
                #     snify_state.cursor.document_index,
                #     (words[i - 1].get_start_ref(), snify_state.cursor.selection[1]),
                # ))]
        raise RuntimeError('Somehow I did not find the previous word.')


class FirstWordShouldntBeIncluded(Command):
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='P',
            description_short=' exclude first selected token',
            description_long='Opposite of [p]. Excludes the first token from the selection.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        snify_state = self.snify_state
        state = snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        assert state.selection is not None
        doc = snify_state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_end_ref() <= state.selection[0]:
                    i += 1
                new_start = words[i + 1].get_start_ref()
                if new_start >= state.selection[1]:
                    interface.admonition('Selection is getting too small', 'error', confirm=True)
                    return []
                return [
                    TextAnnoSetSelectionModification(
                        anno_type_name=self.anno_type_name,
                        old_selection=state.selection,
                        new_selection=(new_start, state.selection[1]),
                    )
                ]
                # return [SetCursorOutcome(SnifyCursor(
                #     snify_state.cursor.document_index,
                #     (new_start, state.selection[1]),
                # ))]
        raise RuntimeError('I could not find the first word.')


class NextWordShouldBeIncluded(Command):
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='n',
            description_short='ext token should be included',
            description_long='Extends the selection to include the next token.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        snify_state = self.snify_state
        state = snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        assert state.selection is not None
        doc = snify_state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_start_ref() < state.selection[1]:
                    i += 1
                if i == len(words):
                    interface.admonition('Already at end of possible selection range.', 'error', confirm=True)
                    return []
                return [
                    TextAnnoSetSelectionModification(
                        anno_type_name=self.anno_type_name,
                        old_selection=state.selection,
                        new_selection=(state.selection[0], words[i].get_end_ref()),
                    )
                ]
                # return [SetCursorOutcome(SnifyCursor(
                #     snify_state.cursor.document_index,
                #     (state.selection[0], words[i].get_end_ref()),
                # ))]
        raise RuntimeError('Somehow I did not find the next word.')


class LastWordShouldntBeIncluded(Command):
    def __init__(self, snify_state: SnifyState, anno_type_name: str):
        self.snify_state = snify_state
        self.anno_type_name = anno_type_name
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='N',
            description_short=' exclude last selected token',
            description_long='Opposite of [n]. Excludes the last token from the selection.')
        )

    def execute(self, call: str) -> list[CommandOutcome]:
        snify_state = self.snify_state
        state = snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        assert state.selection is not None
        doc = snify_state.get_current_document()
        for lstr in doc.get_annotatable_plaintext():
            if lstr.get_end_ref() >= state.selection[0]:
                words = string_to_stemmed_word_sequence(lstr, doc.language)
                i = 0
                while i < len(words) and words[i].get_start_ref() < state.selection[1]:
                    i += 1
                new_end = words[i - 2].get_end_ref()
                if new_end <= state.selection[0]:
                    interface.admonition('Selection is getting too small', 'error', confirm=True)
                    return []
                return [
                    TextAnnoSetSelectionModification(
                        anno_type_name=self.anno_type_name,
                        old_selection=state.selection,
                        new_selection=(state.selection[0], new_end),
                    )
                ]
                # return [SetCursorOutcome(SnifyCursor(
                #     snify_state.cursor.document_index,
                #     (state.selection[0], new_end),
                # ))]
        raise RuntimeError('I could not find the last word.')
