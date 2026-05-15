"""
Generation Module (llama-cpp backend)
=====================================
Uses llama-cpp-python for high-performance CPU inference on quantized
GGUF models. Supports AVX-512 on Zen 5 architecture. Provides
token-per-second metrics for benchmarking.
"""

import re
import time
from pathlib import Path

from llama_cpp import Llama

from config import (
    GENERATION_MODEL, GGUF_MODEL_PATH, MAX_NEW_TOKENS,
    TEMPERATURE, TOP_P, CONTEXT_WINDOW, N_THREADS,
)


class Generator:
    """GGUF-based text generator using llama-cpp-python."""

    def __init__(self, model_path=None):
        path = model_path or str(GGUF_MODEL_PATH)
        print("Loading GGUF model: " + Path(path).name)
        print("Context window: {} tokens | Threads: {}".format(CONTEXT_WINDOW, N_THREADS))

        self.llm = Llama(
            model_path=path,
            n_ctx=CONTEXT_WINDOW,
            n_threads=N_THREADS,
            n_threads_batch=N_THREADS,
            verbose=False,
        )

        print("Model loaded: " + Path(path).name)
        size_gb = Path(path).stat().st_size / 1e9
        print("File size: {:.2f} GB | Vocab: {}".format(size_gb, self.llm.n_vocab()))

        self.last_tps = 0.0
        self.last_token_count = 0

    def _build_system_msg(self, user_context=""):
        msg = (
            "You are a helpful assistant. Answer using ONLY facts from the context. "
            "Be natural and conversational. Match your answer length to the question: "
            "simple questions get 1-2 sentence answers, complex questions get longer ones. "
            "State specific numbers, temperatures, times, and facts directly. "
            "Never say 'refer to', 'visit', 'described as having', or 'is provided by'. "
            "Never repeat the question. Never mention the source or context. "
            "Just answer like a person would."
        )
        if user_context:
            msg += "\n\n" + user_context
        return msg

    def _clean_context(self, context):
        context = re.sub(r"#{1,6}\s+", "", context)
        context = re.sub(r"\n{3,}", "\n\n", context)
        max_context_chars = 2400
        if len(context) > max_context_chars:
            context = context[:max_context_chars].rsplit("\n", 1)[0]
        return context

    def _build_prompt(self, question, context, user_context="", history=""):
        context = self._clean_context(context)
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

    def generate(self, question, context, temperature_override=None,
                 user_context="", history=""):
        prompt = self._build_prompt(question, context, user_context, history)
        temp = temperature_override if temperature_override is not None else TEMPERATURE
        t0 = time.time()

        output = self.llm(
            prompt,
            max_tokens=MAX_NEW_TOKENS,
            temperature=max(temp, 0.01),
            top_p=TOP_P,
            repeat_penalty=1.15,
            stop=["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
            echo=False,
        )

        elapsed = time.time() - t0
        response = output["choices"][0]["text"].strip()
        token_count = output["usage"]["completion_tokens"]
        self.last_token_count = token_count
        self.last_tps = token_count / elapsed if elapsed > 0 else 0.0
        return response

    def stream(self, question, context, user_context="", history=""):
        """Stream tokens one at a time. Yields text chunks."""
        prompt = self._build_prompt(question, context, user_context, history)
        t0 = time.time()
        token_count = 0

        for output in self.llm(
            prompt,
            max_tokens=MAX_NEW_TOKENS,
            temperature=max(TEMPERATURE, 0.01),
            top_p=TOP_P,
            repeat_penalty=1.15,
            stop=["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
            echo=False,
            stream=True,
        ):
            chunk = output["choices"][0]["text"]
            token_count += 1
            yield chunk

        elapsed = time.time() - t0
        self.last_token_count = token_count
        self.last_tps = token_count / elapsed if elapsed > 0 else 0.0

    def get_last_stats(self):
        return {
            "tokens": self.last_token_count,
            "tps": round(self.last_tps, 1),
        }


class GeneratorHF:
    """HuggingFace Transformers fallback generator."""

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
        context = re.sub(r"#{1,6}\s+", "", context)
        context = re.sub(r"\n{3,}", "\n\n", context)
        max_context_chars = 800
        if len(context) > max_context_chars:
            context = context[:max_context_chars].rsplit("\n", 1)[0]
        system_msg = "You are a helpful assistant. Answer using ONLY facts from the context. Be natural and concise. Match answer length to the question. State specific numbers and facts directly. Never mention the source. Just answer like a person would."
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
    print("\nPerformance: {} tokens at {} tok/sec".format(stats["tokens"], stats["tps"]))
