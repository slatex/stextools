# `stepper` module

The `stepper` module provides functionality for building
a command line interfaces for batch annotation tasks.
The most prominent use case is `snify`.


Key concepts
============

The stepper is centered around `Commands`.
A `Command` typically is a simple action like adding an annotation or skipping a document.
When called, a `Command` does not actually change anything, but instead returns `CommandOutcome`s,
which carry information about what should happen.
The `Controller` usually translates `CommandOutcome`s into
simple `Modification`s, which can be applied (and undone).
In general, this separation lets us gradually decompose
commands into simple, re-usable modifications.
For example, the `ReplaceCommand`, which can be used to replace the currently selected string,
will return a `SubstitutionOutcome` and a `SetNewCursor` outcome,
which in turn are translated into a `FileModification` and a `CursorModification`.

In some cases, the conversion to `Modification`s is not necessary
and `CommandOutcome`s can be applied directly.

A `CommandCollection` holds all commands that can be executed in a particular situation.

