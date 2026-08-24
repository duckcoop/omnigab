"""Which models a machine can run, decided from measured constants.

The Developer tab's benchmark button used to answer a different question
than the one people ask of it. It timed one generation on the model that
happened to be loaded, so it could say nothing about a model you had not
loaded and nothing about whether it would fit. Worse, it asked "what is
2+2", got a single token back, and reported the resulting tokens-per-second
as though it were throughput: 3.1 on one click and 4.1 on the next, for a
model that actually sustains about 56.

`model_capability` answers the real question, and does it as a pure
function of VRAM and RAM so it can be tested on a machine with neither.
"""

from __future__ import annotations

import pytest

from config import AVAILABLE_MODELS
from core.model_manager import (
    KV_CACHE_GB_PER_1K,
    MODEL_PROFILE,
    VRAM_RESERVE_GB,
    max_context_for,
    model_capability,
)


def test_every_catalog_model_is_reported():
    rows = model_capability(vram_gb=12, ram_gb=32)
    assert [r["filename"] for r in rows] == list(AVAILABLE_MODELS)


def test_a_12gb_card_runs_everything_on_gpu():
    # The card this catalog was measured on. If a change to the profiles or
    # the KV constant ever pushes the 9B off the GPU here, that is a real
    # regression rather than a rounding difference.
    rows = model_capability(vram_gb=12, ram_gb=32)
    assert all(r["verdict"] == "gpu" for r in rows)
    assert all(r["max_context"] >= 8192 for r in rows)


def test_no_gpu_falls_back_to_cpu_not_failure():
    # A machine with no CUDA still runs these models, just slowly. Reporting
    # "no" would tell a laptop user the app cannot work when it can.
    rows = model_capability(vram_gb=0, ram_gb=32)
    assert all(r["verdict"] == "cpu" for r in rows)
    assert all(r["max_context"] == 0 for r in rows)


def test_a_machine_too_small_says_so():
    rows = model_capability(vram_gb=0, ram_gb=2)
    assert all(r["verdict"] == "no" for r in rows)


@pytest.mark.parametrize(
    "vram_gb, expect_gpu",
    [(4, False), (6, True), (8, True), (12, True), (24, True)],
    ids=["4GB", "6GB", "8GB", "12GB", "24GB"],
)
def test_smallest_model_against_common_card_sizes(vram_gb, expect_gpu):
    smallest = min(MODEL_PROFILE.values(), key=lambda p: p["weight_gb"])
    ctx = max_context_for(smallest["weight_gb"], vram_gb)
    assert (ctx > 0) is expect_gpu


def test_context_shrinks_as_the_card_shrinks():
    weight = 6.2
    contexts = [max_context_for(weight, v) for v in (24, 16, 12, 10, 8)]
    # Monotonic: less VRAM can never buy more context.
    assert contexts == sorted(contexts, reverse=True)


def test_reserve_is_actually_held_back():
    # Exactly enough VRAM for the weights and nothing else must not report
    # a usable context. Getting this wrong is what silently pushes the KV
    # cache into system RAM, where throughput collapses.
    assert max_context_for(weight_gb=6.0, vram_gb=6.0) == 0
    assert max_context_for(weight_gb=6.0, vram_gb=6.0 + VRAM_RESERVE_GB) == 0


def test_context_matches_the_measured_kv_cost():
    # 4 GB of headroom at the measured 0.016 GB per 1024 tokens is 256000
    # tokens, which the ladder rounds down to 131072.
    weight, vram = 3.0, 3.0 + VRAM_RESERVE_GB + 4.0
    assert (4.0 / KV_CACHE_GB_PER_1K) * 1024 > 131072
    assert max_context_for(weight, vram) == 131072
