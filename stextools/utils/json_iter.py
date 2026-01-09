from typing import Iterable


def json_iter(j, ignore_keys: set[str] = set()) -> Iterable:
    yield j
    if isinstance(j, dict):
        for key, value in j.items():
            if key not in ignore_keys:
                yield from json_iter(value, ignore_keys)
    elif isinstance(j, list):
        for item in j:
            yield from json_iter(item, ignore_keys)
