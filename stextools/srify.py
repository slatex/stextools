# TODO
# wenn symdecl symbol einführt und danach definiendum kommt, gibt es gerade doppelte einträge
# skip: just press space
import dataclasses
import functools
import itertools
import logging
import re
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Optional, Iterable, Callable

import click
from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexGroupNode, LatexMathNode, LatexCommentNode, \
    LatexSpecialsNode, LatexEnvironmentNode, LatexCharsNode

from stextools import ui

from stextools.cache import Cache
from stextools.linked_str import string_to_lstr, LinkedStr
from stextools.macros import STEX_CONTEXT_DB
from stextools.mathhub import MathHub, make_filter_fun
from stextools.stexdoc import STeXDocument, Dependency
from stextools.tree_regex import words_to_regex
from stextools.ui import pale_color, print_options, simple_choice_prompt, width, color

try:
    import pygments
except ImportError:
    pygments = None
    print(click.style(f'{"Warning":^{width()}}', bold=True, bg='bright_yellow'))
    print()
    print('Failed to import `pygments` – syntax highlighting will be unvailable')
    print('Consider installing it with')
    print('    pip install pygments')
    print()
    click.pause('Press any key to continue...')



logger = logging.getLogger(__name__)

INTRANSPARENT_ENVS: set[str] = {'lstlisting'}
TRANSPARENT_MACROS: set[str] = set()


def latex_format(code: str) -> str:
    if pygments is not None:
        from pygments import highlight
        from pygments.lexers import TexLexer
        if ui.USE_24_BIT_COLORS:
            from pygments.formatters import TerminalTrueColorFormatter as TerminalFormatter
        else:
            from pygments.formatters import TerminalFormatter

        # leading and trailing newlines are removed by pygments
        leading = len(code) - len(code.lstrip('\n'))
        trailing = len(code) - len(code.rstrip('\n'))
        return (
                '\n' * leading +
                highlight(code, TexLexer(), TerminalFormatter(style='vs')).strip('\n') +
                '\n' * trailing
        )
    return code


class FoundWord(Exception):
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end


def symbol_path_without_archive(doc: STeXDocument, doc_internal_symbol_path: str, stylize: bool = False,
                                include_symbol: bool = True) -> str:
    p = doc.get_rel_path()
    if p.endswith('.en.tex'):
        p = p[:-len('.en.tex')]
    l = p.split('/')[1:]   # drop 'source'

    # TODO: does not work for nested modules, but should only result in redundant information
    mod_name = doc_internal_symbol_path.partition('?')[0]
    if mod_name == l[-1]:
        l = l[:-1]

    symb_name = doc_internal_symbol_path.rpartition('?')[-1]
    suffix = '?' + (click.style(symb_name, bg=color('bright_green', (180, 255, 180))) if stylize else symb_name)  # symbol
    if not include_symbol:
        suffix = ''

    return (
            '/'.join(l) + '?' +   # path
            (click.style(mod_name, bg=color('bright_cyan', (180, 180, 255))) if stylize else mod_name) + # module
            suffix  # symbol (if requested)
    )



@functools.cache
def mystem(word: str) -> str:
    import nltk.stem.porter
    if word.isupper():  # acronym
        return word
    if word and word[-1] == 's' and word[:-1].isupper():  # plural acronym
        return word[:-1]
    return ' '.join(nltk.stem.porter.PorterStemmer().stem(w) for w in word.split())


def symbol_is_imported(current_document: STeXDocument, symb_info: 'SymbInfo', mh: MathHub, offset: int) -> bool:
    checked_docs: set[tuple[str, str, Optional[str]]] = set()  # (archive, rel_path, module)
    todo_list: list[Dependency] = [
        dep
        for dep in current_document.get_doc_info(mh).flattened_dependencies() if dep.file and dep.valid_range[0] <= offset <= dep.valid_range[1]
    ]

    def get_doc(archive_name: str, rel_path: str) -> Optional[STeXDocument]:
        repo = mh.get_archive(archive_name)
        if repo is None:
            return None
        return repo.get_stex_doc('source/' + rel_path)

    while todo_list:
        dep = todo_list.pop()
        if (dep.archive, dep.file, dep.module_name) in checked_docs:
            continue
        checked_docs.add((dep.archive, dep.file, dep.module_name))
        dep_doc = get_doc(dep.archive, dep.file)
        if dep_doc is None:
            print('Could not find', dep.archive, dep.file)
            continue
        if dep_doc.path == symb_info.document.path and dep.module_name == symb_info.symbol_path_in_doc.partition('?')[0]:
            return True
        for dep_dep in dep_doc.get_doc_info(mh).flattened_dependencies():
            if dep.module_name:
                module_range = dep.valid_range
                if not (module_range[0] <= dep_dep.intro_range[0] <= module_range[1]):
                    continue

            if dep.file and not dep.is_use and not dep.is_lib:
                todo_list.append(dep)

    return False


def text_and_skipped_words_from_file(edit_state: 'EditState'):
    lines: list[str] = []
    skip_words: set[str] = set()
    with open(edit_state.file) as f:
        for line in f:
            if line.startswith('% srskip '):
                for e in line[len('% srskip'):].split(','):
                    e = e.strip()
                    if e:
                        skip_words.add(e)
            else:
                lines.append(line)
    edit_state.text = ''.join(lines)
    edit_state.skip_words = skip_words
    edit_state.new_text = edit_state.text


def skipped_words_to_comments(skip_words: set[str]) -> str:
    lines: list[str] = []
    current_line = '% srskip'
    for word in skip_words:
        if len(current_line) + len(word) + 2 > 80:
            lines.append(current_line)
            current_line = '% srskip ' + word + ','
        else:
            current_line += ' ' + word + ','
    if current_line != '% srskip':
        lines.append(current_line)
    if lines:
        return '\n'.join(lines) + '\n'
    return ''


class IgnoreList:
    _ignore_list: Optional['IgnoreList'] = None

    def __new__(cls):  # singleton...
        if cls._ignore_list is None:
            cls._ignore_list = super().__new__(cls)
        return cls._ignore_list

    def __init__(self):
        self.path = Path('~/.config/stextools/srify_ignore').expanduser()
        self.path.parent.mkdir(exist_ok=True)
        if not self.path.exists():
            self.path.write_text('')
            logger.info(f'Created {self.path}')
        self.word_list: list[str] = []
        with open(self.path) as f:
            for line in f:
                word = line.strip()
                if word:
                    self.word_list.append(word)
        self.word_set: set[str] = set(self.word_list)
        logger.info(f'Loaded {len(self.word_list)} words from {self.path}')

    def add(self, word: str):
        if word not in self.word_set:
            self.word_set.add(word)
            self.word_list.append(word)
            self.path.write_text('\n'.join(self.word_list) + '\n')


@dataclasses.dataclass
class SymbInfo:
    # info for a particular usage if a symbol (e.g. a in a \definiendum)
    document: STeXDocument
    symbol_path_in_doc: str
    declaration_range: tuple[int, int]

    def __post_init__(self):
        self.symbol_short = self.symbol_path_in_doc.rpartition('?')[-1]


def get_verb_info(mh: MathHub, filter_fun: Callable[[str], bool]) \
        -> tuple[set[str], dict[str, list[SymbInfo]]]:
    all_words = set()
    word_to_symb: dict[str, list[SymbInfo]] = defaultdict(list)
    for archive in mh.iter_stex_archives():
        if not filter_fun(archive.get_archive_name()):
            continue
        for doc in archive.stex_doc_iter():
            if not doc.path.name.endswith('.en.tex'):
                continue
            for module in doc.get_doc_info(mh).iter_modules():
                for symb in module.symbols:
                    symb_name = module.name + '?' + symb.name
                    verbs = symb.verbalizations
                    # if not verbs and symb.decl_def:
                    #     verbs = [symb.name, *symb.decl_def]   # use symbol name if no other verbalizations are given
                    if verbs:
                        verbs = verbs[1:] + [verbs[0]]  # (first verbalization is often declaration - less interesting for viewing)

                    already_listed_verbs = set()
                    for verb, start, stop in verbs:
                        if len(verb) < 2:
                            continue
                        verb = mystem(verb)
                        if verb in already_listed_verbs:
                            continue
                        already_listed_verbs.add(verb)
                        all_words.add(verb)
                        word_to_symb[verb].append(SymbInfo(doc, symb_name, (start, stop)))
    return all_words, word_to_symb


def look_for_next_word(all_words: Iterable[str], to_ignore: set[str], text: str) -> Optional[tuple[int, int, Optional[int], Optional[int]]]:
    regex_core = words_to_regex([word for word in all_words if word not in to_ignore])
    if not regex_core:
        return None
    regex = re.compile(r'\b' + regex_core + r'\b')
    import_insert_pos: list[int] = []  # stack
    use_insert_pos: list[int] = []

    def _recurse(nodes):
        for node in nodes:
            if node.nodeType() in {LatexMacroNode, LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                if node.nodeType() == LatexMacroNode and node.macroname in TRANSPARENT_MACROS:
                    _recurse(node.nodeargs)
                continue
            elif node.nodeType() == LatexEnvironmentNode:
                to_pop = []
                if node.nodeType() == LatexEnvironmentNode and \
                        node.environmentname in {'sproblem', 'smodule', 'sdefinition', 'sparagraph', 'document', 'frame'}:
                    use_insert_pos.append(node.nodelist[0].pos)
                    to_pop.append(use_insert_pos)
                    if node.environmentname == 'smodule':
                        # imports are generally at a higher level - TODO: Is this the correct heuristic?
                        import_insert_pos.append(node.nodelist[0].pos)
                        to_pop.append(import_insert_pos)
                if node.environmentname not in INTRANSPARENT_ENVS:
                    _recurse(node.nodelist)
                    for l in to_pop:
                        l.pop()
            elif node.nodeType() == LatexGroupNode:
                _recurse(node.nodelist)
            else:
                assert node.nodeType() == LatexCharsNode
                lstr: LinkedStr = string_to_lstr(node.chars)
                lstr = lstr.normalize_spaces()
                replacements = []
                # replace words with their stems
                for match in re.finditer(r'\b\w+\b', str(lstr)):
                    word = lstr[match]
                    replacements.append((match.start(), match.end(), mystem(str(word))))
                lstr = lstr.replacements_at_positions(replacements, positions_are_references=False)
                for match in regex.finditer(str(lstr)):
                    print('found match', match, lstr[match])
                    raise FoundWord(lstr[match].get_start_ref() + node.pos, lstr[match].get_end_ref() + node.pos)

    walker = LatexWalker(text, latex_context=STEX_CONTEXT_DB)
    try:
        _recurse(walker.get_latex_nodes()[0])
        return None
    except FoundWord as e:
        return e.start, e.end, import_insert_pos[-1] if import_insert_pos else None, use_insert_pos[-1] if use_insert_pos else None


@dataclasses.dataclass
class EditState:
    file: Path
    tmp_skip: set[str] = dataclasses.field(default_factory=set)
    previous_edit_state: Optional['EditState'] = None
    text: str = ''
    skip_words: set[str] = dataclasses.field(default_factory=set)
    new_text: str = ''
    word_start_index: int = 0
    word_end_index: int = 0
    import_insert_pos: Optional[int] = None
    use_insert_pos: Optional[int] = None
    undoable: bool = False
    no_new_search: bool = False

    @property
    def word(self) -> str:
        return self.text[self.word_start_index:self.word_end_index]


class Srifier:
    def __init__(self, filter_fun: Callable[[str], bool]):
        self.ignore_list = IgnoreList()
        self.mh = Cache.get_mathhub(update_all=True)
        self.all_words, self.word_to_symb = get_verb_info(self.mh, filter_fun)
        if not self.all_words:
            raise click.ClickException('No words found...')
        self.main_commands: list[tuple[str, str]] = [
            ('h', 'elp (show all commands)'),
            ('s', 'kip once'),
            ('S', 'kip always (in this file)'),
            ('i', 'gnore this word forever' + \
             click.style(f' (word list in {self.ignore_list.path})', fg=pale_color())),
        ]
        _it_i = click.style('i', bold=False, italic=True)
        self.other_commands: list[tuple[str, str]] = [
            ('r', 'eplace this word'),
            ('u', 'ndo the last change to the file'),
            ('X', ' exit this file'),
            ('q', 'uit the program'),
        ]

        self.other_commands_only_print: list[tuple[str, str]] = [
            ('v' + _it_i, f' view the document of the {_it_i}-th symbol suggestion'),
        ]

    def get_commmand(self, word: str) -> str:
        options = self.main_commands[:]
        extra_keys = []
        for i, symb_info in enumerate(self.word_to_symb[mystem(word)]):
            extra_keys.append((f'v{i}', ''))
            doc = symb_info.document
            options.append((str(i), (
                    ' ' + doc.archive.get_archive_name() +
                    ' ' + symbol_path_without_archive(doc, symb_info.symbol_path_in_doc, stylize=True) +
                    '\n        ' + click.style(doc.path, italic=True, fg=pale_color())
            )))
        print_options('Commands:', options)

        print()
        choice = simple_choice_prompt(
            [e[0] for e in itertools.chain(options, self.other_commands, extra_keys)],
        )
        return choice

    def show_help(self):
        click.clear()
        print(click.style(f'{"Help":^{width()}}', bold=True, bg='bright_yellow'))
        print()
        print_options('Main commands:', self.main_commands)
        print()
        print_options('Other commands:', self.other_commands + self.other_commands_only_print)
        print()
        click.pause('Press any key to continue...')

    def get_text_with_import(self, current_document: STeXDocument, symb_info: SymbInfo, e: EditState) -> str:
        if symbol_is_imported(current_document, symb_info, self.mh, e.word_start_index):
            return e.text[:e.word_start_index]

        if e.import_insert_pos is not None:
            print_options('The symbol has to be imported. Do you want to use', [
                ('i', 'mportmodule'),
                ('u', 'semodule'),
                ('v', 'view document'),
            ])
            print()
            print('Document:', str(symb_info.document.path))
            command = simple_choice_prompt(['i', 'u', 'v'])
        else:
            command = 'u'
        if command == 'v':
            print(click.style(f'{str(symb_info.document.path):^{width()}}', bold=True, bg='bright_green'))
            print()
            click.echo_via_pager(latex_format(symb_info.document.path.read_text()))
            return self.get_text_with_import(current_document, symb_info, e)

        args = ''
        if symb_info.document.archive != current_document.archive:
            args += f'[{symb_info.document.archive.get_archive_name()}]'
        args += f'{{{symbol_path_without_archive(symb_info.document, symb_info.symbol_path_in_doc, include_symbol=False)}}}'
        insert_pos: int
        import_command: str
        if command == 'i':
            insert_pos = e.import_insert_pos
            import_command = '\\importmodule'
        else:
            assert e.use_insert_pos is not None, 'No use_insert_pos, which means that I could not find the place for inserting the \\usemodule'
            insert_pos = e.use_insert_pos
            import_command = '\\usemodule'
        indentation = ''
        for i in range(insert_pos + 1, e.word_start_index):
            if e.text[i] == ' ':
                indentation += ' '
            else:
                break

        new_text = e.text[:insert_pos] + f'\n{indentation}{import_command}{args}' + e.text[insert_pos:e.word_start_index]

        return new_text

    def print_doc_with_highlight(self, filename: str, text: str, start: int, end: int):
        context_size = 7
        start_index = start
        for _ in range(context_size):
            if start_index > 0:
                start_index -= 1
            while start_index > 0 and text[start_index - 1] != '\n':
                start_index -= 1

        end_index = end
        for _ in range(context_size):
            if end_index + 1 < len(text):
                end_index += 1
            while end_index + 1 < len(text) and text[end_index + 1] != '\n':
                end_index += 1
        end_index += 1

        print(click.style(f'{filename:^{width()}}', bold=True, bg='bright_green'))
        doc = latex_format(text[start_index:start])
        doc += click.style(text[start:end], bg='bright_yellow', bold=True)
        doc += latex_format(text[end:end_index])
        lineno_start = text[:start_index].count('\n') + 1
        for i, line in enumerate(doc.split('\n'), lineno_start):
            print(click.style(f'{i:4} ', fg=pale_color()) + line)

    def notify_user(self, message: str, type: str):
        assert type in {'error', 'info'}
        print()
        print(click.style(f'{type.upper():^{width()}}', bg='bright_cyan' if type == 'info' else 'bright_red', bold=True))
        print()
        print(message)
        print()
        click.pause('Press any key to continue...')

    def look_for_next_word(self, edit_state: EditState) -> bool:
        _r = look_for_next_word(
            self.all_words, edit_state.skip_words | edit_state.tmp_skip | self.ignore_list.word_set, edit_state.text
        )
        if _r is None:
            print('No more words found in', str(edit_state.file))
            return False
        edit_state.word_start_index, edit_state.word_end_index, edit_state.import_insert_pos, edit_state.use_insert_pos = _r
        return True

    def process_file(self, file: str):
        edit_state = EditState(file=Path(file))
        text_and_skipped_words_from_file(edit_state)
        old_state = deepcopy(edit_state)
        while True:
            if edit_state.undoable:
                edit_state.undoable = False
                edit_state = deepcopy(edit_state)
                edit_state.previous_edit_state = old_state
                old_state = deepcopy(edit_state)
            if edit_state.no_new_search:
                edit_state.no_new_search = False
            else:
                text_and_skipped_words_from_file(edit_state)
                if not self.look_for_next_word(edit_state):   # also modifies edit_state
                    break

            click.clear()
            self.print_doc_with_highlight(str(edit_state.file), edit_state.text, edit_state.word_start_index, edit_state.word_end_index)
            print()
            command = self.get_commmand(edit_state.word)

            if command == 'X':
                break
            if command == 'S':
                edit_state.skip_words.add(mystem(edit_state.word))
                edit_state.new_text = edit_state.text
                edit_state.undoable = True
            elif command == 's':
                edit_state.tmp_skip.add(mystem(edit_state.word))
                edit_state.undoable = True
            elif command == 'i':
                self.ignore_list.add(mystem(edit_state.word))
            elif command == 'r':
                new_word = click.prompt('New word:', default=edit_state.word)
                edit_state.new_text = edit_state.text[:edit_state.word_start_index] + new_word + \
                                      edit_state.text[edit_state.word_end_index:]
                # TODO: should we set this for the next iteration and do no_new_search?
                edit_state.undoable = True
            elif command == 'h':
                self.show_help()
            elif command.startswith('v'):
                symb_info = self.word_to_symb[mystem(edit_state.word)][int(command[1:])]
                self.print_doc_with_highlight(
                    str(symb_info.document.path),
                    symb_info.document.path.read_text(),
                    symb_info.declaration_range[0],
                    symb_info.declaration_range[1]
                )
                print()
                click.pause('Press any key to continue...')
            elif command.isdigit():
                repo = self.mh.get_archive_from_path(Path(file))
                current_document = repo.get_stex_doc(str(Path(file).absolute().relative_to(repo.path)))
                current_document.delete_doc_info_if_outdated()

                symb_info = self.word_to_symb[mystem(edit_state.word)][int(command)]
                new_text = self.get_text_with_import(current_document, symb_info, edit_state)
                new_text += self.get_sr(symb_info, edit_state.word)
                new_text += edit_state.text[edit_state.word_end_index:]
                edit_state.new_text = new_text
                edit_state.undoable = True
            elif command == 'u':
                if not edit_state.previous_edit_state:
                    self.notify_user('Nothing to undo', 'error')
                    continue
                edit_state = edit_state.previous_edit_state
                old_state = deepcopy(edit_state)
            elif command == 'q':
                print('Goodbye!')
                sys.exit(0)
            else:
                raise RuntimeError(f'Internal error: unexpected command {command}')

            new_content = edit_state.new_text + skipped_words_to_comments(edit_state.skip_words)
            with open(file, 'w') as f:
                f.write(new_content)

    def get_sr(self, symb: SymbInfo, word: str) -> str:
        # check if symbol name is unique
        _docs_that_introduce_symb = set()
        for _l in self.word_to_symb.values():
            for symb_info in _l:
                if symb_info.symbol_short == symb.symbol_short:
                    _docs_that_introduce_symb.add(symb_info.document)

        symb_path = symb.symbol_path_in_doc
        symb_name = symb_path.rpartition('?')[-1]
        if len(_docs_that_introduce_symb) == 1:
            symb_path = symb_name

        if word == symb_path:
            return '\\sn{' + symb_path + '}'
        elif word == symb_path + 's':
            return '\\sns{' + symb_path + '}'
        elif word[0] == symb_path[0].upper() and word[1:] == symb_path[1:]:
            return '\\Sn{' + symb_path + '}'
        elif word[0] == symb_path[0].upper() and word[1:] == symb_path[1:] + 's':
            return '\\Sns{' + symb_path + '}'
        else:
            return '\\sr{' + symb_path + '}' + '{' + word + '}'


def srify(files: list[str], filter: str, ignore: str):
    srifier = Srifier(make_filter_fun(filter, ignore))
    for file in files:
        srifier.process_file(file)
