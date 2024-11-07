import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Optional

from stextools.core.mathhub import MathHub
from stextools.core.stexdoc import STeXDocument, Symbol, Verbalization
from stextools.utils.intifier import Intifier

logger = logging.getLogger(__name__)


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
        self._link_symbols()
        d = time.time()
        print(f'Compute dep graph: {b - a}')
        print(f'Compute transitive imports: {c - b}')
        print(f'Link symbols: {d - c}')
        print(f'Total: {d - a}')

    def _compute_dep_graph(self):
        self.file_import_graph = defaultdict(set)
        self.module_import_graph = defaultdict(set)
        self.file_to_module = defaultdict(set)
        self.available_module_ranges = defaultdict(set)
        self.module_to_file = {}
        self.module_to_symbs = defaultdict(set)
        self.symbol_to_module = {}
        self.symbs_by_name = defaultdict(set)

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

            def process_dep(dep, int_source_mod: Optional[int] = None):
                if dep.target_no_tex:
                    return
                dep_doc, dep_mod = dep.get_target(mh)
                if dep_doc is None:
                    return
                dep_doc_int = _doc_intify(dep_doc)
                if dep.is_use and dep_mod is not None:
                    _available_module_ranges[int_doc].add((_mod_intify((dep_doc_int, dep_mod.name)),
                                                                dep.valid_range[0], dep.valid_range[1]))
                else:
                    _file_import_graph[int_doc].add(dep_doc_int)
                    if int_source_mod is not None and dep_mod is not None:
                        mod_int = _mod_intify((dep_doc_int, dep_mod.name))
                        _module_import_graph[int_source_mod].add(mod_int)
                        _available_module_ranges[int_doc].add((mod_int, dep.valid_range[0], dep.valid_range[1]))

            for dep in doc_info.dependencies:
                process_dep(dep)

            for mod in doc_info.iter_modules():
                int_mod = self.module_ints.intify((int_doc, mod.name))
                self.file_to_module[int_doc].add(int_mod)
                self.module_to_file[int_mod] = int_doc
                _available_module_ranges[int_doc].add((int_mod, mod.valid_range[0], mod.valid_range[1]))
                for dep in mod.dependencies:
                    process_dep(dep, int_mod)

                for symb in mod.symbols:
                    int_symb = self.symbol_ints.intify((int_mod, symb))
                    self.module_to_symbs[int_mod].add(int_symb)
                    self.symbs_by_name[symb.name].add((int_mod, int_symb))
                    self.symbol_to_module[int_symb] = int_mod

    def _get_docs_topsorted(self) -> Iterable[int]:
        full_processed: set[int] = set()
        already_under_consideration: set[int] = set()
        result: list[int] = []

        def visit(doc: int):
            if doc in full_processed:
                return
            if doc in already_under_consideration:
                logger.error(f'Circular dependency detected (involving {self.document_ints.unintify(doc).path})')
                return
            already_under_consideration.add(doc)
            for dep in self.file_import_graph[doc]:
                visit(dep)
            full_processed.add(doc)
            result.append(doc)

        for doc in list(self.file_import_graph):
            visit(doc)

        return result

    def _compute_transitive_imports(self):
        _module_import_graph = self.module_import_graph

        ti = defaultdict(set)
        for file in self._get_docs_topsorted():
            for mod in self.file_to_module[file]:
                imported = ti[mod]
                imported.add(mod)
                for dep in _module_import_graph[mod]:
                    imported.update(ti[dep])
        self.transitive_imports = ti

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
                    continue
                int_verb = self.verb_ints.intify((file, verb))
                self.verb_to_symb[int_verb] = selection[0]
                self.symb_to_verbs[selection[0]].add(int_verb)
