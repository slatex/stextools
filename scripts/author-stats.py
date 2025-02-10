from annocounthistory2 import load_history

HISTORY_DATA = load_history()

authors = set()

for ci in HISTORY_DATA.values():
    if ci.repo.startswith('smglom/'):
        authors.add(ci.creator)


for author in sorted(authors):
    print(author)
