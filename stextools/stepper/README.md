# Stepper Code

This package provides the `Stepper` functionality that powers `snify`.
A `Stepper` is a tool that iterates over data and interacts with
the user via commands.
For example, `snify` iterates over sTeX documents and the user
has to commands to make annotations etc.

This package is generic, but for examples, we will often refer to `snify`.

## Commmands

A `Command` can be called by the user by entering
the corresponding letter,
for example, `"s"` to call the skip command in `snify`.
When executed, a command returns a list of
`CommandOutcome`s, which can then be handled by the stepper.

## Interface

Instead of printing directly to the commandline,
the stepper package provides a custom methods
for displaying (and styling) strings and getting user input.
This abstraction makes it possible to

* support different kinds of terminals
* support different color schemes
* have a browser interface
* make user interface tests (future work)

## Documents

Often a stepper iterates over documents.
The `Document` class provides methods to
get the document format, the language,
the plain text content, or the formulae.

## Stepper

A `Stepper` maintains a `State` with a cursor that keeps track of the current position.
In general, the `State` should store all relevant information so that it
can be stored (pickled) to resume the session at a later point.

For undoing/redoing, the stepper keeps track of a sequence of
`Modification`s, e.g. moving the cursor or changes to a file,
that can be (un)done.

There are various stepper extensions that can be included via
multiple inheritance.
This is both convenient (just add `QuittableStepper` as a super class
to have support for the `QuitCommand`) and slightly annoying because
multiple inheritance feels unnecessarily complicated.
