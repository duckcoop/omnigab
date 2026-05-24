<p align="center">
  <h1 align="center">omnigab</h1>
  <p align="center">
    <strong>A universal local AI agent that runs 100% on your computer.</strong><br>
    Tool-calling LLM · document search · web search · persistent memory · Indeed job automation.<br>
    No API keys. No cloud. No subscriptions.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python" alt="Python 3.12">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/OS-Windows%2010%2F11-blue" alt="Windows">
    <img src="https://img.shields.io/badge/GPU-CUDA%2012.x-76b900?logo=nvidia" alt="CUDA 12.x">
  </p>
</p>

---

## What this is

omnigab is a tool-calling local LLM. The model is the brain: it reads your message, decides whether to chat, search your local documents, hit the web, save/recall persistent memory, or fire a built-in skill (e.g. the Indeed apply tool). Everything happens on your hardware.

* **Model**: Qwen2.5 (1.5B → 14B) in GGUF format, served by `llama-cpp-python`.
* **GPU offload**: full CUDA support on NVIDIA GPUs (auto-detected, all layers offloaded).
* **UI**: native Windows desktop app (tkinter) + a localhost web UI on `http://localhost:8080`.
* **Tools wired in by default**: `rag_search`, `web_search`, `memory_read`, `memory_write`, `persistent_memory`, `indeed_apply`, plus user-defined skills under `skills/`.

---

## Requirements

| Component | Required | Notes |
|---|---|---|
| **Python** | **3.12.x** (any patch version) | **Not 3.13, not 3.14.** Prebuilt `llama-cpp-python` CUDA wheels only ship for 3.10–3.12. The setup script halts on newer Pythons. |
| OS | Windows 10 / 11 | Linux/macOS work but `setup.bat` is Windows-specific. |
| RAM | 4 GB minimum | 16 GB recommended for the 14B model. |
| GPU (optional) | NVIDIA with ≥ 4 GB VRAM | RTX 4070 Super 12 GB → loads the 14B fully on-GPU at ~33 tok/s. CPU-only also works, just slower. |
| Disk | ~12 GB | venv + dependencies + 14B model. The 1.5B model only needs ~3 GB total. |

You do **not** need to install the CUDA Toolkit separately. The setup script installs the CUDA runtime DLLs from pip (`nvidia-cuda-runtime-cu12` etc.) and wires them next to `llama.dll`.

---

## Step-by-step install

### 1. Install Python 3.12

Download from <https://www.python.org/downloads/release/python-31210/> (any 3.12.x build is fine).

During the installer:
- ✅ **Check "Add Python to PATH"** on the first screen.
- ✅ Use "Install Now" (default options).

Verify in a new terminal:
```cmd
python --version
```
Must print `Python 3.12.x`. If it prints `3.13` or `3.14`, uninstall those — `setup.bat` will refuse to run on them because the CUDA wheels don't exist for those versions yet.

### 2. Clone the repository

```cmd
git clone https://github.com/<your-fork>/omnigab.git
cd omnigab
```

(Or download the ZIP from GitHub and extract.)

### 3. Run the setup script

Double-click `setup.bat`, or from a terminal:
```cmd
setup.bat
```

What it does, in order:
1. Confirms Python 3.12 is present (halts otherwise with installation instructions).
2. Creates a `venv\` virtual environment.
3. Detects your NVIDIA GPU via a Python helper (`scripts/detect_gpu.py`).
4. **If GPU detected**: installs the CUDA runtime DLL pip packages (`nvidia-cuda-runtime-cu12`, `nvidia-cublas-cu12`, `nvidia-cuda-nvrtc-cu12`).
5. Installs `llama-cpp-python` from abetlen's prebuilt CUDA 12.4 wheel index (falls back to 12.2 / 12.1 / 11.8 / CPU as needed).
6. Runs `scripts/install_cuda_dlls.py` to copy `cudart64_12.dll`, `cublas64_12.dll`, `nvrtc64_120_0.dll` etc. into `venv\Lib\site-packages\llama_cpp\lib\` so `llama.dll` loads cleanly.
7. Verifies CUDA actually works via `llama_supports_gpu_offload()`.
8. Installs everything else: `fastapi`, `uvicorn`, `sentence-transformers`, `faiss-cpu`, `huggingface-hub`, `psutil`, `pymupdf`, `fpdf2`, `playwright`, `ddgs`, etc.
9. Installs the Playwright Chromium browser (used by `indeed_apply`).
10. Downloads the default 1.5B model if no model is on disk.
11. Builds the FAISS vector index from any docs in `data/docs/`.
12. Launches `desktop_app.py`.

First run takes 5–10 minutes of downloads (mostly `torch` + the model). Subsequent runs reuse everything and start in seconds.

### 4. Launch later

After the first successful setup, double-click **`omnigab.bat`** in the project root. It skips the install phase and goes straight to the app.

---

## Hardware auto-tuning

On first launch with no saved model preference, omnigab picks the best model that fits your machine:

| VRAM (GPU) | System RAM | Auto-selected model | Tokens/sec |
|---|---|---|---|
| ≥ 10 GB | ≥ 16 GB | Qwen 2.5 **14B** Q4_K_M (~9 GB) | ~30–40 (GPU) |
| 6–10 GB | ≥ 10 GB | Qwen 2.5 **7B** Q4_K_M (~4.4 GB) | ~50 (GPU) |
| 4–6 GB | ≥ 6 GB | Qwen 2.5 **3B** Q4_K_M (~2.1 GB) | ~60 (GPU) |
| No GPU or < 4 GB VRAM | ≥ 4 GB | Qwen 2.5 **1.5B** Q4_K_M (~1.1 GB) | ~6 (CPU) |

You can switch models at any time from the **Models** tab inside the app. Each entry has a `Download` button (with a confirmation popup) and a `Switch` button. Switches are hot — the live model is unloaded from VRAM before the new one loads.

---

## Using omnigab

The chat is plain-English. Examples that route to specific tools:

| You say | Tool fired | What happens |
|---|---|---|
| "find me 5 entry-level IT jobs in Maryland" | `indeed_apply` | Searches Indeed via Playwright, scrapes 5 listings, returns titles + URLs |
| "what does my AD doc say about password resets?" | `rag_search` | Embeds query, finds top chunks in your `data/docs/` |
| "remember that I live in Frederick, MD" | `memory_write` | Saved to `user_memory.json` + SQLite |
| "what's the latest news on the Space Force?" | `web_search` | DuckDuckGo, summarized with citations |
| "what's 17 × 23?" | _(no tool)_ | Direct math answer |

The model never **narrates** intentions — if it's going to use a tool, the very first token it emits is `<tool_call>`. You'll see the tool name and arguments stream in the chat as a cyan-bordered row, then the result, then the model's prose answer.

---

## Project structure

```
omnigab/
├── setup.bat                  # one-click install (Windows)
├── omnigab.bat              # launcher (post-install)
├── desktop_app.py             # tkinter desktop UI
├── requirements.txt
├── scripts/
│   ├── detect_gpu.py          # GPU probe used by setup.bat
│   ├── install_cuda_dlls.py   # wires CUDA runtime DLLs into llama_cpp/lib/
│   └── deploy.py              # flake8 + git push helper
├── src/
│   ├── core/                  # Agent loop + ModelManager + tool protocol
│   ├── tools/                 # Built-in tools: RAG, web, memory, indeed_apply, …
│   ├── web_app.py             # FastAPI server (localhost:8080)
│   ├── generator.py           # llama-cpp wrapper (GPU + async stream)
│   ├── embeddings.py          # sentence-transformers
│   ├── vectorstore.py         # FAISS
│   ├── persistent_memory.py   # SQLite-backed cross-session memory
│   └── …
├── skills/                    # Drop-in user skills (each is a folder with skill.json + skill.py)
├── data/
│   ├── docs/                  # Documents to index (PDF, MD, TXT, etc.)
│   ├── playwright_profile/    # Persistent Indeed login session
│   └── omnigab.db           # Persistent memory store
└── models/                    # GGUF model files
```

---

## Troubleshooting

### `setup.bat` halts with "Python 3.12 is required"
You have Python 3.13 / 3.14 / 3.10 / 3.11 instead. Install 3.12 from [python.org](https://www.python.org/downloads/release/python-31210/), make sure "Add to PATH" is checked, open a fresh terminal, and rerun.

### App window closes immediately on launch
Run it from a terminal instead so you can read the error:
```cmd
venv\Scripts\python.exe desktop_app.py
```
Most common cause: dependencies not installed. Re-run `setup.bat`.

### "CUDA support: False" but I have an NVIDIA GPU
Two possible causes:
1. `nvidia-cuda-runtime-cu12` not installed. Run `venv\Scripts\python.exe -m pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 nvidia-cuda-nvrtc-cu12`, then `venv\Scripts\python.exe scripts\install_cuda_dlls.py`.
2. CUDA wheel didn't install. `venv\Scripts\python.exe -m pip install llama-cpp-python --force-reinstall --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124`.

### Model load is slow / system is swapping
Your VRAM isn't big enough for the chosen model. Switch to a smaller one in the Models tab, or set `RAG_GPU_LAYERS=20` (env var) to offload only the first 20 layers.

### "Failed to load shared library `llama.dll`"
CUDA runtime DLLs aren't where llama.dll can find them. Fix:
```cmd
venv\Scripts\python.exe scripts\install_cuda_dlls.py
```

### Indeed apply tool says "Cloudflare challenge"
Indeed is rate-limiting your IP. Wait a few minutes, or open the Chromium window when it appears and solve the challenge manually — the persistent profile under `data/playwright_profile/` keeps the cookie.

### Tool calls aren't firing — model just chats
Make sure you're on the 14B model (or 7B). The 1.5B model can chat but struggles with the `<tool_call>` syntax. Switch in the Models tab.

---

## Deploying / pushing changes

```cmd
venv\Scripts\python.exe scripts\deploy.py --check          # flake8 only
venv\Scripts\python.exe scripts\deploy.py --commit "msg"   # commit
venv\Scripts\python.exe scripts\deploy.py --push           # commit + push to origin
```

The deploy script lints `src/`, `scripts/`, and `desktop_app.py` (ignoring `venv/`).

---

## License

MIT.
