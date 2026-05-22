"""
RAG Agent Configuration
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
    "qwen2.5-7b-instruct-q4_k_m.gguf": {
        "name": "Qwen 2.5 7B (Great Quality)",
        "size": "~4.4 GB",
        "ram": "~10 GB",
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
    },
    "Qwen2.5-14B-Instruct-Q4_K_M.gguf": {
        "name": "Qwen 2.5 14B (Best Quality)",
        "size": "~8.9 GB",
        "ram": "~16 GB",
        "repo": "bartowski/Qwen2.5-14B-Instruct-GGUF",
    },
}
MODELS_DIR = PROJECT_ROOT.parent / "models"
DEFAULT_GGUF_MODEL = "Qwen2.5-14B-Instruct-Q4_K_M.gguf"


def _load_selected_model() -> str:
    """Read the currently selected model from the state file, if any."""
    try:
        if MODEL_STATE_PATH.exists():
            with open(MODEL_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            filename = state.get("filename", "")
            if filename in AVAILABLE_MODELS:
                return filename
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return DEFAULT_GGUF_MODEL


def save_selected_model(filename: str) -> None:
    """Persist the user-selected model. Caller must validate against AVAILABLE_MODELS."""
    if filename not in AVAILABLE_MODELS:
        raise ValueError("Unknown model filename")
    MODEL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"filename": filename}, f, indent=2)


GGUF_MODEL_PATH = MODELS_DIR / _load_selected_model()
CONTEXT_WINDOW = 8192
N_THREADS = 8       # match your physical core count (Ryzen 9850X3D = 8 cores)

# Legacy HuggingFace fallback (used if USE_GGUF = False)
GENERATION_MODEL = "HuggingFaceTB/SmolLM2-360M-Instruct"
USE_GGUF = True

MAX_NEW_TOKENS = 512
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

