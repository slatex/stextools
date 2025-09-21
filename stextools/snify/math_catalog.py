import abc
from abc import abstractmethod
from typing import Optional

from stextools.snify.catalog import Symb


class MathCatalog(abc.ABC):
    @abstractmethod
    def find_first_match(
            self,
            string: str,
    ) -> Optional[tuple[int, int, list[Symb]]]:
        pass
