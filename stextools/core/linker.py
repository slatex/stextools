import logging
from collections import defaultdict
from collections.abc import Iterable, Callable
from typing import Optional, Union, Mapping

from stextools.core.mathhub import MathHub
from stextools.core.stexdoc import STeXDocument, Symbol, Verbalization, DocInfo, ModuleInfo, Dependency
from stextools.utils.intifier import Intifier

logger = logging.getLogger(__name__)


def top_sort(doc_deps: Mapping[int, Iterable[int]], error_doc_info: Callable[[int], str]) -> Iterable[int]:
    full_processed: set[int] = set()
    already_under_consideration: set[int] = set()
    result: list[int] = []

    def visit(doc: int):
        if doc in full_processed:
            return
        if doc in already_under_consideration:
            logger.error(f'Circular dependency detected (involving {error_doc_info(doc)})')
            return
        already_under_consideration.add(doc)
        for dep in doc_deps[doc]:
            visit(dep)
        full_processed.add(doc)
        result.append(doc)

    for doc in list(doc_deps):
        visit(doc)

    return result


class Linker:
    """
    Heavily optimized:
        * Objects are converted to integers for faster processing.
        * Different things are computed in the same pass to avoid multiple iterations over the same data.
    """

    # intifiers
    # (conversion to integers makes graph algorithms more efficient)
    document_ints: Intifier[STeXDocument]
    module_ints: Intifier[tuple[int, str]]  # (document as int, module name)
    symbol_ints: Intifier[tuple[int, Symbol]]  # (module as int, symbol)
    verb_ints: Intifier[tuple[int, Verbalization]]  # (module as int, verbalization)

    # data from _compute_dep_graph
    file_import_graph: dict[int, set[int]]
    module_import_graph: dict[int, set[int]]   # module -> set[module]
    file_to_module: dict[int, set[int]]        # file -> set[module]  (maps to all modules in the file)
    module_to_file: dict[int, int]             # module -> file
    available_module_ranges: dict[int, set[tuple[int, int, int]]]   # file -> set[(module, range_start, range_end)] - from imports, uses and smodule environments
    module_to_symbs: dict[int, set[int]]        # module -> set[symbol]
    symbol_to_module: dict[int, int]            # symbol -> module
    symbs_by_name: dict[str, set[tuple[int, int]]]   # name -> set[(module, symbol)]
    structures_by_name: dict[str, set[int]]      # name -> set[structure (module)]
    structure_info: dict[int, tuple[str, int, set[str], int]]  # structure -> (name, containing module, dependencies, start_pos)
    structures_by_file: dict[int, list[int]]      # file -> set[structure (module)]
    use_math_structs: dict[int, list[tuple[str, int, int]]]  # file -> set[(struct name, start, end)]

    # data from _transitive_imports
    transitive_imports: dict[int, set[int]]    # module -> set[module] (transitive closure of module imports, including self)

    # data from _link_symbols
    symb_to_verbs: dict[int, set[int]]          # symbol -> set[verbalization]
    verb_to_symb: dict[int, int]                # verbalization -> symbol

    def __init__(self, mh: MathHub):
        self.mh = mh

        self.document_ints = Intifier()
        self.module_ints = Intifier()
        self.symbol_ints = Intifier()
        self.verb_ints = Intifier()

        import time
        a = time.time()
        self._compute_dep_graph()
        b = time.time()
        self._compute_transitive_imports()
        c = time.time()
        self._link_structures()
        d = time.time()
        self._link_symbols()
        e = time.time()
        # print(f'Compute dep graph: {b - a}')
        # print(f'Compute transitive imports: {c - b}')
        # print(f'Link structures: {d - c}')
        # print(f'Link symbols: {e - d}')
        # print(f'Total: {e - a}')

    def _compute_dep_graph(self):
        self.file_import_graph = defaultdict(set)
        self.module_import_graph = defaultdict(set)
        self.file_to_module = defaultdict(set)
        self.available_module_ranges = defaultdict(set)
        self.module_to_file = {}
        self.module_to_symbs = defaultdict(set)
        self.symbol_to_module = {}
        self.symbs_by_name = defaultdict(set)
        self.structures_by_name = defaultdict(set)
        self.structure_info = {}
        self.structures_by_file = defaultdict(list)
        self.use_math_structs = defaultdict(list)

        # local variables are faster
        _doc_intify = self.document_ints.intify
        _mod_intify = self.module_ints.intify
        _available_module_ranges = self.available_module_ranges
        _file_import_graph = self.file_import_graph
        _module_import_graph = self.module_import_graph
        mh = self.mh

        for doc in mh.iter_stex_docs():
            int_doc = _doc_intify(doc)

            _file_import_graph[int_doc] = set()

            doc_info = doc.get_doc_info(mh)

            def process_dep(dep: Dependency, src_doc: STeXDocument, int_source_mod: Optional[int] = None):
                if dep.target_no_tex:
                    return
                dep_doc, dep_mod = dep.get_target(mh, src_doc)
                if dep_doc is None:
                    return
                dep_doc_int = _doc_intify(dep_doc)
                if dep.is_use and dep_mod is not None:
                    _available_module_ranges[int_doc].add((_mod_intify((dep_doc_int, dep_mod.name)),
                                                           dep.scope[0], dep.scope[1]))
                else:
                    _file_import_graph[int_doc].add(dep_doc_int)
                    if int_source_mod is not None and dep_mod is not None:
                        mod_int = _mod_intify((dep_doc_int, dep_mod.name))
                        _module_import_graph[int_source_mod].add(mod_int)
                        _available_module_ranges[int_doc].add((mod_int, dep.scope[0], dep.scope[1]))

            for dep in doc_info.dependencies:
                if dep.is_use_struct:
                    # will be processed later in _link_structures as it requires the import graph
                    assert dep.module_name is not None
                    self.use_math_structs[int_doc].append((dep.module_name, dep.scope[0], dep.scope[1]))
                else:
                    process_dep(dep, doc)

            for mod in doc_info.iter_modules():
                int_mod = self.module_ints.intify((int_doc, mod.name))
                self.file_to_module[int_doc].add(int_mod)
                self.module_to_file[int_mod] = int_doc
                _available_module_ranges[int_doc].add((int_mod, mod.valid_range[0], mod.valid_range[1]))
                for dep in mod.dependencies:
                    process_dep(dep, doc, int_mod)

                for symb in mod.symbols:
                    int_symb = self.symbol_ints.intify((int_mod, symb))
                    self.module_to_symbs[int_mod].add(int_symb)
                    self.symbs_by_name[symb.name].add((int_mod, int_symb))
                    self.symbol_to_module[int_symb] = int_mod

                if mod.is_structure:
                    assert mod.struct_name is not None
                    assert mod.struct_deps is not None
                    self.structures_by_name[mod.struct_name].add(int_mod)
                    int_parent_mod: Optional[int] = None
                    current: Union[DocInfo, ModuleInfo] = doc_info
                    while True:
                        if not current.modules:
                            break
                        keep_going = False
                        for child in current.modules:
                            if child.is_structure and child.name == mod.name:
                                if hasattr(current, 'name'):  # files don't have this
                                    int_parent_mod = _mod_intify((int_doc, current.name))
                                break
                            if child.valid_range[0] <= mod.valid_range[0] and mod.valid_range[1] <= child.valid_range[1]:
                                current = child
                                keep_going = True
                                break
                        if not keep_going:
                            break
                    if int_parent_mod is None:
                        logger.error(f'Failed to determine parent module for structure {mod.name} in {doc.path}')
                        continue

                    self.structure_info[int_mod] = (mod.name, int_parent_mod, set(mod.struct_deps), mod.valid_range[0])
                    self.structures_by_file[int_doc].append(int_mod)

    def _compute_transitive_imports(self):
        _module_import_graph = self.module_import_graph

        ti: dict[int, set[int]] = defaultdict(set)
        for file in top_sort(self.file_import_graph, lambda doc: str(self.document_ints.unintify(doc).path)):
            for mod in self.file_to_module[file]:
                imported = ti[mod]
                imported.add(mod)
                for dep in _module_import_graph[mod]:
                    imported.update(ti[dep])
        self.transitive_imports = ti

    def _link_structures(self):
        # Step 1: Resolve structure dependencies (for extstructure environments)
        struct_deps: dict[int, set[int]] = defaultdict(set)   # structure -> set[structure]
        for doc_int, structures in self.structures_by_file.items():
            for struct in structures:
                _, containing_mod, deps, mod_start_pos = self.structure_info[struct]
                for dep_name in deps:
                    candidates = self.structures_by_name[dep_name]
                    chosen_candidate: Optional[int] = None
                    for candidate in candidates:
                        required_module = self.structure_info[candidate][1]
                        for module, range_start, range_end in self.available_module_ranges[doc_int]:
                            if mod_start_pos > range_end or mod_start_pos < range_start:
                                continue
                            if required_module in self.transitive_imports[module]:
                                chosen_candidate = candidate
                                break
                        if chosen_candidate is not None:
                            break
                    if chosen_candidate is None:
                        logger.warning(f'No structure found for dependency {dep_name} in {self.document_ints.unintify(doc_int).path}')
                        continue
                    struct_deps.setdefault(struct, set()).add(chosen_candidate)

        # Step 2: update transitive import graph with structure dependencies
        for struct in top_sort(struct_deps, lambda struct: f'structure {self.structure_info[struct][0]} in {self.document_ints.unintify(self.module_to_file[struct]).path}'):
            for dep in struct_deps[struct]:
                self.transitive_imports[struct].update(self.transitive_imports[dep])

        # Step 3: Resolve \usestructure commands
        for doc_int, uses in self.use_math_structs.items():
            # self.use_math_structs[int_doc].append((dep.module_name, dep.valid_range[0], dep.valid_range[1]))
            for struct_name, start_range, end_range in uses:
                candidates = self.structures_by_name[struct_name]
                # Note: we assume that len(candidates) is very small - otherwise this would be inefficient
                chosen_candidate = None
                for candidate in candidates:
                    required_module = self.structure_info[candidate][1]
                    for module, range_start, range_end in self.available_module_ranges[doc_int]:
                        if start_range > range_end or end_range < range_start:
                            continue
                        if required_module in self.transitive_imports[module]:
                            chosen_candidate = candidate
                            break
                    if chosen_candidate is not None:
                        break
                if chosen_candidate is None:
                    logger.warning(f'No structure found for \\usestructure{{{struct_name}}} in {self.document_ints.unintify(doc_int).path}')
                    continue
                self.available_module_ranges[doc_int].add((chosen_candidate, start_range, end_range))

    def _link_symbols(self):
        ti = self.transitive_imports
        self.verb_to_symb = {}
        self.symb_to_verbs = defaultdict(set)

        for file in self.document_ints.int_iter():
            # TODO: Should we make an interval tree for faster lookups?
            stexdoc = self.document_ints.unintify(file)
            # for verb in stexdoc.get_doc_info(self.mh).verbalizations:
            for verb in stexdoc.get_doc_info(self.mh).verbalizations:
                # these sets should contain all potential candidates, i.e. all symbols with the same name
                # there shouldn't be many
                candidates = self.symbs_by_name[verb.symbol_name]
                candidate_modules: set[int] = {e[0] for e in candidates}
                # there should never be two symbols with the same name in the same module
                candidate_module_to_candidate_symbol: dict[int, int] = {e[0]: e[1] for e in candidates}

                # modules that are in scope and contain the symbol
                final_candidate_modules: set[int] = set()

                verb_start = verb.macro_range[0]
                verb_end = verb.macro_range[1]

                for module, range_start, range_end in self.available_module_ranges[file]:
                    if verb_start > range_end or verb_end < range_start:
                        continue

                    intersection = candidate_modules & ti[module]
                    if intersection:
                        final_candidate_modules.update(intersection)

                selection: list[int] = []
                for candidate in final_candidate_modules:
                    candidate_symbol = candidate_module_to_candidate_symbol[candidate]
                    if verb.symbol_path_hint and not self.module_ints.unintify(candidate)[1].endswith(verb.symbol_path_hint):
                        continue
                    selection.append(candidate_symbol)

                if not selection:
                    logger.warning(f'No symbol found for verbalization {verb} in {stexdoc.path}')
                    continue
                if len(selection) > 1:
                    logger.warning(f'Multiple symbols found for verbalization {verb} in {stexdoc.path}')
                    # for s in selection:
                    #     logger.warning(f'    {self.symbol_ints.unintify(s)} {self.module_ints.unintify(self.symbol_to_module[s])}')
                    continue
                int_verb = self.verb_ints.intify((file, verb))
                self.verb_to_symb[int_verb] = selection[0]
                self.symb_to_verbs[selection[0]].add(int_verb)
