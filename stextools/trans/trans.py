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
from .fill import compute_fills
from .patterns import lang_flag_tokens, resolve_lang_alias


def _interactive_select(item, candidates, context, default):
    """Prompt the author to choose a translation when a symbol has several candidates.
    Args:
        item: the symbol's metadata (type, key, plural)
        candidates: the list of candidate translations
        context: a string describing the context in which the symbol appears
        default: the default translation to use if the author presses Enter
    """

    plural = " (plural)" if item.get("plural") else ""
    click.echo()
    click.echo(f"  …{context}…")
    click.echo(f"  \\{item['type']}{{{item['key']}}}{plural}")
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


def run_trans(
        file: Path,
        lang_arg: str,
        out: Optional[Path] = None,
        interactive: bool = True,
        fill: bool = True,
        write_report: bool = True,
        placeholders: bool = True,
        review_comments: bool = True,
):
    """Create a target-language sTeX translation template from an English (annotated) module.
    Args:
        file: Path to the input English sTeX module.
        lang_arg: Target language code (e.g., 'de', 'fr').
        out: Optional path for the output translated template. If not provided, a default
            path will be generated based on the input file name and target language.
        interactive: If True, prompt the author to choose translations when multiple
            candidates are available. If False, use the default translation or keep
            placeholders.
        fill: If True, auto-fill known translations from the SMGloM domain model (via FLAMS).
            If False, no auto-filling will be performed.
        write_report: If True, write a JSON report of the translation process alongside
            the output template.
        placeholders: If True, insert placeholders for terms without known translations.
        review_comments: If True, add review comments in the output template for terms
            that were auto-filled or kept as placeholders.
    """
    lang = resolve_lang_alias(lang_arg)
    in_path = Path(file)
    text = in_path.read_text(encoding="utf-8")

    # Compute the fills for each symbol in the text, if requested. If `fill` is False, then
    # `fills` will be an empty dict and `fill_stats` will be None.
    fills = {}
    fill_stats = None
    if fill:
        select = _interactive_select if interactive else None
        fills, fill_stats = compute_fills(text, str(in_path.resolve()), lang, select)

    # Build the translated template, passing in the computed fills and any options for placeholders and review comments. 
    # The `build_template` function returns the new text and a report of the translation
    opts = {"insert_placeholders": placeholders, "add_review_comments": review_comments}
    new_text, report = build_template(text, lang, opts, fills)
    if fill_stats is not None:
        report["fill"] = fill_stats

    # Write the translated template to the specified output path, or to a default path based on
    # the input file name and target language.
    if out:
        out_path = Path(out)
    else:
        stem = re.sub(r"\.(en)$", "", in_path.stem)
        out_path = in_path.with_name(f"{stem}.{lang}.tex")
    out_path.write_text(new_text, encoding="utf-8")
    click.echo(f"Translated template written to: {out_path}")

    # Write a report of the translation process to a JSON file alongside the output template.
    if write_report:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        click.echo(f"Report written to: {json_path}")

    # Print a summary of the fill statistics to the console, if available.
    if fill_stats is not None:
        click.echo(f"Filled {fill_stats['filled']} term(s); "
                   f"{fill_stats['kept_placeholder']} kept as placeholder, "
                   f"{fill_stats['no_verbalization']} without a {lang} verbalization, "
                   f"{fill_stats['unresolved']} unresolved.")
        if not fill_stats["catalog_language_available"]:
            click.echo(f"  (no verbalization catalog for lang={lang} -> nothing could be filled)")
