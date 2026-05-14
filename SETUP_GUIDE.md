# Setup Guide

This guide covers everything you need to get the Local RAG Agent running from scratch. If you just want the quick version, see the [README](README.md).

---

## 1. Install Python

Download Python 3.10 or newer from [python.org/downloads](https://www.python.org/downloads/).

During installation, there is a checkbox at the bottom of the first screen that says **"Add Python to PATH"**. Check that box. If you skip this, none of the commands below will work and you will get a "python is not recognized" error.

To verify it installed correctly, open PowerShell or Command Prompt and type:

```
python --version
```

You should see something like `Python 3.12.x` or `Python 3.14.x`.

---

## 2. Download the Project

**Option A** (with Git):
```
git clone https://github.com/duckcoop/local-rag-agent.git
cd local-rag-agent
```

**Option B** (without Git): Go to [github.com/duckcoop/local-rag-agent](https://github.com/duckcoop/local-rag-agent), click the green **Code** button, click **Download ZIP**, extract it somewhere, and open the extracted folder.

---

## 3. Run the Setup Script

Open PowerShell in the project folder. You can do this by navigating to the folder in File Explorer, then right-clicking on an empty area and choosing "Open in Terminal" or "Open PowerShell window here."

Run these two commands:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup_rag.ps1
```

The first command allows scripts to run in this PowerShell window only. It will ask you to confirm, type **Y** and press Enter. This resets when you close the window and does not change anything permanently.

The setup script creates a virtual environment, installs all the Python packages, and checks that everything is working. It also downloads the AI model automatically if it is not already in the `models/` folder.

**If you prefer Command Prompt over PowerShell**, run `setup_rag.bat` instead. It does the same thing.

---

## 4. Download the AI Model (Manual Method)

The setup script handles this automatically, but if you need to do it by hand (or want a different model), here is how.

The default model is **Qwen2.5-1.5B-Instruct** in GGUF format. It is about 1.1 GB.

### Option A: Using the command line

Activate your virtual environment first, then download:

**PowerShell:**
```powershell
.\venv\Scripts\Activate.ps1
pip install huggingface-hub
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir models/
```

**Command Prompt:**
```cmd
venv\Scripts\activate.bat
pip install huggingface-hub
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir models/
```

### Option B: Download directly from the browser

1. Go to [huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)
2. Click on **Files and versions**
3. Find the file named `qwen2.5-1.5b-instruct-q4_k_m.gguf` and click the download arrow next to it
4. Save it into the `models/` folder inside your project directory

The filename must match exactly. If it downloads with a different name, rename it to `qwen2.5-1.5b-instruct-q4_k_m.gguf`.

### Upgrading to a larger model

If you have extra RAM and want better answers, you can swap in a bigger model. Download one of these and drop it into the `models/` folder:

| Model | File to Download | Size | Link |
|---|---|---|---|
| Qwen2.5-3B (recommended upgrade) | `qwen2.5-3b-instruct-q4_k_m.gguf` | ~2.1 GB | [Download](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF) |
| Qwen2.5-7B (best quality) | `qwen2.5-7b-instruct-q4_k_m.gguf` | ~4.4 GB | [Download](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF) |

After downloading a new model, open `src/config.py` and change the `GGUF_MODEL_PATH` line to point to the new filename:

```python
GGUF_MODEL_PATH = PROJECT_ROOT.parent / "models" / "qwen2.5-3b-instruct-q4_k_m.gguf"
```

---

## 5. Add Your Documents

Put the files you want to search through into the `data/docs/` folder. The system supports these file types: `.txt`, `.md`, `.pdf`, `.json`, `.yaml`, `.yml`, `.csv`, `.log`, `.cfg`, `.ini`

Some sample IT documentation is included so you can test right away without adding anything.

---

## 6. Run the Agent

Every time you open a new terminal window, you need to activate the virtual environment first.

**PowerShell:**
```powershell
.\venv\Scripts\Activate.ps1
cd src
```

**Command Prompt:**
```cmd
venv\Scripts\activate.bat
cd src
```

You should see `(venv)` appear at the start of your prompt. Then run:

**Build the search index** (do this once, and again whenever you add or change documents):
```
python rag_agent.py ingest
```

**Start the interactive chat:**
```
python rag_agent.py query
```

**Run the demo with sample questions:**
```
python rag_agent.py demo
```

Type `quit` to exit the chat.

---

## 7. Adjusting for Your CPU

The default settings are tuned for an 8-core processor. If you have a different CPU, open `src/config.py` and change the `N_THREADS` value to match your physical core count. For example, if you have a 6-core CPU:

```python
N_THREADS = 6
```

Using more threads than your physical core count will actually slow things down, so do not set this to your total thread count if your CPU has hyperthreading/SMT.

---

## Troubleshooting

**"python is not recognized"**: Python is not in your PATH. Reinstall it from [python.org](https://www.python.org/downloads/) and check "Add Python to PATH."

**"pip is not recognized"**: You are running commands outside the virtual environment. Activate it first (see Step 6).

**Red execution policy error in PowerShell**: Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use the `.bat` script in Command Prompt instead.

**"No module named X"**: Dependencies did not install into your venv. Activate the venv, then run `pip install -r requirements.txt`.

**"Model file not found"**: The GGUF file is not in the `models/` folder or has the wrong filename. See Step 4.

**First query takes a while**: Normal. The AI model and embedding engine load into memory on the first query (10 to 20 seconds). After that, queries are fast.
