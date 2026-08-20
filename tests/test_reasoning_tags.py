"""Reasoning models emit <think>; this app renders <thinking>.

Qwen3.x thinks out loud in `<think>` tags on every turn. The desktop
renderer only knows the app's own `<thinking>` spelling, and the web UI
knows neither, so without a rewrite the model's internal monologue lands
in the chat window as ordinary text with visible tags around it.

The second test here is the important one. The streaming path applies this
rewrite to a partial buffer and yields only the newly-appeared tail, so the
rewrite has to be prefix-preserving or the UI receives garbled text as a
tag completes. That property is why this is a rename rather than a strip.
"""

from __future__ import annotations

import pytest

from core.agent import normalize_reasoning_tags


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<think>", "<thinking>"),
        ("</think>", "</thinking>"),
        ("<think>weighing it up</think>done",
         "<thinking>weighing it up</thinking>done"),
        # Already in the app's spelling: must not become <thinkinging>.
        ("<thinking>already right</thinking>",
         "<thinking>already right</thinking>"),
        # Mixed, because a turn can contain both the model's native block
        # and the one the system prompt asks for.
        ("<think>a</think><thinking>b</thinking>",
         "<thinking>a</thinking><thinking>b</thinking>"),
        # Nothing to do.
        ("plain answer", "plain answer"),
        ("", ""),
        # Arithmetic that merely looks like a tag stays untouched.
        ("if a<b then think>0", "if a<b then think>0"),
    ],
    ids=["open", "close", "full block", "idempotent on <thinking>",
         "mixed spellings", "no tags", "empty", "not a tag"],
)
def test_rewrites_native_think_tags(raw: str, expected: str) -> None:
    assert normalize_reasoning_tags(raw) == expected


@pytest.mark.parametrize(
    "stream",
    [
        "<think>reasoning here</think>The answer is 42.",
        "prose first <think>then a thought</think> then more prose",
        "<thinking>app spelling</thinking> unchanged",
    ],
    ids=["leading block", "mid-text block", "app spelling"],
)
def test_rewrite_is_prefix_preserving(stream: str) -> None:
    """Every partial rewrite must be a prefix of the final rewrite.

    This is exactly what `Agent.run_stream` relies on: it recomputes the
    normalized buffer on every token and yields `visible[yielded_up_to:]`.
    If a later token could change characters the UI already received, that
    slice would be wrong and the user would see mangled output.
    """
    final = normalize_reasoning_tags(stream)
    for cut in range(len(stream) + 1):
        partial = normalize_reasoning_tags(stream[:cut])
        assert final.startswith(partial), (
            f"prefix broken at {cut}: {partial!r} is not a prefix of {final!r}")


def test_streamed_deltas_reassemble_correctly() -> None:
    """Replay the streaming loop's accounting one character at a time."""
    stream = "<think>short</think>Answer."
    buffer, yielded_up_to, received = "", 0, []
    for char in stream:
        buffer += char
        visible = normalize_reasoning_tags(buffer)
        if len(visible) > yielded_up_to:
            received.append(visible[yielded_up_to:])
            yielded_up_to = len(visible)
    assert "".join(received) == normalize_reasoning_tags(stream)
