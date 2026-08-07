"""
Provenance and staleness tracking for translation templates --- *change management*.

Verbalization-based translation binds a target-language template to a snapshot of its English
source. When the English is later revised the translation silently goes stale. To make that
detectable, every generated template records a fingerprint (a content hash) of the English
module it was derived from, in a machine-readable header marker:

    % stex-trans-source: v=1 sha256=<64 hex> path=<source/path.en.tex>

Given a translated template, :func:`check_staleness` re-hashes the current English source and
compares: matching hash = up to date, differing hash = the English changed since translation
(stale), missing file = the source moved or was deleted. This module is pure standard library
(no FLAMS), so staleness checking works even without stextools installed.

The marker is intentionally *deterministic* (no timestamps): re-translating an unchanged source
produces byte-identical output, so it never creates spurious diffs.
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, Optional

PROV_VERSION = 1

# The header marker written into every generated template and parsed back out.
_PROV_RE = re.compile(
    r'^% stex-trans-source: v=(?P<v>\d+) sha256=(?P<sha>[0-9a-fA-F]{64}) path=(?P<path>.+?)[ \t]*$',
    re.MULTILINE,
)


def _normalize(text: str) -> str:
    """Line-ending-independent view of the text so CRLF/LF churn is not seen as a change."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def source_sha256(text: str) -> str:
    """SHA-256 of the (EOL-normalized) source text."""
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def fingerprint_file(path) -> Dict:
    """Fingerprint an English source file for provenance recording.

    Args:
        path: path to the English ``.en.tex`` source.
    Returns:
        ``{"path": <forward-slashed path as given>, "sha256": <hex>, "bytes": <int>}``.
    """
    text = Path(path).read_text(encoding="utf-8")
    return {
        "path": str(path).replace("\\", "/"),
        "sha256": source_sha256(text),
        "bytes": len(_normalize(text).encode("utf-8")),
    }


def provenance_comment(fp: Dict) -> str:
    """The header marker line (with trailing newline) recording where a template came from."""
    return f"% stex-trans-source: v={PROV_VERSION} sha256={fp['sha256']} path={fp['path']}\n"


def parse_provenance(template_text: str) -> Optional[Dict]:
    """Extract the provenance marker from a generated template.

    Returns:
        ``{"version": int, "sha256": str, "path": str}`` or ``None`` if the template carries no
        marker (e.g. it was produced with ``--no-review-comments``/an older tool, or is not a
        generated template at all).
    """
    m = _PROV_RE.search(template_text)
    if not m:
        return None
    return {"version": int(m.group("v")), "sha256": m.group("sha").lower(), "path": m.group("path")}


def check_staleness(template_path, source_root=None) -> Dict:
    """Compare a translated template against its recorded English source.

    Args:
        template_path: path to a generated ``.<lang>.tex`` template.
        source_root: optional base directory to resolve a relative recorded source path (or to
            relocate the source by the path recorded in the marker). ``None`` uses the recorded
            path as-is.
    Returns:
        A dict with ``status`` one of:

        - ``up-to-date``     source found and its hash matches the recorded one
        - ``stale``          source found but its hash differs (English changed since translation)
        - ``source-missing`` the recorded source path no longer exists
        - ``no-provenance``  the template carries no provenance marker (untracked)

        plus ``template`` and, when a marker was present, ``source``/``recorded_sha256`` and
        (when the source exists) ``current_sha256``.
    """
    tp = Path(template_path)
    prov = parse_provenance(tp.read_text(encoding="utf-8"))
    if not prov:
        return {"status": "no-provenance", "template": str(template_path)}

    src = Path(prov["path"])
    if source_root is not None:
        candidate = Path(source_root) / prov["path"] if not src.is_absolute() else src
        if candidate.exists():
            src = candidate
        else:
            # last resort: relocate by basename under source_root
            by_name = Path(source_root) / Path(prov["path"]).name
            if by_name.exists():
                src = by_name

    result = {"status": None, "template": str(template_path), "source": prov["path"],
              "recorded_sha256": prov["sha256"]}
    if not src.exists():
        result["status"] = "source-missing"
        return result
    cur = source_sha256(src.read_text(encoding="utf-8"))
    result["current_sha256"] = cur
    result["status"] = "up-to-date" if cur == prov["sha256"] else "stale"
    return result
