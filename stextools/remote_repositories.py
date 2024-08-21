import subprocess

import gitlab
from gitlab.v4.objects import Group

from stextools.mathhub import get_mathhub_path

URL = 'https://gl.mathhub.info'


def get_clone_uri(group, repo):
    return f'git@{URL.split("//")[0].rstrip("/")}:{group}/{repo}.git'


gl: gitlab.Gitlab = gitlab.Gitlab(URL)


def clone_group(group: Group | str, recurse: bool = True):
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
        subprocess.run(['git', 'clone', project.ssh_url_to_repo], check=True, cwd=directory.parent)

    if recurse:
        groups = group.subgroups.list(per_page=1000)
        for subgroup in groups:
            clone_group(gl.groups.get(subgroup.full_name.replace(' / ', '/')), recurse)
