"""Owns the active llama-cpp Llama instance. Hot-swap + GPU offload.

This is the single source of truth for which model is loaded. The web
app, desktop app, agent loop, and tools all read `mm.generator` rather
than constructing their own. Calling `mm.load(filename)` unloads the
current model (releases VRAM/RAM and the ctypes-backed handle), then
loads the requested one. The operation is thread-safe so two requests
firing /api/models/switch concurrently cannot corrupt the slot.
"""

from __future__ import annotations

import gc
import os
import threading

from config import (
    AVAILABLE_MODELS,
    MODELS_DIR,
    CONTEXT_WINDOW,
    N_THREADS,
    save_selected_model,
)


# Per-model VRAM/RAM cost estimates and recommended context sizes.
# Numbers tuned for Q4_K_M GGUFs on a single GPU. Keep n_ctx small enough
# that model_weights + KV_cache + overhead < VRAM, otherwise llama-cpp
# splits to system RAM and inference collapses to 1-3 tok/s.
MODEL_PROFILE: dict[str, dict] = {
    "qwen2.5-1.5b-instruct-q4_k_m.gguf": {"weight_gb": 1.1, "ctx": 8192,  "batch": 512},
    "qwen2.5-3b-instruct-q4_k_m.gguf":   {"weight_gb": 2.1, "ctx": 8192,  "batch": 512},
    "qwen2.5-7b-instruct-q4_k_m.gguf":   {"weight_gb": 4.4, "ctx": 8192,  "batch": 1024},
    # 14B at 8192 ctx with q8_0 KV cache (~1.5 GB) and 9 GB weights sits at
    # ~10.5 GB on a 12 GB card — comfortable headroom, lets us push batch
    # to 1024 for faster prompt processing.
    "Qwen2.5-14B-Instruct-Q4_K_M.gguf":  {"weight_gb": 8.9, "ctx": 8192,  "batch": 1024},
}
_DEFAULT_PROFILE = {"weight_gb": 9.0, "ctx": 4096, "batch": 512}


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def cuda_supported() -> bool:
    """Whether the loaded llama-cpp wheel was built with CUDA."""
    try:
        import llama_cpp  # noqa: WPS433 (local import keeps boot light)

        fn = getattr(llama_cpp, "llama_supports_gpu_offload", None)
        return bool(fn()) if fn else False
    except Exception:
        return False


def detect_vram_gb() -> int:
    """Best-effort VRAM detection via nvidia-smi. Returns 0 if unknown."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip().splitlines()
        if out:
            return int(out[0]) // 1024
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        pass
    return 0


def detect_ram_gb() -> int:
    """Total system RAM in GB. Uses psutil if available, ctypes on Windows
    otherwise. Returns 0 if we can't tell — the autotuner treats unknown
    as 'low end' and picks the safest model.
    """
    try:
        import psutil
        return int(psutil.virtual_memory().total / (1024 ** 3))
    except ImportError:
        pass

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys / (1024 ** 3))
        except Exception:
            return 0

    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // (1024 ** 2)
    except (OSError, ValueError, IndexError):
        pass
    return 0


# Hardware tier → recommended GGUF. Ordered from biggest to smallest;
# we pick the largest model whose VRAM (or RAM, for CPU-only) headroom
# fits comfortably with a 1.5 GB safety margin.
HARDWARE_TIERS = [
    {"min_vram_gb": 10, "model": "Qwen2.5-14B-Instruct-Q4_K_M.gguf"},
    {"min_vram_gb": 6,  "model": "qwen2.5-7b-instruct-q4_k_m.gguf"},
    {"min_vram_gb": 4,  "model": "qwen2.5-3b-instruct-q4_k_m.gguf"},
    {"min_vram_gb": 0, "min_ram_gb": 16, "model": "qwen2.5-3b-instruct-q4_k_m.gguf"},
    {"min_vram_gb": 0, "min_ram_gb": 0,  "model": "qwen2.5-1.5b-instruct-q4_k_m.gguf"},
]


def select_optimal_model() -> tuple[str, dict]:
    """Pick the right model for this machine. Returns (filename, details).

    Heuristic:
      * If a CUDA wheel is loaded AND nvidia-smi reports VRAM, scale by VRAM.
      * Otherwise scale by system RAM (CPU inference path).
      * Always falls through to the 1.5B safety net if nothing else fits.
    """
    vram = detect_vram_gb() if cuda_supported() else 0
    ram = detect_ram_gb()

    for tier in HARDWARE_TIERS:
        v_ok = vram >= tier.get("min_vram_gb", 0)
        r_ok = ram >= tier.get("min_ram_gb", 0)
        if v_ok and r_ok and tier["model"] in AVAILABLE_MODELS:
            return tier["model"], {
                "reason": "auto-selected for this hardware",
                "vram_gb": vram,
                "ram_gb": ram,
                "gpu_path": vram > 0,
            }

    fallback = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    return fallback, {
        "reason": "safety fallback",
        "vram_gb": vram, "ram_gb": ram, "gpu_path": False,
    }


def ensure_model_downloaded(filename: str, *, progress: bool = True) -> bool:
    """Download `filename` from Hugging Face if it's not already on disk.

    Returns True if the file is present after this call. Uses the repo
    configured in AVAILABLE_MODELS. Safe to call on every startup — it
    is a no-op when the file already exists.
    """
    if filename not in AVAILABLE_MODELS:
        return False
    target = MODELS_DIR / filename
    if target.exists():
        return True

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[omnigab] huggingface-hub not installed; cannot auto-download.")
        return False

    repo = AVAILABLE_MODELS[filename]["repo"]
    if progress:
        size = AVAILABLE_MODELS[filename]["size"]
        print(f"[omnigab] Downloading {filename} ({size}) from {repo}…")
    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        hf_hub_download(repo_id=repo, filename=filename, local_dir=str(MODELS_DIR))
        return target.exists()
    except Exception as exc:
        print(f"[omnigab] Download failed: {exc}")
        return False


def default_gpu_layers() -> int:
    """High explicit number = offload every layer that fits.

    Llama.cpp silently caps the request at the model's actual layer count,
    so 999 effectively means 'all'. Returns 0 if CUDA isn't supported.
    Honours RAG_GPU_LAYERS for power users who want to dial it back.
    """
    if not cuda_supported():
        return 0
    return _env_int("RAG_GPU_LAYERS", 999)


def optimal_context(filename: str, vram_gb: int) -> tuple[int, int]:
    """Pick (n_ctx, n_batch) so KV cache fits in VRAM without swapping.

    On a 12 GB card (RTX 4070 Super) with the 14B Q4 (~9 GB), this leaves
    ~3 GB for KV cache → 8192 tokens is safe. On 8 GB cards we drop the
    14B context to 4096 to avoid the system-RAM spillover that pins
    inference at 1-3 tok/s.
    """
    profile = MODEL_PROFILE.get(filename, _DEFAULT_PROFILE)
    weight_gb = profile["weight_gb"]
    ctx = profile["ctx"]
    batch = profile["batch"]

    if vram_gb > 0:
        # 0.5 GB safety margin — nvidia-smi rounds GB down, real headroom
        # is usually a few hundred MB more than the integer suggests.
        headroom = vram_gb - weight_gb - 0.5
        if headroom <= 0:
            # Won't fully offload; conservative defaults to avoid CPU spill.
            ctx = min(ctx, 2048)
            batch = 256
        elif headroom < 1.0:
            ctx = min(ctx, 4096)
            batch = 256
        elif headroom < 2.5:
            ctx = min(ctx, 8192)
            batch = 512
        # else: keep profile defaults (large headroom on big GPUs)

    # Env override still wins.
    ctx = _env_int("RAG_CONTEXT_WINDOW", ctx)
    batch = _env_int("RAG_N_BATCH", batch)
    return ctx, batch


class ModelManager:
    """Holds the single live Generator. Thread-safe swap."""

    def __init__(self, initial_model: str):
        self._lock = threading.Lock()
        self.current_model_name: str = ""
        self.generator = None
        self.gpu_supported: bool = cuda_supported()
        self.gpu_layers: int = default_gpu_layers()
        self.vram_gb: int = detect_vram_gb()
        self.n_ctx: int = CONTEXT_WINDOW
        self.n_batch: int = 512
        self.load(initial_model)

    # ----- public API ---------------------------------------------------

    def load(self, filename: str) -> dict:
        if filename not in AVAILABLE_MODELS:
            raise ValueError(f"Unknown model: {filename}")
        path = MODELS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Model file not downloaded: {filename}")

        with self._lock:
            self._unload_locked()
            from generator import Generator  # local import: avoid top-level llama_cpp load

            n_ctx, n_batch = optimal_context(filename, self.vram_gb if self.gpu_supported else 0)
            self.n_ctx = n_ctx
            self.n_batch = n_batch

            self.generator = Generator(
                model_path=str(path),
                n_gpu_layers=self.gpu_layers,
                n_ctx=n_ctx,
                n_batch=n_batch,
                n_threads=N_THREADS,
            )
            self.current_model_name = filename
            try:
                save_selected_model(filename)
            except (OSError, ValueError):
                pass
            return self.status_locked()

    def unload(self) -> None:
        with self._lock:
            self._unload_locked()
            self.current_model_name = ""

    def status(self) -> dict:
        with self._lock:
            return self.status_locked()

    def status_locked(self) -> dict:
        return {
            "current_model": self.current_model_name,
            "loaded": self.generator is not None,
            "gpu_supported": self.gpu_supported,
            "gpu_layers": self.gpu_layers,
            "vram_gb": self.vram_gb,
            "context_window": self.n_ctx,
            "n_batch": self.n_batch,
            "threads": N_THREADS,
        }

    # ----- internal -----------------------------------------------------

    def _unload_locked(self) -> None:
        if self.generator is None:
            return
        try:
            llm = getattr(self.generator, "llm", None)
            if llm is not None and hasattr(llm, "close"):
                llm.close()
            elif llm is not None and hasattr(llm, "__del__"):
                # Llama's destructor frees the underlying ctypes model
                del llm
        except Exception:
            pass
        self.generator = None
        gc.collect()
