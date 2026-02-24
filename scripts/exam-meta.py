from pathlib import Path
import os
import re
import subprocess

import sys

def get_last_commit_date(path):
    result = subprocess.run(
            ['git', 'log', '-1', '--pretty=format:%cs', str(path.absolute())],
            stdout=subprocess.PIPE,
            cwd=path.parent
    )
    if result.returncode != 0:
        print(f'Error getting git log for {path}: {result.stderr.decode()}')
        return None
    return result.stdout.decode().strip()


MATHHUB = os.getenv('MATHHUB','')
assert MATHHUB
MATHHUB = Path(MATHHUB)

courses = (MATHHUB / 'courses' / 'FAU').glob('*')

for course in courses:
    # if course.name != 'AI': continue
    if not course.is_dir():
        print('Not a directory:', course)
        continue
    
    coursename = course.name

    hwexamsources = course / 'hwexam' / 'source'

    if not hwexamsources.is_dir():
        print(f'No exam source for {coursename}:', hwexamsources)
        continue

    
    semdirs = hwexamsources.glob('*')  # semester directory
    for semdir in semdirs:
        if not semdir.is_dir():
            continue

        semname = semdir.name
        if not re.match(r'^[WS]S[0-9]{2,4}$', semname):
            print(f'Invalid semester directory name {semname} in {coursename}')
            continue

        for path in semdir.rglob('*.tex'):
            exammatch = re.match(r'^(orig\.)?(retake|exam|retake-exam)(\.en)?\.tex$', path.name, re.IGNORECASE)
            quizmatch = re.match(r'^quiz(?P<num>[0-9]+)(\.en)?\.tex$', path.name, re.IGNORECASE)
            hwmatch = re.match(r'^(hw|a)(?P<num>[0-9]+)(\.en)?\.tex$', path.name, re.IGNORECASE)
            mode = None
            if exammatch:
                mode = 'exam'
            elif quizmatch:
                mode = 'quiz'
            elif hwmatch:
                mode = 'homework'
            if not mode:
                continue
            num = None
            if mode in {'quiz', 'homework'}:
                num = int(quizmatch.group('num') if mode == 'quiz' else hwmatch.group('num'))

            content = path.read_text(encoding='utf-8')
            if f'\\{mode}data' in content:
                print(f'\\{mode}data already present in {path}')
                continue

            date = re.search(r'\\date\{([^}]*)\}', content)
            if date:
                date_str = date.group(1)
            else:
                date_str = None
            # if date_str is None and mode != 'exam':
            #     d = get_last_commit_date(path)
            #     if d[2:4] in semname:   # quick and dirty hack to ignore dates from late refactoring commits
            #         date_str = d

            data = {
                'course': coursename,
                'term': semname,
            }
            if date_str:
                data['date'] = date_str
            if mode == 'exam':
                data['retake'] = 'true' if 'retake' in path.name.lower() else 'false'
            annotation = f'\n\\{mode}data{{\n    ' + ',\n    '.join(f'{k}={{{v}}}' for k, v in data.items()) + '\n}\n'

            print('+++++++++++++++++++++++')
            print(f'File: {path}')
            print(annotation)
            print('+++++++++++++++++++++++')

            if len(sys.argv) > 1 and sys.argv[1] == '--write':
                path.write_text(
                        content.replace(r'\begin{document}', annotation + r'\begin{document}'),
                        )
            else:
                print(f'Run with --write to update {path}')

