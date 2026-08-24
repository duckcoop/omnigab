<p align="center">
  <h1 align="center">OmniGab</h1>
  <p align="center">
    <strong>A private AI assistant that runs entirely on your own computer.</strong><br>
    No cloud. No API keys. No subscriptions. Your files never leave your machine.
  </p>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white">
  <img alt="MIT License" src="https://img.shields.io/badge/License-MIT-green">
  <img alt="Windows 10/11" src="https://img.shields.io/badge/OS-Windows%2010%2F11-0078D6?logo=windows&logoColor=white">
  <img alt="CUDA 12.x" src="https://img.shields.io/badge/GPU-CUDA%2012.x-76B900?logo=nvidia&logoColor=white">
</p>

---

## Why this exists

Most AI assistants require you to upload your data to a company's servers. For a lot of what people actually want help with, that is a bad trade. Your lease, your medical bills, your resume, your bank statements: these are exactly the documents where an assistant would be most useful, and exactly the ones you should be most reluctant to hand over.

OmniGab runs the language model on your own GPU. With no server in the loop, privacy stops being a promise in a policy document and becomes a property of how the software is built. Unplug your network and it still works.

That constraint shapes everything else here.

---

## What it does

**Chat with a real model, offline.** A Qwen3.5 model runs locally through llama.cpp, on your GPU if you have an NVIDIA card and on your CPU if you do not.

**Answer questions from your own documents.** Drop PDFs, Markdown, text, config files, or logs into the Docs tab. They are chunked, embedded, and indexed into a local vector store. Ask a question and it retrieves the relevant passages and answers from them, so you get grounded answers with sources instead of guesses.

**Remember things between sessions.** Tell it a fact once and it stores it in a local SQLite file. Still there next week.

**Search for jobs across several boards.** Federal roles come from the official USAJOBS API, ranked against your resume and certifications. Private-sector roles come from Amazon Jobs, RemoteOK, and any company using Greenhouse or Lever. See [Job search](#job-search) for how boards that prohibit automation are handled.

**Draft a federal resume.** Using your existing resume plus what it remembers about you, it drafts a tailored federal-style resume for a specific posting.

**Look up vulnerabilities.** Queries the NIST National Vulnerability Database 2.0 API and the CISA Known Exploited Vulnerabilities catalog for real CVE data: full records with CVSS severity, KEV membership, and the remediation due dates CISA sets for federal agencies. The KEV catalog is cached locally for 24 hours rather than refetched per query. NVD is rate limited to 5 requests per 30 seconds without a key and returns 503s under load, so the tool is written to always return a structured result with a readable error instead of throwing.

**Do exact math.** Rather than guessing at arithmetic, it runs code in a sandboxed Python tool.

**Run drop-in skills.** Small folders that extend it. Ships with document summarizing, action item extraction, document comparison, and cited web search.

---

## How it is built

The interesting problem in this project is not getting a model to talk. It
is knowing when to believe it, and noticing quickly when something breaks.

**Verify, do not trust.** The extraction path never shows a value the model
asserted. It shows values that code confirmed against the source document
by exact string match, and discards the rest. Three verdicts, not two:
confirmed, needs a human look, rejected. Collapsing that to a boolean would
force every uncertain case into either lying to the user or hiding a real
obligation from them.

**One command tells you if it is broken.** `verify.bat` runs flake8 and the
full test suite and exits non-zero on either. 67 tests, and the default run
needs no GPU, no model file, and no network, because that is what a
stranger cloning the repo actually has.

**Measure instead of inheriting.** Numbers in this codebase are measured on
the hardware and cited where they are used, not carried forward from
whatever was true once:

- KV cache cost is 16.2 MB per 1024 tokens on the 9B and 16.6 on the 4B,
  taken from the VRAM slope between two context sizes on an RTX 4070 SUPER.
  The previous figure was 0.09 GB, inherited from a different model, with a
  comment claiming it scaled with model size. Both halves were wrong: it is
  5.6x cheaper and identical across both models, because they share a KV
  geometry.
- The context ceiling is 262144, read out of the GGUF metadata, not the
  32768 that had been assumed.
- Model file sizes are the bytes on disk. Both quants came in larger than
  their size class implied, and the autotuner subtracts that figure from
  VRAM to size the cache, so a low guess is exactly what pushes the cache
  into system RAM and collapses throughput.

**Hardware aware at runtime.** VRAM is detected through `nvidia-smi` and RAM
through `psutil`, the model is auto-selected against both, and context and
batch size are tuned so weights plus cache stay inside VRAM. GPU offload is
verified after load rather than assumed, because a CPU-only wheel accepts
the offload flag silently and then runs 10x slower with no error.

**Findings get written down, with reproduction.** `docs/TODOS.md` is a log
of problems found and deliberately not fixed yet, each with what it is, why
it matters, how it was found, and what unblocks it. Examples currently
open: 19 `print` sites that raise `UnicodeEncodeError` on a cp1252 console
and will break a Windows CI runner, and three handlers that call
`NameError` at the exact moment they are supposed to display an error,
because a lambda reads an `except ... as e` variable after Python has
unbound it.

**Documented constraints.** `AGENTS.md` records the invariants that must not
be broken and why, so the reasoning survives past the commit that created
it. `docs/PLAN.md` sequences the work and commits to a kill criterion for
the extraction feature before any results exist, so the threshold cannot be
moved after seeing them.

---

## Install

You need **Python 3.10, 3.11, or 3.12** and **Windows 10 or 11**. An NVIDIA GPU is optional but makes a large difference.

```bash
git clone https://github.com/duckcoop/omnigab.git
cd omnigab
setup.bat
```

`setup.bat` finds your Python, creates a virtual environment, detects your GPU, installs `llama-cpp-python` with the matching CUDA wheel, wires in the CUDA runtime DLLs, installs dependencies, downloads the default model (~3 GB), builds the document index, and launches the app.

The first run downloads a few GB. Later runs start in seconds.

After setup, **double click `omnigab.bat`.** That is the only thing you need to run.

---

## Models

Pick one in the Models tab. Bigger models answer better and use tools far more reliably, but need more memory and run slower.

| Model | Disk | Suggested RAM | Notes |
|---|---|---|---|
| Qwen 3.5 4B | ~3.0 GB | ~6 GB | Downloaded by default. Runs on a laptop without a GPU. |
| Qwen 3.5 9B | ~6.2 GB | ~12 GB | Best quality. Auto-selected when you have 8 GB of VRAM or more. |

Both sizes are measured, not estimated: those are the actual file sizes on disk.

Both read `tools: ready` in the topbar, and both earned it the same way: run through the real agent loop, each picked the right tool and filled its arguments correctly on 4 of 4 simple calls and 5 of 6 large-schema calls, with no tool called on a plain greeting. They scored identically, so the 4B is not labelled weaker. Sizes below 4B are not offered, because a model that cannot call a tool reliably cannot do most of what this app is for.

### Adding any other model

Those two are the curated defaults, not the limit. Anything on Hugging Face in GGUF format works, including other families: the bundled llama.cpp understands Gemma, Llama, Mistral, GLM, Phi, Granite, OLMo, SmolLM and gpt-oss as well as Qwen.

1. Browse [huggingface.co GGUF models](https://huggingface.co/models?library=gguf&sort=trending). Repos from `bartowski`, `unsloth`, and `lmstudio-community` are reliable requants of official weights.
2. Copy the address from your browser. The plain URL, a `/tree/main` link, or a bare `org/repo` id all work.
3. Paste it into **Models -> Add from Hugging Face** and press BROWSE.
4. Pick a quant. `Q4_K_M` is the usual balance of size against quality; the list shows every file with its real size so you can match one to your card.

The app then reads the model's own metadata and tells you whether it fits: weights come from the file size, and cache cost from the model's attention geometry, so the HARDWARE panel gives a correct "fits in VRAM, up to N tokens" verdict for a model it has never seen before.

Two limits worth knowing. Split quants (`-00001-of-00003.gguf`) need every part and are listed but not downloadable. And a model larger than your VRAM will load, but the part that does not fit runs on the CPU, which is dramatically slower rather than slightly.

### Context window

Settings → Advanced controls how much the model can hold at once. Auto sizes it to fit your GPU, and the panel shows both what is currently loaded and what your card could handle.

The KV cache is quantized to q8_0, which roughly halves its memory cost. On a 12 GB card the 9B leaves plenty of room at 8192 tokens and has headroom above that; pushing the window until weights plus cache exceed VRAM spills into system RAM and slows generation to a crawl.

---

## Job search

Job boards differ in how they allow access, and OmniGab is explicit about which is which rather than pretending they are all the same.

| Access | Boards | How it works |
|---|---|---|
| **Public API** | USAJOBS, Amazon Jobs, RemoteOK, Greenhouse, Lever | Documented endpoints. Fast, stable, allowed. Results appear in the app. |
| **Browser handoff** | LinkedIn, Handshake, Indeed | The search URL is built for you and opened in your own browser. |

The handoff design is deliberate, not a shortfall. LinkedIn's terms prohibit automated access and they enforce it with account restrictions; Handshake needs a school single sign-on session. Scraping either risks your account to obtain results you can get instantly in a browser you are already signed into. OmniGab saves you the typing and stays out of the way.

Every USAJOBS link is verified with an HTTP request before you see it, and dead or closed postings are discarded. Result lists are rendered from that verified data by code, never retyped by the model, so a link cannot be invented.

---

## Document extraction (in progress)

OmniGab is growing a life-admin capability: read a bill or a lease, extract the deadline and the amount, and remind you before it matters.

The hard part is not extraction, it is trust. A tool that occasionally invents a due date is worse than no tool, because you stop checking it. So every extracted value passes a **mechanical verification gate** before you ever see it:

1. The model must return the exact sentence it took the value from. Code searches the document for that sentence. No match means the extraction is discarded entirely.
2. The value must appear inside its own quote. If not, the item is flagged for you to check rather than shown as confirmed.
3. The value must have the right shape for an amount or a date.

String matching, not similarity scoring, because `$142.87` and `$1,428.70` are highly similar and one of them is wrong.

See [`docs/EXTRACTION.md`](docs/EXTRACTION.md) for the design and the 20 adversarial tests.

---

## Privacy, concretely

| What | Where it lives |
|---|---|
| The language model | `models/`, on your disk, running on your GPU |
| Your documents | `data/docs/`, indexed into a local vector store |
| What it remembers | `data/storage.db`, a local SQLite file |
| Chat history | Local, in memory and on disk |

The only time OmniGab touches the network is when you ask it to: a web search, a job board query, a CVE lookup, or downloading a model. Turn web search off in Settings and it makes no network calls at all.

Nothing is uploaded. There is no account, no telemetry, and no server to have a breach.

---

## Repository layout

```
omnigab/
├── setup.bat              One click installer, run this first
├── omnigab.bat            Opens the app, run this every time after
├── desktop_app.py         The desktop app (tkinter)
├── requirements.txt
│
├── src/
│   ├── core/              Agent loop, model manager, result rendering
│   ├── tools/             Document search, web, memory, jobs, CVE, Python
│   ├── extraction/        Bill extraction schema and verification gate
│   ├── jobs/              Job board sources and multi-board search
│   ├── desktop_ui.py      Design tokens and shared desktop components
│   ├── web_app.py         Local FastAPI backend
│   ├── generator.py       llama.cpp wrapper with GPU offload
│   ├── embeddings.py      sentence-transformers embeddings
│   ├── vectorstore.py     FAISS index
│   └── persistent_memory.py   SQLite memory
│
├── skills/                Drop-in skills, one folder each
├── docs/                  Setup guide, extraction design, deferred work
├── tests/                 Test suites, no GPU required
└── data/                  Your documents and local state (gitignored)
```

---

## Tests

```bash
venv\Scripts\python.exe -m pytest
venv\Scripts\python.exe -m pytest -m integration
```

The default run needs no GPU, no downloaded model, and no network. The
second one opts into the checks that query USAJOBS and NIST NVD live.

---

## Requirements

| Requirement | Details |
|---|---|
| Python 3.10 to 3.12 | These have prebuilt `llama-cpp-python` CUDA wheels. Newer versions run but may lack a GPU wheel. Check "Add python.exe to PATH" when installing. |
| Windows 10 or 11 | The setup and launch scripts are batch files. |
| Git | To clone the repository. |
| RAM | ~6 GB for the 4B, ~12 GB for the 9B. |
| NVIDIA GPU, CUDA 12.x | Optional. You do not install the CUDA Toolkit yourself; setup pulls the runtime DLLs from pip. CPU-only works, just slower. |
| Disk | ~5 GB with the 4B, ~9 GB with the 9B. |

---

## License

MIT. See [LICENSE](LICENSE).
