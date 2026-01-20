"""
Code for parsing sTeX files.
This is not based on FLAMS (FLAMS only extracts annotations, and we need the informal content as well).
"""
import logging
from pathlib import Path
from typing import Iterable, Optional

from pylatexenc.latexwalker import get_default_latex_context_db, LatexWalker, LatexMathNode, LatexCommentNode, \
    LatexSpecialsNode, LatexMacroNode, LatexEnvironmentNode, LatexGroupNode, LatexCharsNode, LatexNode
from pylatexenc.macrospec import MacroSpec, std_environment, VerbatimArgsParser, ParsedMacroArgs

from stextools.config import CONFIG_DIR
from stextools.stepper.interface import interface
from stextools.utils.linked_str import LinkedStr, string_to_lstr, fixed_range_lstr, concatenate_lstrs

logger = logging.getLogger(__name__)

STEX_MACRO_SPECS: list = [ ]
STEX_ENV_SPECS: list = [ ]
STANDARD_MACRO_SPECS: list = [
    MacroSpec('lstinline', args_parser=VerbatimArgsParser(verbatim_arg_type="verb-macro")),
    MacroSpec('wdalign', '{{'),   # wikidata alignment (non-standard)
]
STANDARD_ENV_SPECS: list = [ ]

# By default, macros are not searched for potential annotations.
# This is a list of exceptions to this rule.
# The keys are the names of the macros (note that they should be in the pylatexenc context).
# The values are the indices of the arguments that should be searched.
# For key/value arguments, specific values can be specified as tuples (arg_index, key_name).
PLAINTEXT_EXTRACTION_MACRO_RECURSION: dict[str, list[int | tuple[int, str]]] = { }

# By default, the content of environment is searched for potential annotations,
# but the arguments are not.
# This is a list of exceptions to this rule.
# The keys are the names of the environments (note that they should be in the pylatexenc context).
# The values are pairs (a, b), where
#   - a is a boolean indicating whether the environment content should be searched
#   - b is a list of indices of the arguments that should be searched (like in the macro case).
PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES: dict[str, tuple[bool, list[int | tuple[int, str]]]] = { }

STEX_CONTEXT_DB = get_default_latex_context_db()


class InvalidMacroSpecError(Exception):
    pass


def _populate_stex_context_db():
    for path in [
        Path(__file__).parent / 'latex_macros',
        Path(__file__).parent / 'stex_macros',
        CONFIG_DIR / 'latex_macros',
        CONFIG_DIR / 'stex_macros',
    ]:
        if not path.exists():
            continue
        logger.info(f'Loading LaTeX macros from {path}')
        is_stex = path.name == 'stex_macros'
        with open(path, 'r') as fp:
            for i, line in enumerate(fp):
                error = InvalidMacroSpecError(f"Invalid environment spec at {path}:{i+1}: {line}")
                line = line.strip()
                if line.startswith('#') or not line:
                    continue  # comment/empty line
                if line.startswith(r'\begin{'):  # environment
                    if '}' not in line:
                        raise error
                    envname = line[len(r'\begin{'):line.index('}')]
                    rest = [s.strip() for s in line[line.index('}') + 1:].split(',')]
                    parens = rest[0] if rest else ''
                    if not all(s in {'[', '{'} for s in parens):
                        raise error
                    if len(rest) > 1:
                        recurse = True
                        argrecurse = []
                        for r in rest[1:]:
                            if r == 'norec':
                                recurse = False
                            elif r.isdigit():
                                if int(r) > len(parens):
                                    raise error
                                argrecurse.append(int(r) - 1)
                            else:
                                rr = r.split(':')
                                if len(rr) != 2 or not rr[0].isdigit() or not rr[1].isalpha() or int(rr[0]) > len(parens):
                                    raise error
                                argrecurse.append((int(rr[0]) - 1, rr[1]))
                        PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES[envname] = (recurse, argrecurse)

                    env_spec = std_environment(envname, parens)
                    if is_stex:
                        STEX_ENV_SPECS.append(env_spec)
                    else:
                        STANDARD_ENV_SPECS.append(env_spec)
                else:   # macro
                    parts = [s.strip() for s in line.split(',')]
                    parens_index = len(parts[0])
                    while parens_index > 0 and parts[0][parens_index - 1] in {'[', '{'}:
                        parens_index -= 1
                    if parts[0][0] != '\\' or not all(p.isalpha() or p == '*' for p in parts[0][1:parens_index]):
                        raise error
                    macroname = parts[0][1:parens_index]
                    parens = parts[0][parens_index:]
                    recursion_rules = []
                    for p in parts[1:]:
                        if p.isdigit():
                            if int(p) > len(parens):
                                raise error
                            recursion_rules.append(int(p) - 1)
                        else:
                            pp = p.split(':')
                            if len(pp) != 2 or not pp[0].isdigit() or not pp[1].isalpha() or int(pp[0]) > len(parens):
                                raise error
                            recursion_rules.append((int(pp[0]) - 1, pp[1]))

                    if recursion_rules:
                        PLAINTEXT_EXTRACTION_MACRO_RECURSION[macroname] = recursion_rules

                    macro_spec = MacroSpec(macroname, parens)
                    if is_stex:
                        STEX_MACRO_SPECS.append(macro_spec)
                    else:
                        STANDARD_MACRO_SPECS.append(macro_spec)




    STEX_CONTEXT_DB.add_context_category('stex', macros=STEX_MACRO_SPECS, environments=STEX_ENV_SPECS)
    STEX_CONTEXT_DB.add_context_category('std', macros=STANDARD_MACRO_SPECS, environments=STANDARD_ENV_SPECS)
    try:
        STEX_CONTEXT_DB.freeze()
    except AttributeError:   # freeze is only available in newer pylatexenc versions
        pass

_populate_stex_context_db()

#############
# UTILITIES FOR MACRO ARGUMENTS
#############


class OptArgKeyVals:
    """ A class to represent optional arguments with key-value pairs in LaTeX.
        Note: at the moment it's a relatively hacky implementation that does not support changing values.
        This might have to be changed in the future.
    """

    def __init__(self, nodelist: list[LatexNode]):
        self.nodelist = nodelist
        self._keyvals: dict[str, str] = {}

        current_key: str = ''
        looking_for_val: bool = False
        current_val: str = ''
        # TODO: the following could also track the source refs to enable edits in the source
        for node in self.nodelist:
            if isinstance(node, LatexCharsNode):
                remainder = node.chars
                while remainder:
                    if looking_for_val:
                        if ',' in remainder:
                            valrest, _, remainder = remainder.partition(',')
                            current_val += valrest
                            self._keyvals[current_key.strip()] = current_val.strip()
                            current_key = ''
                            current_val = ''
                            looking_for_val = False
                        else:
                            current_val += remainder
                            remainder = None
                    else:
                        if '=' in remainder:
                            keyrest, _, remainder = remainder.partition('=')
                            current_key += keyrest
                            looking_for_val = True
                        else:
                            current_key += remainder
                            remainder = None
            else:
                if looking_for_val:
                    current_val += node.latex_verbatim()
                else:
                    current_key += node.latex_verbatim()
        if current_key:
            self._keyvals[current_key.strip()] = current_val.strip()

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in self._keyvals.items()}

    @classmethod
    def from_first_macro_arg(cls, args: ParsedMacroArgs) -> Optional['OptArgKeyVals']:
        if not args.argnlist:
            return None
        first_arg = args.argnlist[0]
        if not isinstance(first_arg, LatexGroupNode):  # is this even possible?
            return None
        if first_arg.delimiters != ('[', ']'):
            return None
        return cls(first_arg.nodelist)

    def get_val(self, key: str) -> Optional[str]:
        return self._keyvals.get(key)

    def __len__(self) -> int:
        return len(self._keyvals)





#############
# PLAIN TEXT EXTRACTION FOR ANNOTATIONS
#############


def get_annotatable_plaintext(
        walker: LatexWalker,
        suppress_errors: bool = False,
) -> list[LinkedStr]:
    result: list[LinkedStr] = []
    # walker = LatexWalker(latex_text, latex_context=STEX_CONTEXT_DB)
    latex_text = walker.s

    def _recurse(nodes):
        for node in nodes:
            if node is None or node.nodeType() in {LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                # TODO: recurse into math nodes?
                continue
            if node.nodeType() == LatexMacroNode:
                if node.macroname in PLAINTEXT_EXTRACTION_MACRO_RECURSION:
                    for arg_idx in PLAINTEXT_EXTRACTION_MACRO_RECURSION[node.macroname]:
                        if arg_idx >= len(node.nodeargd.argnlist) and not suppress_errors:
                            interface.clear()
                            interface.write_header('Error', style='error')
                            interface.write_text(f"Macro {node.macroname} does not have argument {arg_idx}",
                                                 style='error')
                            interface.write_text('\nContext:\n')
                            interface.show_code(
                                latex_text,
                                format='tex',
                                highlight_range=(node.pos, node.pos + node.len),
                                limit_range=3,
                            )
                            interface.write_text('\n\nPlease report this error\n', style='bold')
                            interface.await_confirmation()
                            continue
                        _recurse([node.nodeargd.argnlist[arg_idx]])
            elif node.nodeType() == LatexEnvironmentNode:
                if node.envname in PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES:
                    recurse_content, recurse_args = PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES[node.envname]
                else:
                    recurse_content, recurse_args = True, []
                for arg_idx in recurse_args:
                    _recurse([node.nodeargd.argnlist[arg_idx]])
                if recurse_content:
                    _recurse(node.nodelist)
            elif node.nodeType() == LatexGroupNode:
                _recurse(node.nodelist)
            elif node.nodeType() == LatexCharsNode:
                result.append(string_to_lstr(node.chars, node.pos))
            else:
                raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

    _recurse(walker.get_latex_nodes()[0])

    return result


def verbalization_from_macro(node: LatexMacroNode) -> str:
    prefix = ''
    postfix = ''
    if not node.nodeargd:
        return ''
    if node.macroname in {'sr', 'definiendum'}:
        verbalization = node.nodeargd.argnlist[-1].latex_verbatim()[1:-1]
    else:
        params = OptArgKeyVals.from_first_macro_arg(node.nodeargd)
        if params:
            prefix = params.get_val('pre') or ''
            postfix = params.get_val('post') or ''
        symbol = node.nodeargd.argnlist[-1].latex_verbatim()[1:-1]
        verbalization = symbol.split('?')[-1]
    if node.macroname in {'Sn', 'Sns', 'Definame'}:
        if verbalization:
            verbalization = verbalization[0].upper() + verbalization[1:]
        else:
            return ''
    if node.macroname in {'sns', 'Sns'}:
        verbalization += 's'

    verbalization = prefix + verbalization + postfix

    return verbalization


def get_plaintext_approx(
        walker: LatexWalker,
        formula_token: str = 'X',
) -> LinkedStr:
    result: list[LinkedStr] = []

    def _recurse(nodes):
        for node in nodes:
            if node is None or node.nodeType() in {LatexCommentNode, LatexSpecialsNode}:
                continue
            if node.nodeType() == LatexMathNode:
                result.append(fixed_range_lstr(formula_token, node.pos, node.pos + node.len))
            elif node.nodeType() == LatexMacroNode:
                if node.macroname in PLAINTEXT_EXTRACTION_MACRO_RECURSION:
                    for arg_idx in PLAINTEXT_EXTRACTION_MACRO_RECURSION[node.macroname]:
                        if isinstance(arg_idx, int):
                            _recurse([node.nodeargd.argnlist[arg_idx]])
                elif node.macroname in {
                    'definiendum', 'definame', 'Definame',
                    'sn', 'sns', 'Sn', 'Sns', 'sr',
                }:
                    verbalization = verbalization_from_macro(node)
                    result.append(fixed_range_lstr(verbalization, node.pos, node.pos + node.len))
            elif node.nodeType() == LatexEnvironmentNode:
                if node.envname in PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES:
                    recurse_content, recurse_args = PLAINTEXT_EXTRACTION_ENVIRONMENT_RULES[node.envname]
                else:
                    recurse_content, recurse_args = True, []
                for arg_idx in recurse_args:
                    if isinstance(arg_idx, int):
                        _recurse([node.nodeargd.argnlist[arg_idx]])
                if recurse_content:
                    _recurse(node.nodelist)
            elif node.nodeType() == LatexGroupNode:
                _recurse(node.nodelist)
            elif node.nodeType() == LatexCharsNode:
                result.append(string_to_lstr(node.chars, node.pos))
            else:
                raise RuntimeError(f"Unexpected node type: {node.nodeType()}")

    _recurse(walker.get_latex_nodes()[0])

    return concatenate_lstrs(result, None)


def iterate_latex_nodes(nodes) -> Iterable[LatexNode]:
    for node in nodes:
        yield node
        if node is None or node.nodeType() in {LatexSpecialsNode}:
            continue
        elif node.nodeType() in {LatexMacroNode}:
            if node.nodeargd:
                yield from iterate_latex_nodes(node.nodeargd.argnlist)
        elif node.nodeType() in {LatexMathNode, LatexGroupNode, LatexEnvironmentNode}:
            yield from iterate_latex_nodes(node.nodelist)
        elif node.nodeType() in {LatexCommentNode, LatexCharsNode}:
            pass
        else:
            raise RuntimeError(f"Unexpected node type: {node.nodeType()}")
