import dataclasses
from pathlib import Path
from typing import Optional, override

from pylatexenc.latexwalker import LatexMathNode, LatexCommentNode, LatexSpecialsNode, LatexMacroNode, \
    LatexEnvironmentNode, LatexGroupNode, LatexCharsNode, LatexWalker

from stextools.core.linker import Linker
from stextools.core.macros import STEX_CONTEXT_DB
from stextools.core.simple_api import get_symbols, SimpleSymbol
from stextools.snify.annotate_command import AnnotateMixin, symbol_display
from stextools.snify.skip_and_ignore import SkipOnceCommand
from stextools.stepper.base_controller import BaseController
from stextools.stepper.command_outcome import CommandOutcome, Exit
from stextools.stepper.commands import CommandCollection, QuitProgramCommand, ExitFileCommand, UndoCommand, RedoCommand, \
    RescanCommand, ViewCommand, EditCommand, Command, CommandInfo
from stextools.stepper.session_storage import SessionStorage, IgnoreSessions
from stextools.stepper.state import State, SelectionCursor, PositionCursor
from stextools.utils.fzf import get_symbol_from_fzf


@dataclasses.dataclass
class DefiAnnoState(State[None]):
    # macros of potential interest
    macros: set[str] = dataclasses.field(default_factory=lambda: {'emph', 'textbf', 'textit'})
    # environments of interest (if None, all macro occurrences are considered)
    environments: Optional[set[str]] = None


class DefiAnnotateCommand(Command, AnnotateMixin):
    """ This is a bit of a hack to re-use the AnnotateMixin from snify """
    def __init__(self, linker: Linker, state: State):
        Command.__init__(self, CommandInfo(
            show=True,
            pattern_presentation='a',
            pattern_regex='^a$',
            description_short='nnotate definiendum',
            description_long='Look up a symbol for the current definiendum'
        ))
        AnnotateMixin.__init__(self, state, linker, import_policy='prefer_import_warn_use')

    def execute(self, *, state: State, call: str) -> list[CommandOutcome]:
        file = state.get_current_file_simple_api(self.linker)
        cursor = state.cursor
        assert isinstance(cursor, SelectionCursor)

        symbol = get_symbol_from_fzf(
            [symbol for symbol in get_symbols(self.linker)],
            lambda s: symbol_display(file, s, state, style=False)
        )

        return self.get_outcome_for_symbol(symbol) if symbol else []

    @override
    def get_sr(self, symbol: SimpleSymbol) -> str:
        source = self.state.get_selected_text()
        walker = LatexWalker(source, latex_context=STEX_CONTEXT_DB)
        node = walker.get_latex_nodes()[0][0]
        assert isinstance(node, LatexMacroNode)
        verbalization = node.nodeargd.argnlist[-1].latex_verbatim()

        if self._symbol_is_unique(symbol):
            symb_path = symbol.name
        else:
            symb_path = symbol.path_rel_to_archive

        return f'\\definiendum{{{symb_path}}}{verbalization}'


class DefiAnnoController(BaseController):
    def get_current_command_collection(self) -> CommandCollection:
        return CommandCollection(
            name='snify standard commands',
            commands=[
                QuitProgramCommand(),
                ExitFileCommand(),
                UndoCommand(is_possible=bool(self._modification_history)),
                RedoCommand(is_possible=bool(self._modification_future)),
                RescanCommand(),
                DefiAnnotateCommand(self.linker, self.state),
                SkipOnceCommand(),
                ViewCommand(),
                EditCommand(1),
                EditCommand(2),
            ],
            have_help=True
        )

    def find_next_selection(self) -> Optional[SelectionCursor]:
        assert isinstance(self.state.cursor, PositionCursor)
        cursor: PositionCursor = self.state.cursor
        assert isinstance(self.state, DefiAnnoState)
        macros = self.state.macros
        environments = self.state.environments

        while cursor.file_index < len(self.state.files):
            latex_text = self.state.get_current_file_text()

            def _recurse(nodes, in_definition_environment: bool):
                for node in nodes:
                    if node is None or node.nodeType() in {LatexMathNode, LatexCommentNode, LatexSpecialsNode, LatexCharsNode}:
                        continue
                    if node.pos + node.len < cursor.offset:
                        continue
                    if node.nodeType() == LatexMacroNode:
                        if node.macroname in macros and in_definition_environment and node.pos >= cursor.offset:
                            return SelectionCursor(file_index=cursor.file_index, selection_start=node.pos, selection_end=node.pos + node.len)
                        _recurse(node.nodeargd.argnlist, in_definition_environment)
                    elif node.nodeType() == LatexEnvironmentNode:
                        _recurse(node.nodelist, in_definition_environment or node.envname in environments)  # type: ignore
                    elif node.nodeType() == LatexGroupNode:
                        _recurse(node.nodelist, in_definition_environment)
                    else:
                        raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

            walker = LatexWalker(latex_text, latex_context=STEX_CONTEXT_DB)
            result = _recurse(walker.get_latex_nodes()[0], False or environments is None)
            if result is not None:
                return result

            cursor = PositionCursor(cursor.file_index + 1, offset=0)
            self.state.cursor = cursor

        return None


def defianno(files: list[str], macros: Optional[set[str]] = None, environments: Optional[set[str]] = None):
    session_storage = SessionStorage('defianno')
    result = session_storage.get_session_dialog()
    if isinstance(result, Exit):
        return
    if isinstance(result, IgnoreSessions):
        state = DefiAnnoState(files=[], cursor=PositionCursor(file_index=0, offset=0),
                              environments=environments, **({} if macros is None else {'macros': macros}))
        paths: list[Path] = []
        for file in files:
            path = Path(file).absolute().resolve()
            if path.is_dir():
                paths.extend(path.rglob('*.tex'))
            else:
                paths.append(path)
        controller = DefiAnnoController(state, paths)
    else:
        assert isinstance(result, DefiAnnoState)
        state = result
        controller = DefiAnnoController(state, [])
    unfinished = controller.run()
    if unfinished:
        session_storage.store_session_dialog(state)
    else:
        session_storage.delete_session_if_loaded()
