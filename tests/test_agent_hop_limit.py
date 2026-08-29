"""What the agent says when it runs out of tool hops.

`MAX_TOOL_HOPS` caps a turn at four tool calls, which is right: a model
that loops forever has to be stopped. What was wrong is what happened
next. The loop fell out of `for ... else` with no further generation, so
the model never got a turn in which to say what it had found.

In the synchronous path that left the turn holding whatever the model
said just before its last tool call, which is characteristically a
sentence announcing the call ("Let me try a broader keyword to see what's
available:"). In the streaming path it was worse: the branch emitted
"[stopped: tool hop limit reached]" and nothing else, so four successful
searches could end a turn with no answer a user could read.

Everything here runs against a scripted fake generator, so no GGUF file
and no GPU are needed and the tests hold under invariant I7.
"""

from __future__ import annotations

import asyncio

import pytest

from core.agent import FINAL_ANSWER_NUDGE, MAX_TOOL_HOPS, Agent

CLOSING_ANSWER = "I ran four searches and found nothing usable. Here is why."


class FakeGenerator:
    """Emits a tool call every turn until the closing prompt arrives.

    Recognising the closing pass by the nudge text is the point: it proves
    the agent actually asked for a summary rather than reusing an earlier
    generation.
    """

    def __init__(self, closing_answer: str = CLOSING_ANSWER) -> None:
        self.closing_answer = closing_answer
        self.prompts: list[str] = []

    def format_messages(self, messages: list[dict]) -> str:
        return "\n".join(f"{m['role']}: {m['content']}" for m in messages)

    def _reply(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if FINAL_ANSWER_NUDGE in prompt:
            return self.closing_answer
        return '<tool_call>{"name":"echo","arguments":{"text":"hi"}}</tool_call>'

    def generate_raw(self, prompt: str, *args, **kwargs) -> str:
        return self._reply(prompt)

    async def stream_async(self, prompt: str):
        for chunk in self._reply(prompt).split(" "):
            yield chunk + " "

    def get_last_stats(self) -> dict:
        return {"tokens": 7, "tps": 1.0}


class RaisingGenerator(FakeGenerator):
    """Fails the closing pass, to prove the turn survives it."""

    def generate_raw(self, prompt: str, *args, **kwargs) -> str:
        if FINAL_ANSWER_NUDGE in prompt:
            raise RuntimeError("model died during the closing pass")
        return super().generate_raw(prompt)

    async def stream_async(self, prompt: str):
        if FINAL_ANSWER_NUDGE in prompt:
            raise RuntimeError("model died during the closing pass")
        async for chunk in super().stream_async(prompt):
            yield chunk


class FakeModelManager:
    def __init__(self, generator) -> None:
        self.generator = generator
        self.current_model_name = "fake-model.gguf"


class EchoTool:
    name = "echo"
    description = "Echo the text back."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    def __init__(self) -> None:
        self.calls = 0

    def run(self, arguments: dict) -> dict:
        self.calls += 1
        return {"ok": True, "echoed": arguments.get("text", "")}


@pytest.fixture
def agent_parts():
    gen = FakeGenerator()
    tool = EchoTool()
    agent = Agent(FakeModelManager(gen), {tool.name: tool}, memory=None)
    return agent, gen, tool


def _drain(agent, message):
    async def go():
        return [event async for event in agent.stream(message)]
    return asyncio.run(go())


# ----------------------------------------------------------- the defect

def test_synchronous_turn_answers_instead_of_reporting_the_stop(agent_parts):
    agent, _gen, tool = agent_parts
    turn = agent.run("find me some jobs")

    assert tool.calls == MAX_TOOL_HOPS
    assert len(turn.tool_calls) == MAX_TOOL_HOPS
    assert turn.answer == CLOSING_ANSWER
    assert "hop limit" not in turn.answer


def test_streaming_turn_emits_an_answer_not_just_the_stop_notice(agent_parts):
    agent, _gen, tool = agent_parts
    events = _drain(agent, "find me some jobs")

    assert tool.calls == MAX_TOOL_HOPS
    assert sum(1 for e in events if e["type"] == "tool_start") == MAX_TOOL_HOPS
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert CLOSING_ANSWER.split(".")[0] in streamed
    assert "hop limit" not in streamed


def test_the_closing_pass_can_see_every_tool_result(agent_parts):
    """The summary is only worth asking for if the observations are there."""
    agent, gen, _tool = agent_parts
    agent.run("find me some jobs")

    closing = [p for p in gen.prompts if FINAL_ANSWER_NUDGE in p]
    assert len(closing) == 1, "exactly one closing pass per exhausted turn"
    # Four dispatches of the echo tool, all visible to the closing prompt.
    assert closing[0].count('"echoed"') == MAX_TOOL_HOPS


def test_history_records_the_answer_rather_than_an_empty_turn(agent_parts):
    agent, _gen, _tool = agent_parts
    _drain(agent, "find me some jobs")

    assert agent.history[-1] == {"role": "assistant", "content": CLOSING_ANSWER}
    assert agent.history[-1]["content"] != "(no answer)"


# ------------------------------------------------------- degraded paths

def test_a_blank_closing_answer_falls_back_to_the_stop_notice():
    """An empty summary must not produce an empty turn.

    The old message is still the right thing to say when there is genuinely
    nothing else; it just should not be the only thing that can happen.
    """
    gen = FakeGenerator(closing_answer="   ")
    tool = EchoTool()
    agent = Agent(FakeModelManager(gen), {tool.name: tool}, memory=None)

    assert "hop limit" in agent.run("find me some jobs").answer
    streamed = "".join(e["text"] for e in _drain(agent, "again")
                       if e["type"] == "token")
    assert "hop limit" in streamed


def test_a_failing_closing_pass_does_not_lose_the_turn():
    """A model that dies on the extra generation must not raise out.

    The caller reached this branch by running normally, so an exception
    here would turn a degraded answer into a crashed request.
    """
    gen = RaisingGenerator()
    tool = EchoTool()
    agent = Agent(FakeModelManager(gen), {tool.name: tool}, memory=None)

    turn = agent.run("find me some jobs")
    assert turn.answer
    assert tool.calls == MAX_TOOL_HOPS

    events = _drain(agent, "find me some jobs")
    assert "".join(e["text"] for e in events if e["type"] == "token")


def test_a_turn_that_answers_early_never_reaches_the_closing_pass():
    """One tool call then an answer is the normal path and must be untouched."""
    class AnswersAfterOneCall(FakeGenerator):
        def _reply(self, prompt: str) -> str:
            self.prompts.append(prompt)
            if '"echoed"' in prompt:
                return "Found it."
            return '<tool_call>{"name":"echo","arguments":{"text":"hi"}}</tool_call>'

    gen = AnswersAfterOneCall()
    tool = EchoTool()
    agent = Agent(FakeModelManager(gen), {tool.name: tool}, memory=None)

    turn = agent.run("find me some jobs")
    assert turn.answer == "Found it."
    assert tool.calls == 1
    assert not [p for p in gen.prompts if FINAL_ANSWER_NUDGE in p]


def test_a_partial_tool_call_tag_is_never_streamed_to_the_user():
    """The closing stream holds its tail back so a half tag cannot leak.

    The model is told not to call a tool, and mostly obeys, but "<tool_" is
    a plausible token sequence and showing it to a user is a glitch.
    """
    class EmitsATrailingTag(FakeGenerator):
        async def stream_async(self, prompt: str):
            if FINAL_ANSWER_NUDGE in prompt:
                self.prompts.append(prompt)
                for chunk in ("Nothing found. ", "<tool_call>",
                              '{"name":"echo","arguments":{}}'):
                    yield chunk
            else:
                async for chunk in super().stream_async(prompt):
                    yield chunk

    gen = EmitsATrailingTag()
    tool = EchoTool()
    agent = Agent(FakeModelManager(gen), {tool.name: tool}, memory=None)

    streamed = "".join(e["text"] for e in _drain(agent, "find me some jobs")
                       if e["type"] == "token")
    assert "Nothing found." in streamed
    assert "<tool" not in streamed
    assert "echo" not in streamed.replace("tool_start", "")
