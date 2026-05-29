"""Resume ingest: PDF / DOCX → baseresume.txt.

Convention: drop a single `baseresume.{pdf,docx,txt}` in the project
root. This module scans for whichever variant exists, extracts plain
text via stdlib-friendly libraries (`pymupdf` for PDF, `docx2txt` for
DOCX), and writes the result to `baseresume.txt` so every downstream
consumer (resume drafter, USAJOBS scoring, watcher) reads ONE canonical
text file.

The extraction is idempotent — if the .txt is newer than every source
file we found, the call is a no-op. So setup.bat can invoke this on
every launch without redoing work.

CLI wrapper at scripts/ingest_resume.py exposes this for manual use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_RESUME_TXT = PROJECT_ROOT / "baseresume.txt"

# Source files we look at, in priority order. PDF preferred over DOCX
# because federal resumes are usually distributed as PDF; DOCX preferred
# over TXT because most modern resumes are authored as DOCX.
_SOURCE_NAMES = ("baseresume.pdf", "baseresume.docx")


@dataclass
class IngestResult:
    ok: bool
    action: str        # 'extracted' | 'up-to-date' | 'no-source' | 'failed'
    source: Path | None
    target: Path
    chars_written: int = 0
    error: str | None = None


def _extract_pdf(path: Path) -> str | None:
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        parts: list[str] = []
        with pymupdf.open(str(path)) as doc:
            for page in doc:
                parts.append(page.get_text())
        return "\n".join(parts)
    except Exception:
        return None


def _extract_docx(path: Path) -> str | None:
    try:
        import docx2txt
    except ImportError:
        return None
    try:
        return docx2txt.process(str(path)) or ""
    except Exception:
        return None


def ingest_from_path(src: Path, *, project_root: Path = PROJECT_ROOT,
                     verbose: bool = False) -> IngestResult:
    """Extract text from an arbitrary source file and overwrite
    `baseresume.txt` in `project_root`. Used by the web UI's
    /api/resume/upload handler so the user can pick a resume from the
    desktop file picker instead of dropping it in the project root.

    Supports the same formats as `ingest_resume`: PDF (pymupdf), DOCX
    (docx2txt), plus TXT/MD (read as UTF-8). Always overwrites — the
    upload path is explicit user intent.
    """
    target = project_root / "baseresume.txt"
    if not src.exists():
        return IngestResult(ok=False, action="failed", source=src, target=target,
                            error=f"source not found: {src}")

    suffix = src.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf(src)
    elif suffix == ".docx":
        text = _extract_docx(src)
    elif suffix in (".txt", ".md"):
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return IngestResult(ok=False, action="failed", source=src, target=target,
                                error=f"read failed: {exc}")
    else:
        return IngestResult(ok=False, action="failed", source=src, target=target,
                            error=f"unsupported source format: {suffix}")

    if text is None:
        return IngestResult(ok=False, action="failed", source=src, target=target,
                            error="extraction returned None — is pymupdf/docx2txt installed?")
    text = text.strip()
    if not text:
        return IngestResult(ok=False, action="failed", source=src, target=target,
                            error="extraction produced empty text (image-only PDF?)")

    target.write_text(text, encoding="utf-8")
    if verbose:
        print(f"[ingest] wrote {len(text)} chars to {target.name} from {src.name}")
    return IngestResult(ok=True, action="extracted",
                        source=src, target=target, chars_written=len(text))


def ingest_resume(*, force: bool = False, project_root: Path = PROJECT_ROOT,
                  verbose: bool = False) -> IngestResult:
    """Look for baseresume.{pdf,docx} in `project_root`. If found AND
    newer than baseresume.txt (or `force=True`), extract text and write
    baseresume.txt. Otherwise no-op.
    """
    target = project_root / "baseresume.txt"

    sources = [project_root / name for name in _SOURCE_NAMES]
    sources = [p for p in sources if p.exists()]

    if verbose:
        print(f"[ingest] scanning {project_root}")
        print(f"[ingest] sources found: {[s.name for s in sources] or '(none)'}")
        print(f"[ingest] target exists: {target.exists()}")

    if not sources:
        return IngestResult(
            ok=target.exists(),
            action="no-source",
            source=None, target=target,
            error=None if target.exists() else "no baseresume.{pdf,docx,txt} found",
        )

    # Pick the most recently modified source (lets the user iterate on
    # whichever format they're editing).
    src = max(sources, key=lambda p: p.stat().st_mtime)

    # Skip if .txt is newer or equal to the source AND not forced.
    if not force and target.exists():
        target_mtime = target.stat().st_mtime
        src_mtime = src.stat().st_mtime
        if target_mtime >= src_mtime:
            if verbose:
                print(f"[ingest] {target.name} is current (newer than {src.name})")
            return IngestResult(ok=True, action="up-to-date",
                                source=src, target=target,
                                chars_written=target.stat().st_size)

    if verbose:
        print(f"[ingest] extracting {src.name} → {target.name}")

    if src.suffix.lower() == ".pdf":
        text = _extract_pdf(src)
    elif src.suffix.lower() == ".docx":
        text = _extract_docx(src)
    else:
        # Shouldn't happen given the _SOURCE_NAMES guard, but defensive.
        return IngestResult(ok=False, action="failed", source=src, target=target,
                            error=f"unsupported source format: {src.suffix}")

    if text is None:
        return IngestResult(
            ok=False, action="failed", source=src, target=target,
            error=f"extraction returned None — is pymupdf/docx2txt installed?",
        )

    text = text.strip()
    if not text:
        return IngestResult(
            ok=False, action="failed", source=src, target=target,
            error=f"extraction produced empty text — {src.name} may be corrupt or image-only",
        )

    target.write_text(text, encoding="utf-8")
    if verbose:
        print(f"[ingest] wrote {len(text)} chars")
    return IngestResult(ok=True, action="extracted",
                        source=src, target=target, chars_written=len(text))


__all__ = ["ingest_resume", "ingest_from_path", "IngestResult",
           "BASE_RESUME_TXT", "PROJECT_ROOT"]
