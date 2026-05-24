"""Copy the CUDA runtime DLLs from the nvidia-* pip packages into the
llama-cpp-python lib directory so llama.dll's loader finds them.

The prebuilt llama-cpp-python CUDA wheel dynamically links to:
  cudart64_12.dll       (nvidia-cuda-runtime-cu12)
  cublas64_12.dll       (nvidia-cublas-cu12)
  cublasLt64_12.dll     (nvidia-cublas-cu12)
  nvrtc64_120_0.dll     (nvidia-cuda-nvrtc-cu12)
  nvrtc-builtins64_*.dll (nvidia-cuda-nvrtc-cu12)

The DLLs ship in `site-packages/nvidia/<subpkg>/bin/`, which the loader
does not search. Copying them next to `llama.dll` is the simplest fix
that works without modifying PATH or adding os.add_dll_directory()
calls in user code.

Idempotent: skips files that already exist with the same size.
"""

from __future__ import annotations

import shutil
import site
import sys
from pathlib import Path


def find_llama_lib() -> Path | None:
    for site_dir in site.getsitepackages() + [site.getusersitepackages()]:
        candidate = Path(site_dir) / "llama_cpp" / "lib"
        if candidate.is_dir():
            return candidate
    return None


def find_nvidia_dlls() -> list[Path]:
    out: list[Path] = []
    for site_dir in site.getsitepackages() + [site.getusersitepackages()]:
        nvidia_root = Path(site_dir) / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for dll in nvidia_root.rglob("*.dll"):
            out.append(dll)
    return out


def main() -> int:
    target = find_llama_lib()
    if target is None:
        print("[install_cuda_dlls] llama_cpp/lib not found — skipping.", file=sys.stderr)
        return 0  # not fatal

    dlls = find_nvidia_dlls()
    if not dlls:
        print("[install_cuda_dlls] No nvidia/*.dll found — install nvidia-cuda-runtime-cu12 first.",
              file=sys.stderr)
        return 1

    copied = 0
    skipped = 0
    for src in dlls:
        dst = target / src.name
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            skipped += 1
            continue
        try:
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            print(f"[install_cuda_dlls] copy failed {src.name}: {exc}", file=sys.stderr)

    print(f"[install_cuda_dlls] Copied {copied} DLLs into {target} (skipped {skipped}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
