"""
`stextools trans` — create a target-language sTeX translation template from an English
(annotated) module, auto-filling each term's known translation from the SMGloM domain
model (via FLAMS), and prompting the author whenever a symbol has several candidate
translations.
"""
import json
import re
from pathlib import Path
from typing import Optional

import click

from .builder import build_template
from .fill import compute_fills, build_index, _BUILD_INDEX
from .patterns import lang_flag_tokens, resolve_lang_alias


def _interactive_select(item, candidates, context, default):
    """Prompt the author to choose a translation when a symbol has several candidates.
    Args:
        item: the symbol's metadata (type, key, plural)
        candidates: the list of candidate translations
        context: a (before, target, after) tuple of the source around the term; `target`
            (the annotation being translated) is highlighted in the prompt
        default: the default translation to use if the author presses Enter
    """

    plural = " (plural)" if item.get("plural") else ""
    before, target, after = context
    highlighted = before + click.style(target, fg="cyan", bold=True) + after
    click.echo()
    click.echo(f"  ...{highlighted}...")
    click.echo(f"  \\{item['type']}{{{item['key']}}}{plural}")
    if not candidates:
        # a new defined term with no existing translation: ask the author to provide one
        val = click.prompt("  no existing translation - enter one (Enter to keep placeholder)",
                           default="", show_default=False).strip()
        return val or None
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


def _process_one(file: Path, lang: str, select, index, fill: bool, out: Optional[Path],
                 write_report: bool, placeholders: bool, review_comments: bool):
    """Translate a single file. Returns (out_path, fill_stats | None)."""
    in_path = Path(file)
    text = in_path.read_text(encoding="utf-8")

    fills, fill_stats = {}, None
    if fill:
        fills, fill_stats = compute_fills(text, str(in_path.resolve()), lang, select, index=index)

    opts = {"insert_placeholders": placeholders, "add_review_comments": review_comments}
    new_text, report = build_template(text, lang, opts, fills)
    if fill_stats is not None:
        report["fill"] = fill_stats

    stem = re.sub(r"\.(en)$", "", in_path.stem)
    out_path = Path(out) if out else in_path.with_name(f"{stem}.{lang}.tex")
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
        placeholders: bool = True,
        review_comments: bool = True,
):
    """Translate one or more English (annotated) sTeX modules to target-language templates.

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
        placeholders: Insert placeholders for untranslated terms.
        review_comments: Add the review-comment header to each output.
    """
    files = list(files)
    lang = resolve_lang_alias(lang_arg)
    select = _interactive_select if interactive else None

    index = _BUILD_INDEX
    if fill:
        index = build_index(lang)   # built once, reused for every file
        if index is None:
            click.echo(f"(no verbalization catalog for lang={lang}; producing placeholders only)")

    agg = {"filled": 0, "kept_placeholder": 0, "no_verbalization": 0, "unresolved": 0}
    for f in files:
        out_path, stats = _process_one(f, lang, select, index, fill, out,
                                       write_report, placeholders, review_comments)
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
              placeholders=True, review_comments=True):
    """Backward-compatible single-file wrapper around run_batch()."""
    run_batch([file], lang_arg, out=out, interactive=interactive, fill=fill,
              write_report=write_report, placeholders=placeholders, review_comments=review_comments)


def _staging_path(src, out_dir, lang) -> Path:
    """Where a translated module is written in the staging dir, mirroring its archive path
    (e.g. .../smglom/sets/source/mod/set.en.tex -> <out_dir>/smglom/sets/source/mod/set.de.tex)."""
    s = str(src).replace("\\", "/")
    if "/source/" in s:
        prefix, suffix = s.split("/source/", 1)
        rel = Path("/".join(prefix.split("/")[-2:])) / "source" / suffix
    else:
        rel = Path(Path(s).name)
    stem = re.sub(r"\.en$", "", Path(rel).stem)
    return Path(out_dir) / rel.with_name(f"{stem}.{lang}.tex")


def run_referenced(
        seeds,
        lang_arg: str,
        out_dir,
        depth: Optional[int] = 1,
        only_archives=None,
        translate_seeds: bool = False,
        interactive: bool = True,
        yes: bool = False,
        write_report: bool = True,
        placeholders: bool = True,
        review_comments: bool = True,
):
    """Translate the reference closure of the seed documents into a staging directory.

    Collects the symbols the seeds reference that lack a target-language verbalization,
    finds the local English modules that define them (transitively, up to `depth`), orders
    them so definitions come before uses, previews the plan, asks for confirmation, then
    translates each in order --- feeding every newly created verbalization forward so later
    modules' references fill, and keeping the author's synonym choices consistent run-wide.
    Args:
        seeds: seed document paths whose references drive the closure.
        lang_arg: target language code or alias.
        out_dir: staging directory to write the generated templates into.
        depth: how far to follow references (1 = only directly referenced definitions).
        only_archives: optional iterable of archive ids to restrict the closure to.
        translate_seeds: also translate the seed files themselves.
        interactive: prompt on ambiguous terms and ask to confirm the closure.
        yes: skip the confirmation prompt.
        write_report/placeholders/review_comments: as for run_batch.
    """
    from .closure import reference_closure

    lang = resolve_lang_alias(lang_arg)
    out_dir = Path(out_dir)
    index = build_index(lang)
    if index is None:
        click.echo(f"(no verbalization catalog for lang={lang}; translations cannot be suggested)")
        index = {}

    scope = None
    if only_archives:
        allowed = {a.strip() for a in only_archives}
        scope = lambda a: a in allowed

    seeds_abs = [str(Path(s).resolve()) for s in seeds]
    order, report = reference_closure(seeds_abs, index, scope=scope,
                                      translate_seeds=translate_seeds, max_depth=depth)

    click.echo(f"\nReference closure (seeds={report['seeds']}, depth={depth}):")
    click.echo(f"  {report['modules_to_translate']} module(s) to translate"
               + (" [capped at the safety limit]" if report["capped"] else ""))
    for a, n in sorted(report["by_archive"].items(), key=lambda x: -x[1]):
        click.echo(f"      {n:4}  {a}")
    if report["external_symbols"]:
        click.echo(f"  {report['external_symbols']} referenced symbol(s) have no local source (skipped)")
    if report["out_of_scope_symbols"]:
        click.echo(f"  {report['out_of_scope_symbols']} referenced symbol(s) out of scope (skipped)")
    if not order:
        click.echo("Nothing to translate - every referenced concept already has a translation.")
        return
    if interactive and not yes:
        if not click.confirm(f"\nTranslate {len(order)} module(s) into {out_dir}/?", default=False):
            click.echo("Aborted.")
            return

    select = _interactive_select if interactive else None
    chosen: dict = {}   # run-wide synonym consistency + feed-forward defaults
    opts = {"insert_placeholders": placeholders, "add_review_comments": review_comments}
    agg = {"filled": 0, "kept_placeholder": 0, "no_verbalization": 0, "unresolved": 0}

    for i, m in enumerate(order, 1):
        text = Path(m).read_text(encoding="utf-8")
        fills, stats = compute_fills(text, m, lang, select, index=index, chosen_by_uri=chosen,
                                     ask_new_definienda=True)
        new_text, rep = build_template(text, lang, opts, fills)
        rep["fill"] = stats
        out_path = _staging_path(m, out_dir, lang)
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
        click.echo(f"[{i}/{len(order)}] {out_path}   ({_coverage(stats)})")

    total = sum(agg.values())
    pct = f"{100 * agg['filled'] / total:.0f}%" if total else "n/a"
    click.echo(f"\n== closure: {len(order)} modules, filled {agg['filled']}/{total} ({pct}); "
               f"{agg['kept_placeholder']} kept, {agg['no_verbalization']} untranslated, "
               f"{agg['unresolved']} unresolved ==")
    click.echo(f"Templates written under {out_dir}/ (staging - review before moving into archives).")
