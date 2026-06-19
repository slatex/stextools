import functools
import os
import subprocess
from pathlib import Path
from typing import Optional

import gitlab
from gitlab.v4.objects import Group

from stextools.stepper.interface import interface


@functools.cache
def get_mathhub_path() -> Path:
    path_str = os.environ.get("MATHHUB")
    if path_str is None:
        raise RuntimeError("MATHHUB environment variable not set")
    if ',' in path_str:
        path_str = path_str.split(',')[0]
        if not interface.ask_yes_no(f'MATHHUB variable contains multiple paths. Is it ok if I use {path_str}?'):
            raise RuntimeError("Currently there is no support to choose a different path")
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"MATHHUB path {path} does not exist")
    return path


def get_containing_archive(path: Path) -> Optional[Path]:
    while path and not (path / '.git').exists():
        path = path.parent
    if path:
        return path
    return None



URL = 'https://gl.mathhub.info'


gl: gitlab.Gitlab = gitlab.Gitlab(URL)


def clone_group(group: Group | str, recurse: bool = True, use_ssh: bool = True):
    if isinstance(group, str):
        group = gl.groups.get(group)
    # TODO: deal properly with pagination (also below for subgroups)
    projects = group.projects.list(per_page=1000)

    for project in projects:
        directory = get_mathhub_path() / project.path_with_namespace
        if not directory.parent.exists():
            directory.parent.mkdir(parents=True)
        if directory.exists():
            print(f'Skipping {project.name} (already exists)')
            continue

        url = project.ssh_url_to_repo if use_ssh else project.http_url_to_repo
        subprocess.run(['git', 'clone', url], check=True, cwd=directory.parent)

    if recurse:
        groups = group.subgroups.list(per_page=1000)
        for subgroup in groups:
            clone_group(gl.groups.get(subgroup.full_name.replace(' / ', '/')), recurse)
