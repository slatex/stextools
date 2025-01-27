from pathlib import Path

from pylatexenc.latexwalker import LatexWalker, LatexMathNode, LatexCommentNode, LatexSpecialsNode, LatexMacroNode, \
    LatexEnvironmentNode, LatexCharsNode, LatexGroupNode

from stextools.core.macros import STEX_CONTEXT_DB


def quickcheck(filecontent: str) -> bool:
    """ returns true iff the file may have to be processed, i.e. if it introduces symbols """
    if 'symdecl' in filecontent or 'symdef' in filecontent:
        return True
    return False


def recurse(nodes):
    for node in nodes:
        if node is None or node.nodeType() in {LatexMathNode, LatexCommentNode, LatexSpecialsNode, LatexCharsNode}:
            continue
        if node.nodeType() == LatexMacroNode:
            if node.macroname in MACRO_RECURSION_RULES:
                for arg_idx in MACRO_RECURSION_RULES[node.macroname]:
                    if arg_idx >= len(node.nodeargd.argnlist):
                        click.clear()
                        standard_header('Error', bg='red')
                        print(f"Macro {node.macroname} does not have argument {arg_idx}")
                        print('Context:')
                        print(latex_text[max(node.pos - 100, 0):min(len(latex_text) - 1, node.pos + 300)])
                        print()
                        print('Please report this error')
                        click.pause()
                        continue
                    _recurse([node.nodeargd.argnlist[arg_idx]])
        elif node.nodeType() in {LatexEnvironmentNode, LatexGroupNode}:
            recurse(node.nodelist)
        else:
            raise RuntimeError(f"Unexpected node type: {node.nodeType()}")



def symname(file: Path):
    with open(file) as fp:
        filecontent = fp.read()

    if not quickcheck(filecontent):
        return

    walker = LatexWalker(filecontent, latex_context=STEX_CONTEXT_DB)
    nodes = walker.get_latex_nodes()[0]

