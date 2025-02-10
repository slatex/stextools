import dataclasses
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from stextools.core.cache import Cache
from stextools.core.mathhub import get_mathhub_path
from stextools.core.simple_api import get_linker, get_repos


def run_sh(command: str, cwd: Optional[Path]) -> tuple[str, int]:
    result = subprocess.run(['sh', '-c', command], capture_output=True, text=True, cwd=cwd)

    return result.stdout, result.returncode


def prepare():
    Cache.clear = lambda: None  # type: ignore
    logging.getLogger('pylatexenc.latexwalker').setLevel(logging.WARNING)
    # TODO: the linker indicates both real sTeX issues and missing features – we should not suppress them in general
    logging.getLogger('stextools.core.linker').setLevel(logging.FATAL)
    logging.basicConfig(level=logging.INFO)


current_names = ['sn', 'sns', 'Sn', 'Sns', 'sr']
intermediate_names = ['symname', 'Symname', 'symref']
old_names = [prefix + core + suff + suffsuff for core in ['tref', 'Tref'] for suff in ['i', 'ii', 'iii', 'iv'] for
             suffsuff in ['', 's'] for prefix in ['', 'm']]


def anno_count(repo_path: Path) -> int:
    regex = re.compile(r'\\(' + '|'.join(current_names + intermediate_names + old_names) + r')[{[]')
    count = 0
    for texfile in repo_path.glob('**/*.tex'):
        if any(x in texfile.name for x in ['all.', 'glossary', 'dictionary']):  # those are generated files
            continue
        try:
            count += len(regex.findall(texfile.read_text()))
        except Exception as e:
            print(e)
            print()
    return count


def process_repo(path: Path):
    branch = 'private' if path.name == 'problems' and 'courses/FAU' in path.as_uri() else 'main'
    if 'courses/FAU/EiDA/course' in path.as_uri():
        branch = 'master'
    if 'courses/FAU/GDP/problems' in path.as_uri():
        branch = 'main'
    _, code = run_sh(f'git checkout {branch}', path)
    assert code == 0, f'Error checking out {branch} in {path}'
    history, code = run_sh("git log --pretty='format:%H!%ci!%cn'", path)
    assert code == 0, f'Error getting history in {path}'
    for line in history.splitlines():
        if not line.strip():
            continue
        commit_hash, date, creator = line.split('!')
        if commit_hash in HISTORY_DATA:
            continue
        _, code = run_sh(f'git checkout {commit_hash}', path)
        assert code == 0, f'Error checking out {commit_hash} in {path}'
        count = anno_count(path)
        HISTORY_DATA[commit_hash] = CommitInfo(
            date, count, creator, commit_hash, str(path.relative_to(get_mathhub_path()))
        )
    _, code = run_sh(f'git checkout {branch}', path)


@dataclasses.dataclass
class CommitInfo:
    date: str
    anno_count: int
    creator: str
    commit_hash: str
    repo: str

    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    def date_as_datetime(self) -> datetime:
        return datetime.strptime(self.date, "%Y-%m-%d %H:%M:%S %z")

    @classmethod
    def from_json(cls, data: dict) -> 'CommitInfo':
        return cls(**data)


HISTORY_DATA: dict[str, CommitInfo] = {}  # hash -> CommitInfo

_HIST_PATH = Path(__file__).parent / 'history.json'


def load_history():
    hist_data = {}
    if _HIST_PATH.exists():
        with open(_HIST_PATH, 'r') as f:
            for key, val in json.load(f).items():
                hist_data[key] = CommitInfo.from_json(val)
    return hist_data


def save_history():
    with open(_HIST_PATH, 'w') as f:
        json.dump({
            key: val.to_json() for key, val in HISTORY_DATA.items()
        }, f)  # type: ignore


def main():
    global HISTORY_DATA
    prepare()
    HISTORY_DATA = load_history()
    linker = get_linker()
    repos = get_repos(linker)

    try:
        for repo in repos:
            print(f'Processing {repo.path}')
            process_repo(repo.path)
    except KeyboardInterrupt:
        pass
    finally:
        save_history()


if __name__ == '__main__':
    main()
