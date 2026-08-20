"""Reasoning is opt-in, and the prompt is what carries the switch.

Qwen3.5 reasons on every turn by default. Measured on the 9B, "What is
2+2?" costs 1 token with reasoning off and 2048 with it on, where 2048 is
MAX_NEW_TOKENS: the model is still thinking when the budget runs out and
never reaches an answer. So the default is off, and the mechanism is the
same one the model's own chat template uses, a pre-closed think block.
"""

from __future__ import annotations

import pytest

import config
import generator


@pytest.fixture
def thinking_state(tmp_path, monkeypatch):
    """Point the setting file at tmp_path so the real one is untouched."""
    monkeypatch.setattr(config, "THINKING_STATE_PATH", tmp_path / "thinking.json")
    return tmp_path / "thinking.json"


def test_default_is_off(thinking_state):
    # No file written yet: the default has to be the safe one, because a
    # fresh install has no setting and should not spend its whole token
    # budget reasoning about a greeting.
    assert config.load_thinking_enabled() is False


@pytest.mark.parametrize("enabled", [True, False], ids=["on", "off"])
def test_setting_round_trips(thinking_state, enabled):
    config.save_thinking_enabled(enabled)
    assert config.load_thinking_enabled() is enabled


def test_corrupt_setting_falls_back_to_default(thinking_state):
    thinking_state.write_text("{not json", encoding="utf-8")
    assert config.load_thinking_enabled() is False


def test_prompt_suppresses_reasoning_when_off(thinking_state, monkeypatch):
    monkeypatch.setattr(generator, "load_thinking_enabled", lambda: False)
    turn = generator._assistant_turn()
    assert turn.startswith("<|im_start|>assistant")
    # The pre-closed block is the whole mechanism: the model finds the
    # reasoning already finished and goes straight to the answer.
    assert turn.endswith(generator._NO_THINK_PREFILL)
    assert "<think>" in turn and "</think>" in turn


def test_prompt_leaves_reasoning_open_when_on(thinking_state, monkeypatch):
    monkeypatch.setattr(generator, "load_thinking_enabled", lambda: True)
    turn = generator._assistant_turn()
    assert turn == "<|im_start|>assistant\n"
    assert "</think>" not in turn


def test_format_messages_carries_the_switch(thinking_state, monkeypatch):
    messages = [{"role": "user", "content": "hi"}]
    monkeypatch.setattr(generator, "load_thinking_enabled", lambda: False)
    off = generator.Generator.format_messages(None, messages)
    monkeypatch.setattr(generator, "load_thinking_enabled", lambda: True)
    on = generator.Generator.format_messages(None, messages)
    assert off.endswith(generator._NO_THINK_PREFILL)
    assert not on.endswith(generator._NO_THINK_PREFILL)
    # Same conversation either way; only the trailing turn marker differs.
    assert off.startswith(on.rstrip("\n")[:20])
