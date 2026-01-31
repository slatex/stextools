import functools
import sys
from pathlib import Path
from typing import Any
import os
import logging

import orjson
from cffi import FFI

from stextools.stepper.interface import interface

logger = logging.getLogger(__name__)


class _Flams:
    def __init__(self):
        self._all_files_loaded = False
        self.ffi = FFI()
        self.ffi.cdef("""
void hello_world(size_t arg);
void initialize();
void load_all_files();
char* get_file_annotations(char* path);
void load_file(char* s);
char* list_of_loaded_files();
char* list_of_all_files();
void free_string(char* s);
void reset_global_backend();
extern size_t FFI_VERSION;
""")

    @functools.cached_property
    def lib(self):
        path = os.getenv('FLAMS_LIB_PATH')
        if not path:
            logger.info(f'FLAMS_LIB_PATH not set.')

        if sys.platform == 'darwin':
            filename = 'libflams_ffi.dylib'
            zipfilename = 'ffi-macos.zip'
        elif sys.platform == 'linux':
            filename = 'libflams_ffi.so'
            zipfilename = 'ffi-linux.zip'
        else:
            raise RuntimeError(f'Unsupported platform: {sys.platform}')

        if not path:
            logger.info(f'Using ~/.cache/stextools/{filename} as FLAMS library path.')
            path = str(Path.home() / '.cache' / 'stextools' / filename)

        if not Path(path).exists():
            download = interface.ask_yes_no(f'''The FLAMS library was not found at {path}.
You can download it from https://github.com/FlexiFormal/FLAMS/releases/tag/latest
Should I do that for you?''')
            if not download:
                interface.write_text(f'Cannot proceed without FLAMS library. Exiting.', 'error')
                sys.exit(1)
            # download zip into temp file and extract
            import tempfile
            import zipfile
            import requests
            import shutil
            url = f'https://github.com/FlexiFormal/FLAMS/releases/download/latest/{zipfilename}'
            with tempfile.TemporaryDirectory() as tmpdirname:
                tmpzipfile = Path(tmpdirname) / zipfilename
                interface.write_text(f'Downloading FLAMS library from {url}...\n')
                response = requests.get(url)
                response.raise_for_status()
                with open(tmpzipfile, 'wb') as f:
                    f.write(response.content)
                with zipfile.ZipFile(tmpzipfile, 'r') as zip_ref:
                    zip_ref.extractall(tmpdirname)
                extracted_path = Path(tmpdirname) / filename
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(extracted_path, path)   # os.rename does not work across filesystems
                interface.write_text(f'Successfully downloaded and extracted FLAMS library to {path}.')

        lib: Any = self.ffi.dlopen(path)
        print('INITIALIZE')
        lib.initialize()
        return lib

    def _cstr_to_json(self, c_str) -> Any:
        """Convert a C string to a JSON object."""
        py_str = self.ffi.string(c_str).decode('utf-8')
        self.lib.free_string(c_str)
        return orjson.loads(py_str)

    def hello_world(self, arg: int):
        self.lib.hello_world(arg)

    def load_all_files(self):
        self.lib.load_all_files()
        self._all_files_loaded = True

    def require_all_files_loaded(self):
        if not self._all_files_loaded:
            self.load_all_files()

    def load_file(self, filepath: str | Path):
        filepath_c = self.ffi.new('char[]', str(filepath).encode('utf-8'))
        self.lib.load_file(filepath_c)

    def get_file_annotations(self, filepath: str | Path, load: bool = True):
        if load:
            # note: if not explicitly loading, the file may only be partially loaded
            # i.e. some annotations may not be available
            self.load_file(filepath)
        filepath_c = self.ffi.new('char[]', str(filepath).encode('utf-8'))
        c_str = self.lib.get_file_annotations(filepath_c)
        py_str = self.ffi.string(c_str).decode('utf-8')
        self.lib.free_string(c_str)
        if not py_str:
            self.load_file(filepath)
            c_str = self.lib.get_file_annotations(filepath_c)
            py_str = self.ffi.string(c_str).decode('utf-8')
            self.lib.free_string(c_str)
        if py_str:
            return orjson.loads(py_str)
        return None

    def get_loaded_files(self) -> list[str]:
        return self._cstr_to_json(self.lib.list_of_loaded_files())

    def get_all_files(self, rescan: bool = False) -> list[str]:
        if rescan:
            self.reset_global_backend()
        return self._cstr_to_json(self.lib.list_of_all_files())

    def reset_global_backend(self):
        print('RESET')
        self.lib.reset_global_backend()


    @property
    def ffi_version(self) -> int:
        return self.lib.FFI_VERSION

FLAMS = _Flams()


if __name__ == '__main__':

    # print('Getting file json')
    # path = str(Path('/home/jfs/git/gl.mathhub.info/smglom/mv/source/mod/mv.en.tex'))
    # path = str(Path('/home/jfs/MMT/MMT-content/courses/FAU/AI/problems/source/csp/quiz/csp23.en.tex'))
    print(orjson.dumps(FLAMS.get_file_annotations(Path(sys.argv[1]).resolve())).decode('utf-8'))

    # while True:
    #     print('FLAMS FFI VERSION:', FLAMS.ffi_version)
    #     print(len(FLAMS.get_all_files()))
    #     input()
    #     FLAMS.reset_global_backend()


    # relpath = str(Path('/home/jfs/MMT/MMT-content/smglom/mv/source/mod/constant.en.tex')).encode('utf-8')

#     print(relpath)
#     lib.load_file(ffi.new('char[]', relpath))
#     c_str = lib.get_file_annotations(ffi.new('char[]', relpath))
#     print(ffi.string(c_str).decode('utf-8'))
#
#     print('Getting list of loaded files')
#     print(json.loads(ffi.string(lib.list_of_loaded_files()).decode('utf-8')))
#     for file in json.loads(ffi.string(lib.list_of_loaded_files()).decode('utf-8')):
#         if file:
#             print(file)
