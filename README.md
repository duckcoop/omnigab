<p align="center">
  <h1 align="center">OmniGab</h1>
  <p align="center">
    <strong>A private AI assistant that runs entirely on your own computer.</strong><br>
    No cloud. No API keys. No subscriptions. Your data never leaves your machine.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
    <img src="https://img.shields.io/badge/OS-Windows%2010%2F11-0078D6?logo=windows&logoColor=white" alt="Windows 10/11">
    <img src="https://img.shields.io/badge/GPU-CUDA%2012.x-76B900?logo=nvidia&logoColor=white" alt="CUDA 12.x">
  </p>
</p>

---

## What is OmniGab?

OmniGab is a chat assistant that runs a real language model directly on your PC instead of sending your messages to a company server. You type a question, and a Qwen2.5 model loaded on your own GPU (or CPU) writes the answer locally. Because nothing leaves your computer, you can point it at private documents, personal notes, or work files without handing them to anyone.

It is more than a chatbot. The model can decide, on its own, to search your documents, look something up on the web, remember a fact for later, search real job listings, or run one of its built in skills, then use what it finds to answer you. You talk to it through a normal desktop window.

---

## What it can do

**Chat privately.** Have a normal conversation with a capable local model. Everything runs offline once the model is downloaded.

**Answer from your own documents.** Drop PDFs, Markdown, text, config, or log files into the Docs tab (or the `data/docs` folder) and OmniGab reads and indexes them. Ask a question and it pulls the most relevant passages and answers from them, so you get grounded answers instead of guesses.

**Search the live web.** When something is outside your files, it queries DuckDuckGo, opens the actual pages, reads them, and answers with the source links. No search API key is needed.

**Remember things between sessions.** Tell it a fact ("my location is Austin, TX") and it stores that in a local database, so it still knows next time you open the app.

**Find federal jobs.** It searches real openings through the official USAJOBS API and ranks them against your resume and certifications. It can also open Indeed and other job sites in your normal browser so listings load without bot blocking.

**Draft a federal resume.** Using your active resume plus what it remembers about you, it drafts tailored federal style resumes, and can briefly switch to a faster model just for the drafting step.

**Look up vulnerabilities.** A security tool queries the NIST National Vulnerability Database and the CISA Known Exploited Vulnerabilities catalog for real CVE data.

**Do exact math and parsing.** Instead of guessing at arithmetic, it can run code in a sandboxed Python tool for deterministic results.

**Run drop in skills.** Skills are small folders you can add to extend it. It ships with summarize a document, extract action items, compare two documents, and web search and cite.

**Swap models on the fly.** From the Models tab you can move between a small fast model and a large accurate one. Bigger models are noticeably better at deciding when to use tools.

---

## How it works (the technology)

OmniGab is a Python application that wires several local components together.

**The model.** Language models run through `llama-cpp-python`, which loads Qwen2.5 Instruct models in GGUF format (quantized to Q4_K_M so they fit in modest memory). On an NVIDIA card the layers are offloaded to the GPU with CUDA 12.x for speed; with no GPU it falls back to CPU. The context window is 8192 tokens.

**The agent loop.** Rather than a plain prompt and reply, OmniGab runs an agent loop. The model is given a catalog of tools and answers with a `<tool_call>` instruction when it wants one. The app runs that tool, feeds the result back, and lets the model continue until it is ready to answer. This is what lets one message trigger a document search, a web lookup, and a memory write in sequence.

**Document search (RAG).** Your files are split into overlapping chunks and turned into vectors with the `sentence-transformers/all-MiniLM-L6-v2` embedding model. Those vectors live in a FAISS index, and a question is embedded the same way to retrieve the closest passages by cosine similarity. PDFs are read with PyMuPDF.

**Web access.** Search comes from the keyless `ddgs` DuckDuckGo library, and page content is fetched with `requests` and cleaned with BeautifulSoup, with a URL safety check before anything is opened.

**Memory.** Facts and session data persist in a local SQLite database (`data/storage.db`), so memory survives restarts.

**Interfaces.** The default is a native desktop window built with Python's `tkinter`. There is also a browser based UI served by a local FastAPI and Uvicorn server at `http://localhost:8080`, and a plain terminal chat.

Everything above runs on your hardware. There is no external API in the request path.

---

## The interface

The desktop window is organized into tabs:

- **Chat** is the main conversation, showing the model name, token speed, and whether web access is on.
- **Jobs** runs the job search and ranking features.
- **Docs** is where you add and manage the documents it can search.
- **Models** lets you download and switch between the available models.
- **Settings** controls behavior like web search and generation options.
- **Developer** exposes lower level details for debugging.

---

## Requirements

| Requirement | Details |
|---|---|
| **Python 3.10 to 3.12** | Any patch version. These versions have prebuilt `llama-cpp-python` CUDA wheels, so GPU support installs cleanly. Newer versions (3.13+) still run but print a warning, since a matching GPU wheel may not exist yet. Check "Add python.exe to PATH" during install. |
| **Windows 10 or 11** | The setup and launch scripts are Windows batch files. |
| **Git** | To clone the repository (or download the ZIP). |
| **RAM** | About 4 GB for the smallest model, 16 GB for the 14B model. |
| **NVIDIA GPU with CUDA 12.x** (optional) | Recommended for speed. You do not install the CUDA Toolkit yourself; setup pulls the CUDA runtime DLLs from pip. CPU only also works, just slower. |
| **Disk space** | Roughly 3 GB total with the small model, up to about 12 GB with the 14B model and full dependencies. |

---

## Quick start

1. **Clone the repository.**

   ```cmd
   git clone https://github.com/duckcoop/omnigab.git
   cd omnigab
   ```

2. **Run the setup script.** Double click `setup.bat`, or run it from a terminal:

   ```cmd
   setup.bat
   ```

   Setup finds a real Python, creates the `venv` virtual environment, updates pip, detects your GPU, installs `llama-cpp-python` with the matching CUDA wheel, wires in the CUDA runtime DLLs, installs the remaining dependencies and the Playwright browser, downloads the default model, builds the document index, and launches the app. The first run downloads a few GB, so give it several minutes. Later runs reuse everything and start quickly.

3. **Launch any time.** After the first setup, double click `omnigab.bat` to open the desktop app. Use `start.bat` for the browser UI at `http://localhost:8080`, or `start.bat --terminal` for a plain terminal chat.

---

## Models

Pick a model in the Models tab. Larger models answer better and use tools more reliably, but need more memory and run slower.

| Model | Size on disk | Suggested RAM | Notes |
|---|---|---|---|
| Qwen 2.5 1.5B | ~1.1 GB | ~4 GB | Fastest, downloaded by default |
| Qwen 2.5 3B | ~2.1 GB | ~6 GB | Good balance |
| Qwen 2.5 7B | ~4.4 GB | ~10 GB | Strong quality |
| Qwen 2.5 14B | ~8.9 GB | ~16 GB | Best quality |

---

## Repository structure

```
omnigab/
├── setup.bat              One click installer and launcher (Windows)
├── omnigab.bat            Opens the desktop app after setup
├── start.bat              Launches the web UI or terminal chat
├── desktop_app.py         Native tkinter desktop app (default entry point)
├── launcher.py            Alternate browser app mode launcher
├── requirements.txt
│
├── src/
│   ├── core/              Agent loop, model manager, tool protocol
│   ├── tools/             Built in tools (document search, web, memory,
│   │                      USAJOBS, CVE lookup, python eval, resume drafter)
│   ├── web_app.py         FastAPI server (localhost:8080)
│   ├── generator.py       llama-cpp wrapper with GPU offload and streaming
│   ├── embeddings.py      sentence-transformers embeddings
│   ├── vectorstore.py     FAISS vector store
│   ├── ingest.py          Document loading and chunking (PDF via PyMuPDF)
│   ├── web_search.py      DuckDuckGo search and page scraping
│   └── persistent_memory.py   SQLite backed cross session memory
│
├── skills/                Drop in skills (one folder per skill)
│   ├── summarize_document/
│   ├── extract_action_items/
│   ├── compare_two_documents/
│   └── web_search_and_cite/
│
├── scripts/               Setup and maintenance helpers
│   ├── detect_gpu.py          GPU probe used by setup.bat
│   ├── install_llama_cpp.py   Installs the correct llama-cpp-python wheel
│   ├── install_cuda_dlls.py   Wires CUDA runtime DLLs into llama_cpp/lib
│   └── ...
│
├── data/                  Local data
│   ├── docs/              Documents to index
│   └── storage.db         Persistent memory store
│
└── models/                GGUF model files
```

---

## Privacy

OmniGab is local first by design. The language model, the document index, and your memory all live on your machine. The only time it reaches the internet is when you ask it to search the web, download a model, or search job listings. Nothing else is sent anywhere.

---

## License

Released under the MIT License. See [LICENSE](LICENSE) for details.
