import unittest

from pylatexenc.latexwalker import LatexWalker, LatexMacroNode

from stextools.utils.macro_arg_utils import OptArgKeyVals
from stextools.core.macros import STEX_CONTEXT_DB


def parse_macro(s: str) -> LatexMacroNode:
    walker = LatexWalker(s, latex_context=STEX_CONTEXT_DB)
    nodes = walker.get_latex_nodes()[0]
    assert len(nodes) == 1
    return nodes[0]


class MacroTest(unittest.TestCase):
    def test_key_val(self):
        keyvals = OptArgKeyVals.from_first_macro_arg(
            parse_macro(r'\mhtikzinput[archive=MiKoMH/ComSem,width=10cm]{hou/tikz/ellipsis-ex}').nodeargd
        )
        self.assertIsNotNone(keyvals)
        assert keyvals is not None   # for mypy
        self.assertEqual(len(keyvals), 2)
        self.assertEqual(keyvals.get_val('archive'), 'MiKoMH/ComSem')
        self.assertEqual(keyvals.get_val('width'), '10cm')
