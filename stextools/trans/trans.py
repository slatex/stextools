"""
`stextools trans` — create a translation template of an annotated sTeX module for another
language (English to German, German to English, ...), auto-filling each term's known
translation from the SMGloM domain model (via FLAMS), and prompting the author whenever a
symbol has several candidate translations. The source language is read from the file name
(set.de.tex is German).
"""
import json
import sys
from pathlib import Path
from typing import Optional

import click

from .builder import build_template, direction_problem, is_generated_template
from .fill import compute_fills, build_index, _BUILD_INDEX
from .patterns import base_name, lang_flag_tokens, lang_of_path, resolve_lang_alias  # noqa: F401


def ensure_utf8_stdout():
    """Make stdout/stderr tolerate non-ASCII output even under a legacy code page.

    Term verbalizations can be non-ASCII (e.g. CJK for zhs/jp). On Windows a redirected or piped
    stdout defaults to cp1252, so printing such a candidate would crash with UnicodeEncodeError.
    Reconfigure to UTF-8 with errors='replace'; best-effort no-op where reconfigure is missing.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _show_term(item, context):
    """Print the term being translated in its context, highlighted for orientation.
    Args:
        item: the symbol's metadata (type, key, plural)
        context: a (before, target, after) tuple of the source around the term; `target`
            (the annotation being translated) is highlighted
    """
    plural = " (plural)" if item.get("plural") else ""
    before, target, after = context
    highlighted = before + click.style(target, fg="cyan", bold=True) + after
    click.echo()
    click.echo(f"  ...{highlighted}...")
    click.echo(f"  \\{item['type']}{{{item['key']}}}{plural}")


def _ask_new_word(item, context):
    """Ask the author for a translation of a defined term that has none yet.
    Returns the typed translation, or None (Enter) to keep the placeholder."""
    _show_term(item, context)
    val = click.prompt("  no existing translation - enter one (Enter to keep placeholder)",
                       default="", show_default=False).strip()
    return val or None


def _interactive_select(item, candidates, context, default):
    """Prompt the author to choose a translation when a symbol has several candidates.
    Args:
        item: the symbol's metadata (type, key, plural)
        candidates: the list of candidate translations
        context: a (before, target, after) tuple of the source around the term; `target`
            (the annotation being translated) is highlighted in the prompt
        default: the default translation to use if the author presses Enter
    """
    if not candidates:
        return _ask_new_word(item, context)
    _show_term(item, context)
    for i, c in enumerate(candidates, 1):
        mark = "  (default)" if c == default else ""
        click.echo(f"    {i}. {c}{mark}")
    while True:
        raw = click.prompt(
            f"  choose 1-{len(candidates)} / [k]eep placeholder / [c]ustom / Enter=default",
            default="", show_default=False,
        ).strip()
        if raw == "":
            return default
        if raw == "k":
            return None
        if raw == "c":
            return click.prompt("  custom translation").strip() or default
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            return candidates[int(raw) - 1]
        click.echo("  ? enter a number, k, c, or Enter")


def _coverage(stats) -> str:
    """One-line coverage summary from a fill-stats dict."""
    total = stats["filled"] + stats["kept_placeholder"] + stats["no_verbalization"] + stats["unresolved"]
    pct = f"{100 * stats['filled'] / total:.0f}%" if total else "n/a"
    return (f"filled {stats['filled']}/{total} ({pct}); {stats['kept_placeholder']} kept, "
            f"{stats['no_verbalization']} untranslated, {stats['unresolved']} unresolved")


def _print_todo(stats, limit: Optional[int] = None):
    """Print the checklist of terms still needing manual translation."""
    todo = stats.get("todo", [])
    if not todo:
        return
    click.echo("  still needs translation:")
    for t in (todo if limit is None else todo[:limit]):
        click.echo(f"    - {click.style(t['surface'], fg='yellow')}   [{t['key']}]  ({t['reason']})")
    if limit is not None and len(todo) > limit:
        click.echo(f"    ... and {len(todo) - limit} more (see the .json report)")


def _check_output(out_path, in_path=None):
    """Raise ValueError if writing `out_path` could destroy something: the input itself, or an
    existing file this tool did not generate (e.g. a hand-written translation)."""
    out_path = Path(out_path)
    if in_path is not None and out_path.resolve() == Path(in_path).resolve():
        raise ValueError("output path equals the input source; refusing to overwrite it "
                         "(check --lang / --out)")
    if out_path.exists():
        try:
            existing = out_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
        if not is_generated_template(existing):
            raise ValueError(f"{out_path} already exists and was not generated by this tool; "
                             "not overwriting it (delete it or choose another --out)")


def _process_one(file: Path, lang: str, select, index, fill: bool, out: Optional[Path],
                 write_report: bool, from_lang: str = "en", ask_new=None, chosen_by_uri=None):
    """Translate a single file. Returns (out_path, fill_stats | None).

    The source language is read from the file name (``set.de.tex`` is German), else `from_lang`.
    Raises ValueError, before any prompt, if the direction makes no sense or the output would
    overwrite the input or a file this tool did not generate. `ask_new` and `chosen_by_uri`
    are passed on to compute_fills (ask for missing words; reuse words given earlier in the run).
    """
    in_path = Path(file)
    text = in_path.read_text(encoding="utf-8")
    src_lang = lang_of_path(in_path, default=from_lang)
    problem = direction_problem(text, src_lang, lang)
    if problem:
        raise ValueError(problem)
    out_path = Path(out) if out else in_path.with_name(f"{base_name(in_path)}.{lang}.tex")
    _check_output(out_path, in_path)

    fills, fill_stats = {}, None
    if fill:
        fills, fill_stats = compute_fills(text, str(in_path.resolve()), lang, select, index=index,
                                          chosen_by_uri=chosen_by_uri, ask_new=ask_new)

    opts = {"insert_placeholders": True, "add_review_comments": True}
    new_text, report = build_template(text, lang, opts, fills, src_lang=src_lang)
    if fill_stats is not None:
        report["fill"] = fill_stats

    out_path.write_text(new_text, encoding="utf-8")
    if write_report:
        out_path.with_suffix(".json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path, fill_stats


def run_batch(
        files,
        lang_arg: str,
        out: Optional[Path] = None,
        interactive: bool = True,
        fill: bool = True,
        write_report: bool = True,
        from_lang: str = "en",
        ask_new: bool = False,
):
    """Translate one or more annotated sTeX modules into templates for the target language.

    The verbalization catalog (the expensive part of filling) is built once and reused
    across all files. For each file a coverage summary and a checklist of the terms still
    needing translation are printed; a per-run aggregate is printed for multiple files.
    Args:
        files: An iterable of input file paths (already expanded from files/directories).
        lang_arg: Target language code or alias (e.g. 'de', 'fr').
        out: Output path; only valid when translating a single file.
        interactive: Prompt on ambiguous terms (default); if False, take the top candidate.
        fill: Auto-fill known translations via FLAMS; if False, only insert placeholders.
        write_report: Write a .json report next to each output.
        from_lang: Source language of files whose name carries no language code.
        ask_new: With interactive=False, still ask for a word when a defined term has none.
    """
    files = list(files)
    lang = resolve_lang_alias(lang_arg)
    select = _interactive_select if interactive else None
    asker = _ask_new_word if (interactive or ask_new) else None
    chosen: dict = {}   # words chosen or typed earlier in the run are reused for the same concept

    index = _BUILD_INDEX
    if fill:
        index = build_index(lang)   # built once, reused for every file
        if index is None:
            click.echo(f"(no verbalization catalog for lang={lang}; producing placeholders only)")

    agg = {"filled": 0, "kept_placeholder": 0, "no_verbalization": 0, "unresolved": 0}
    for f in files:
        try:
            out_path, stats = _process_one(f, lang, select, index, fill, out, write_report,
                                           from_lang=from_lang, ask_new=asker, chosen_by_uri=chosen)
        except ValueError as e:   # e.g. output path would overwrite the input source
            click.echo(f"  skipped {f}: {e}", err=True)
            continue
        click.echo(f"wrote {out_path}")
        if stats is not None:
            for k in agg:
                agg[k] += stats[k]
            click.echo("  " + _coverage(stats))
            _print_todo(stats, limit=None if len(files) == 1 else 8)

    if fill and len(files) > 1:
        total = sum(agg.values())
        pct = f"{100 * agg['filled'] / total:.0f}%" if total else "n/a"
        click.echo(f"\n== {len(files)} files: filled {agg['filled']}/{total} ({pct}); "
                   f"{agg['kept_placeholder']} kept, {agg['no_verbalization']} untranslated, "
                   f"{agg['unresolved']} unresolved ==")


def run_trans(file, lang_arg, out=None, interactive=True, fill=True, write_report=True,
              from_lang="en", ask_new=False):
    """Backward-compatible single-file wrapper around run_batch()."""
    run_batch([file], lang_arg, out=out, interactive=interactive, fill=fill,
              write_report=write_report, from_lang=from_lang, ask_new=ask_new)


def _staging_path(src, out_dir, lang) -> Path:
    """Where a translated module is written in the staging dir, mirroring its archive path
    (e.g. .../smglom/sets/source/mod/set.en.tex -> <out_dir>/smglom/sets/source/mod/set.de.tex)."""
    s = str(src).replace("\\", "/")
    if "/source/" in s:
        prefix, suffix = s.split("/source/", 1)
        rel = Path("/".join(prefix.split("/")[-2:])) / "source" / suffix
    else:
        rel = Path(Path(s).name)
    return Path(out_dir) / rel.with_name(f"{base_name(rel)}.{lang}.tex")


def run_closure(
        seeds,
        lang_arg: str,
        out_dir,
        depth: Optional[int] = 1,
        interactive: bool = True,
        write_report: bool = True,
        ask_new: bool = False,
        from_lang: str = "en",
):
    """Translate the given files together with the definitions they are missing (--depth >= 1).

    Collects the concepts the files use that have no target-language word, finds the local
    modules that define them (following references up to `depth` steps; None = no limit),
    orders everything so definitions come before their uses and the given files last,
    previews the plan, asks for confirmation, then translates each into the staging directory
    --- feeding every new word forward so later files fill with it, and keeping the author's
    synonym choices consistent run-wide.
    Args:
        seeds: the files to translate (their references drive the closure).
        lang_arg: target language code or alias.
        out_dir: staging directory; outputs mirror their archive paths below it.
        depth: how many steps of "this definition needs another one" to follow (None = all).
        interactive: prompt on ambiguous terms and for missing words, and confirm the plan.
        write_report: as for run_batch.
        ask_new: with interactive=False, still ask for missing words (and confirm the plan).
        from_lang: source language of given files whose name carries no language code.
    """
    from .closure import reference_closure

    lang = resolve_lang_alias(lang_arg)
    out_dir = Path(out_dir)
    select = _interactive_select if interactive else None
    asker = _ask_new_word if (interactive or ask_new) else None
    depth_txt = "all" if depth is None else str(depth)

    # check the given files first, so a wrong direction is reported before any FLAMS work
    seed_paths = []
    for s in seeds:
        s = str(Path(s).resolve())
        text = Path(s).read_text(encoding="utf-8")
        try:
            problem = direction_problem(text, lang_of_path(s, default=from_lang), lang)
            if problem:
                raise ValueError(problem)
            _check_output(_staging_path(s, out_dir, lang), s)
        except ValueError as e:
            click.echo(f"  skipped {s}: {e}", err=True)
            continue
        seed_paths.append(s)
    if not seed_paths:
        return

    try:
        index = build_index(lang)
    except Exception as e:   # a FLAMS/catalog failure should not surface as a raw traceback
        click.echo(f"--depth needs FLAMS ({type(e).__name__}: {e}).", err=True)
        return
    if index is None:
        click.echo(f"(no verbalization catalog for lang={lang}; translations cannot be suggested)")
        index = {}

    order, report = reference_closure(seed_paths, index, translate_seeds=True, max_depth=depth)
    seed_set = set(seed_paths)
    n_defs = sum(1 for m in order if m not in seed_set)

    click.echo(f"\nPlan (depth={depth_txt}): {len(order)} file(s) to translate into {out_dir}/ "
               f"- {n_defs} missing definition(s) first, then your {len(order) - n_defs} file(s)"
               + (" [capped at the safety limit]" if report["capped"] else ""))
    for a, n in sorted(report["by_archive"].items(), key=lambda x: -x[1]):
        click.echo(f"      {n:4}  {a}")
    if report["external_symbols"]:
        click.echo(f"  {report['external_symbols']} referenced concept(s) have no local source "
                   "(they stay placeholders)")
    if not n_defs:
        click.echo("  No definitions are missing: every concept they use already has a translation.")
    if asker is not None:
        if not click.confirm(f"\nTranslate {len(order)} file(s) into {out_dir}/?", default=False):
            click.echo("Aborted.")
            return

    chosen: dict = {}   # run-wide synonym consistency + feed-forward defaults
    opts = {"insert_placeholders": True, "add_review_comments": True}
    agg = {"filled": 0, "kept_placeholder": 0, "no_verbalization": 0, "unresolved": 0}

    for i, m in enumerate(order, 1):
        is_seed = m in seed_set
        text = Path(m).read_text(encoding="utf-8")
        src_lang = lang_of_path(m, default=from_lang if is_seed else "en")
        out_path = _staging_path(m, out_dir, lang)
        try:
            problem = direction_problem(text, src_lang, lang)
            if problem:
                raise ValueError(problem)
            _check_output(out_path, m)
        except ValueError as e:
            click.echo(f"[{i}/{len(order)}] skipped {m}: {e}", err=True)
            continue
        fills, stats = compute_fills(text, m, lang, select, index=index, chosen_by_uri=chosen,
                                     ask_new=asker)
        new_text, rep = build_template(text, lang, opts, fills, src_lang=src_lang)
        rep["fill"] = stats
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(new_text, encoding="utf-8")
        if write_report:
            out_path.with_suffix(".json").write_text(
                json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        # feed forward: a newly translated definition becomes available for later modules
        for uri, verb in stats["new_verbs"]:
            index.setdefault(uri, [])
            if verb not in index[uri]:
                index[uri].append(verb)
        for k in agg:
            agg[k] += stats[k]
        click.echo(f"[{i}/{len(order)}] {out_path}   ({_coverage(stats)})"
                   + ("   <- your file" if is_seed else ""))
        if is_seed:
            _print_todo(stats, limit=None if len(seed_set) == 1 else 8)

    total = sum(agg.values())
    pct = f"{100 * agg['filled'] / total:.0f}%" if total else "n/a"
    click.echo(f"\n== depth {depth_txt}: {len(order)} files, filled {agg['filled']}/{total} ({pct}); "
               f"{agg['kept_placeholder']} kept, {agg['no_verbalization']} untranslated, "
               f"{agg['unresolved']} unresolved ==")
    click.echo(f"Templates written under {out_dir}/ (staging - review before moving into archives).")
