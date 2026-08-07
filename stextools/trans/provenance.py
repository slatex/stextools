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

The hash is taken over the *raw bytes* of the source with line endings normalized, so a
non-UTF-8 source can never crash the check and a pure CRLF/LF change is not seen as a change.
The marker is intentionally *deterministic* (no timestamps): re-translating an unchanged source
produces byte-identical output, so it never creates spurious diffs.
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, Optional

PROV_VERSION = 1
_MARKER_PREFIX = "% stex-trans-source:"

# The header marker written into every generated template and parsed back out.
_PROV_RE = re.compile(
    r'^% stex-trans-source: v=(?P<v>\d+) sha256=(?P<sha>[0-9a-fA-F]{64}) path=(?P<path>.+?)[ \t]*$',
    re.MULTILINE,
)


def _normalize_bytes(data: bytes) -> bytes:
    """Line-ending-independent view of the bytes so CRLF/LF churn is not seen as a change."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(_normalize_bytes(data)).hexdigest()


def source_sha256(text: str) -> str:
    """SHA-256 of source text (EOL-normalized). Files are hashed by bytes; see :func:`fingerprint_file`."""
    return _sha256_bytes(text.encode("utf-8"))


def fingerprint_file(path) -> Dict:
    """Fingerprint an English source file for provenance recording.

    Reads raw bytes (so a non-UTF-8 source does not raise) and hashes them EOL-normalized.

    Args:
        path: path to the English ``.en.tex`` source.
    Returns:
        ``{"path": <forward-slashed path as given>, "sha256": <hex>, "bytes": <int>}``. Pass a
        resolved/absolute path so the marker is independent of the working directory.
    """
    data = Path(path).read_bytes()
    return {
        "path": str(path).replace("\\", "/"),
        "sha256": _sha256_bytes(data),
        "bytes": len(_normalize_bytes(data)),
    }


def provenance_comment(fp: Dict) -> str:
    """The header marker line (with trailing newline) recording where a template came from."""
    return f"% stex-trans-source: v={PROV_VERSION} sha256={fp['sha256']} path={fp['path']}\n"


def parse_provenance(template_text: str) -> Optional[Dict]:
    """Extract the provenance marker from a generated template.

    Returns:
        ``{"version": int, "sha256": str, "path": str}`` or ``None`` if the template carries no
        (well-formed) marker. Use :func:`check_staleness` to distinguish a missing marker from a
        malformed one.
    """
    m = _PROV_RE.search(template_text)
    if not m:
        return None
    return {"version": int(m.group("v")), "sha256": m.group("sha").lower(), "path": m.group("path")}


def _resolve_source(recorded_path: str, source_root=None) -> Optional[Path]:
    """Locate the current English source for a recorded provenance path.

    Tries the recorded path as-is first. If it is missing and ``source_root`` is given, relocate
    by matching a *tail* of the recorded path under the root (longest tail first, at least two
    path segments) --- this handles a moved MathHub checkout without the ambiguity of matching an
    unrelated file that merely shares a basename.
    """
    src = Path(recorded_path)
    if src.exists():
        return src
    if source_root is not None:
        root = Path(source_root)
        parts = Path(recorded_path).parts
        for i in range(len(parts)):
            tail = parts[i:]
            if len(tail) < 2:      # never relocate on the basename alone (would be ambiguous)
                break
            cand = root.joinpath(*tail)
            if cand.exists():
                return cand
    return None


def check_staleness(template_path, source_root=None) -> Dict:
    """Compare a translated template against its recorded English source.

    Args:
        template_path: path to a generated ``.<lang>.tex`` template.
        source_root: optional base directory to relocate the recorded source path (e.g. a
            different MathHub checkout). ``None`` uses the recorded path as-is.
    Returns:
        A dict with ``status`` one of:

        - ``up-to-date``          source found and its hash matches the recorded one
        - ``stale``               source found but its hash differs (English changed)
        - ``source-missing``      the recorded source path no longer exists (even under source_root)
        - ``no-provenance``       the template carries no provenance marker (untracked)
        - ``malformed-provenance``a marker line is present but does not parse (tampered/truncated)

        plus ``template`` and, when a marker was present, ``source``/``recorded_sha256`` and (when
        the source was located) ``resolved_source``/``current_sha256``.
    """
    text = Path(template_path).read_text(encoding="utf-8", errors="replace")
    prov = parse_provenance(text)
    if prov is None:
        status = "malformed-provenance" if _MARKER_PREFIX in text else "no-provenance"
        return {"status": status, "template": str(template_path)}

    result = {"status": None, "template": str(template_path), "source": prov["path"],
              "recorded_sha256": prov["sha256"]}
    src = _resolve_source(prov["path"], source_root)
    if src is None:
        result["status"] = "source-missing"
        return result
    result["resolved_source"] = str(src)
    cur = _sha256_bytes(src.read_bytes())
    result["current_sha256"] = cur
    result["status"] = "up-to-date" if cur == prov["sha256"] else "stale"
    return result
