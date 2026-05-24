"""Install the right llama-cpp-python wheel for this machine.

Replaces the deeply-nested cmd batch logic that was miscounting parens.
This script:

1. Detects whether an NVIDIA GPU is present (via nvidia-smi).
2. If GPU: tries the abetlen prebuilt CUDA wheels in order
   (cu124 -> cu122 -> cu121 -> cu118), copies CUDA runtime DLLs into
   llama_cpp/lib/, and verifies the import actually exposes GPU offload.
3. If no GPU, or every CUDA path fails: installs the CPU wheel.

Exit code 0 = success (CUDA or CPU). Exit code 1 = total install failure.

Called by setup.bat as a single line, so cmd batch never has to nest
half a dozen if-blocks.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


PYTHON = sys.executable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_CUDA_DLLS = PROJECT_ROOT / "scripts" / "install_cuda_dlls.py"

CUDA_WHEEL_INDEXES = [
    ("cu124", "https://abetlen.github.io/llama-cpp-python/whl/cu124"),
    ("cu122", "https://abetlen.github.io/llama-cpp-python/whl/cu122"),
    ("cu121", "https://abetlen.github.io/llama-cpp-python/whl/cu121"),
    ("cu118", "https://abetlen.github.io/llama-cpp-python/whl/cu118"),
]
CPU_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"


def has_nvidia_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def llama_cpp_present() -> bool:
    try:
        subprocess.run([PYTHON, "-c", "import llama_cpp"],
                       capture_output=True, timeout=15, check=True)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def llama_cpp_has_cuda() -> bool:
    try:
        result = subprocess.run(
            [PYTHON, "-c",
             "import llama_cpp,sys; fn=getattr(llama_cpp,'llama_supports_gpu_offload',None); "
             "sys.exit(0 if (fn and fn()) else 1)"],
            capture_output=True, timeout=15, check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def pip(*args: str) -> int:
    cmd = [PYTHON, "-m", "pip", *args]
    print(f"  $ {' '.join(cmd[2:])}")
    result = subprocess.run(cmd)
    return result.returncode


def install_cuda_runtime_dlls() -> bool:
    """Install the nvidia-* runtime packages and copy DLLs next to llama.dll."""
    rc = pip("install",
             "nvidia-cuda-runtime-cu12",
             "nvidia-cublas-cu12",
             "nvidia-cuda-nvrtc-cu12",
             "--quiet", "--no-cache-dir")
    if rc != 0:
        print("  WARNING: CUDA runtime DLL install failed.")
        return False
    rc = subprocess.run([PYTHON, str(INSTALL_CUDA_DLLS)]).returncode
    return rc == 0


def install_cpu_wheel() -> bool:
    print("[install_llama_cpp] Installing CPU wheel...")
    pip("uninstall", "-y", "llama-cpp-python")
    rc = pip("install", "llama-cpp-python",
             "--prefer-binary",
             "--extra-index-url", CPU_WHEEL_INDEX,
             "--upgrade", "--force-reinstall", "--no-cache-dir")
    return rc == 0


def try_install_cuda_wheel() -> bool:
    """Try each CUDA wheel index in order; copy DLLs; verify GPU offload."""
    pip("uninstall", "-y", "llama-cpp-python")

    installed = False
    for label, index_url in CUDA_WHEEL_INDEXES:
        print(f"[install_llama_cpp] Trying prebuilt {label} wheel...")
        rc = pip("install", "llama-cpp-python",
                 "--prefer-binary",
                 "--extra-index-url", index_url,
                 "--upgrade", "--force-reinstall", "--no-cache-dir")
        if rc == 0:
            installed = True
            print(f"[install_llama_cpp] {label} wheel installed.")
            break
        print(f"[install_llama_cpp] {label} unavailable.")

    if not installed:
        return False

    print("[install_llama_cpp] Wiring CUDA runtime DLLs next to llama.dll...")
    install_cuda_runtime_dlls()

    if llama_cpp_has_cuda():
        print("[install_llama_cpp] CUDA-enabled llama-cpp-python verified.")
        return True

    print("[install_llama_cpp] WARNING: wheel installed but llama_supports_gpu_offload=False.")
    return False


def main() -> int:
    gpu = has_nvidia_gpu()
    print(f"[install_llama_cpp] GPU present: {gpu}")

    # Fast path: already installed and correct for this hardware.
    if llama_cpp_present():
        if gpu and llama_cpp_has_cuda():
            print("[install_llama_cpp] llama-cpp-python with CUDA already installed. Re-syncing DLLs...")
            install_cuda_runtime_dlls()
            return 0
        if not gpu and not llama_cpp_has_cuda():
            print("[install_llama_cpp] llama-cpp-python (CPU) already installed.")
            return 0

    # Reinstall path.
    if gpu:
        # Make sure runtime DLL packages are present BEFORE the verification,
        # otherwise import fails for reasons unrelated to the wheel itself.
        install_cuda_runtime_dlls()
        if try_install_cuda_wheel():
            return 0
        print("[install_llama_cpp] CUDA wheel path failed. Falling back to CPU.")

    if install_cpu_wheel():
        return 0

    print("[install_llama_cpp] ERROR: Could not install llama-cpp-python at all.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
