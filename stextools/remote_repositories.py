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
    projects = group.projects.list()

    directory = get_mathhub_path() / group.name
    if not directory.exists():
        directory.mkdir(parents=True)

    for project in projects:
        if (directory / project.name).exists():
            print(f'Skipping {project.name} (already exists)')
            continue
        print(f'Cloning {project.ssh_url_to_repo}')
        subprocess.run(['git', 'clone', project.ssh_url_to_repo], check=True, cwd=directory)

    if recurse:
        groups = group.subgroups.list()
        for subgroup in groups:
            clone_group(gl.groups.get(subgroup.full_name.replace(' / ', '/')), recurse)
