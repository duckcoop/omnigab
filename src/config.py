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
# Primary: quantized GGUF for fast CPU inference
# Drop larger models into the models/ directory and update the path:
#   qwen2.5-3b-instruct-q4_k_m.gguf    (~2.1 GB, recommended)
#   qwen2.5-7b-instruct-q4_k_m.gguf    (~4.4 GB, best quality)
#   phi-4-mini-instruct-q4_k_m.gguf     (~2.3 GB, strong reasoning)
GGUF_MODEL_PATH = PROJECT_ROOT.parent / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
CONTEXT_WINDOW = 8192
N_THREADS = 8       # match your physical core count (Ryzen 9850X3D = 8 cores)

# Legacy HuggingFace fallback (used if USE_GGUF = False)
GENERATION_MODEL = "HuggingFaceTB/SmolLM2-360M-Instruct"
USE_GGUF = True

MAX_NEW_TOKENS = 512
TEMPERATURE = 0.3
TOP_P = 0.9

# -- Verification Layer --
FAITHFULNESS_THRESHOLD = 0.8
CLAIM_SUPPORT_THRESHOLD = 0.35    # lowered for more capable models that paraphrase accurately
MAX_CORRECTION_ROUNDS = 2
RETRY_TEMP_BOOST = 0.15
RETRY_TOPK_BOOST = 2

# -- System Prompt (used by legacy HF generator only) --
SYSTEM_PROMPT = """You are an IT documentation assistant. Answer questions using ONLY the context provided below. If the context does not contain enough information to answer the question, say so clearly. Do not make up information.

Context:
{context}

Question: {question}

Answer:"""
