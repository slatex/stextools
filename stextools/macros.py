from pylatexenc.latexwalker import get_default_latex_context_db
from pylatexenc.macrospec import MacroSpec

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
]

STEX_ENV_SPECS: list = []

STEX_CONTEXT_DB = get_default_latex_context_db()
STEX_CONTEXT_DB.add_context_category('stex', macros=STEX_MACRO_SPECS, environments=STEX_ENV_SPECS)
try:
    STEX_CONTEXT_DB.freeze()
except AttributeError:   # freeze is only available in newer pylatexenc versions
    pass
