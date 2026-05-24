"""Generation Module (llama-cpp backend).

Wraps llama-cpp-python so the rest of the project does not depend on
its API directly. Exposes:

  * `generate(question, context, ...)` — legacy single-shot used by
    skills and the verifier.
  * `generate_raw(prompt)` — used by the new Agent loop; takes a
    pre-formatted prompt string.
  * `format_messages(messages)` — turns OpenAI-style chat dicts into
    the model's prompt format (ChatML for Qwen).
  * `stream(question, context, ...)` — legacy sync token generator.
  * `stream_async(prompt)` — async iterator the FastAPI streaming
    endpoint pulls from without blocking the event loop.

When llama-cpp-python was compiled with CUDA support, passing
`n_gpu_layers=-1` offloads every layer that fits in VRAM. With a CPU
wheel the parameter is silently ignored, so it is safe to leave on.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path
from typing import AsyncIterator

from llama_cpp import Llama

from config import (
    GENERATION_MODEL, GGUF_MODEL_PATH, MAX_NEW_TOKENS,
    TEMPERATURE, TOP_P, CONTEXT_WINDOW, N_THREADS,
)
from security import (
    DOC_START,
    DOC_END,
    INJECTION_DEFENSE_INSTRUCTION,
    strip_chat_tokens,
)


_STOP_TOKENS = ["<|im_end|>", "<|im_start|>", "<|endoftext|>"]


class Generator:
    """GGUF-based text generator using llama-cpp-python."""

    def __init__(
        self,
        model_path: str | None = None,
        n_gpu_layers: int = 999,
        n_ctx: int = CONTEXT_WINDOW,
        n_threads: int = N_THREADS,
        n_batch: int = 512,
    ):
        path = model_path or str(GGUF_MODEL_PATH)
        gpu_msg = "(GPU offload)" if n_gpu_layers != 0 else "(CPU only)"
        print(f"Loading GGUF model: {Path(path).name} {gpu_msg}")
        print(f"Context: {n_ctx} | Batch: {n_batch} | Threads: {n_threads} | GPU layers: {n_gpu_layers}")

        self.llm = Llama(
            model_path=path,
            n_ctx=n_ctx,
            n_batch=n_batch,
            n_threads=n_threads,
            n_threads_batch=n_threads,
            n_gpu_layers=n_gpu_layers,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
        )

        size_gb = Path(path).stat().st_size / 1e9
        print(f"Model loaded: {Path(path).name}")
        print(f"File size: {size_gb:.2f} GB | Vocab: {self.llm.n_vocab()}")

        self.model_path = path
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.n_batch = n_batch
        self.last_tps = 0.0
        self.last_token_count = 0

    # ---------------------------------------------------------- legacy
    # The verifier, skills, and RAGAgent fallback still call these.

    def _build_system_msg(self, user_context: str = "") -> str:
        msg = (
            "You are a helpful assistant. Answer using ONLY facts from the context. "
            "Be natural and conversational. Match your answer length to the question: "
            "simple questions get 1-2 sentence answers, complex questions get longer ones. "
            "State specific numbers, temperatures, times, and facts directly. "
            "Never say 'refer to', 'visit', 'described as having', or 'is provided by'. "
            "Never repeat the question. Never mention the source or context. "
            "Just answer like a person would.\n\n"
            + INJECTION_DEFENSE_INSTRUCTION
        )
        if user_context:
            msg += "\n\n" + user_context
        return msg

    def _clean_context(self, context: str) -> str:
        context = strip_chat_tokens(context)
        context = re.sub(r"#{1,6}\s+", "", context)
        context = re.sub(r"\n{3,}", "\n\n", context)
        max_context_chars = 2400
        if len(context) > max_context_chars:
            context = context[:max_context_chars].rsplit("\n", 1)[0]
        return context

    def _wrap_context(self, context: str) -> str:
        if DOC_START in context:
            return context
        return f"{DOC_START}\n{context}\n{DOC_END}"

    def _build_prompt(self, question: str, context: str, user_context: str = "",
                      history: str = "") -> str:
        context = self._clean_context(context)
        context = self._wrap_context(context)
        system_msg = self._build_system_msg(user_context)
        user_msg = ""
        if history:
            user_msg += "Recent conversation:\n" + history + "\n\n"
        user_msg += "Context:\n" + context + "\n\nQuestion: " + question
        return (
            "<|im_start|>system\n" + system_msg + "<|im_end|>\n"
            "<|im_start|>user\n" + user_msg + "<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

    def generate(self, question: str, context: str, temperature_override=None,
                 user_context: str = "", history: str = "") -> str:
        prompt = self._build_prompt(question, context, user_context, history)
        temp = temperature_override if temperature_override is not None else TEMPERATURE
        return self.generate_raw(prompt, temperature=temp)

    def stream(self, question: str, context: str, user_context: str = "",
               history: str = ""):
        """Sync token generator (used by legacy callers)."""
        prompt = self._build_prompt(question, context, user_context, history)
        t0 = time.time()
        token_count = 0
        for output in self.llm(
            prompt,
            max_tokens=MAX_NEW_TOKENS,
            temperature=max(TEMPERATURE, 0.01),
            top_p=TOP_P,
            repeat_penalty=1.15,
            stop=_STOP_TOKENS,
            echo=False,
            stream=True,
        ):
            chunk = output["choices"][0]["text"]
            token_count += 1
            yield chunk

        elapsed = time.time() - t0
        self.last_token_count = token_count
        self.last_tps = token_count / elapsed if elapsed > 0 else 0.0

    # ---------------------------------------------------------- new API

    def format_messages(self, messages: list[dict]) -> str:
        """Render OpenAI-style messages as a ChatML prompt."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                # ChatML doesn't have a native tool role; surface it as a user
                # observation so the model can read it. Name it for clarity.
                tool_name = msg.get("name", "tool")
                content = f"[tool:{tool_name}]\n{content}"
                role = "user"
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    def generate_raw(self, prompt: str, temperature: float | None = None,
                     max_tokens: int = MAX_NEW_TOKENS) -> str:
        """Run a single completion against a pre-built prompt."""
        temp = max(temperature if temperature is not None else TEMPERATURE, 0.01)
        t0 = time.time()
        output = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temp,
            top_p=TOP_P,
            repeat_penalty=1.15,
            stop=_STOP_TOKENS,
            echo=False,
        )
        elapsed = time.time() - t0
        text = output["choices"][0]["text"].strip()
        completion_tokens = output["usage"]["completion_tokens"]
        self.last_token_count = completion_tokens
        self.last_tps = completion_tokens / elapsed if elapsed > 0 else 0.0
        return text

    async def stream_async(self, prompt: str, temperature: float | None = None,
                           max_tokens: int = MAX_NEW_TOKENS) -> AsyncIterator[str]:
        """Bridge llama-cpp's blocking stream into an async iterator.

        Runs the producer in a background thread so the FastAPI event
        loop stays free to handle other requests (including a model
        switch coming in on a parallel connection).
        """
        loop = asyncio.get_running_loop()
        # Bounded queue gives backpressure: if the SSE consumer falls behind,
        # the producer thread will skip put_nowait failures rather than balloon
        # memory. 64 tokens is roughly 0.3 s of generation at 200 tok/s.
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        SENTINEL: object = object()
        temp = max(temperature if temperature is not None else TEMPERATURE, 0.01)
        t0 = time.time()
        token_count_box = [0]

        def _safe_put(item):
            """Schedule a queue put on the loop, dropping items if backpressure trips."""
            def _put():
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    # Drop the oldest token to keep the stream live; the next
                    # tokens carry the meaning forward.
                    try:
                        queue.get_nowait()
                        queue.put_nowait(item)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass
            loop.call_soon_threadsafe(_put)

        def _produce():
            try:
                for output in self.llm(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temp,
                    top_p=TOP_P,
                    repeat_penalty=1.15,
                    stop=_STOP_TOKENS,
                    echo=False,
                    stream=True,
                ):
                    chunk = output["choices"][0]["text"]
                    token_count_box[0] += 1
                    _safe_put(chunk)
            except Exception as exc:
                _safe_put({"__error__": str(exc)})
            finally:
                _safe_put(SENTINEL)

        threading.Thread(target=_produce, daemon=True).start()

        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    return
                if isinstance(item, dict) and "__error__" in item:
                    raise RuntimeError(item["__error__"])
                yield item
        finally:
            elapsed = time.time() - t0
            self.last_token_count = token_count_box[0]
            self.last_tps = (token_count_box[0] / elapsed) if elapsed > 0 else 0.0

    def get_last_stats(self) -> dict:
        return {
            "tokens": self.last_token_count,
            "tps": round(self.last_tps, 1),
        }


class GeneratorHF:
    """HuggingFace Transformers fallback generator (unchanged)."""

    def __init__(self, model_name=GENERATION_MODEL):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print("Loading HF model: " + model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            dtype=torch.float32,
            device_map="cpu",
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )
        self.model.eval()
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.last_tps = 0.0
        self.last_token_count = 0

    def generate(self, question, context, temperature_override=None,
                 user_context="", history=""):
        import torch
        context = strip_chat_tokens(context)
        context = re.sub(r"#{1,6}\s+", "", context)
        context = re.sub(r"\n{3,}", "\n\n", context)
        max_context_chars = 800
        if len(context) > max_context_chars:
            context = context[:max_context_chars].rsplit("\n", 1)[0]
        if DOC_START not in context:
            context = f"{DOC_START}\n{context}\n{DOC_END}"
        system_msg = (
            "You are a helpful assistant. Answer using ONLY facts from the context. "
            "Be natural and concise. Match answer length to the question. State specific "
            "numbers and facts directly. Never mention the source. Just answer like a person would.\n\n"
            + INJECTION_DEFENSE_INSTRUCTION
        )
        if user_context:
            system_msg += "\n\n" + user_context
        user_msg = ""
        if history:
            user_msg += "Recent conversation:\n" + history + "\n\n"
        user_msg += "Context:\n" + context + "\n\nQuestion: " + question
        messages = [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]
        try:
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            prompt = system_msg + "\n\n" + user_msg + "\n\nAnswer:"
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
        temp = temperature_override if temperature_override is not None else TEMPERATURE
        t0 = time.time()
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                temperature=max(temp, 0.01),
                top_p=TOP_P,
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id,
                repetition_penalty=1.15,
            )
        elapsed = time.time() - t0
        new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        self.last_token_count = len(new_tokens)
        self.last_tps = self.last_token_count / elapsed if elapsed > 0 else 0.0
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    def get_last_stats(self):
        return {"tokens": self.last_token_count, "tps": round(self.last_tps, 1)}


if __name__ == "__main__":
    print("=== Generator Test (GGUF) ===\n")
    gen = Generator()

    test_context = """To reset a user password in Active Directory:
1. Open Active Directory Users and Computers (ADUC)
2. Navigate to the user's OU
3. Right-click the user account and select Reset Password
4. Enter the new password twice
5. Check User must change password at next logon if required"""

    test_question = "How do I reset a password in Active Directory?"
    print("Question: " + test_question + "\n")
    answer = gen.generate(test_question, test_context)
    stats = gen.get_last_stats()
    print("Answer: " + answer)
    print(f"\nPerformance: {stats['tokens']} tokens at {stats['tps']} tok/sec")
