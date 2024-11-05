"""
An Intifier allows the conversion of (immutable and hashable) objects to integers and back.
Some algorithms are more efficient on integers than on hashable objects.

For example, some graph algorithms are more efficient if we have an adjacency matrix,
which requires that nodes correspond to integers.
"""

import typing

_T = typing.TypeVar('_T', bound=typing.Hashable)


class Intifier(typing.Generic[_T]):
    def __init__(self):
        self._int_to_obj: list[_T] = []
        self._obj_to_int: dict[_T, int] = {}

    def intify(self, obj: _T) -> int:
        if obj not in self._obj_to_int:
            self._obj_to_int[obj] = len(self._obj_to_int)
            self._int_to_obj.append(obj)
        return self._obj_to_int[obj]

    def unintify(self, i: int) -> _T:
        return self._int_to_obj[i]

    def int_iter(self) -> typing.Iterable[int]:
        """ TODO: should ints be included that were added during the iteration? """
        return range(len(self._int_to_obj))

    def unint_iter(self) -> typing.Iterable[_T]:
        return iter(self._obj_to_int)

    def items(self) -> typing.Iterable[tuple[_T, int]]:
        return self._obj_to_int.items()

    def __len__(self) -> int:
        return len(self._int_to_obj)
