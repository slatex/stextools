"""
Code for adding imports to sTeX documents.
This code is rather nasty (complex/unreadable/possibly buggy).
The problem is inherently rather tricky:
- there are many positions where the import can be added
- imports are scoped
- we need to prevent cyclic imports
- there distinction of usemodule vs importmodule
- we want to remove redundant imports/usages
- the result should look nice (indentation etc.)
- ...
"""

import dataclasses
from copy import deepcopy
from typing import Sequence, Optional, Literal, Iterable, Callable

from pylatexenc.latexwalker import LatexEnvironmentNode

from stextools.snify.snify_state import SnifyState
from stextools.snify.text_anno.local_stex_catalog import LocalStexSymbol
from stextools.stepper.command import Command, CommandInfo, CommandOutcome, CommandCollection
from stextools.stepper.document import STeXDocument, Document, get_missing_dependencies
from stextools.stepper.document_stepper import SubstitutionOutcome, DocumentCollectionModification
from stextools.stepper.interface import interface
from stextools.stepper.stepper import Modification
from stextools.stepper.stepper_extensions import QuitCommand, QuitOutcome
from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import get_transitive_imports, OpenedStexFLAMSFile, get_transitive_structs, FlamsUri
from stextools.stex.stex_py_parsing import iterate_latex_nodes
from stextools.utils.json_iter import json_iter


class AnnotationAborted(Exception):
    pass


@dataclasses.dataclass
class DependencyModificationOutcome(CommandOutcome):
    """ Indicates that the document was modified and (possibly) dependencies have changed.
    The stepper can use this to e.g. include the dependencies in the "todo list".
    """
    document: Document

    def get_modification(self, state: SnifyState) -> Optional[Modification]:
        if not state.deep_mode:
            return None

        new_documents = state.documents[:]
        new_documents.extend(
            get_missing_dependencies([self.document], {doc.identifier for doc in state.documents})
        )

        return DocumentCollectionModification(
            old_documents=state.documents,
            new_documents=new_documents,
            old_document_index=state.cursor.document_index,
            new_document_index=state.cursor.document_index
        )



class ImportCommand(Command):
    def __init__(self, letter: str, description_short: str, description_long: str, outcome: SubstitutionOutcome,
                 redundancies: list[SubstitutionOutcome]):
        super().__init__(CommandInfo(
            pattern_presentation=letter,
            description_short=description_short,
            description_long=description_long)
        )
        self.outcome = outcome
        self.redundancies = redundancies

    def execute(self, call: str) -> Sequence[CommandOutcome]:
        cmds: list[SubstitutionOutcome] = self.redundancies + [self.outcome]
        cmds.sort(key=lambda x: x.start_pos, reverse=True)
        return cmds


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


    pot_red_on_use: dict[str, list[tuple[int, int]]] = {}
    pot_red_on_import: dict[str, list[tuple[int, int]]] = {}
    pot_red_on_top_use: dict[str, list[tuple[int, int]]] = {}

    pot_red_on_use_struct: dict[str, list[tuple[int, int]]] = {}
    pot_red_on_import_use_struct: dict[str, list[tuple[int, int]]] = {}
    pot_red_on_top_use_struct: dict[str, list[tuple[int, int]]] = {}

    # STEP 2: find modules in scope and the imports/uses
    available_modules: list[tuple[str, str]] = []   # (module uri, module path)
    available_structs: list[tuple[str, str]] = []   # (structure uri, structure path)
    for item in json_iter(annos):
        if isinstance(item, dict) and ('ImportModule' in item or 'UseModule' in item or 'UseStructure' in item):
            value = item.get('ImportModule') or item.get('UseModule') or item.get('UseStructure')
            assert value
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

                # assert module_env is not None

                if 'ImportModule' in item and (module_env is None or module_env.pos == containing_env.pos):
                    if module_env is None:
                        interface.write_text('Warning: found \\importmodule outside of module.\n', style='warning')
                        continue
                    pot_red_on_import.setdefault(uri, []).append(full_range)
                elif 'UseModule' in item:
                    pot_red_on_top_use.setdefault(uri, []).append(full_range)
                    if use_env and surrounding_envs_pos.index(containing_env.pos) >= surrounding_envs_pos.index(use_env.pos):
                        pot_red_on_use.setdefault(uri, []).append(full_range)
                else:
                    assert is_struct
                    pot_red_on_top_use_struct.setdefault(uri, []).append(full_range)
                    if module_env and module_env.pos == containing_env.pos:
                        pot_red_on_import_use_struct.setdefault(uri, []).append(full_range)
                    if use_env and surrounding_envs_pos.index(containing_env.pos) >= surrounding_envs_pos.index(use_env.pos):
                        pot_red_on_use_struct.setdefault(uri, []).append(full_range)

        elif isinstance(item, dict) and ('Module' in item or 'MathStructure' in item):
            value = item.get('Module') or item.get('MathStructure')
            assert value
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


def get_import(
        document: STeXDocument,
        ii: _ImportInfo,
        symb: LocalStexSymbol,
        show_state_fun: Callable[[], None],
) -> Sequence[CommandOutcome]:

    # Step 1: determine structure and module
    symbol = FlamsUri(symb.uri)
    structure: Optional[FlamsUri] = None
    if '/' in symbol.module:      # TODO: better way to identify structures
        structure = deepcopy(symbol)
        structure.module, _, structure.symbol = symbol.module.rpartition('/')
    module: FlamsUri = deepcopy(structure or symbol)
    module.symbol = ''

    # Step 2: do we need to do anything?
    if structure is not None and structure in ii.structs_in_scope:
        return []
    if str(module) in ii.modules_in_scope and structure is None:
        return []


    # Step 3: Prepare to generate import commands
    explain_loc = lambda loc: f' after \\begin{{{loc}}}' if loc else ' at the beginning of the file'

    def _get_indentation(pos: int) -> str:
        file_text = document.get_content()
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
            document, 'top_use', str(module), symb.path
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
            document, 'use', str(module), symb.path
        ))
    )

    # Step 6: Evaluate feasibility of import
    import_impossible_reason: Optional[str] = None
    if ii.import_pos is None:
        import_impossible_reason = 'not in an smodule'
    elif str(document.path) in get_transitive_imports([
        (str(module), symb.path)
    ]).values():
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
                document, 'import', str(module), symb.path
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
        show_state_fun()
        interface.write_header('Import options', style='subdialog')
        interface.write_text('The symbol is not in scope.\n')
        if import_impossible_reason:
            interface.write_text(f'\\importmodule is impossible: {import_impossible_reason}')
        interface.newline()
        results = cmd_collection.apply()
        if any(isinstance(o, QuitOutcome) for o in results):
            raise AnnotationAborted()

    return list(results) + [DependencyModificationOutcome(document)]
