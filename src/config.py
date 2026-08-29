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
THINKING_STATE_PATH = MODEL_STATE_PATH.parent / "thinking.json"

# Reasoning models (Qwen3.5 and anything else that emits <think>) default to
# thinking out loud on every turn. Measured on this catalog, "What is 2+2?"
# costs 1890 tokens and 37 seconds of it. That is most of MAX_NEW_TOKENS
# spent before the answer starts, on a question that needs none of it, and
# it eats the 8192 window the tool loop also has to live in.
#
# So the default is off, and it is a setting rather than a constant because
# the reasoning genuinely helps on hard questions and the cost is only
# absurd on easy ones.
THINKING_DEFAULT = False

# Bounds for the user-adjustable context window. The floor is what the
# agent needs to hold its system prompt plus a reply. The ceiling is the
# window the model was actually trained for, read out of the GGUF metadata
# rather than assumed: both Qwen3.5 quants report
# qwen35.context_length = 262144. Quality degrades past a model's trained
# window even when the hardware allows it, so that is the right ceiling.
#
# It was 32768, which was Qwen2.5's trained window and is an 8x
# underestimate here. The memory is not the constraint it looks like:
# measured KV cache on this catalog is about 16 MB per 1024 tokens, so the
# full 262144 costs roughly 4.1 GB and the 9B fits weights plus that inside
# 12 GB. Smaller cards cannot, which is what optimal_context() is for; this
# constant is only the ceiling on what a user may ask for.
CONTEXT_MIN = 2048
CONTEXT_MAX = 262144


def load_thinking_enabled() -> bool:
    """Whether the model should be allowed to emit a reasoning block."""
    try:
        if THINKING_STATE_PATH.exists():
            with open(THINKING_STATE_PATH, "r", encoding="utf-8") as f:
                value = json.load(f).get("enabled")
            if isinstance(value, bool):
                return value
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return THINKING_DEFAULT


def save_thinking_enabled(enabled: bool) -> None:
    """Persist the reasoning-block setting."""
    THINKING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(THINKING_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"enabled": bool(enabled)}, f, indent=2)


JOB_PROFILE_PATH = MODEL_STATE_PATH.parent / "job_profile.json"

# Which federal hiring paths the person using this app can actually apply
# under. USAJOBS gates most postings on these, and the answer is a fact
# about the user that no amount of reading their resume will produce: a
# resume does not say whether somebody is a veteran, a current federal
# employee, or still enrolled.
#
# It is a setting rather than a constant because the app is not written for
# one person. The default is the public path alone, which is what anyone
# has, so an untouched install hides nothing it should not.
JOB_PROFILE_DEFAULT = ["public"]


def load_job_profile() -> list[str]:
    """Hiring paths the user qualifies for. Always includes "public"."""
    paths: list[str] = []
    try:
        if JOB_PROFILE_PATH.exists():
            with open(JOB_PROFILE_PATH, "r", encoding="utf-8") as f:
                value = json.load(f).get("paths")
            if isinstance(value, list):
                paths = [str(p) for p in value if isinstance(p, str)]
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        paths = []
    if not paths:
        return list(JOB_PROFILE_DEFAULT)
    # "The public" is not a claim anybody can fail to make, and dropping it
    # would hide every ordinary vacancy from a user who only ticked
    # "veteran". Cheaper to guarantee it here than to trust the caller.
    if "public" not in paths:
        paths.append("public")
    return paths


def save_job_profile(paths: list[str]) -> None:
    """Persist the hiring paths the user qualifies for."""
    from jobs.eligibility import HIRING_PATHS

    unknown = [p for p in paths if p not in HIRING_PATHS]
    if unknown:
        raise ValueError(f"Unknown hiring path(s): {', '.join(sorted(unknown))}")
    JOB_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JOB_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump({"paths": sorted(set(paths) | {"public"})}, f, indent=2)


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

# Per-response generation ceiling. Short chats cost nothing: the model
# emits EOT naturally regardless of this cap.
#
# It has to fit in what is left of the context after the prompt, and there
# is not much. Measured on the 9B at CONTEXT_WINDOW = 8192, on a job-search
# turn with no history at all:
#
#   SYSTEM_PROMPT          3641 tokens
#   tool catalog, 15 tools 2382 tokens
#   assembled hop-2 prompt 6228 tokens
#   room left for a reply  1964 tokens
#
# The value here was 2048, which is 84 tokens more room than exists, and
# the comment above it claimed 1536 while the constant said otherwise. 1536
# is the number that was actually reasoned about, so the constant now says
# it. That leaves roughly 400 tokens of slack for conversation history,
# which is thin: see docs/TODOS.md, the prompt is the thing that has to
# shrink and PR4 owns it.
MAX_NEW_TOKENS = 1536
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
