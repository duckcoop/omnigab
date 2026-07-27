"""
omnigab Configuration
=======================
Central config for all pipeline components. Edit these values to swap models,
adjust chunk sizes, or tune retrieval parameters.
"""

import os
import json
from pathlib import Path

# -- Paths --
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT.parent / "data"
DOCS_DIR = DATA_DIR / "docs"
VECTORSTORE_DIR = PROJECT_ROOT.parent / "vectorstore"
INDEX_PATH = VECTORSTORE_DIR / "faiss_index"
METADATA_PATH = VECTORSTORE_DIR / "metadata.json"
MODEL_STATE_PATH = DATA_DIR / "model_state.json"

# -- Document Processing --
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".log", ".cfg", ".ini", ".yaml", ".yml", ".json", ".csv"}
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# -- Embedding Model --
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

# -- Retrieval --
TOP_K = 3
SIMILARITY_THRESHOLD = 0.3

# -- Generation Model (GGUF via llama-cpp) --
# Available models (download into models/ folder):
AVAILABLE_MODELS = {
    "qwen2.5-1.5b-instruct-q4_k_m.gguf": {
        "name": "Qwen 2.5 1.5B (Default)",
        "size": "~1.1 GB",
        "ram": "~4 GB",
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    },
    "qwen2.5-3b-instruct-q4_k_m.gguf": {
        "name": "Qwen 2.5 3B (Recommended)",
        "size": "~2.1 GB",
        "ram": "~6 GB",
        "repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
    },
    # 7B uses bartowski's single-file quant. The official Qwen repo
    # shards the 7B Q4_K_M into two pieces (gguf-split format), which
    # hf_hub_download can't fetch with a plain filename. Bartowski's
    # repo is the same source we already use for the 14B.
    "Qwen2.5-7B-Instruct-Q4_K_M.gguf": {
        "name": "Qwen 2.5 7B (Great Quality)",
        "size": "~4.4 GB",
        "ram": "~10 GB",
        "repo": "bartowski/Qwen2.5-7B-Instruct-GGUF",
    },
    "Qwen2.5-14B-Instruct-Q4_K_M.gguf": {
        "name": "Qwen 2.5 14B (Best Quality)",
        "size": "~8.9 GB",
        "ram": "~16 GB",
        "repo": "bartowski/Qwen2.5-14B-Instruct-GGUF",
    },
}
MODELS_DIR = PROJECT_ROOT.parent / "models"
# Must match what setup.bat actually downloads. A first run that defaults
# to a model the installer never fetched leaves a new user staring at a
# "model not downloaded" error before they have typed anything.
DEFAULT_GGUF_MODEL = "qwen2.5-1.5b-instruct-q4_k_m.gguf"


def _load_selected_model() -> str:
    """Read the currently selected model from the state file, if any."""
    try:
        if MODEL_STATE_PATH.exists():
            with open(MODEL_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            filename = state.get("filename", "")
            # Only honour the saved choice if the file is still on disk.
            # Otherwise a deleted or half-downloaded model would break
            # startup with no obvious cause.
            if filename in AVAILABLE_MODELS and (MODELS_DIR / filename).exists():
                return filename
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return _first_available_model()


def _first_available_model() -> str:
    """Prefer a model actually present on disk, smallest first.

    A user who deleted a big model, or whose download was interrupted,
    should still get a working app rather than a hard failure at startup.
    """
    try:
        for filename in AVAILABLE_MODELS:  # dict order is smallest to largest
            if (MODELS_DIR / filename).exists():
                return filename
    except OSError:
        pass
    return DEFAULT_GGUF_MODEL


def save_selected_model(filename: str) -> None:
    """Persist the user-selected model. Caller must validate against AVAILABLE_MODELS."""
    if filename not in AVAILABLE_MODELS:
        raise ValueError("Unknown model filename")
    MODEL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"filename": filename}, f, indent=2)


CONTEXT_STATE_PATH = MODEL_STATE_PATH.parent / "context_override.json"

# Bounds for the user-adjustable context window. The floor is what the
# agent needs to hold its system prompt plus a reply; the ceiling is what
# Qwen2.5 models are trained for. Going past 32768 degrades quality even
# when the hardware allows it.
CONTEXT_MIN = 2048
CONTEXT_MAX = 32768


def load_context_override() -> int | None:
    """User-set context window, or None to auto-size against VRAM."""
    try:
        if CONTEXT_STATE_PATH.exists():
            with open(CONTEXT_STATE_PATH, "r", encoding="utf-8") as f:
                value = json.load(f).get("n_ctx")
            if value is None:
                return None
            value = int(value)
            if CONTEXT_MIN <= value <= CONTEXT_MAX:
                return value
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def save_context_override(n_ctx: int | None) -> None:
    """Persist a context window override. Pass None to restore auto-sizing.

    Raises ValueError if the value is outside the supported range, so the
    UI can show a real message instead of the model failing to load later.
    """
    if n_ctx is not None:
        n_ctx = int(n_ctx)
        if not (CONTEXT_MIN <= n_ctx <= CONTEXT_MAX):
            raise ValueError(
                f"Context window must be between {CONTEXT_MIN} and {CONTEXT_MAX}."
            )
    CONTEXT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONTEXT_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"n_ctx": n_ctx}, f, indent=2)


GGUF_MODEL_PATH = MODELS_DIR / _load_selected_model()
CONTEXT_WINDOW = 8192
N_THREADS = 8       # match your physical core count (Ryzen 9850X3D = 8 cores)

# Legacy HuggingFace fallback (used if USE_GGUF = False)
GENERATION_MODEL = "HuggingFaceTB/SmolLM2-360M-Instruct"
USE_GGUF = True

# Per-response generation ceiling. Job-search answers need room for the
# <thinking> block (~250 tokens for 10 jobs) plus ~50 tokens per rendered
# job. 10 jobs = ~750-900 tokens; 25 jobs = ~1500. 1536 leaves comfortable
# headroom and still fits inside the 8192-token context alongside the
# system prompt, tool result, and history. Short chats cost nothing — the
# model emits EOT naturally regardless of this cap.
MAX_NEW_TOKENS = 2048
TEMPERATURE = 0.15
TOP_P = 0.9

# -- Web Search --
WEB_SEARCH_ENABLED = True       # set to False to disable web search entirely
WEB_SEARCH_MAX_RESULTS = 3      # number of web results to fetch per query

# -- Verification Layer --
FAITHFULNESS_THRESHOLD = 0.8
CLAIM_SUPPORT_THRESHOLD = 0.45
MAX_CORRECTION_ROUNDS = 2
RETRY_TEMP_BOOST = 0.15
RETRY_TOPK_BOOST = 2

