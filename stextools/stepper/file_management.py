from pathlib import Path

import click

from stextools.core.mathhub import MathHub
from stextools.core.stexdoc import Dependency


def include_inputs(mh: MathHub, files: list[Path]) -> list[Path]:
    """If the files input other files, the user will be asked if those should be included as well.
    The return value is the list of all files that should be processed.
    """
    have_inputs = False
    for file in files:
        stexdoc = mh.get_stex_doc(file)
        if not stexdoc:
            continue
        for dep in stexdoc.get_doc_info(mh).dependencies:
            if dep.is_input:
                have_inputs = True
                break
        if have_inputs:
            break
    if have_inputs and click.confirm(
            'The selected files input other files. Should I include those as well?'
    ):
        all_files: list[Path] = []
        all_files_set: set[Path] = set()
        todo_list = list(reversed(files))
        while todo_list:
            file = todo_list.pop()
            path = file.absolute().resolve()
            if path in all_files_set:
                continue
            stexdoc = mh.get_stex_doc(path)
            if stexdoc:
                all_files.append(path)
                all_files_set.add(path)
                dependencies: list[Dependency] = [
                    dep
                    for dep in stexdoc.get_doc_info(mh).dependencies
                    if dep.is_input
                ]
                # reverse as todo_list is a stack
                dependencies.sort(key=lambda dep: dep.intro_range[0] if dep.intro_range else 0, reverse=True)
                for dep in dependencies:
                    if not dep.is_input:
                        continue
                    target_path = dep.get_target_path(mh, stexdoc)
                    if target_path:
                        todo_list.append(target_path)
            else:
                print(f'File {path} is not loaded')

        return all_files
    else:
        return files
