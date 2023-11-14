from stextools.mathhub import MathHub
import sys

if len(sys.argv) != 2 or sys.argv[1] not in {'test', 'write', 'ask'}:
    print('Usage: python dependency_check.py test|write|ask')
    sys.exit(1)

mh = MathHub()
mh.load_all_doc_infos()

for archive in mh.iter_stex_archives():
    needed_dependencies = set(
        dep.archive for doc in archive.stex_doc_iter() for dep in doc.get_doc_info(mh).flattened_dependencies()
    )
    needed_dependencies.add('sTeX/meta-inf')
    new_dependencies: list[str] = []
    manifest = archive.get_manifest()
    for dependency in manifest.get_dependencies():
        if dependency.startswith('MMT'):   # keep them (not sure if we can correctly identify if we need them)
            new_dependencies.append(dependency)
        elif dependency in needed_dependencies:
            new_dependencies.append(dependency)
    for dependency in needed_dependencies:
        if dependency == archive.get_archive_name():   # no self-dependencies
            continue
        if dependency not in new_dependencies:
            new_dependencies.append(dependency)

    print(f'Updating {manifest.path}:')
    print(f'Old dependencies: {manifest["dependencies"]}')
    print(f'New dependencies: {",".join(new_dependencies)}')
    if sys.argv[1] == 'test':
        pass
    elif sys.argv[1] == 'write':
        manifest['dependencies'] = ','.join(new_dependencies)
        manifest.write()
    else:
        assert sys.argv[1] == 'ask'
        answer = input('Should I do it? [y/n] ')
        if answer in {'y', 'Y', 'yes', 'Yes'}:
            manifest['dependencies'] = ','.join(new_dependencies)
            manifest.write()
        else:
            print('Skipping...')
