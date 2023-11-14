"""Code for parsing and editing MANIFEST.MF files."""
from pathlib import Path


class ManifestProcessingException(Exception):
    pass


class Manifest(dict):
    def __init__(self, path: Path):
        dict.__init__(self)
        self.path = path

        # load manifest data
        if not path.is_file():
            raise FileNotFoundError(f'{path} is does not exist')
        with open(self.path) as fp:
            for line in fp:
                before, _, after = line.rpartition(':')
                if not before:
                    raise ManifestProcessingException(f'Failed to process a line in {self.path}: {line!r}')
                self[before] = after.strip()

    def write(self):
        """Write the data back to the file."""
        with open(self.path, 'w') as fp:
            for key, value in self.items():
                fp.write(f'{key}: {value}\n')

    def get_dependencies(self) -> list[str]:
        return [d.strip() for d in self['dependencies'].split(',')]

    def update_dependencies(self, dependencies: list[str]):
        self['dependencies'] = ','.join(dependencies)
