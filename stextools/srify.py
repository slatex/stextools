import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Optional

import click
from pylatexenc.latexwalker import LatexWalker, LatexMacroNode, LatexGroupNode, LatexMathNode, LatexCommentNode, \
    LatexSpecialsNode, LatexEnvironmentNode, LatexCharsNode

from stextools.cache import Cache
from stextools.macros import STEX_CONTEXT_DB
from stextools.mathhub import get_mathhub_path
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


def srify(files: list[str]):
    mh = Cache.get_mathhub()

    skipped = 0

    all_words = set()
    word_to_symb: dict[str, list[tuple[str, STeXDocument]]] = defaultdict(list)
    for archive in mh.iter_stex_archives():
        for doc in archive.stex_doc_iter():
            if not doc.path.name.endswith('.en.tex'):
                continue
            for symb, verbs in doc.get_doc_info(mh).nldefs.items():
                for verb in verbs:
                    if not verb or '?' in verb or len(verb) < 4:
                        skipped += 1
                        continue
                    all_words.add(verb)
                    word_to_symb[verb].append((symb, doc))

    Cache.store_mathhub(mh)

    print('Skipped', skipped, 'words')

    for file in files:
        allowed_words = deepcopy(all_words)

        while True:
            walker = LatexWalker(Path(file).read_text(), latex_context=STEX_CONTEXT_DB)
            regex = re.compile(words_to_regex(allowed_words))

            import_insert_pos: Optional[int] = None

            def _recurse(nodes):
                nonlocal import_insert_pos

                for node in nodes:
                    if node.nodeType() in {LatexMacroNode, LatexMathNode, LatexCommentNode, LatexSpecialsNode}:
                        continue
                    elif node.nodeType() in {LatexGroupNode, LatexEnvironmentNode}:
                        if node.nodeType() == LatexEnvironmentNode and \
                                node.environmentname in {'sproblem', 'smodule', 'sdefinition'}:
                            import_insert_pos = node.nodelist[0].pos
                        _recurse(node.nodelist)
                    else:
                        assert node.nodeType() == LatexCharsNode
                        for match in regex.finditer(node.chars):
                            raise FoundWord(match.start() + node.pos, match.end() + node.pos)

            try:
                _recurse(walker.get_latex_nodes()[0])
                print('done with file')
                break
            except FoundWord as e:
                text = Path(file).read_text()
                word = text[e.start:e.end]
                print('\n' + '~' * 80 + '\n')
                print(text[max(0, e.start - 150):e.start], end='', sep='')
                print(click.style(word, fg='red', bold=True), end='', sep='')
                print(text[e.end:min(len(text), e.end + 150)], sep='')
                print()
                print('Options:')
                opt_style = lambda x: '  ' + click.style(x, bold=True)
                print(opt_style('[S]') + 'kip file')
                print(opt_style('[s]') + 'kip word')
                for i, (symb, doc) in enumerate(word_to_symb[word]):
                    print(opt_style(f'[{i}]'), doc.archive.get_archive_name(), doc_path_rel_spec(doc) + '?' + symb)
                    print('         ', click.style(doc.path, italic=True))

                print()
                choice = click.prompt(
                    click.style('>>> ', reverse=True, bold=True),
                    type=click.Choice(['S', 's'] + [str(i) for i in range(len(word_to_symb[word]))]),
                    show_choices=False, prompt_suffix=''
                )
                if choice == 'S':
                    break
                if choice == 's':
                    allowed_words.remove(word)
                    continue

                git_repo = Path(file).absolute()
                while not (git_repo / '.git').is_dir():
                    git_repo = git_repo.parent

                # Making a new STeXDocument as the existing one is not guaranteed to be up-to-date
                r = mh.get_archive(git_repo.relative_to(get_mathhub_path()).as_posix())
                assert r is not None, f'Could not find archive for {git_repo} in MathHub'
                current_document = STeXDocument(
                    r,
                    Path(file)
                )
                current_document.create_doc_info(mh)

                symb, symbdoc = word_to_symb[word][int(choice)]
                symbol_already_imported = False
                # check if symbdoc is already imported
                checked_docs: set[tuple[str, str]] = set()   # (archive, rel_path
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
                        symbol_already_imported = True
                        break
                    for dep in dep_doc.get_doc_info(mh).flattened_dependencies():
                        if dep.file and not dep.is_use and not dep.is_lib:
                            todo_list.append((dep.archive, dep.file))

                with open(file, 'w') as f:
                    f.write(text[:import_insert_pos])
                    if not symbol_already_imported:
                        f.write(
                            f'\n  \\usemodule[{symbdoc.archive.get_archive_name()}]{{{doc_path_rel_spec(symbdoc)}}}\n'
                        )
                    f.write(text[import_insert_pos:e.start])
                    f.write('\\sr{' + symbdoc.get_rel_path()[:-len(".en.tex")].split('/')[-1] + '?' + symb + '}' +
                            '{' + word + '}')
                    f.write(text[e.end:])
