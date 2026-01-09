from __future__ import annotations

import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class WordLex:
    lang: str
    archive_camel_case: str
    words: dict[str, WordLexEntry]

    def store(self, directory: Path):
        with open(directory / f'{self.archive_camel_case}Words{self.lang}.json', 'w') as fp:
            json.dump(
                {
                    fun : {
                        'linearization': word.lin,
                        'source': word.source,
                        'cat': word.cat,
                    }
                    for fun, word in self.words.items()
                },
                fp,
                indent=2,
            )

    @classmethod
    def load(cls, archive_camel_case: str, directory: Path, lang: str, create_if_nonexistent: bool = False) -> WordLex:
        path = directory / f'{archive_camel_case}Words{lang}.json'
        if not path.exists() and create_if_nonexistent:
            return cls(archive_camel_case=archive_camel_case, lang=lang, words={})
        with open(path, 'r') as fp:
            data = json.load(fp)
            words = {
                fun: WordLexEntry(lin=entry['linearization'], source=entry['source'], cat=entry['cat'])
                for fun, entry in data.items()
            }
        return cls(archive_camel_case=archive_camel_case, lang=lang, words=words)

    def to_gf(self, directory: Path):
        name = f'{self.archive_camel_case}Words{self.lang}'
        with open(directory / f'{name}Abs.gf', 'w') as fp:
            fp.write(f'-- auto-generated; do not edit\n')
            fp.write(f'abstract {name}Abs = Cat ** {{\n')
            fp.write('fun\n')
            for fun, word in self.words.items():
                fp.write(f'  \'{fun}\' = {word.lin}   -- {word.source}\n')
            fp.write('}\n')

        with open(directory / f'{name}.gf', 'w') as fp:
            fp.write(f'-- auto-generated; do not edit\n')
            fp.write(f'concrete {name} of {name}Abs = CatEng ** open Paradigms{self.lang} in {{\n')
            fp.write('lin\n')
            for fun, word in self.words.items():
                fp.write(f'  \'{fun}\' = {word.lin}   -- {word.source}\n')
            fp.write('}\n')



@dataclasses.dataclass
class WordLexEntry:
    cat: str
    lin: str
    source: str
