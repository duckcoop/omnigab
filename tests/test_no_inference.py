"""The project must work with no inference library installed.

llama-cpp-python is an optional extra as of PR1a, so a stranger who runs
`pip install -e ".[dev]"` gets no llama_cpp at all. Everything that does
not load a model has to keep working for them, and the one thing that does
load a model has to fail with a sentence rather than a traceback.

These run under a simulated absence (see `no_llama_cpp` in conftest.py) so
they mean something on a developer machine where the library IS installed,
which is every machine this suite has run on so far. Nothing here asserts
that the library is present, because the whole point is that the suite
passes either way.
"""

from __future__ import annotations

import pytest

import generator
from config import DEFAULT_GGUF_MODEL
from core.model_manager import ModelManager


# Every module on a path that does not load a model. `generator` and
# `core.model_manager` are the two this PR changed; the other three are
# what AGENTS.md invariant I7 is really about, since the verification gate
# has no business needing a GPU inference library to import.
IMPORTABLE_WITHOUT_INFERENCE = [
    "config",
    "extraction",
    "core.tool_protocol",
    "generator",
    "core.model_manager",
]


@pytest.mark.parametrize("module_name", IMPORTABLE_WITHOUT_INFERENCE)
def test_imports_without_llama_cpp(no_llama_cpp, module_name):
    assert no_llama_cpp(module_name) is not None


def test_inference_available_reports_absence(no_llama_cpp):
    assert generator.inference_available() is False


def test_model_load_raises_the_actionable_message(no_llama_cpp):
    # The real constructor, because this is exactly what web_app.startup()
    # does. No GGUF file is needed to reach the raise, which is the point
    # of checking the library before the model file in ModelManager.load().
    #
    # The filename comes from the catalog rather than being written out
    # here: it has to be a real AVAILABLE_MODELS key or the unknown-model
    # guard fires first and this tests the wrong branch. Hardcoding one is
    # how this test broke when the catalog moved from Qwen2.5 to 3.5.
    with pytest.raises(generator.InferenceUnavailable) as caught:
        ModelManager(initial_model=DEFAULT_GGUF_MODEL)

    # Not an ImportError, and not a stack trace: a message naming the fix.
    assert not isinstance(caught.value, ImportError)
    message = str(caught.value)
    assert "Local inference is not installed" in message
    assert "setup.bat" in message
    assert "omnigab[inference]" in message


def test_message_names_the_wheel_index():
    # PyPI alone cannot satisfy the extra, so the message has to say where
    # the wheels actually come from or the second option is a dead end.
    assert "abetlen.github.io" in generator.INFERENCE_MISSING_MESSAGE
