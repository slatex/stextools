import dataclasses
from typing import Optional

from stextools.core.cache import Cache
from stextools.core.linker import Linker
from stextools.core.stexdoc import Symbol, Verbalization


@dataclasses.dataclass
class SimpleSymbol:
    _symbol: Symbol
    _symbol_int: int
    _linker: Linker

    def get_verbalizations(self, lang: Optional[str] = None) -> list['SimpleVerbalization']:
        for verb_int in self._linker.symb_to_verbs[self._symbol_int]:
            verb = self._linker.verb_ints.unintify(verb_int)[1]
            if lang is not None and verb.lang != lang:
                continue
            yield SimpleVerbalization(verb, self._linker)


@dataclasses.dataclass
class SimpleVerbalization:
    _verbalization: Verbalization
    _linker: Linker

    @property
    def verb_str(self) -> str:
        return self._verbalization.verbalization


def get_symbols(linker: Linker) -> list[SimpleSymbol]:
    for symbol, symbol_int in linker.symbol_ints.items():
        yield SimpleSymbol(symbol[1], symbol_int, linker)


def get_linker() -> Linker:
    mh = Cache.get_mathhub(update_all=True)
    return Linker(mh)
