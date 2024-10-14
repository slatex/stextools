"""
copied from spotterbase (spotterbase would be an unnecessarily large dependency for this project)
"""

from __future__ import annotations

import bisect
import dataclasses
import itertools
import re
from typing import TypeVar, Sequence, Generic, Optional, Iterable

#: TypeVariable bound for :class:`LinkedStr`
LinkedStr_T = TypeVar('LinkedStr_T', bound='LinkedStr')

_MetaInfoType = TypeVar('_MetaInfoType')



def pairwise(iterable):
    iterator = iter(iterable)
    a = next(iterator, None)
    for b in iterator:
        yield a, b
        a = b

if not hasattr(itertools, 'pairwise'):
    # only available in python 3.10+
    itertools.pairwise = pairwise


@dataclasses.dataclass(frozen=True)
class _RelData(Generic[_MetaInfoType]):
    """ It is expensive to copy references and strings.
    By storing the offsets relative to another LinkedStr, we can save memory and computation time.
    References and strings are now only created on demand.
    This makes the code much more tedious and a bit more error-prone, but should have a substantial performance impact.
    """
    based_on: LinkedStr[_MetaInfoType]
    start_offset: int
    end_offset: int        # exclusive


class LinkedStr(Generic[_MetaInfoType]):
    """ Should be treated as immutable! For optimization, references are used (e.g. when created a sub-linked-str) """

    # relative data (for sub-linked-strs)
    # Note that the other attributes (e.g. _string) take precedence
    _rel_data: Optional[_RelData[_MetaInfoType]] = None

    _string: Optional[str] = None
    _start_refs: Optional[Sequence[int]] = None
    _end_refs: Optional[Sequence[int]] = None
    _meta_info: _MetaInfoType

    def __init__(self, *,
                 meta_info: _MetaInfoType,
                 string: Optional[str] = None,
                 start_refs: Optional[Sequence[int]] = None,
                 end_refs: Optional[Sequence[int]] = None,
                 _rel_data: Optional[_RelData[_MetaInfoType]] = None,
                 ):
        self._meta_info = meta_info
        self._string = string
        self._start_refs = start_refs
        self._end_refs = end_refs
        if string is None or start_refs is None or end_refs is None:
            if _rel_data is None:
                raise ValueError('No _RelData provided for incompletely populated instantiation')
            self._rel_data = _rel_data

        # self.get_start_refs()
        # self.get_end_refs()
        # str(self)
        # assert len(self._string) == len(self._start_refs) == len(self._end_refs)

    def get_indices_from_ref_range(self, start_ref, end_ref) -> tuple[int, int]:
        # Note: could also work from rel data
        # Note: this looks easy, but getting it right was surprisingly challenging
        return bisect.bisect(self.get_end_refs(), start_ref), bisect.bisect(self.get_start_refs(), end_ref - 1)

    def with_string(self: LinkedStr_T, string: str) -> LinkedStr_T:
        assert len(string) == len(self)
        return type(self)(meta_info=self._meta_info, string=string, start_refs=self._start_refs,
                          end_refs=self._end_refs, _rel_data=self._rel_data)

    def get_start_refs(self) -> Sequence[int]:
        if (sr := self._start_refs) is None:
            rd = self._rel_data
            assert rd is not None
            sr = rd.based_on.get_start_refs()[rd.start_offset:rd.end_offset]
            self._start_refs = sr
        return sr

    def get_end_refs(self) -> Sequence[int]:
        if (er := self._end_refs) is None:
            rd = self._rel_data
            assert rd is not None
            er = rd.based_on.get_end_refs()[rd.start_offset:rd.end_offset]
            self._end_refs = er
        return er

    def get_start_ref(self) -> int:
        # more efficient than calling self.get_start_refs
        if (sr := self._start_refs) is not None:
            return sr[0]
        rd = self._rel_data
        assert rd is not None
        return rd.based_on.get_start_refs()[rd.start_offset]

    def get_end_ref(self) -> int:
        # more efficient than calling self.get_end_refs
        if (er := self._end_refs) is not None:
            return er[-1]
        rd = self._rel_data
        assert rd is not None
        return rd.based_on.get_end_refs()[rd.end_offset - 1]

    def __len__(self) -> int:
        if (rd := self._rel_data) is not None:
            return rd.end_offset - rd.start_offset
        s = self._string
        assert s is not None
        return len(s)

    def __getitem__(self: LinkedStr_T, item) -> LinkedStr_T:
        if isinstance(item, slice):
            start, stop, step = item.indices(len(self))
            if step == 1:
                return type(self)(meta_info=self._meta_info, _rel_data=_RelData(self, start, stop))
            return type(self)(meta_info=self._meta_info, string=str(self)[item], start_refs=self.get_start_refs()[item],
                              end_refs=self.get_end_refs()[item])
        elif isinstance(item, int):
            return type(self)(meta_info=self._meta_info, string=str(self)[item],
                              start_refs=[self.get_start_refs()[item]],
                              end_refs=[self.get_end_refs()[item]])
        elif isinstance(item, LinkedStr):
            # TODO: Should we check that it's based on the same document?
            start_index, end_index = self.get_indices_from_ref_range(item.get_start_ref(), item.get_end_ref())
            return self[start_index:end_index]
        elif isinstance(item, re.Match):
            return self[item.start():item.end()]
        else:
            raise TypeError(f'Unsupported type {type(item)}')

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({repr(str(self))})'

    def __str__(self) -> str:
        if (s := self._string) is not None:
            return s
        rd = self._rel_data
        assert rd is not None
        self._string = str(rd.based_on)[rd.start_offset:rd.end_offset]
        return self._string

    def strip(self: LinkedStr_T) -> LinkedStr_T:
        str_start = 0
        str_end = 0
        string = str(self)
        for i in range(len(string)):
            if not string[i].isspace():
                str_start = i
                break
        for i in range(len(string) - 1, -1, -1):
            if not string[i].isspace():
                str_end = i + 1
                break
        return self[str_start:str_end]

    def lower(self: LinkedStr_T) -> LinkedStr_T:
        return self.with_string(str(self).lower())

    def upper(self: LinkedStr_T) -> LinkedStr_T:
        return self.with_string(str(self).upper())

    def normalize_spaces(self: LinkedStr_T) -> LinkedStr_T:
        """ replace sequences of whitespaces with a single one."""
        # the following is much more efficient than iterating character by character
        return self.replacements_at_positions(
            [
                (match.start(), match.end(), ' ')
                for match in re.finditer(r'\s+', str(self))
                if match.group() != ' '
            ],
            positions_are_references=False
        )

    def get_meta_info(self) -> _MetaInfoType:
        return self._meta_info

    def char_at(self, pos: int) -> str:
        return str(self)[pos]

    def replacements_at_positions(
            self: LinkedStr_T,
            replacements: Iterable[tuple[int, int, str]],   # more efficient if we do all at once
            positions_are_references: bool = True,    # if False, positions are indices into the string
    ) -> LinkedStr_T:

        @dataclasses.dataclass(frozen=True)
        class Entry:
            start_str: int
            end_str: int
            start_ref: int
            end_ref: int
            replacement: str

        entries: list[Entry] = []
        for start, end, replacement in replacements:
            if positions_are_references:
                start_ref, end_ref = start, end
                start_str, end_str = self.get_indices_from_ref_range(start, end)
            else:
                start_str, end_str = start, end
                start_ref, end_ref = self.get_start_refs()[start], self.get_end_refs()[end - 1]
            entries.append(Entry(start_str, end_str, start_ref, end_ref, replacement))

        if not entries:
            return self   # nothing to do

        entries.sort(key=lambda e: e.start_str)

        # TODO: maybe we can support for overlapping replacements (just concatenate the replacements)
        assert all(x.end_str <= y.start_str for x, y in itertools.pairwise(entries)), 'Some ranges are overlapping'

        new_start_refs: list[int] = []
        new_end_refs: list[int] = []
        strings: list[str] = []

        start_refs = self.get_start_refs()
        end_refs = self.get_end_refs()
        string = str(self)

        previous_end: int = 0
        for entry in entries:
            # copy until start of range
            new_start_refs.extend(start_refs[previous_end:entry.start_str])
            new_end_refs.extend(end_refs[previous_end:entry.start_str])
            strings.append(string[previous_end:entry.start_str])

            # put replacement string
            new_start_refs.extend(itertools.repeat(entry.start_ref, len(entry.replacement)))
            new_end_refs.extend(itertools.repeat(entry.end_ref, len(entry.replacement)))
            strings.append(entry.replacement)

            previous_end = entry.end_str

        new_start_refs.extend(start_refs[previous_end:])
        new_end_refs.extend(end_refs[previous_end:])
        strings.append(string[previous_end:])

        return type(self)(meta_info=self.get_meta_info(), string=''.join(strings), start_refs=new_start_refs,
                          end_refs=new_end_refs)


def string_to_lstr(string: str) -> LinkedStr[None]:
    return LinkedStr(meta_info=None, string=string, start_refs=list(range(len(string))),
                     end_refs=list(range(1, len(string) + 1)))
