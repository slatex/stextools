import datetime
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt

paths: list[Path] = [Path(p) for p in sys.argv[1:]]

repo_paths: list[Path] = []

for path in paths:
    for line in subprocess.run(
            ['sh', '-c', 'find -name .git'], cwd=path, capture_output=True, text=True
    ).stdout.splitlines():
        print(line)
        line = line.strip()
        if line:
            repo_paths.append((path / line).parent)


def checkout_date(repo_path: Path, date: datetime.date):
    result = subprocess.run(
        ['sh', '-c', f'git rev-list -n1 --before={date.isoformat()} main | xargs git checkout'],
        cwd=repo_path
    )
    if result.returncode != 0:
        print(f'Error checking out {date.isoformat()} in {repo_path}')


# MacroSpec('sn', '[{'),
# MacroSpec('sns', '[{'),
# MacroSpec('Sn', '[{'),
# MacroSpec('Sns', '[{'),
# MacroSpec('sr', '[{{'),

current_names = ['sn', 'sns', 'Sn', 'Sns', 'sr']
intermediate_names = ['symname', 'Symname', 'symref']
old_names = [
    prefix + core + suff + suffsuff
    for core in ['tref', 'Tref']
    for suff in ['i', 'ii', 'iii', 'iv']
    for suffsuff in ['', 's']
    for prefix in ['', 'm']
]


def anno_count(repo_path: Path):
    regex = re.compile(r'\\(' + '|'.join(current_names + intermediate_names + old_names) + r')[{[]')
    count = 0
    for texfile in repo_path.glob('**/*.tex'):
        if any(x in texfile.name for x in ['all.', 'glossary', 'dictionary']):   # those are generated files
            continue
        try:
            count += len(regex.findall(texfile.read_text()))
        except Exception as e:
            print(e)
            print()
    return count


end_date = datetime.date.today()

HISTORY = {}
HISTORY_BY_REPO = {}

for i in range(100):
    print(i)
    cur_date = end_date - i * datetime.timedelta(days=14)

    HISTORY[cur_date.isoformat()] = 0

    for repo_path in repo_paths:
        checkout_date(repo_path, cur_date)
        HISTORY[cur_date.isoformat()] += anno_count(repo_path)
        HISTORY_BY_REPO.setdefault(str(repo_path), {})[cur_date.isoformat()] = anno_count(repo_path)


with open('history.json', 'w') as f:
    json.dump(HISTORY_BY_REPO, f)


labels_to_show = set(sorted(list(HISTORY.keys()))[::4])


def draw_hist(hist, label):
    vals = []
    for k in sorted(hist.keys()):
        # keys.append(k)
        vals.append(hist[k])

    import random
    plt.plot([b - a + random.random() for a, b in itertools.pairwise(vals)], label=label)


for repo in repo_paths:
    draw_hist(HISTORY_BY_REPO[str(repo)], str(repo))

draw_hist(HISTORY, 'Σ')

plt.xticks(ticks=list(range(len(HISTORY.keys()) - 1)), labels=[k for k in sorted(HISTORY.keys())][1:], rotation=90)

plt.legend()
plt.show()
