from copy import deepcopy
from pathlib import Path
from typing import Sequence, Any, Optional

from stextools.snify.snify_state import SnifyState
from stextools.snify.stex_dependency_addition import get_modules_in_scope_and_import_locations
from stextools.snify.text_anno.catalog import Verbalization
from stextools.snify.text_anno.local_stex_catalog import LocalStexSymbol, LocalStexVerbalization
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.document import STeXDocument
from stextools.stepper.interface import interface
from stextools.stex.local_stex import FlamsUri, get_module_import_sequence


class Explain_i_Command(Command):
    def __init__(self, candidates: list[tuple[Any, Verbalization]], snify_state: SnifyState):
        super().__init__(CommandInfo(
            show=False,
            pattern_presentation='x𝑖',
            pattern_regex='^x[0-9]+$',
            description_short=' explain candidate symbol 𝑖',
            description_long='Displays additional information about candidate symbol no. 𝑖; in particular, why it was suggested.'
        ))
        self.candidates = candidates
        self.snify_state = snify_state

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        i = int(call[1:])
        if i >= len(self.candidates):
            interface.admonition('Invalid number', 'error', True)
            return []

        symbol, verbalization = self.candidates[i]

        with interface.big_infopage():
            interface.write_header(f'Explanation for symbol {i}: {symbol.uri if hasattr(symbol, "uri") else repr(symbol)}')
            if isinstance(symbol, LocalStexSymbol):
                interface.write_text(f'Path: {symbol.path}\n')
                interface.write_text(f'Reference count: {symbol.srefcount}\n\n')
            interface.write_text('Suggested because of verbalization:\n')
            if isinstance(verbalization, LocalStexVerbalization):
                interface.write_text(verbalization.local_path + ':\n')
                interface.show_code(
                    Path(verbalization.local_path).read_text(),
                    highlight_range=verbalization.path_range,
                    format='sTeX',
                    limit_range=2,
                )
                interface.newline()

            document = self.snify_state.get_current_document()
            if isinstance(document, STeXDocument):
                importinfo = get_modules_in_scope_and_import_locations(document, self.snify_state.cursor.in_doc_pos)

                symbol = FlamsUri(symbol.uri)
                structure: Optional[FlamsUri] = None
                if '/' in symbol.module:  # TODO: better way to identify structures
                    structure = deepcopy(symbol)
                    structure.module, _, structure.symbol = symbol.module.rpartition('/')
                module: FlamsUri = deepcopy(structure or symbol)
                module.symbol = ''

                is_imported: bool = False
                if structure is not None:
                    if str(structure) in importinfo.structs_in_scope:
                        is_imported = True
                elif str(module) in importinfo.modules_in_scope:
                    is_imported = True

                if is_imported:
                    interface.write_text('The symbol is already imported in the current document via the sequence:\n')
                    if structure:
                        interface.write_text(f'structure: {str(structure)}\n')
                    import_sequence = get_module_import_sequence(
                        importinfo.modules_directly_imported,
                        str(module)
                    )
                    for uri, _ in import_sequence:
                        interface.write_text(f'module: {uri}\n')

            interface.newline()


        return []

