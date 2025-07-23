import dataclasses
from copy import deepcopy
from typing import Optional, Literal, Iterable, Sequence, Any

from pylatexenc.latexwalker import LatexEnvironmentNode

from stextools.snify.catalog import Verbalization
from stextools.stepper.document import STeXDocument
from stextools.stex.local_stex import OpenedStexFLAMSFile, get_transitive_imports, FlamsUri, get_transitive_structs
from stextools.snify.local_stex_catalog import LocalStexSymbol, LocalFlamsCatalog
from stextools.snify.snify_commands import ImportCommand
from stextools.stepper.document_stepper import SubstitutionOutcome
from stextools.snify.snifystate import SnifyState, SnifyCursor
from stextools.stex.stex_py_parsing import iterate_latex_nodes
from stextools.stepper.command import Command, CommandInfo, CommandOutcome, CommandCollection
from stextools.stepper.interface import interface
from stextools.stepper.stepper_extensions import QuitCommand, QuitOutcome, SetCursorOutcome
from stextools.stex.flams import FLAMS
from stextools.utils.json_iter import json_iter


class AnnotationAborted(Exception):
    pass


class STeXAnnotateBase(Command):
    def __init__(
            self,
            state: SnifyState,
            catalog: LocalFlamsCatalog,
            stepper,
    ):
        self.state = state
        self.catalog = catalog
        self.stepper = stepper
        document = state.get_current_document()
        assert isinstance(document, STeXDocument)
        self.document: STeXDocument = document
        self.importinfo = get_modules_in_scope_and_import_locations(
            self.document,
            state.cursor.selection[0] if isinstance(state.cursor.selection, tuple) else state.cursor.selection,
        )

    def annotate_symbol(self, symbol: LocalStexSymbol) -> list[CommandOutcome]:
        cursor = self.state.cursor
        outcomes: list[Any] = []

        try:
            import_thing = self.get_import(symbol)
        except AnnotationAborted:
            return []

        if import_thing:
            outcomes.extend(import_thing)

        sr = self.get_sr(symbol.uri)
        outcomes.append(
            SubstitutionOutcome(sr, cursor.selection[0], cursor.selection[1])
        )

        # at this point, we only have substitutions
        # -> sort them and update the offsets
        # TODO: maybe the controller should be responsible for this
        offset = 0
        outcomes.sort(key=lambda o: o.start_pos)
        for o in outcomes:
            o.start_pos += offset
            o.end_pos += offset
            offset += len(o.new_str) - (o.end_pos - o.start_pos)

        # outcomes.append(StatisticUpdateOutcome('annotation_inc'))
        outcomes.append(SetCursorOutcome(SnifyCursor(cursor.document_index, cursor.selection[0] + offset)))

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
        word = self.state.get_selected_text()
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

    def get_import(self, symb: LocalStexSymbol) -> Sequence[CommandOutcome]:
        ii = self.importinfo

        # Step 1: determine structure and module
        symbol = FlamsUri(symb.uri)
        structure: Optional[FlamsUri] = None
        if '/' in symbol.module:      # TODO: better way to identify structures
            structure = deepcopy(symbol)
            structure.module, _, structure.symbol = symbol.path.rpartition('/')
        module: FlamsUri = deepcopy(structure or symbol)
        module.symbol = None

        # Step 2: do we need to do anything?
        if structure is not None and structure in ii.structs_in_scope:
            return []
        if str(module) in ii.modules_in_scope and structure is None:
            return []


        # Step 3: Prepare to generate import commands
        explain_loc = lambda loc: f' after \\begin{{{loc}}}' if loc else ' at the beginning of the file'

        def _get_indentation(pos: int) -> str:
            file_text = self.document.get_content()
            indentation = '\n'
            i = pos + 1
            while i < len(file_text):
                if file_text[i] == ' ':
                    indentation += ' '
                else:
                    break
                i += 1
            return indentation

        def _get_use_struct(pos: int) -> str:
            if structure is None:
                return ''
            return _get_indentation(pos) + f'\\usestructure{{{structure.symbol}}}'

        # TODO: skip archive if redundant (and path as well?)
        args = f'[{module.archive}]{{{module.path}?{module.module}}}'


        # Step 4: Top level use
        top_use_cmd = ImportCommand(
            't',
            'op-level usemodule (i.e.' + explain_loc(ii.top_use_env) + ')'
            if ii.top_use_env else
            'op-level usemodule (in this case same as [u])',
            'Inserts \\usemodule at the top of the document (i.e.' + explain_loc(ii.top_use_env) + ')'
            if ii.top_use_env else
            'Inserts \\usemodule at the top of the document (in this case same as [u])',
            SubstitutionOutcome(
                _get_indentation(ii.top_use_pos) + f'\\usemodule{args}' + _get_use_struct(
                    ii.top_use_pos),
                ii.top_use_pos, ii.top_use_pos
            ),
            redundancies=list(ii.get_redundant_import_removals(
                self.document, 'top_use', str(module), symb.path
            ))
        )

        # Step 5: Use module
        use_module_cmd = ImportCommand(
            'u', 'semodule' + explain_loc(ii.use_env),
                 'Inserts \\usemodule' + explain_loc(ii.use_env),
            SubstitutionOutcome(
                _get_indentation(ii.use_pos) + f'\\usemodule{args}' + _get_use_struct(ii.use_pos),
                ii.use_pos, ii.use_pos
            ),
            redundancies=list(ii.get_redundant_import_removals(
                self.document, 'use', str(module), symb.path
            ))
        )

        # Step 6: Evaluate feasibility of import
        import_impossible_reason: Optional[str] = None
        if ii.import_pos is None:
            import_impossible_reason = 'not in an smodule'
        elif self.document.path in get_transitive_imports([
            (str(module), symb.path)
        ]):
            import_impossible_reason = 'import would result cyclic dependency'

        # Step 7: Import module
        import_command: Optional[ImportCommand] = None
        if not import_impossible_reason:
            import_command = ImportCommand(
                'i', 'mportmodule',
                'Inserts \\importmodule',
                SubstitutionOutcome(
                    _get_indentation(ii.import_pos) + f'\\importmodule{args}' + _get_use_struct(ii.import_pos),
                    ii.import_pos, ii.import_pos
                ),
                redundancies=list(ii.get_redundant_import_removals(
                    self.document, 'import', str(module), symb.path
                ))
            )

        # Step 8: Ask user
        commands: list[Command] = [
            use_module_cmd,
            top_use_cmd,
        ]
        if import_command:
            commands.append(import_command)
        commands.append(QuitCommand('Stop this annotation'))

        cmd_collection = CommandCollection('Import options', commands, have_help=True)

        results: Sequence[CommandOutcome] = []
        while not results:
            self.stepper.show_current_state()
            results = cmd_collection.apply()
            interface.newline()
            interface.write_header('Import options', style='subdialog')
            interface.write_text('The symbol is not in scope.')
            if import_impossible_reason:
                interface.write_text(f'\\importmodule is impossible: {import_impossible_reason}')
            if any(isinstance(o, QuitOutcome) for o in results):
                raise AnnotationAborted()

        return results




class STeXAnnotateCommand(STeXAnnotateBase, Command):
    def __init__(
            self,
            state: SnifyState,
            options: list[tuple[LocalStexSymbol, Verbalization]],
            catalog: LocalFlamsCatalog,
            stepper,
    ):
        self.options = options
        STeXAnnotateBase.__init__(self, state, catalog, stepper)
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
            module_uri_f = FlamsUri(symbol.uri)
            module_uri_f.symbol = None
            symbol_display = ' '
            symbol_display += (
                style('✓', 'correct-weak')
                if str(module_uri_f) in self.importinfo.modules_in_scope
                else style('✗', 'error-weak')
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
                state: SnifyState,
                catalog: LocalFlamsCatalog,
                stepper,
        ):
            STeXAnnotateBase.__init__(self, state, catalog, stepper)

            Command.__init__(self, CommandInfo(
                show=False,
                pattern_presentation='l',
                description_short='ookup a symbol',
                description_long='Look up a symbol for annotation'
            ))
            self.state = state

    def execute(self, call: str) -> list[CommandOutcome]:
        cursor = self.state.cursor
        # filter_fun = make_filter_fun(state.filter_pattern, state.ignore_pattern)

        symbol = interface.list_search(
            {
                stex_symbol_style(FlamsUri(symbol.uri)) : symbol
                for symbol in self.catalog.symb_iter()
            }
        )

        return self.annotate_symbol(symbol) if symbol else []




@dataclasses.dataclass
class _ImportInfo:
    modules_in_scope: set[str]
    structs_in_scope: set[str]
    top_use_pos: int
    use_pos: int
    import_pos: Optional[int]
    use_env: Optional[str]
    top_use_env: Optional[str]

    # potential redundancies on use/import
    # module uri -> full range of use/import
    pot_red_on_use: dict[str, list[tuple[int, int]]]
    pot_red_on_import: dict[str, list[tuple[int, int]]]
    pot_red_on_top_use: dict[str, list[tuple[int, int]]]

    pot_red_on_use_struct: dict[str, list[tuple[int, int]]]
    pot_red_on_import_use_struct: dict[str, list[tuple[int, int]]]
    pot_red_on_top_use_struct: dict[str, list[tuple[int, int]]]


    def get_redundant_import_removals(
            self,
            document: STeXDocument,
            type_: Literal['use', 'import', 'top_use'],
            module_uri: str,
            module_path: str,
    ) -> Iterable[SubstitutionOutcome]:
        """
        Assuming module_uri get imported according to type_,
        this method returns substitutions that remove then-redundant imports.
        TODO: Extend this to structures as well (less relevant in practice)
        """
        pot_red = {
            'use': self.pot_red_on_use,
            'import': self.pot_red_on_import,
            'top_use': self.pot_red_on_top_use,
        }[type_]

        text = document.get_content()

        uri_trans = get_transitive_imports([(module_uri, module_path)])
        for uri, importrange in pot_red.items():
            if uri not in uri_trans:
                continue

            for from_, to in importrange:
                while from_ > 0 and text[from_ - 1] in {' ', '\t'}:
                    from_ -= 1
                while to < len(text) and text[to].isspace():
                    to += 1
                yield SubstitutionOutcome('', from_, to)


def get_modules_in_scope_and_import_locations(document: STeXDocument, offset: int) -> _ImportInfo:
    """
    collects import information and potential import locations in the document.
    Uses both FLAMS and pylatexenc.

    Note: Comparing latex environments for equality doesn't work in pylatexenc
    (equal environments are not equal),
    so, as a quick hack, I use the positions instead.
    """

    annos = FLAMS.get_file_annotations(document.path)
    file = OpenedStexFLAMSFile(str(document.path))
    surrounding_envs = get_surrounding_envs(document, offset)
    surrounding_envs_pos = [e.pos for e in surrounding_envs]

    # STEP 1: find interesting environments for new imports/uses
    module_env: Optional[LatexEnvironmentNode] = None
    _modules = [e for e in surrounding_envs if e.environmentname == 'smodule']
    if _modules:
        module_env = _modules[-1]
    _containers = [e for e in surrounding_envs if e.environmentname in {
        'sproblem', 'smodule', 'sdefinition', 'sparagraph', 'document', 'frame'
    }]
    use_env = _containers[-1] if _containers else None

    pot_red_on_use = {}
    pot_red_on_import = {}
    pot_red_on_top_use = {}
    pot_red_on_use_struct = {}
    pot_red_on_import_use_struct = {}
    pot_red_on_top_use_struct = {}

    # STEP 2: find modules in scope and the imports/uses
    available_modules: list[tuple[str, str]] = []   # (module uri, module path)
    available_structs: list[tuple[str, str]] = []   # (structure uri, structure path)
    for item in json_iter(annos):
        if isinstance(item, dict) and ('ImportModule' in item or 'UseModule' in item or 'UseStructure' in item):
            value = item.get('ImportModule') or item.get('UseModule') or item.get('UseStructure')
            is_struct = 'UseStructure' in item
            full_range = file.flams_range_to_offsets(value['full_range'])
            containing_envs = list(get_surrounding_envs(document, full_range[0]))

            uri = value['structure' if is_struct else 'module']['uri']
            full_path = value['structure' if is_struct else 'module']['filepath' if is_struct else 'full_path']

            if not containing_envs:
                if is_struct:
                    available_structs.append((uri, full_path))
                    pot_red_on_top_use_struct.setdefault(uri, []).append(full_range)
                else:
                    available_modules.append((uri, full_path))
                    pot_red_on_top_use.setdefault(uri, []).append(full_range)
                continue


            containing_env = containing_envs[-1]
            if containing_env.pos in surrounding_envs_pos:
                if is_struct:
                    available_structs.append((uri, full_path))
                else:
                    available_modules.append((uri, full_path))

                if 'ImportModule' in item and module_env.pos == containing_env.pos:
                    pot_red_on_import.setdefault(uri, []).append(full_range)
                elif 'UseModule' in item:
                    pot_red_on_top_use.setdefault(uri, []).append(full_range)
                    if use_env and surrounding_envs_pos.index(containing_env.pos) >= surrounding_envs_pos.index(use_env.pos):
                        pot_red_on_use.setdefault(uri, []).append(full_range)
                else:
                    assert is_struct
                    pot_red_on_top_use_struct.setdefault(uri, []).append(full_range)
                    if module_env.pos == containing_env.pos:
                        pot_red_on_import_use_struct.setdefault(uri, []).append(full_range)
                    if use_env and surrounding_envs_pos.index(containing_env.pos) >= surrounding_envs_pos.index(use_env.pos):
                        pot_red_on_use_struct.setdefault(uri, []).append(full_range)

        elif isinstance(item, dict) and ('Module' in item or 'MathStructure' in item):
            value = item.get('Module') or item.get('MathStructure')
            module_offset = file.flams_range_to_offsets(value['name_range'])[0]   # lots of things would work here
            containing_envs = list(get_surrounding_envs(document, module_offset))
            assert containing_envs
            containing_env = containing_envs[-1]
            if containing_env.pos in surrounding_envs_pos:
                if 'Module' in item:
                    available_modules.append((value['uri'], str(document.path)))
                else:
                    available_structs.append((value['uri'], str(document.path)))

    return _ImportInfo(
        modules_in_scope = set(get_transitive_imports(available_modules)),
        structs_in_scope = set(get_transitive_structs(available_structs)),
        top_use_pos = surrounding_envs[0].nodelist[0].pos if surrounding_envs else 0,
        use_pos = use_env.nodelist[0].pos if use_env else 0,
        import_pos = module_env.nodelist[0].pos if module_env else None,
        use_env = use_env.environmentname if use_env else None,
        top_use_env = surrounding_envs[0].environmentname if surrounding_envs else None,
        pot_red_on_use = pot_red_on_use,
        pot_red_on_import = pot_red_on_import,
        pot_red_on_top_use = pot_red_on_top_use,
        pot_red_on_use_struct = pot_red_on_use_struct,
        pot_red_on_import_use_struct = pot_red_on_import_use_struct,
        pot_red_on_top_use_struct = pot_red_on_top_use_struct,
    )



def get_surrounding_envs(document: STeXDocument, offset: int) -> list[LatexEnvironmentNode]:
    """
    Returns the surrounding environments of the given offset in the document.
    """
    return [
        node
        for node in iterate_latex_nodes(document.get_latex_walker().get_latex_nodes()[0])
        if isinstance(node, LatexEnvironmentNode) and node.pos <= offset < node.pos + node.len
    ]
