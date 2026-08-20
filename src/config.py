"""
omnigab Configuration
=======================
Central config for all pipeline components. Edit these values to swap models,
adjust chunk sizes, or tune retrieval parameters.
"""

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
# Both entries are bartowski requants of the official Qwen weights. Unlike
# Qwen2.5, the Qwen team publishes no first-party GGUFs for 3.5, so there
# is no official repo to prefer. Bartowski was already the source for the
# old 7B and 14B entries, ships single-file quants rather than gguf-split
# (which hf_hub_download cannot fetch by plain filename), and mirrors the
# upstream Apache-2.0 license.
#
# The doubled name in the filenames is bartowski's <org>_<model> convention,
# not a typo. It has to match the file on the Hub exactly, because
# ensure_model_downloaded() passes it straight to hf_hub_download.
AVAILABLE_MODELS = {
    "Qwen_Qwen3.5-4B-Q4_K_M.gguf": {
        "name": "Qwen 3.5 4B (Default)",
        "size": "~3.0 GB",
        "ram": "~6 GB",
        "repo": "bartowski/Qwen_Qwen3.5-4B-GGUF",
    },
    "Qwen_Qwen3.5-9B-Q4_K_M.gguf": {
        "name": "Qwen 3.5 9B (Best Quality)",
        "size": "~6.2 GB",
        "ram": "~12 GB",
        "repo": "bartowski/Qwen_Qwen3.5-9B-GGUF",
    },
}
MODELS_DIR = PROJECT_ROOT.parent / "models"
# Must match what setup.bat actually downloads. A first run that defaults
# to a model the installer never fetched leaves a new user staring at a
# "model not downloaded" error before they have typed anything.
DEFAULT_GGUF_MODEL = "Qwen_Qwen3.5-4B-Q4_K_M.gguf"


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
# agent needs to hold its system prompt plus a reply. The ceiling was set
# to what Qwen2.5 was trained for and has not been re-derived for the
# Qwen3.5 catalog, so treat 32768 as a conservative cap rather than a
# measured limit: quality degrades past a model's trained window even when
# the hardware allows it.
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
