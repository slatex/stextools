# Design decisions

## Data caching
Processing all the files with pylatexenc takes a while ⟶ the results are cached in ~/.stextools/cache

**Stored data:**
* The whole `MathHub` object is stored, which contains a list of archives, which, in turn, contain a list of files.
  Each file contains the module tree structure, dependencies, symbols, and verbalizations.
* The data is not linked (e.g. a verbalization is not linked to the symbol it belongs to)
  because it would make cache updates more complicated (and may lead to reduced performance).
* If a file changes, the whole file info must be computed from scratch (there is no incremental update).

**Cache updates:**
* The cache data is discarded if stextools is updated (`--keep-cache` disables this).
* Whenever the cached data is loaded, all of MathHub is scanned for missing files.
* Furthermore, for every file, it is checked whether the file has been modified.
* For the missing/modified files, the cache is updated.

**Optimizations:**
* It turns out that various `pathlib` operations are quite slow when scanning, and there are some hacks to optimize it.
* Using `slots=True` in dataclasses seems to slow down pickling.
* The cached data is a tree (no cycles). Having cycles (e.g. linking from a symbol to a file and back) causes
  significant performance issues (possible explanation: garbage collection).


## Linker
The linker links all the data from the `MathHub` object in a highly optimized way.
If anything changes in the `MathHub` object (typically because a file was modified), a new linker must be created.
Incremental updates are not possible at the moment.

## Simple API
The simple API is designed to abstract away from the `MathHub` data structures and the linker,
both of which have been designed with performance in mind, rather than simplicity or convenience.

It creates simple (and relatively cheap) data structures that are easy to work with.
Internally, they use the linker to access the data from the `MathHub` object.

As a consequence, simple API objects should be considered ephemeral and not be used after the linker is discarded.
