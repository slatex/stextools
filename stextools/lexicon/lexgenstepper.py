import functools
import os
from pathlib import Path

from stextools.lexicon.lexgen_commands import SkipCommand
from stextools.lexicon.lexgenstate import LexGenState
from stextools.lexicon.ud import sentence_tokenize, word_tokenize, get_word_info
from stextools.lexicon.wordlex import WordLex
from stextools.snify.snifystate import SnifyCursor
from stextools.stepper.command import CommandCollection
from stextools.stepper.document import STeXDocument
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Stepper, StopStepper
from stextools.stepper.stepper_extensions import QuittableStepper, CursorModifyingStepper, UndoableStepper
from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import OpenedStexFLAMSFile
from stextools.utils.json_iter import json_iter

UPOS_TO_GF_CAT: dict[str, str] = {
    'ADJ': 'A',
    'ADP': 'Prep',
    'ADV': 'Adv',
    'AUX': '',
    'CCONJ': 'Conj',
    'DET': 'Det',
    'INTJ': '',
    'NOUN': 'N',
    'NUM': '',
    'PART': '',
    'PRON': 'Pron',
    'PROPN': 'PN',
    'PUNCT': 'Punct',
    'SCONJ': 'Conj',  # is it?
    'SYM': 'Symb',
    'VERB': 'V',
    'X': '',
}


@functools.cache
def get_wordlex(lang: str, archive: str):
    parts = archive.split('/')
    cc = ''.join(
        part[0].upper() + part[1:] if part else ''
        for part in parts
    )
    directory = Path(os.environ['MATHHUB']) / archive / 'source'
    return WordLex.load(
        cc,
        directory,
        lang,
        create_if_nonexistent=True,
    )


class LexGenStepper(QuittableStepper, CursorModifyingStepper, UndoableStepper, Stepper[LexGenState]):
    def ensure_state_up_to_date(self):
        cursor = self.state.cursor
        if not isinstance(cursor.selection, int):
            return   # already have a selection

        while cursor.document_index < len(self.state.documents):
            doc = self.state.get_current_document()
            assert isinstance(doc, STeXDocument), 'currently only STeXDocuments are supported'
            opened_file = OpenedStexFLAMSFile(str(doc.path))

            annos = FLAMS.get_file_annotations(doc.path)
            for item in json_iter(annos):
                if not isinstance(item, dict):
                    continue
                if 'SymName' not in item:
                    continue
                item = item['SymName']
                symbol = item['uri'][0]['uri']
                a, b = opened_file.flams_range_to_offsets(item['full_range'])
                if not any(x in doc.get_content()[a:b] for x in ['definame', 'definiendum', 'Definame']):
                    continue   # not a definiendum
                if a < cursor.selection:
                    continue

                cursor = SnifyCursor(cursor.document_index, (a, b))
                self.state.cursor = cursor
                return

            cursor = SnifyCursor(
                document_index=cursor.document_index + 1,
                selection=0
            )

        interface.clear()
        interface.write_text('There is nothing left to annotate.\n')
        interface.write_text('Quitting.\n')
        interface.await_confirmation()
        raise StopStepper('done')


    def show_current_state(self):
        doc = self.state.get_current_document()
        interface.clear()
        interface.write_header(
            doc.identifier
        )
        interface.show_code(
            doc.get_content(),
            doc.format,  # type: ignore
            highlight_range=self.state.cursor.selection if isinstance(self.state.cursor.selection, tuple) else None,
            limit_range=5,
        )
        interface.newline()

    def get_current_command_collection(self) -> CommandCollection:
        error_cmds = CommandCollection(
            'lexgen (error)',
            [
                SkipCommand(self.state)
            ]
        )
        doc = self.state.get_current_document()
        plaintext = doc.get_plaintext_approximation()
        sentence_offsets = sentence_tokenize(str(plaintext), doc.language)
        relevant_sentence_ranges = [
            (start, end)
            for start, end in sentence_offsets
            if plaintext[start].get_start_ref() <= self.state.cursor.selection[0] < plaintext[end].get_end_ref()
        ]

        a, b = plaintext.get_indices_from_ref_range(*self.state.cursor.selection)
        if not relevant_sentence_ranges:
            interface.write_text('No valid sentence range found for the current selection.\n')
            return error_cmds

        sentence = plaintext[relevant_sentence_ranges[0][0]:relevant_sentence_ranges[0][1]]
        # word_offsets = word_tokenize(str(plaintext), doc.language)
        for word_start, word_end in word_tokenize(str(sentence), doc.language):
            if sentence[word_end].get_end_ref() <= self.state.cursor.selection[0]:
                continue
            if sentence[word_start].get_start_ref() >= self.state.cursor.selection[1]:
                continue

            lemma, upos, feats = get_word_info(str(sentence), word_start, word_end, doc.language)

            fun = lemma + '_' + UPOS_TO_GF_CAT[upos]

            # TODO: this can be improved using FLAMS
            parts = str(doc.path.relative_to(os.environ['MATHHUB'])).split('/')  # type: ignore
            archivename = '/'.join(parts[:parts.index('source')])
            wordlex = get_wordlex(doc.language, archivename)  # type: ignore

            if fun not in wordlex.words:
                interface.write_text(f'No word found for {fun} in {archivename}.\n')
                return CommandCollection(
                    'lexgen',
                    [
                        SkipCommand(self.state)
                    ]
                )

        return error_cmds