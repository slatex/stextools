import dataclasses
import functools
import math
from copy import deepcopy
from typing import Any, Callable

from sympy import substitution

from stextools.snify.snify_state import SnifyState, SnifyCursor, SetOngoingAnnoTypeModification
from stextools.snify.stex_dependency_addition import AnnotationAborted, get_modules_in_scope_and_import_locations, \
    get_import
from stextools.snify.text_anno.catalog import Verbalization
from stextools.snify.text_anno.text_anno_state import TextAnnoState
from stextools.stepper.document import STeXDocument, LocalFtmlDocument
from stextools.stex.local_stex import FlamsUri
from stextools.snify.text_anno.local_stex_catalog import LocalStexSymbol, LocalFlamsCatalog
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.stepper.command import Command, CommandInfo, CommandOutcome
from stextools.stepper.interface import interface
from stextools.stepper.stepper_extensions import SetCursorOutcome


class AnnotationCandidates:
    pass


@dataclasses.dataclass(frozen=True)
class TextAnnotationCandidates(AnnotationCandidates):
    candidates: list[tuple[Any, Verbalization]]


@dataclasses.dataclass(frozen=True)
class MathAnnotationCandidates(AnnotationCandidates):
    candidates: list[Any]


class STeXAnnotateBase(Command):
    def __init__(
            self,
            snify_state: SnifyState,
            catalog: LocalFlamsCatalog,
            show_state_fun: Callable[[], None],
            anno_type_name: str,
    ):
        self.snify_state = snify_state
        self.catalog = catalog
        self.show_state_fun = show_state_fun
        self.anno_type_name = anno_type_name
        document = snify_state.get_current_document()
        assert isinstance(document, STeXDocument) or isinstance(document, LocalFtmlDocument)
        self.document: STeXDocument = document

    @property
    @functools.cache
    def importinfo(self):
        if not isinstance(self.document, STeXDocument):
            raise RuntimeError('Import info is only available for STeX documents')
        return get_modules_in_scope_and_import_locations(self.document, self.state.selection[0])

    @property
    def state(self) -> TextAnnoState:
        state = self.snify_state[self.anno_type_name]
        assert isinstance(state, TextAnnoState)
        return state

    def annotate_symbol(self, symbol: LocalStexSymbol) -> list[CommandOutcome]:
        if isinstance(self.document, STeXDocument):
            return self.annotate_symbol_tex(symbol)
        elif isinstance(self.document, LocalFtmlDocument):
            return self.annotate_symbol_html(symbol)
        else:
            raise RuntimeError(f'Annotation not supported for document type {type(self.document)}')

    def annotate_symbol_html(self, symbol: LocalStexSymbol) -> list[CommandOutcome]:
        substitution = SubstitutionOutcome(
            f'<span data-ftml-term="OMID" data-ftml-head="{symbol.uri}" data-ftml-notationid="">'
            f'<span class="ftml-comp" data-ftml-comp="">{self.state.get_selected_text(self.snify_state)}</span></span>',
            self.state.selection[0],
            self.state.selection[1]
        )
        c = self.snify_state.cursor
        offset = len(substitution.new_str) - (substitution.end_pos - substitution.start_pos)
        new_cursor = SnifyCursor(
            document_index=c.document_index,
            banned_annotypes=c.banned_annotypes | {self.snify_state.ongoing_annotype},
            in_doc_pos=c.in_doc_pos + offset,
        )
        return [
            substitution,
            SetOngoingAnnoTypeModification(self.snify_state.ongoing_annotype, None),
            SetCursorOutcome(new_cursor=new_cursor),
        ]

    def annotate_symbol_tex(self, symbol: LocalStexSymbol) -> list[CommandOutcome]:
        state = self.state
        outcomes: list[Any] = []

        try:
            # import_thing = self.get_import(symbol)
            import_thing = get_import(
                self.document,
                self.importinfo,
                symbol,
                self.show_state_fun,
            )
        except AnnotationAborted:
            return []

        if import_thing:
            outcomes.extend(import_thing)

        sr = self.get_sr(symbol.uri)
        outcomes.append(
            SubstitutionOutcome(sr, state.selection[0], state.selection[1])
        )

        # at this point, we only have substitutions
        # -> sort them and update the offsets
        # TODO: maybe the controller should be responsible for this
        offset = 0
        outcomes.sort(key=lambda o: o.start_pos if isinstance(o, SubstitutionOutcome) else math.inf)
        for o in outcomes:
            if isinstance(o, SubstitutionOutcome):
                o.start_pos += offset
                o.end_pos += offset
                offset += len(o.new_str) - (o.end_pos - o.start_pos)

        # outcomes.append(StatisticUpdateOutcome('annotation_inc'))
        # outcomes.append(SetCursorOutcome(SnifyCursor(cursor.document_index, cursor.selection[0] + offset)))

        c = self.snify_state.cursor
        new_cursor = SnifyCursor(
            document_index=c.document_index,
            banned_annotypes=c.banned_annotypes | {self.snify_state.ongoing_annotype},
            in_doc_pos=c.in_doc_pos + offset,
        )
        outcomes.extend([
            SetOngoingAnnoTypeModification(self.snify_state.ongoing_annotype, None),
            SetCursorOutcome(new_cursor=new_cursor),
        ])

        return outcomes


    def _symbname_unique(self, symbol: FlamsUri) -> bool:
        for s in self.catalog.symb_iter():
            if FlamsUri(s.uri).symbol == symbol.symbol:
                if str(FlamsUri(s.uri)) != str(symbol):
                    # Note: A policy variation would be to additionally check if the symbol was imported
                    return False
        return True

    def get_sr(self, symbol_uri: str) -> str:
        symbol = FlamsUri(symbol_uri)
        # check if symbol is uniquely identified by its name
        word = self.state.get_selected_text(self.snify_state)
        if word is None:
            raise RuntimeError('No text selected for annotation')

        symb_name = symbol.symbol
        if self._symbname_unique(symbol):
            symb_path = symb_name
        else:
            symb_path = symbol.module + '?' + symb_name

        if word == symb_name:
            return '\\sn{' + symb_path + '}'
        elif word == symb_name + 's':
            return '\\sns{' + symb_path + '}'
        elif word[0] == symb_name[0].upper() and word[1:] == symb_name[1:]:
            return '\\Sn{' + symb_path + '}'
        elif word[0] == symb_name[0].upper() and word[1:] == symb_name[1:] + 's':
            return '\\Sns{' + symb_path + '}'
        elif word.startswith(symb_name) and ' ' not in word[len(symb_name):]:
            return f'\\sn[post={word[len(symb_name):]}]{{' + symb_path + '}'
        elif word.endswith(symb_name) and ' ' not in word[:-len(symb_name)]:
            return f'\\sn[pre={word[:-len(symb_name)]}]{{' + symb_path + '}'
        else:
            return '\\sr{' + symb_path + '}' + '{' + word + '}'




class STeXAnnotateCommand(STeXAnnotateBase, Command):
    def __init__(
            self,
            snify_state: SnifyState,
            options: TextAnnotationCandidates,
            catalog: LocalFlamsCatalog,
            show_state_fun: Callable[[], None],
            anno_type_name: str,
    ):
        self.options = options.candidates
        STeXAnnotateBase.__init__(self, snify_state, catalog, show_state_fun, anno_type_name)
        Command.__init__(
            self,
            CommandInfo(
                pattern_presentation='𝑖',
                pattern_regex='^[0-9]+$',
                description_short=' annotate with 𝑖',
                description_long='Annotates the current selection with option number 𝑖'
            )
        )

    def standard_display(self):
        style = interface.apply_style
        for i, (symbol, verbalization) in enumerate(self.options):
            assert isinstance(symbol, LocalStexSymbol)
            symbol_display = ' '
            if isinstance(self.document, STeXDocument):
                module_uri_f = FlamsUri(symbol.uri)
                if '/' in module_uri_f.module:  # TODO: better way to identify structures
                    structure = deepcopy(module_uri_f)
                    structure.module, _, structure.symbol = module_uri_f.module.rpartition('/')
                    is_available = str(structure) in self.importinfo.structs_in_scope
                else:
                    module_uri_f.symbol = None
                    is_available = str(module_uri_f) in self.importinfo.modules_in_scope
                symbol_display += (
                    style('✓', 'correct-weak') if is_available else style('✗', 'error-weak')
                )
            uri = FlamsUri(symbol.uri)
            symbol_display += ' ' + stex_symbol_style(uri)

            interface.write_command_info(
                str(i),
                symbol_display
            )


    def execute(self, call: str) -> list[CommandOutcome]:
        if int(call) >= len(self.options):
            interface.write_text('Invalid annotation number', style='error')
            interface.await_confirmation()
            return []

        symbol, _ = self.options[int(call)]
        return self.annotate_symbol(symbol)


def stex_symbol_style(uri: FlamsUri) -> str:
    style = interface.apply_style
    return (
        style(uri.archive, 'highlight1') +
        ' ' + uri.path + '?' +
        style(uri.module, 'highlight2') +
        '?' + style(uri.symbol, 'highlight3')
    )


class STeXLookupCommand(STeXAnnotateBase, Command):
    def __init__(
                self,
                snify_state: SnifyState,
                catalog: LocalFlamsCatalog,
                show_state_fun: Callable[[], None],
                anno_type_name: str,
        ):
            STeXAnnotateBase.__init__(self, snify_state, catalog, show_state_fun, anno_type_name)

            Command.__init__(self, CommandInfo(
                show=False,
                pattern_presentation='l',
                description_short='ookup a symbol',
                description_long='Look up a symbol for annotation'
            ))
            self.snify_state = snify_state

    def execute(self, call: str) -> list[CommandOutcome]:
        cursor = self.snify_state.cursor
        # filter_fun = make_filter_fun(snify_state.filter_pattern, snify_state.ignore_pattern)

        symbol = interface.list_search(
            {
                stex_symbol_style(FlamsUri(symbol.uri)) : symbol
                for symbol in self.catalog.symb_iter()
            }
        )

        return self.annotate_symbol(symbol) if symbol else []
