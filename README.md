# stextools - Lightweight Tools for sTeX Authoring and Management

This package provides tools and a shared infrastructure for working with STeX content.  It
is still at an early stage of development.

## Tools 

### snify for large-scale term reference annotations

`snify` has an shell-based interface like an old `ispell` and just steps through a set of
sTeX files and suggests term reference annotations based on the verbalizations in the
SMGloM. The can select annotations by number, and ``snify` inserts the appropriate
annotation in the sTeX source, together with the respective imports (if necessary and
consistent). A couple of other keyboard-based interactions allow to fine-tune the workflow
and/or skip/refine annotations. 

`snify` is a good productivity tool for bulk annotation of existing LaTeX source files. It
works well, if the material covered is backed by a well-developed domain model (for the
respective language). 

### update-dependencies
This command updates the archive dependencies (in `META-INF/MANIFEST.MF`).
Example usages:
```bash
# always ask before updating
python3 -m stextools update-dependencies --mode=ask
# show what would be updated (but do not update anything)
python3 -m stextools update-dependencies --mode=test
# update the dependencies without asking
python3 -m stextools update-dependencies --mode=write
# only consider smglom archives
python3 -m stextools update-dependencies --mode=ask --filter='smglom/*'
```


## Installation
```bash
git clone https://github.com/jfschaefer/stextools.git
cd stextools
python3 -m pip install -e .
```

## Usage
See
```bash
python3 -m stextools --help
```

