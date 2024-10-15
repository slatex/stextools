# TODO
# wenn symdecl symbol einführt und danach definiendum kommt, gibt es gerade doppelte einträge
# skip: just press space

import functools
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional, Iterable

import click
from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexGroupNode, LatexMathNode, LatexCommentNode, \
    LatexSpecialsNode, LatexEnvironmentNode, LatexCharsNode

from stextools.cache import Cache
from stextools.linked_str import string_to_lstr, LinkedStr
from stextools.macros import STEX_CONTEXT_DB
from stextools.mathhub import MathHub
from stextools.stexdoc import STeXDocument
from stextools.tree_regex import words_to_regex
from stextools.ui import pale_color, print_options, simple_choice_prompt

logger = logging.getLogger(__name__)


INTRANSPARENT_ENVS: set[str] = {'lstlisting'}
TRANSPARENT_MACROS: set[str] = set()


class FoundWord(Exception):
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end


def doc_path_rel_spec(doc: STeXDocument, stylize_file_name: bool=False) -> str:
    p = doc.get_rel_path()
    if p.endswith('.en.tex'):
        p = p[:-len('.en.tex')]
    l = p.split('/')
    return '/'.join(l[1:-1]) + '?' + (click.style(l[-1], fg='cyan') if stylize_file_name else l[-1])


@functools.cache
def mystem(word: str) -> str:
    import nltk.stem.porter
    if word.isupper():   # acronym
        return word
    if word and word[-1] == 's' and word[:-1].isupper():  # plural acronym
        return word[:-1]
    return ' '.join(nltk.stem.porter.PorterStemmer().stem(w) for w in word.split())


def symbol_is_imported(current_document: STeXDocument, symbdoc: STeXDocument, mh: MathHub) -> bool:
    checked_docs: set[tuple[str, str]] = set()  # (archive, rel_path)
    todo_list: list[tuple[str, str]] = [
        (dep.archive, dep.file)
        for dep in current_document.get_doc_info(mh).flattened_dependencies() if dep.file
    ]
    while todo_list:
        archive_name, rel_path = todo_list.pop()
        if (archive_name, rel_path) in checked_docs:
            continue
        checked_docs.add((archive_name, rel_path))
        # dep_doc = mh.getget_stex_doc(archive_name, rel_path)
        repo = mh.get_archive(archive_name)
        if repo is None:
            continue
        dep_doc = repo.get_stex_doc('source/' + rel_path)
        if dep_doc is None:
            print('Could not find', archive_name, rel_path)
            continue
        if dep_doc.path == symbdoc.path:
            return True
        for dep in dep_doc.get_doc_info(mh).flattened_dependencies():
            if dep.file and not dep.is_use and not dep.is_lib:
                todo_list.append((dep.archive, dep.file))

    return False


def text_and_skipped_words_from_file(path: Path) -> tuple[str, set[str]]:
    lines: list[str] = []
    skip_words: set[str] = set()
    with open(path) as f:
        for line in f:
            if line.startswith('% srskip '):
                for e in line[len('% srskip'):].split(','):
                    e = e.strip()
                    if e:
                        skip_words.add(e)
            else:
                lines.append(line)
    return ''.join(lines), skip_words


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


def get_verb_info(mh: MathHub) -> tuple[set[str], dict[str, list[tuple[str, STeXDocument]]]]:
    skipped = 0
    all_words = set()
    word_to_symb: dict[str, list[tuple[str, STeXDocument]]] = defaultdict(list)
    for archive in mh.iter_stex_archives():
        for doc in archive.stex_doc_iter():
            if not doc.path.name.endswith('.en.tex'):
                continue
            for symb, verbs in doc.get_doc_info(mh).nldefs.items():
                for verb in verbs:
                    if len(verb) < 2:
                        skipped += 1
                        continue
                    verb = mystem(verb)
                    all_words.add(verb)
                    word_to_symb[verb].append((symb, doc))

    return all_words, word_to_symb


def look_for_next_word(all_words: Iterable[str], to_ignore: set[str], text: str) -> Optional[tuple[int, int, int, int]]:
    regex = re.compile(r'\b' + words_to_regex([word for word in all_words if word not in to_ignore]) + r'\b')
    import_insert_pos: Optional[int] = None
    use_insert_pos: Optional[int] = None

    def _recurse(nodes):
        nonlocal import_insert_pos, use_insert_pos

        for node in nodes:
            if node.nodeType() in {LatexMacroNode, LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                if node.nodeType() == LatexMacroNode and node.macroname in TRANSPARENT_MACROS:
                    _recurse(node.nodeargs)
                continue
            elif node.nodeType() == LatexEnvironmentNode:
                if node.nodeType() == LatexEnvironmentNode and \
                        node.environmentname in {'sproblem', 'smodule', 'sdefinition', 'sparagraph', 'document'}:
                    use_insert_pos = node.nodelist[0].pos
                    if node.environmentname == 'smodule':
                        # imports are generally at a higher level - TODO: Is this the correct heuristic?
                        import_insert_pos = node.nodelist[0].pos
                if node.environmentname not in INTRANSPARENT_ENVS:
                    _recurse(node.nodelist)
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
                    raise FoundWord(lstr[match].get_start_ref() + node.pos, lstr[match].get_end_ref() + node.pos)

    walker = LatexWalker(text, latex_context=STEX_CONTEXT_DB)
    try:
        _recurse(walker.get_latex_nodes()[0])
        return None
    except FoundWord as e:
        return e.start, e.end, import_insert_pos, use_insert_pos


class Srifier:
    def __init__(self):
        self.ignore_list = IgnoreList()
        self.mh = Cache.get_mathhub()
        self.all_words, self.word_to_symb = get_verb_info(self.mh)

    def process_file(self, file: str):
        tmp_skip: set[str] = set()
        while True:
            text, skip_words = text_and_skipped_words_from_file(Path(file))

            _r = look_for_next_word(self.all_words, skip_words | tmp_skip | self.ignore_list.word_set, text)
            if _r is None:
                print('No more words found in', file)
                break
            word_start_index, word_end_index, import_insert_pos, use_insert_pos = _r

            word = text[word_start_index:word_end_index]
            click.clear()
            print(click.style(f'{file:-^80}', bg='bright_green'))
            print('...' + text[max(0, word_start_index - 150):word_start_index], end='', sep='')
            print(click.style(word, fg='red', bold=True), end='', sep='')
            print(text[word_end_index:min(len(text), word_end_index + 150)] + '...', sep='')
            print()
            options = [
                ('s', 'kip once'),
                ('S', 'kip always (in this file)'),
                ('r', 'eplace this word'),
                ('i', 'gnore this word forever' + \
                 click.style(f' (word list in {self.ignore_list.path})', fg=pale_color())),
                ('X', ' exit this file')
            ]
            for i, (symb, doc) in enumerate(self.word_to_symb[mystem(word)]):
                options.append((str(i), (
                        ' ' + doc.archive.get_archive_name() +
                        ' ' + doc_path_rel_spec(doc, stylize_file_name=True) + '?' + click.style(symb, fg='green') +
                        '\n        ' + click.style(doc.path, italic=True, fg=pale_color())
                )))
            print_options('Commands:', options)

            print()
            choice = simple_choice_prompt(
                ['S', 's', 'i', 'r', 'X'] + [str(i) for i in range(len(self.word_to_symb[mystem(word)]))]
            )
            if choice == 'X':
                break
            if choice == 'S':
                skip_words.add(mystem(word))
                new_text = text
            elif choice == 's':
                tmp_skip.add(mystem(word))
                new_text = text
            elif choice == 'i':
                self.ignore_list.add(mystem(word))
                new_text = text
            elif choice == 'r':
                new_word = click.prompt('New word:', default=word)
                new_text = text[:word_start_index] + new_word + text[word_end_index:]
            else:  # choice is a number
                # Making a new STeXDocument as the existing one is not guaranteed to be up-to-date
                current_document = STeXDocument(self.mh.get_archive_from_path(Path(file)), Path(file))
                current_document.create_doc_info(self.mh)

                symb, symbdoc = self.word_to_symb[mystem(word)][int(choice)]

                if symbol_is_imported(current_document, symbdoc, self.mh):
                    new_text = text[:word_start_index]
                else:
                    if import_insert_pos is not None:
                        print_options('The symbol has to be imported. Do you want to use', [
                                      ('i', 'mportmodule'),
                                      ('u', 'semodule')
                        ])
                        choice = simple_choice_prompt(['i', 'u'])
                    else:
                        choice = 'u'
                    args = f'[{symbdoc.archive.get_archive_name()}]{{{doc_path_rel_spec(symbdoc)}}}'
                    if choice == 'i':
                        new_text = text[:import_insert_pos] + f'\n  \\importmodule{args}' + \
                                   text[import_insert_pos:word_start_index]
                    else:
                        assert use_insert_pos is not None, 'No use_insert_pos, which means that I could not find the place for inserting the \\usemodule'
                        new_text = text[:use_insert_pos] + f'\n  \\usemodule{args}' + text[use_insert_pos:word_start_index]

                new_text += self.get_sr(symb, word, symbdoc)
                new_text += text[word_end_index:]

            with open(file, 'w') as f:
                f.write(new_text + skipped_words_to_comments(skip_words))

    def get_sr(self, symb: str, word: str, symbdoc: STeXDocument) -> str:
        # check if symbol name is unique
        _docs_that_introduce_symb = set()
        for _l in self.word_to_symb.values():
            for _s, _doc in _l:
                if _s == symb:
                    _docs_that_introduce_symb.add(_doc)
        if len(_docs_that_introduce_symb) > 1:
            prefix = symbdoc.get_rel_path()[:-len(".en.tex")].split('/')[-1] + '?'
        else:
            assert len(_docs_that_introduce_symb) == 1
            prefix = ''

        if word == symb:
            return '\\sn{' + prefix + symb + '}'
        elif word == symb + 's':
            return '\\sns{' + prefix + symb + '}'
        elif word[0] == symb[0].upper() and word[1:] == symb[1:]:
            return '\\Sn{' + prefix + symb + '}'
        elif word[0] == symb[0].upper() and word[1:] == symb[1:] + 's':
            return '\\Sns{' + prefix + symb + '}'
        else:
            return '\\sr{' + prefix + symb + '}' + '{' + word + '}'


def srify(files: list[str]):
    srifier = Srifier()
    for file in files:
        srifier.process_file(file)
