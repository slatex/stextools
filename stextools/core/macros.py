from pylatexenc.latexwalker import get_default_latex_context_db
from pylatexenc.macrospec import MacroSpec, std_environment, VerbatimArgsParser

STEX_MACRO_SPECS: list = [
    # from section 3.5 of the stex manual (targets modules)
    MacroSpec('importmodule', '[{'),
    MacroSpec('requiremodule', '[{'),
    MacroSpec('usemodule', '[{'),

    # from section 2.2 of the stex manual (targets tex files)
    MacroSpec('inputref', '*[{'),
    MacroSpec('mhinput', '*[{'),

    # targets non-tex files
    MacroSpec('mhgraphics', '[{'),
    MacroSpec('cmhgraphics', '[{'),
    MacroSpec('mhtikzinput', '[{'),
    MacroSpec('cmhtikzinput', '[{'),
    MacroSpec('lstinputmhlisting', '[{'),
    MacroSpec('addmhbibresource', '[{'),

    # others
    MacroSpec('includeproblem', '[{'),

    # from section 1.3 of the stex manual (targets lib/ directory)
    MacroSpec('libinput', '[{'),
    MacroSpec('libusepackage', '[{'),
    MacroSpec('libusetikzlibrary', '[{'),

    # various others
    MacroSpec('MSC', '{'),
    MacroSpec('notation', '{[{'),
    MacroSpec('symdecl', '*{'),
    MacroSpec('symdef', '{[{'),
    MacroSpec('definiendum', '[{{'),
    MacroSpec('definame', '[{'),
    MacroSpec('Definame', '[{'),
    MacroSpec('sn', '[{'),
    MacroSpec('sns', '[{'),
    MacroSpec('Sn', '[{'),
    MacroSpec('Sns', '[{'),
    MacroSpec('sr', '[{{'),
    MacroSpec('objective', '{{'),
    MacroSpec('sref', '[{'),
    MacroSpec('usestructure', '{'),
]

STEX_ENV_SPECS: list = [
    std_environment('smodule', '[{'),
    std_environment('sdefinition', '['),
    std_environment('sproblem', '['),
    std_environment('sparagraph', '['),
    std_environment('scb', '['),
    std_environment('smcb', '['),
]


STANDARD_MACRO_SPECS: list = [
    MacroSpec('lstinline', args_parser=VerbatimArgsParser(verbatim_arg_type="verb-macro")),
    MacroSpec('lstset', '{'),
    MacroSpec('lstinputlisting', '[{'),

    # less standard
    MacroSpec('ednote', '{'),
]

STANDARD_ENV_SPECS: list = [
    std_environment('lstlisting', '['),
]

STEX_CONTEXT_DB = get_default_latex_context_db()
STEX_CONTEXT_DB.add_context_category('stex', macros=STEX_MACRO_SPECS, environments=STEX_ENV_SPECS)
STEX_CONTEXT_DB.add_context_category('std', macros=STANDARD_MACRO_SPECS, environments=STANDARD_ENV_SPECS)
try:
    STEX_CONTEXT_DB.freeze()
except AttributeError:   # freeze is only available in newer pylatexenc versions
    pass
