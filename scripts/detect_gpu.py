"""Probe NVIDIA GPU info using nvidia-smi without cmd batch quirks.

Prints exactly one line to stdout in the form:
    PRESENT|NAME|VRAM_GB

If no GPU is found, prints:
    0||0

Exit code is always 0 — the caller parses the line. All errors are
silently swallowed so cmd batch never sees stderr garbage from
nvidia-smi or python.

Used by setup.bat. Stdlib only (no numpy/psutil) so it runs before
any pip install has happened.
"""

from __future__ import annotations

import subprocess
import sys


def _smi(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def main() -> int:
    name = _smi(["--query-gpu=name", "--format=csv,noheader"])
    vram_raw = _smi(["--query-gpu=memory.total", "--format=csv,noheader,nounits"])

    if not name:
        print("0||0")
        return 0

    # nvidia-smi returns one line per GPU. Take the first only.
    name = name.splitlines()[0].strip()
    vram_gb = 0
    if vram_raw:
        try:
            vram_mb = int(vram_raw.splitlines()[0].strip())
            vram_gb = vram_mb // 1024
        except (ValueError, IndexError):
            pass

    print(f"1|{name}|{vram_gb}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Last-resort fallback so the helper never crashes the caller.
        print("0||0")
        sys.exit(0)
