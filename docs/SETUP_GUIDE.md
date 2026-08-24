# Setup Guide

This guide goes into more detail than the README. If you just want the quick version, see the [README](README.md).

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
git clone https://github.com/duckcoop/omnigab.git
cd omnigab
```

**Option B** (without Git): Go to [github.com/duckcoop/omnigab](https://github.com/duckcoop/omnigab), click the green **Code** button, click **Download ZIP**, extract it somewhere, and open the extracted folder.

---

## 3. Create a Virtual Environment

Open a terminal in the project folder and run:

```
python -m venv venv
```

Then activate it:

**PowerShell:** `.\venv\Scripts\Activate.ps1`

**Command Prompt:** `venv\Scripts\activate.bat`

You should see `(venv)` at the start of your prompt. This means you are working inside the virtual environment, and any packages you install will stay contained in the project folder.

If you get an execution policy error in PowerShell, run this first:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
This only affects the current window and resets when you close it.

**Troubleshooting:** If `activate.bat` is missing after creating the venv, your Python installation may not include pip. Fix it with:
```
python -m ensurepip --upgrade
python -m venv venv
```

---

## 4. Install Dependencies

With the virtual environment activated:

```
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python scripts\install_llama_cpp.py
```

The first two lines install PyTorch, transformers, sentence-transformers, FAISS, and everything else. PyTorch is around 2 GB so it takes a few minutes.

The third line installs the local inference engine, llama-cpp-python. It is a separate step because PyPI carries no prebuilt wheels for it, so a plain `pip install` would try to compile it from source and need a C++ toolchain. `scripts/install_llama_cpp.py` picks the right prebuilt GPU or CPU wheel for your machine and wires in the CUDA runtime DLLs. `setup.bat` runs the same script, so the automatic path already does this for you.

Skip that third line only if you do not intend to run a model: the app needs it, but the document extraction gate, the tests, and the linters all work without it.

---

## 5. Download the AI Model

The model is the only thing not included in the repo because it is about 3 GB and GitHub has a 100 MB file limit.

### Option A: Run the download script

**PowerShell:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\download_model.ps1
```

**Command Prompt:** Run `download_model.bat` (you can just double-click it in File Explorer).

The script downloads the model into the `models/` folder automatically.

### Option B: Download from the command line manually

With your virtual environment activated:

```
pip install huggingface-hub
huggingface-cli download bartowski/Qwen_Qwen3.5-4B-GGUF Qwen_Qwen3.5-4B-Q4_K_M.gguf --local-dir models/
```

### Option C: Download directly from your browser

1. Go to [huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF)
2. Click on **Files and versions**
3. Find the file named `Qwen_Qwen3.5-4B-Q4_K_M.gguf` and click the download arrow next to it
4. Save it into the `models/` folder inside your project directory

The filename must match exactly, including the doubled `Qwen_Qwen` prefix, which is that publisher's naming convention rather than a mistake. A file saved under any other name is invisible to the app.

---

## 6. Upgrading to a Larger Model

If you have extra RAM and want better quality answers, you can swap in a bigger model. Download one of these and put it in the `models/` folder:

| Model | File to Download | Size | Link |
|---|---|---|---|
| Qwen3.5-9B (best quality) | `Qwen_Qwen3.5-9B-Q4_K_M.gguf` | ~6.2 GB | [Download](https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF) |

The easier route is the **Models tab in the app**, which downloads and switches for you and is the only place that records your choice. That tab also takes any Hugging Face GGUF repo: paste the URL from your browser into **Add from Hugging Face**, pick a quant, and it downloads and profiles it against your hardware. See the README for the walkthrough.

You do not need to edit `src/config.py`. The app reads which model to use from `data/model_state.json`, written when you pick one in the Models tab, and falls back to whatever it finds in `models/` if that file is missing. Editing `GGUF_MODEL_PATH` by hand is not how the setting is read.

---

## 7. Add Your Documents

Put the files you want to search through into the `data/docs/` folder. Supported file types: `.txt`, `.md`, `.pdf`, `.json`, `.yaml`, `.yml`, `.csv`, `.log`, `.cfg`, `.ini`

Some sample IT documentation is already included so you can test right away without adding anything.

---

## 8. Run the Agent

Every time you open a new terminal window, you need to activate the virtual environment first.

**PowerShell:** `.\venv\Scripts\Activate.ps1`

**Command Prompt:** `venv\Scripts\activate.bat`

You should see `(venv)` at the start of your prompt. Then run:

**Build the search index** (do this once, and again whenever you add or change documents):
```
cd src
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

## 9. Adjusting for Your CPU

The default settings are tuned for an 8-core processor. If you have a different CPU, open `src/config.py` and change the `N_THREADS` value to match your physical core count. For example, if you have a 6-core CPU:

```python
N_THREADS = 6
```

Using more threads than your physical core count will actually slow things down, so do not set this to your total thread count if your CPU has hyperthreading/SMT.

---

## Troubleshooting

**"python is not recognized"**: Python is not in your PATH. Reinstall it from [python.org](https://www.python.org/downloads/) and check "Add Python to PATH."

**"pip is not recognized"**: You are running commands outside the virtual environment. Activate it first (see Step 8).

**Red execution policy error in PowerShell**: Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use Command Prompt instead.

**"No module named X"**: Dependencies did not install into your venv. Activate the venv, then run `pip install -r requirements.txt`.

**"Local inference is not installed"**: llama-cpp-python is missing, which happens if you followed the manual install and skipped `python scripts\install_llama_cpp.py`. Run it now (see Step 4). Everything that does not load a model keeps working without it.

**"Model file not found"**: The GGUF file is not in the `models/` folder or has the wrong filename. See Step 5.

**First query takes a while**: Normal. The AI model and embedding engine load into memory on the first query (10 to 20 seconds). After that, queries are fast.
