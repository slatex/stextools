import functools
from pathlib import Path
from typing import Any
import os

import orjson
from cffi import FFI


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
""")

    @functools.cached_property
    def lib(self):
        path = os.getenv('FLAMS_LIB_PATH') or raise RuntimeError('FLAMS_LIB_PATH environment variable not set')
        lib: Any = self.ffi.dlopen(path)
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

    def get_all_files(self) -> list[str]:
        return self._cstr_to_json(self.lib.list_of_all_files())

FLAMS = _Flams()


if __name__ == '__main__':

    print('Getting file json')
    # path = str(Path('/home/jfs/MMT/MMT-content/smglom/mv/source/mod/constant.en.tex').relative_to(Path.cwd(), walk_up=True)).encode('utf-8')
    path = str(Path('/home/jfs/MMT/MMT-content/smglom/algebra/source/mod/subgroup.en.tex'))
    print(orjson.dumps(FLAMS.get_file_annotations(path)).decode('utf-8'))
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
