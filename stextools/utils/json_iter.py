from typing import Iterable


def json_iter(j) -> Iterable:
    yield j
    if isinstance(j, dict):
        for value in j.values():
            yield from json_iter(value)
    elif isinstance(j, list):
        for item in j:
            yield from json_iter(item)
