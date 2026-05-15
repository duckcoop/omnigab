"""
RAG Agent Configuration
=======================
Central config for all pipeline components. Edit these values to swap models,
adjust chunk sizes, or tune retrieval parameters.
"""

import os
from pathlib import Path

# -- Paths --
PROJECT_ROOT = Path(__file__).parent
DOCS_DIR = PROJECT_ROOT.parent / "data" / "docs"
VECTORSTORE_DIR = PROJECT_ROOT.parent / "vectorstore"
INDEX_PATH = VECTORSTORE_DIR / "faiss_index"
METADATA_PATH = VECTORSTORE_DIR / "metadata.json"

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
    "qwen2.5-14b-instruct-q4_k_m.gguf": {
        "name": "Qwen 2.5 14B (Best Quality)",
        "size": "~8.9 GB",
        "ram": "~16 GB",
        "repo": "Qwen/Qwen2.5-14B-Instruct-GGUF",
    },
}
MODELS_DIR = PROJECT_ROOT.parent / "models"
GGUF_MODEL_PATH = MODELS_DIR / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
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
