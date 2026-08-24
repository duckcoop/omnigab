"""Adding a model from Hugging Face, and profiling whatever arrives.

The parsing and profiling here are pure functions on purpose: a user
pastes text and the app has to decide what it means and whether the result
will run, and neither question should need a network call or a GPU to
test.
"""

from __future__ import annotations

import pytest

from core import model_catalog as catalog


@pytest.mark.parametrize(
    "pasted",
    [
        "https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF",
        "https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/",
        "https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/tree/main",
        "https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/blob/main/x.gguf",
        "https://www.huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF",
        "http://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF?library=gguf",
        "bartowski/Qwen_Qwen3.5-4B-GGUF",
        "  bartowski/Qwen_Qwen3.5-4B-GGUF  ",
    ],
    ids=["plain url", "trailing slash", "tree", "blob", "www", "query",
         "bare id", "whitespace"],
)
def test_every_shape_a_user_might_paste(pasted):
    # The point of this feature is copying from the address bar, so each of
    # these is something a person will actually paste.
    assert catalog.parse_model_ref(pasted) == "bartowski/Qwen_Qwen3.5-4B-GGUF"


@pytest.mark.parametrize(
    "bad", ["", "   ", "not a url", "huggingface.co", "https://example.com/x/y/z/w"],
    ids=["empty", "spaces", "prose", "host only", "too many parts"],
)
def test_unusable_input_says_what_it_wanted(bad):
    with pytest.raises(ValueError) as caught:
        catalog.parse_model_ref(bad)
    # An error that does not show the expected shape leaves the user
    # guessing, which is the whole failure mode this feature invites.
    assert "org/repo" in str(caught.value) or "huggingface.co" in str(caught.value)


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("Qwen_Qwen3.5-4B-Q4_K_M.gguf", "model"),
        ("gemma-3-12b-it-Q4_K_M.gguf", "model"),
        ("mmproj-Qwen_Qwen3.5-4B-f16.gguf", "aux"),
        ("Qwen_Qwen3.5-4B-imatrix.gguf", "aux"),
        ("big-model-Q4_K_M-00001-of-00003.gguf", "split"),
        ("README.md", "aux"),
    ],
    ids=["quant", "other family", "vision projector", "imatrix", "split", "readme"],
)
def test_repo_files_are_classified(filename, expected):
    assert catalog.classify_gguf(filename) == expected


def test_kv_formula_matches_the_measurement():
    # Qwen3.5 reports 33 layers and a 256-wide KV dim. The VRAM slope on an
    # RTX 4070 SUPER measured 0.016 GB per 1024 tokens. The formula should
    # land close, and on the high side: overestimating cache cost makes the
    # "will it fit" answer conservative, and underestimating is what pushes
    # the cache into system RAM where throughput collapses.
    derived = catalog.kv_gb_per_1k(n_layers=33, kv_dim_total=256)
    assert 0.016 <= derived <= 0.016 * 1.25


def test_kv_scales_with_geometry():
    # Tolerance is for the 4-decimal rounding the function applies for
    # display, not slack in the scaling itself: a version that ignored
    # either dimension would be out by 100 percent, not 0.3.
    base = catalog.kv_gb_per_1k(32, 256)
    assert catalog.kv_gb_per_1k(64, 256) == pytest.approx(base * 2, rel=0.01)
    assert catalog.kv_gb_per_1k(32, 512) == pytest.approx(base * 2, rel=0.01)


def test_kv_is_zero_when_geometry_is_unknown():
    # A GGUF missing the keys must not produce a confident number.
    assert catalog.kv_gb_per_1k(0, 256) == 0.0
    assert catalog.kv_gb_per_1k(33, 0) == 0.0


def test_profile_reads_namespaced_metadata():
    # Keys are namespaced per architecture, so they are matched by suffix
    # rather than by a family lookup that would need editing for every new
    # model this is meant to support.
    metadata = {
        "general.architecture": "gemma4",
        "gemma4.block_count": 48,
        "gemma4.attention.key_length": 256,
        "gemma4.context_length": 131072,
    }
    profile = catalog.profile_from_metadata(metadata, size_bytes=8_000_000_000)
    assert profile["architecture"] == "gemma4"
    assert profile["n_layers"] == 48
    assert profile["trained_context"] == 131072
    assert profile["weight_gb"] == 8.0
    assert profile["kv_gb_per_1k"] > 0


def test_profile_survives_metadata_it_does_not_recognise():
    profile = catalog.profile_from_metadata({"general.architecture": "mystery"},
                                            size_bytes=1_000_000_000)
    assert profile["architecture"] == "mystery"
    assert profile["weight_gb"] == 1.0
    # Unknown geometry yields 0 rather than a fabricated cost.
    assert profile["kv_gb_per_1k"] == 0.0


def test_user_models_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "USER_MODELS_PATH", tmp_path / "user_models.json")
    assert catalog.load_user_models() == {}
    catalog.save_user_model("x.gguf", {"name": "X", "repo": "org/x"})
    assert catalog.load_user_models()["x.gguf"]["repo"] == "org/x"
    assert catalog.forget_user_model("x.gguf") is True
    assert catalog.forget_user_model("x.gguf") is False


def test_corrupt_user_models_file_does_not_break_startup(tmp_path, monkeypatch):
    path = tmp_path / "user_models.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(catalog, "USER_MODELS_PATH", path)
    assert catalog.load_user_models() == {}


def test_curated_models_win_a_name_collision(tmp_path, monkeypatch):
    from config import AVAILABLE_MODELS

    curated = next(iter(AVAILABLE_MODELS))
    monkeypatch.setattr(catalog, "USER_MODELS_PATH", tmp_path / "user_models.json")
    catalog.save_user_model(curated, {"name": "hijacked"})
    # A user entry must not shadow a known-good model of the same filename.
    assert catalog.all_models()[curated]["name"] != "hijacked"
