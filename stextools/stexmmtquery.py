from collections import defaultdict

import requests


PREFIX: str = '''
PREFIX ulo: <http://mathhub.info/ulo#>
PREFIX archive: <mmt://memory/archive#>
'''


def get_sparql_result(query):
    r = requests.post('https://stexmmt.mathhub.info/:query/sparql', data=query,
                      headers={'content-type': 'text/plain'})
    if not r.ok:
        r.raise_for_status()
    return r.json()


def archive_id_from_uri(uri: str) -> str:
    if not uri.startswith('mmt://memory/archive#'):
        raise ValueError(f'Not an archive URI: {uri}')
    return uri[len('mmt://memory/archive#'):]


def get_dependencies() -> dict[str, list[str]]:
    query = PREFIX + '''SELECT DISTINCT ?from ?to WHERE {
    ?from a ulo:library .
    ?from ulo:contains ?file .
    ?file ulo:contains ?content .
    ?content ulo:specifies ?thing .
    ?thing ulo:include ?included .
    ?othercontent ulo:specifies ?included .
    ?otherfile ulo:contains ?othercontent .
    ?otherfile a ulo:file .
    ?to ulo:contains ?otherfile .
}'''
    results = defaultdict(list)
    json = get_sparql_result(query)
    for binding in json['results']['bindings']:
        results[archive_id_from_uri(binding['from']['value'])].append(archive_id_from_uri(binding['to']['value']))
    return results
