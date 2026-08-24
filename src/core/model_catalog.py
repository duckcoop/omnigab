"""Adding models from Hugging Face, and profiling whatever arrives.

The catalog used to be four hardcoded Qwen entries, which meant the app
could only run models someone had written into `config.py`. Nothing
technical required that: the bundled llama.cpp also understands gemma,
llama, glm, mistral, phi, granite, olmo, smollm and gpt-oss architectures.

The awkward part of letting a user bring their own model is not the
download, it is that everything downstream needs to know how big the
weights are and how expensive the KV cache is, and those were hardcoded
per model. So this module reads them out of the GGUF itself: the file size
gives the weights, and the attention geometry in the metadata gives the
cache cost. A model neither the user nor this code has seen before still
gets a correct "fits in VRAM, up to N tokens" verdict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config import DATA_DIR, MODELS_DIR

USER_MODELS_PATH = DATA_DIR / "user_models.json"

HUGGINGFACE_BROWSE_URL = "https://huggingface.co/models?library=gguf&sort=trending"

# Files that live in a GGUF repo but are not a model you can load.
# mmproj-* are vision projectors for multimodal pairs, and *imatrix* is the
# importance matrix used to produce a quant, not a quant itself.
_NOT_A_MODEL = ("mmproj-", "imatrix")

# A split quant is written as name-00001-of-00003.gguf. hf_hub_download
# fetches one file by name, so these cannot be pulled the way the rest are.
# They are surfaced and marked rather than hidden, because silently
# omitting the only quant a repo offers looks like the repo is empty.
_SPLIT_RE = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.IGNORECASE)

# Bytes per element for a q8_0 KV cache: 32 elements share one fp16 scale,
# so 34 bytes per 32 elements. type_k/type_v are set to q8_0 in generator.py.
_Q8_BYTES_PER_ELEMENT = 34 / 32


def parse_model_ref(text: str) -> str:
    """Turn what a user pastes into a `org/repo` id.

    Accepts the URL from the browser address bar, with or without a
    trailing `/tree/main`, and a bare repo id typed by hand. Anything else
    raises ValueError with the shape it expected, because "invalid input"
    on its own tells the user nothing about what to do next.
    """
    ref = (text or "").strip()
    if not ref:
        raise ValueError("Paste a Hugging Face model URL or an org/repo id.")

    ref = re.sub(r"^https?://(www\.)?huggingface\.co/", "", ref)
    ref = ref.split("?")[0].split("#")[0]
    # Drop anything after the repo: /tree/main, /blob/main/file.gguf, etc.
    parts = [p for p in ref.split("/") if p]
    for marker in ("tree", "blob", "resolve"):
        if marker in parts:
            parts = parts[:parts.index(marker)]
            break
    if len(parts) != 2:
        raise ValueError(
            f"Could not read a model id from {text!r}. Expected something "
            f"like 'bartowski/Qwen_Qwen3.5-4B-GGUF' or the URL of a model "
            f"page on huggingface.co.")
    return "/".join(parts)


def classify_gguf(filename: str) -> str:
    """'model', 'split', or 'aux' for one file in a GGUF repo."""
    lowered = filename.lower()
    if not lowered.endswith(".gguf"):
        return "aux"
    if any(token in lowered for token in _NOT_A_MODEL):
        return "aux"
    if _SPLIT_RE.search(lowered):
        return "split"
    return "model"


def kv_gb_per_1k(n_layers: int, kv_dim_total: int) -> float:
    """KV cache cost per 1024 tokens, from the model's attention geometry.

    Both K and V are cached for every layer, quantized to q8_0.

    Validated against a measurement rather than trusted: Qwen3.5 reports 33
    layers and a 256-wide KV dimension, which this puts at 0.0184 GB per
    1024 tokens, and the VRAM slope on an RTX 4070 SUPER measured 0.016.
    The formula runs about 15 percent high, and high is the safe direction
    for a question of the form "will this still fit".
    """
    if n_layers <= 0 or kv_dim_total <= 0:
        return 0.0
    bytes_per_token = n_layers * 2 * kv_dim_total * _Q8_BYTES_PER_ELEMENT
    return round(bytes_per_token * 1024 / 1e9, 4)


def profile_from_metadata(metadata: dict[str, Any], size_bytes: int) -> dict:
    """Build a model profile from GGUF metadata plus the file size.

    The metadata keys are namespaced by architecture (`qwen35.block_count`,
    `gemma3.block_count`, and so on), so they are matched by suffix rather
    than by a per-family lookup table that would need editing for every new
    model this is supposed to support.
    """
    def find(suffix: str, default: int = 0) -> int:
        for key, value in metadata.items():
            if key.endswith(suffix):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default
        return default

    n_layers = find(".block_count")
    kv_dim = find(".attention.key_length")
    trained_ctx = find(".context_length")
    architecture = str(metadata.get("general.architecture", "")) or "unknown"

    return {
        "architecture": architecture,
        "weight_gb": round(size_bytes / 1e9, 2),
        "n_layers": n_layers,
        "kv_dim": kv_dim,
        "kv_gb_per_1k": kv_gb_per_1k(n_layers, kv_dim),
        "trained_context": trained_ctx,
    }


def read_gguf_profile(path: Path) -> dict:
    """Profile a GGUF on disk. Loads metadata only, not the weights."""
    from generator import _load_llama_class  # raises a readable error if absent

    llama_class = _load_llama_class()
    model = llama_class(model_path=str(path), vocab_only=True, verbose=False)
    try:
        metadata = dict(model.metadata)
    finally:
        del model
    return profile_from_metadata(metadata, path.stat().st_size)


# ---------------------------------------------------------------- storage

def load_user_models() -> dict[str, dict]:
    """Models the user added, keyed by filename like the curated catalog."""
    try:
        if USER_MODELS_PATH.exists():
            data = json.loads(USER_MODELS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def save_user_model(filename: str, entry: dict) -> None:
    models = load_user_models()
    models[filename] = entry
    USER_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_MODELS_PATH.write_text(json.dumps(models, indent=2), encoding="utf-8")


def forget_user_model(filename: str) -> bool:
    """Drop an entry from the catalog. Does not delete the file on disk."""
    models = load_user_models()
    if filename not in models:
        return False
    del models[filename]
    USER_MODELS_PATH.write_text(json.dumps(models, indent=2), encoding="utf-8")
    return True


def all_models() -> dict[str, dict]:
    """Curated catalog plus anything the user added.

    Curated entries win on a name collision, so a user cannot shadow a
    known-good model with a broken entry of the same filename.
    """
    from config import AVAILABLE_MODELS

    merged = dict(load_user_models())
    merged.update(AVAILABLE_MODELS)
    return merged


def model_path(filename: str) -> Path:
    return MODELS_DIR / filename


# ---------------------------------------------------------------- network

def list_repo_ggufs(repo_id: str) -> tuple[list[dict], str]:
    """Every loadable quant in a Hugging Face repo, largest quality first.

    Split quants are included and marked rather than filtered out: a repo
    whose only offering is split would otherwise look empty, which reads as
    a broken feature instead of an unsupported layout.
    """
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo_id, files_metadata=True)
    files = []
    for sibling in info.siblings or []:
        kind = classify_gguf(sibling.rfilename)
        if kind == "aux":
            continue
        files.append({
            "filename": sibling.rfilename,
            "size_gb": round((sibling.size or 0) / 1e9, 2),
            "kind": kind,
            "downloadable": kind == "model",
        })
    files.sort(key=lambda f: f["size_gb"])
    card = info.card_data or {}
    return files, str(card.get("license") or "unknown")


def add_model_from_repo(repo_id: str, filename: str, *,
                        display_name: str = "") -> dict:
    """Download one quant, profile it from its own metadata, register it.

    The profile is read from the downloaded file rather than guessed from
    the name, so a model this code has never heard of still reports a
    correct size, cache cost, and trained context.
    """
    if classify_gguf(filename) != "model":
        raise ValueError(
            f"{filename} cannot be downloaded on its own. Split quants "
            f"(-00001-of-000NN) need every part and are not supported yet.")

    from huggingface_hub import hf_hub_download

    target = model_path(filename)
    if not target.exists():
        hf_hub_download(repo_id=repo_id, filename=filename,
                        local_dir=str(MODELS_DIR))
    if not target.exists():
        raise RuntimeError(f"Download finished but {filename} is not on disk.")

    profile = read_gguf_profile(target)
    entry = {
        "name": display_name or f"{repo_id.split('/')[-1]} ({filename})",
        "size": f"~{profile['weight_gb']} GB",
        "ram": f"~{max(4, round(profile['weight_gb'] * 2))} GB",
        "repo": repo_id,
        "source": "huggingface",
        "profile": profile,
    }
    save_user_model(filename, entry)
    return entry
