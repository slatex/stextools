# TODO
# documents sollte als "electronic document" annotiert werden
import functools
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import click
from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexGroupNode, LatexMathNode, LatexCommentNode, \
    LatexSpecialsNode, LatexEnvironmentNode, LatexCharsNode

from stextools.cache import Cache
from stextools.linked_str import string_to_lstr, LinkedStr
from stextools.macros import STEX_CONTEXT_DB
from stextools.mathhub import MathHub
from stextools.stexdoc import STeXDocument
from stextools.tree_regex import words_to_regex


class FoundWord(Exception):
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end


def doc_path_rel_spec(doc: STeXDocument) -> str:
    p = doc.get_rel_path()
    if p.endswith('.en.tex'):
        p = p[:-len('.en.tex')]
    l = p.split('/')
    return '/'.join(l[1:-1]) + '?' + l[-1]


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


def srify(files: list[str]):
    mh = Cache.get_mathhub()
    mh.load_all_doc_infos()   # Doing it now (and not later) to take advantage of multiprocessing implementation

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

    Cache.store_mathhub(mh)

    # print('Skipped', skipped, 'words')

    for file in files:
        tmp_skip: set[str] = set()
        while True:
            text, skip_words = text_and_skipped_words_from_file(Path(file))
            walker = LatexWalker(Path(file).read_text(), latex_context=STEX_CONTEXT_DB)
            regex = re.compile(r'\b' + words_to_regex([word for word in all_words if word not in skip_words and word not in tmp_skip]) + r'\b')

            import_insert_pos: Optional[int] = None
            use_insert_pos: Optional[int] = None

            def _recurse(nodes):
                nonlocal import_insert_pos, use_insert_pos

                for node in nodes:
                    if node.nodeType() in {LatexMacroNode, LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                        continue
                    elif node.nodeType() in {LatexGroupNode, LatexEnvironmentNode}:
                        if node.nodeType() == LatexEnvironmentNode and \
                                node.environmentname in {'sproblem', 'smodule', 'sdefinition', 'sparagraph', 'document'}:
                            use_insert_pos = node.nodelist[0].pos
                            if node.environmentname == 'smodule':
                                # imports are generally at a higher level - TODO: Is this the correct heuristic?
                                import_insert_pos = node.nodelist[0].pos
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

            try:
                _recurse(walker.get_latex_nodes()[0])
                print('done with file')
                break
            except FoundWord as e:
                word = text[e.start:e.end]
                # print('\n' + '~' * 80 + '\n')
                click.clear()
                print('...' + text[max(0, e.start - 150):e.start], end='', sep='')
                print(click.style(word, fg='red', bold=True), end='', sep='')
                print(text[e.end:min(len(text), e.end + 150)] + '...', sep='')
                print()
                print('Options:')
                opt_style = lambda x: '  ' + click.style(x, bold=True)
                print(opt_style('[s]') + 'kip once')
                print(opt_style('[S]') + 'kip always (in this file)')
                print(opt_style('[X]') + ' exit this file')
                for i, (symb, doc) in enumerate(word_to_symb[mystem(word)]):
                    print(opt_style(f'[{i}]'), doc.archive.get_archive_name(), doc_path_rel_spec(doc) + '?' + symb)
                    print('         ', click.style(doc.path, italic=True))

                print()
                choice = click.prompt(
                    click.style('>>> ', reverse=True, bold=True),
                    type=click.Choice(['S', 's', 'X'] + [str(i) for i in range(len(word_to_symb[mystem(word)]))]),
                    show_choices=False, prompt_suffix=''
                )
                if choice == 'X':
                    break
                if choice == 'S':
                    skip_words.add(mystem(word))
                    new_text = text
                elif choice == 's':
                    tmp_skip.add(mystem(word))
                    new_text = text
                else:
                    # Making a new STeXDocument as the existing one is not guaranteed to be up-to-date
                    current_document = STeXDocument(mh.get_archive_from_path(Path(file)), Path(file))
                    current_document.create_doc_info(mh)

                    symb, symbdoc = word_to_symb[mystem(word)][int(choice)]

                    if symbol_is_imported(current_document, symbdoc, mh):
                        new_text = text[:e.start]
                    else:
                        if import_insert_pos is not None:
                            print('The symbol has to be imported. Do you want to use')
                            print(opt_style('[i]') + 'mportmodule')
                            print(opt_style('[u]') + 'semodule')
                            print()
                            choice = click.prompt(
                                click.style('>>> ', reverse=True, bold=True),
                                type=click.Choice(['i', 'u']),
                                show_choices=False, prompt_suffix=''
                            )
                        else:
                            choice = 'u'
                        args = f'[{symbdoc.archive.get_archive_name()}]{{{doc_path_rel_spec(symbdoc)}}}'
                        if choice == 'i':
                            new_text = text[:import_insert_pos] + f'\n  \\importmodule{args}' + \
                                       text[import_insert_pos:e.start]
                        else:
                            assert use_insert_pos is not None, 'No use_insert_pos, which means that I could not find the place for inserting the \\usemodule'
                            new_text = text[:use_insert_pos] + f'\n  \\usemodule{args}' + text[use_insert_pos:e.start]

                    # check if symbol name is unique
                    _docs_that_introduce_symb = set()
                    for _l in word_to_symb.values():
                        for _s, _doc in _l:
                            if _s == symb:
                                _docs_that_introduce_symb.add(_doc)
                    if len(_docs_that_introduce_symb) > 1:
                        prefix = symbdoc.get_rel_path()[:-len(".en.tex")].split('/')[-1] + '?'
                    else:
                        assert len(_docs_that_introduce_symb) == 1
                        prefix = ''

                    if word == symb:
                        new_text += '\\sn{' + prefix + symb + '}'
                    elif word == symb + 's':
                        new_text += '\\sns{' + prefix + symb + '}'
                    elif word[0] == symb[0].upper() and word[1:] == symb[1:]:
                        new_text += '\\Sn{' + prefix + symb + '}'
                    elif word[0] == symb[0].upper() and word[1:] == symb[1:] + 's':
                        new_text += '\\Sns{' + prefix + symb + '}'
                    else:
                        new_text += '\\sr{' + prefix + symb + '}' + '{' + word + '}'
                    new_text += text[e.end:]

                with open(file, 'w') as f:
                    f.write(new_text + skipped_words_to_comments(skip_words))
