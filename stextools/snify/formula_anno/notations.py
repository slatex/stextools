import functools
import re
from collections import defaultdict
from typing import Optional

from stextools.snify.text_anno.local_stex_catalog import LocalStexSymbol
from stextools.stex.flams import FLAMS
from stextools.stex.local_stex import OpenedStexFLAMSFile
from stextools.utils.json_iter import json_iter


@functools.cache   # TODO: cache must be invalidated if the file changes
def extract_notations_from_file(path: str) -> dict[str, list[tuple[LocalStexSymbol, str]]]:
    result = defaultdict(list)
    annos = FLAMS.get_file_annotations(path)
    of = OpenedStexFLAMSFile(path)

    for item in json_iter(annos):
        if not isinstance(item, dict):
            continue
        if 'Symdef' in item:  # TODO: also support \notation
            # quick and dirty extraction of notation
            item = item['Symdef']
            uri = item['uri']['uri']
            path = item['uri']['filepath']

            a, _ = of.flams_range_to_offsets(item['full_range'])

            line = of.text[a:].splitlines()[0]

            main_def = re.match(r'\\symdef\{(?P<macroname>[^}]+)\}(?P<args>\[([^[\]]|\[[^\]]*\])*\])?(?P<rest>[^%]*)', line)

            if not main_def:
                continue

            record = {}
            arg_match = re.match(r'.*args=(?P<args>[^,\]]*)', main_def.group('args') or '')
            if arg_match:
                args = arg_match.group('args')
                args = args.strip()
                # if re.match(r'^[ibaB]+$', args):
                record['args'] = args

            rest = main_def.group('rest').strip()
            rest = rest[1:-1]
            # remove some junk (also removing braces)
            cleanedup = ''
            while rest:
                if rest[0] != '\\':
                    cleanedup += rest[0]
                    rest = rest[1:]
                    continue

                foundsomething = False

                for badmacro in ['\\comp', '\\dobrackets', '\\maincomp', '\\mathbin', '\\mathrel', '\\mathop']:
                    if rest.startswith(badmacro):
                        rest = rest[len(badmacro):]
                        foundsomething = True
                        # try to also remove braces around
                        if rest.startswith('{'):
                            bracelevel = 1
                            rest = rest[1:]
                            for i, c in enumerate(rest):
                                if c == '{':
                                    bracelevel += 1
                                elif c == '}':
                                    bracelevel -= 1
                                    if bracelevel == 0:
                                        rest = rest[:i] + rest[i + 1:]
                                        break
                        break

                if not foundsomething:
                    cleanedup += rest[0]
                    rest = rest[1:]
            result[cleanedup].append((LocalStexSymbol(uri, path), main_def.group('macroname')))
    return result


@functools.cache
def get_notations() -> dict[str, list[tuple[LocalStexSymbol, str]]]:
    """ collects some notations from smglom """
    all_files = FLAMS.get_all_files()
    result = defaultdict(list)
    for path in all_files:
        # quick-and-dirty filtering
        if 'smglom' in path and path.endswith('.en.tex') and (
            'smglom/sets' in path
        ):
            for notation, symbols in extract_notations_from_file(path).items():
                result[notation].extend(symbols)
    return result


# def get_notations(snify_state: SnifyState) -> dict[str, list[tuple[FlamsUri, str]]]:
#     """ returns notation -> symbol uris
#     (only considers symbols in scope at the moment)
#     """
#     document = snify_state.get_current_document()
#     assert isinstance(document, STeXDocument)
#
#     importinfo = get_modules_in_scope_and_import_locations(document, snify_state.cursor.in_doc_pos)
#
#     result = defaultdict(list)
#
#     for module, path in importinfo.modules_in_scope.items():
#         for notation, uris in extract_notations_from_file(path).items():
#             result[notation].extend(uris)
#
#     return result


@functools.lru_cache(maxsize=2**14)
def get_notation_match(
        notation: str,
        string: str,
) -> Optional[list[tuple[int, int]]]:
    """ if it matches, returns list of argument positions (start, end), else None"""
    notation_regex = re.escape(notation)
    number_of_groups = 0
    for i in range(1, 10):
        if f'\\#{i}' in notation_regex:
            number_of_groups = i
            notation_regex = notation_regex.replace(f'\\#{i}', f'(?P<arg{i}>.+?)')
    notation_regex = f'^{notation_regex}$'
    try:
        match = re.match(notation_regex, string)
    except re.PatternError:
        return None
    if not match:
        return None
    return [match.span(f'arg{i}') for i in range(1, number_of_groups + 1)]
