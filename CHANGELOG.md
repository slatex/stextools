# Changelog


## Release 0.3.1 (2026-01-09)
This release is the result of significant changes to all of `stextools` (which were not tracked in the changelog).
The most important change is that `snify` now uses [FLAMS](https://github.com/flexiformal/flams) for processing sTeX files.
This makes `snify` compatible with the new sTeX version, and also makes faster/more responsive.
Furthermore, the whole setup is much more modular and extensible.
In the process, some (less used) features were lost, but will be reintroduced in future releases if needed.

## Release 0.1.3 (2025-06-04)

**New features:**

* `defianno` tool added (helps with annotating definienda)
* `snify`'s `x𝑖` command now also shows the import path of symbols (if in scope)
* Can quit in session dialog
* You can override `snify`'s language detection with the `--lang` argument
* Started Python API (currently supports searching for symbols by verbalization)


**Bugfixes:**

* The explain (`x𝑖`) ignored the actual verbalization string of the selection


**Other modifications/improvements:**

* Factoring a `stepper` module out of `snify`
* More error messages when an archive is cloned twice (related to [#62](https://github.com/slatex/stextools/issues/62))
* Skip malformed `smodule` environments instead of crashing (see also [#78](https://github.com/slatex/stextools/issues/78))
* More generally, continue if stex processing fails for a file
* Better text for `[c]`ontinue command in session dialog


## Release 0.1.2 (2025-02-03)

**New features:**

* `snify` accepts `--focus` argument to immediately focus on a symbol ([#76](https://github.com/slatex/stextools/issues/76))


**Bugfixes:**

* Fix misleading "focus mode ended" in `snify` 
* Use `.en.tex` as a fallback in path resolution


**Other modifications/improvements:**

* various improvements to `stextools.core.simple_api`
* fixes to type hints


## Release 0.1.1 (2024-12-09)

**New features:**

* `snify` accepts directories as arguments (along with paths)
* `x𝑖` command added to `snify` (to explain symbol suggestions)
* `version` command added


**Bugfixes:**

* `snify`: Do not presume color support by pager in `h` (#71)
* `snify`: Fix bug during unfocusing


**Other modifications/improvements:**

* better colors for dark terminals
* `snify` help slightly restructured
* various improvements to `stextools.core.simple_api`




## Release 0.1.0 (2024-12-05)

**Other:**

* Last release without changelog


