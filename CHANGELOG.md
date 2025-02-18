# Changelog


## Upcoming release

**New features:**

* `defianno` tool added (helps with annotating definienda)
* `snify`'s `x𝑖` command now also shows the import path of symbols (if in scope)

**Other modifications/improvements:**

* Factoring a `stepper` module out of `snify`
* More error messages when an archive is cloned twice (related to [#62](https://github.com/slatex/stextools/issues/62))
* Skip malformed `smodule` environments instead of crashing (see also [#78](https://github.com/slatex/stextools/issues/78))
* More generally, continue if stex processing fails for a file


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


