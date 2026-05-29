<p align="center">
  <h1 align="center">OmniGab</h1>
  <p align="center">
    <strong>A universal local AI agent that runs entirely on your computer.</strong><br>
    Zero cloud dependencies. No API keys. No subscriptions.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
    <img src="https://img.shields.io/badge/OS-Windows%2010%2F11-0078D6?logo=windows&logoColor=white" alt="Windows 10/11">
    <img src="https://img.shields.io/badge/GPU-CUDA%2012.x-76B900?logo=nvidia&logoColor=white" alt="CUDA 12.x">
  </p>
</p>

---

## Overview

OmniGab is a universal local AI agent that runs 100% on your own hardware. There are no cloud dependencies, no API keys, and no subscriptions. The model is the brain: it reads your message and decides on its own whether to chat, search your local documents, query the web, save or recall memory, or fire a built-in skill. Every token is generated on your machine, so your data never leaves it.

Under the hood, OmniGab serves Qwen2.5 models (1.5B through 14B) in GGUF format through `llama-cpp-python`, with full CUDA offload on NVIDIA GPUs. You interact with it through a native Windows desktop app or a local web UI at `http://localhost:8080`.

---

## Core Features

* **Tool calling.** The model autonomously selects and invokes tools mid-conversation, streaming the tool name, arguments, and results inline before it writes its answer.
* **Document search.** Point OmniGab at your files and it embeds them into a local FAISS index, then retrieves the most relevant passages to ground its responses (local RAG).
* **Web search.** Live queries through DuckDuckGo, summarized with citations, for anything outside your local knowledge base.
* **Persistent memory.** Cross-session memory backed by SQLite, so the agent remembers facts you tell it across restarts.
* **Indeed job automation.** A built-in skill that drives a Playwright browser to search Indeed listings and assist with applications end to end.

---

## Prerequisites

Install these before running OmniGab.

| Requirement | Details |
|---|---|
| **Python 3.12.x** | Any 3.12 patch version. Not 3.13 or 3.14: prebuilt `llama-cpp-python` CUDA wheels only ship for 3.10 through 3.12, and setup halts on newer versions. Check "Add Python to PATH" during install. |
| **Windows 10 or 11** | The setup and launch scripts are Windows native. |
| **Git** | Needed to clone the repository (or download the ZIP instead). |
| **RAM** | 4 GB minimum, 16 GB recommended for the 14B model. |
| **NVIDIA GPU with CUDA 12.x** (optional) | Recommended for speed. You do not need to install the CUDA Toolkit yourself; the setup script pulls the CUDA 12.x runtime DLLs from pip. CPU only also works, just slower. |
| **Disk space** | Roughly 12 GB for the virtual environment, dependencies, and the 14B model. The 1.5B model needs about 3 GB total. |

---

## Quick Start

1. **Clone the repository.**

   ```cmd
   git clone https://github.com/duckcoop/omnigab.git
   cd omnigab
   ```

2. **Run the setup script.** Double-click `setup.bat`, or run it from a terminal:

   ```cmd
   setup.bat
   ```

   This confirms Python 3.12 is present, creates the `venv\` virtual environment, detects your GPU, installs `llama-cpp-python` with the matching CUDA wheel, wires in the CUDA runtime DLLs, installs the remaining dependencies and the Playwright browser, downloads the default 1.5B model, builds the document index, and launches the app. The first run takes 5 to 10 minutes of downloads; later runs reuse everything and start in seconds.

3. **Launch the agent.** After the first setup, start OmniGab any time by double-clicking `omnigab.bat` in the project root. It skips the install phase and opens the desktop app directly. To launch the web UI instead, run `start.bat`, or `start.bat --terminal` for a plain terminal chat.

---

## Repository Structure

```
omnigab/
├── setup.bat              One-click installer (Windows)
├── omnigab.bat            Primary launcher (post-install)
├── start.bat              Alternate launcher for the web / terminal UI
├── desktop_app.py         Native tkinter desktop app (main entry point)
├── launcher.py            Browser app-mode launcher (alternate entry point)
├── requirements.txt
├── README.md
├── LICENSE
│
├── src/                   Application source code
│   ├── core/              Agent loop, ModelManager, and tool protocol
│   ├── tools/             Built-in tools: RAG, web, memory, indeed_apply
│   ├── web_app.py         FastAPI server (localhost:8080)
│   ├── generator.py       llama-cpp wrapper with GPU and async streaming
│   ├── embeddings.py      sentence-transformers embeddings
│   ├── vectorstore.py     FAISS vector store
│   └── persistent_memory.py   SQLite-backed cross-session memory
│
├── skills/                Drop-in user skills (one folder per skill)
│   ├── summarize_document/
│   ├── extract_action_items/
│   ├── compare_two_documents/
│   └── web_search_and_cite/
│
├── scripts/               Setup helpers and maintenance scripts
│   ├── detect_gpu.py          GPU probe used by setup.bat
│   ├── install_cuda_dlls.py   Wires CUDA runtime DLLs into llama_cpp/lib/
│   ├── install_llama_cpp.py   Installs the correct llama-cpp-python wheel
│   ├── deploy.py              flake8 plus git push helper
│   ├── download_model.bat     Manual model downloader
│   └── ...                    Other .bat / .ps1 maintenance scripts
│
├── tests/                 Test suite
│   ├── test_omnigab.py
│   ├── test_usajobs.py
│   └── evolution_benchmark.py
│
├── data/                  Local data
│   ├── docs/              Documents to index (PDF, MD, TXT, etc.)
│   ├── playwright_profile/    Persistent Indeed login session
│   └── storage.db         Persistent memory store
│
└── models/                GGUF model files
```

---

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.
