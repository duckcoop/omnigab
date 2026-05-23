<p align="center">
  <h1 align="center">OmniAgent</h1>
  <p align="center">
    <strong>A universal local AI agent that runs 100% on your computer.</strong><br>
    Tool-calling LLM, document search, web search, persistent memory, job automation — no API keys, no cloud, no subscriptions.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python" alt="Python 3.12">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/OS-Windows%2010%2F11-blue" alt="Windows">
    <img src="https://img.shields.io/badge/GPU-CUDA%20optional-76b900?logo=nvidia" alt="CUDA optional">
  </p>
</p>

---

## What This Is

OmniAgent is a local autonomous AI agent. The LLM is the central brain — it sees the user's message and decides whether to chat, search your documents, hit the web, query persistent memory, or invoke a skill (including the built-in Indeed job-application tool).

Everything runs on your machine. The model is GGUF + llama-cpp. If you have an NVIDIA GPU, layers are offloaded automatically.

---

## Quick Start

OmniAgent scales to your hardware. On first launch it detects your RAM + VRAM and auto-downloads the right model:

| VRAM            | RAM    | Auto-selected model |
|-----------------|--------|--------------------|
| 10 GB or more   | any    | Qwen 2.5 14B Q4    |
| 6 – 10 GB       | any    | Qwen 2.5 7B Q4     |
| 4 – 6 GB        | any    | Qwen 2.5 3B Q4     |
| No GPU          | ≥16 GB | Qwen 2.5 3B Q4     |
| No GPU          | <16 GB | Qwen 2.5 1.5B Q4   |

### Requirements

1. **Python 3.12** — install from [python.org](https://www.python.org/downloads/release/python-3128/). Check **Add Python to PATH**. (Setup will refuse 3.13+ because the prebuilt CUDA wheels for `llama-cpp-python` only ship for 3.10-3.12.)
2. **Optional: NVIDIA GPU** with current drivers for CUDA acceleration. Setup auto-installs the right CUDA wheel.

### Install + run

Double-click **`setup.bat`** (or run it from a terminal). It will:

- Confirm you're on Python 3.12.
- Create the `venv/`.
- Detect your GPU + VRAM.
- Install the right `llama-cpp-python` build (CUDA cu124/cu122/cu121/cu118, falling back to CPU).
- Install Playwright + Chromium for the job-applicator tool.
- Auto-download the model that best fits your hardware.
- Launch the desktop app.

---

## What you get

- **Agentic chat** — the model chooses its own tools per turn. No forced pipeline.
- **Local document search (RAG)** — drop files into `data/docs/`, hit re-index.
- **Web search** (DuckDuckGo) — only when the model decides external info is needed.
- **Persistent memory** — SQLite-backed; survives restarts and gets auto-injected into every prompt.
- **Indeed job automation** — Playwright-driven; searches Indeed, scrapes descriptions, fills Easy Apply forms using your saved screener answers, stops at the Submit button by default.
- **Plugin skills** — drop a Python file under `skills/`, it becomes a callable tool.
- **Hot model swap** — switch between 1.5B / 3B / 7B / 14B from the UI; the new model loads into VRAM with proper unload of the old one.

---

## Project layout

```
omniagent/
  data/                 Indexed docs, persistent memory DB, playwright profile
  models/               GGUF model files
  src/
    core/               Agent loop, model manager, tool protocol
    tools/              Built-in tools (rag, web, memory, indeed_apply)
    static/             Web UI
    web_app.py          FastAPI + SSE backend
  skills/               User plugin skills (auto-discovered)
  scripts/
    deploy.py           flake8 + git commit + push
  desktop_app.py        Native Tk desktop UI
  setup.bat             One-click installer
```

---

## Development

Lint + commit + push in one shot:

```
python scripts/deploy.py --auto
```

Run lint only:

```
python scripts/deploy.py
```

---

## License

MIT
