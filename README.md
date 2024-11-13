# stextools - Lightweight Tools for sTeX Authoring and Management

This package provides tools and a shared infrastructure for working with STeX content.  It
is still at an early stage of development.

## Tools 

### srify for large-scale term reference annotations

`srify` has an shell-based interface like an old `ispell` and just steps through a set of
sTeX files and suggests term reference annotations based on the verbalizations in the
SMGloM. The can select annotations by number, and ``srify` inserts the appropriate
annotation in the sTeX source, together with the respective imports (if necessary and
consistent). A couple of other keyboard-based interactions allow to fine-tune the workflow
and/or skip/refine annotations. 

`srify` is a good productivity tool for bulk annotation of existing LaTeX source files. It
works well, if the material covered is backed by a well-developed domain model (for the
respective language). 


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

