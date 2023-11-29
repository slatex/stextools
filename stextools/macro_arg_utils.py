from typing import Optional

from pylatexenc.latexwalker import LatexNode, LatexCharsNode, LatexGroupNode
from pylatexenc.macrospec import ParsedMacroArgs


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
        return {k:v for k, v in self._keyvals.items()}

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


def get_first_macro_arg_opt(node: ParsedMacroArgs) -> Optional[str]:
    """ Returns the optional argument of a macro, if it exists. It has to be the first argument. """
    assert node.argnlist
    first_arg = node.argnlist[0]
    if first_arg is None or not isinstance(first_arg, LatexGroupNode):  # is this even possible?
        return None
    if first_arg.delimiters != ('[', ']'):  # is this even possible?
        return None
    return first_arg.latex_verbatim()[1:-1]  # remove brackets


def get_first_main_arg(node: ParsedMacroArgs) -> Optional[str]:
    """ Returns the first main argument of a macro, if it exists. """
    assert node.argnlist
    i = 0
    main_arg = node.argnlist[i]
    while (main_arg is None or  # optional arg (not provided)
           main_arg.nodeType() == LatexCharsNode or  # *
           main_arg.delimiters == ('[', ']')):  # optional arg (provided)
        i += 1
        if i >= len(node.argnlist):  # shouldn't really happen...
            return None
        main_arg = node.argnlist[i]
    assert main_arg.delimiters == ('{', '}')
    return main_arg.latex_verbatim()[1:-1]  # remove braces
