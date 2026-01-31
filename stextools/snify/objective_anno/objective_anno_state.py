import dataclasses
from typing import Literal, TypeAlias

from stextools.utils.json_iter import json_iter


@dataclasses.dataclass
class ObjectiveAnnoState:
    pass


# bloom dimensions (we currently only use three)
Dimension: TypeAlias = Literal['remember', 'understand', 'apply']
DIMENSIONS: list[Dimension] = ['remember', 'understand', 'apply']

DIM_TO_LETTER: dict[Dimension, str] = {
    'remember': 'R',
    'understand': 'U',
    'apply': 'A',
}

DIM_BY_LETTER: dict[str, Dimension] = {
    f(letter): dim
    for dim, letter in DIM_TO_LETTER.items()
    for f in (str.upper, str.lower)
}

@dataclasses.dataclass
class ObjectiveStatus:
    uri: str
    dimension: set[Dimension]

    @classmethod
    def from_flams_json(cls, flams_json: dict) -> list['ObjectiveStatus']:
        objectives: dict[str, ObjectiveStatus] = {}
        for e in json_iter(flams_json, ignore_keys={'full_range', 'parsed_args', 'name_range'}):
            if not isinstance(e, dict):
                continue
            if 'SymName' in e and e['SymName']['uri']:
                uri = e['SymName']['uri'][0]['uri']
                if uri not in objectives:
                    objectives[uri] = ObjectiveStatus(uri=uri, dimension=set())
            if 'Objective' in e and e['Objective']['uri']:
                uri = e['Objective']['uri'][0]['uri']
                if uri not in objectives:
                    objectives[uri] = ObjectiveStatus(uri=uri, dimension=set())
                dim = e['Objective']['dim'].lower()
                if dim in DIMENSIONS:
                    objectives[uri].dimension.add(dim)

        return [objectives[uri] for uri in sorted(objectives.keys())]  # sort by uri to have a stable order



