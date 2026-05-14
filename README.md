<p align="center">
  <h1 align="center">Local RAG Agent</h1>
  <p align="center">
    <strong>Ask questions about your documents using AI that runs 100% on your computer.</strong><br>
    No API keys. No cloud. No subscriptions. Just your hardware.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/OS-Windows%2010%2F11-blue" alt="Windows">
  </p>
</p>

---

## What This Does

You give it your documents (text files, markdown, PDFs, JSON, YAML, CSV). It reads them, indexes them, and then lets you ask questions in plain English. The AI generates answers using **only** your documents as source material, and it automatically fact-checks every sentence against your files before showing you the result. If something can't be verified, it gets removed.

Everything runs locally on your CPU. Nothing is sent to the internet.

---

## Requirements

Before you start, make sure you have these two things installed:

1. **Python 3.10 or newer** from [python.org/downloads](https://www.python.org/downloads/). During installation, **check the box that says "Add Python to PATH"**. This is critical.

2. **Git** (optional, for cloning) from [git-scm.com](https://git-scm.com/downloads/win). You can also just download the ZIP from GitHub.

---

## Setup

Everything you need is already in this repo (source code, sample documents, config). The only thing not included is the AI model file because it's 1.1 GB and GitHub has a 100 MB file limit.

### Step 1: Download the project

Click the green **Code** button above, then **Download ZIP**. Extract it and open the folder.

Or with Git:
```
git clone https://github.com/duckcoop/local-rag-agent.git
cd local-rag-agent
```

### Step 2: Create a virtual environment

Open a terminal in the project folder:

```
python -m venv venv
```

Activate it:

**PowerShell:** `.\venv\Scripts\Activate.ps1`

**Command Prompt:** `venv\Scripts\activate.bat`

You should see `(venv)` at the start of your prompt.

### Step 3: Install dependencies

```
pip install -r requirements.txt
```

This takes a few minutes since PyTorch is a large download.

### Step 4: Download the AI model

The model is the only thing not in the repo (~1.1 GB, too large for GitHub). Pick whichever method you prefer:

**Option A: Run the download script**

**PowerShell:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\download_model.ps1
```

**Command Prompt:** Run `download_model.bat` (you can just double-click it).

**Option B: Download it in your browser**

Go to [huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF), click **Files and versions**, find `qwen2.5-1.5b-instruct-q4_k_m.gguf`, download it, and put it in the `models/` folder.

For more detail on model options and CPU tuning, see the [Setup Guide](SETUP_GUIDE.md).

### Add your documents

Put the files you want to search through into the `data/docs/` folder. Supported file types: `.txt`, `.md`, `.pdf`, `.json`, `.yaml`, `.yml`, `.csv`, `.log`, `.cfg`, `.ini`

Some sample IT documentation is already included so you can test right away.

### Run it

Make sure your virtual environment is activated (you should see `(venv)` in your prompt), then:

```
cd src
python rag_agent.py ingest
python rag_agent.py query
```

The `ingest` command reads your documents and builds the search index. Run it again whenever you add or change documents.

The `query` command opens an interactive chat. Ask a question, get an answer sourced from your files. Type `quit` to exit.

---

## Troubleshooting

**"python is not recognized"** means Python isn't in your PATH. Reinstall Python from [python.org](https://www.python.org/downloads/) and make sure you check "Add Python to PATH" during installation.

**"pip is not recognized"** means you're running pip outside the virtual environment. Make sure you activated it first (Step 4 above). You should see `(venv)` at the start of your command prompt.

**Red "execution policy" error in PowerShell** means you need to run the `Set-ExecutionPolicy` command shown in Step 2 first, or just use the `.bat` script in Command Prompt instead.

**"No module named X"** means dependencies didn't install into your venv. Make sure `(venv)` appears in your prompt, then run `pip install -r requirements.txt` again.

**First query is slow** because the AI model and embedding engine need to load into memory. This takes 10 to 20 seconds. After that, each query is much faster.

**"Model file not found"** means the GGUF model isn't in the `models/` folder. Run `download_model.bat` or `download_model.ps1`, or download it manually from [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF).

---

## How It Works (the short version)

1. **Ingest**: Your documents get split into small overlapping chunks and converted into numerical vectors (embeddings).
2. **Search**: When you ask a question, it finds the most relevant chunks using similarity search.
3. **Answer**: A local AI model reads those chunks and writes an answer.
4. **Verify**: Every sentence in the answer is checked against the source material. Anything the model made up gets removed. If too many claims fail, it retries automatically.

The verification step is what makes this different from a basic chatbot. It catches hallucinations at the sentence level so the final answer only contains information that actually appears in your documents.

---

## Configuration

All settings are in `src/config.py`. The important ones:

**N_THREADS**: Set this to your CPU's physical core count. Default is 8 (for Ryzen 9850X3D). If you have a different CPU, change this number to match your core count for best performance.

**CHUNK_SIZE**: How many characters per document chunk. Default 512 works well for most documents.

**TOP_K**: How many document chunks to retrieve per question. Default is 3.

**USE_GGUF**: Set to `False` if you don't have a GGUF model and want to use the slower HuggingFace fallback instead.

---

## Using a Different Model

The default model is Qwen2.5-1.5B (1.1 GB). You can swap in a larger model for better answers if you have the RAM:

| Model | Download Size | RAM Needed | Quality |
|---|---|---|---|
| Qwen2.5-1.5B (default) | ~1.1 GB | ~4 GB | Good for quick answers |
| Qwen2.5-3B | ~2.1 GB | ~6 GB | Recommended upgrade |
| Qwen2.5-7B | ~4.4 GB | ~10 GB | Best answer quality |

To switch models: download the new GGUF file into the `models/` folder, then update the filename in `src/config.py` on the `GGUF_MODEL_PATH` line.

---

## Project Structure

```
local-rag-agent/
  data/docs/            Your documents go here
  models/               AI model files (GGUF format)
  src/                  Python source code
  tests/                Benchmark tests
  vectorstore/          Search index (created after ingest)
  download_model.ps1    Model downloader (PowerShell)
  download_model.bat    Model downloader (Command Prompt)
  requirements.txt      Python dependencies
```

---

## Demo Mode

To see the system in action with the included sample documents:

```
.\venv\Scripts\Activate.ps1
cd src
python rag_agent.py demo
```

For a color-coded visual version:

```
python demo_ui.py
```

---

## License

MIT
