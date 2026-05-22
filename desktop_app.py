"""
RAG Agent - Native Desktop Application
=======================================
A real native Windows desktop app using tkinter.
No browser, no HTML - pure native GUI with a terminal aesthetic.

Starts the FastAPI backend in a background thread and provides
a native chat interface with tabs for all features.
"""

import sys
import os
import json
import time
import threading
import socket
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import urllib.request
import urllib.error

# ============ CONFIG ============
PORT = 8080
API = f"http://127.0.0.1:{PORT}"
BG = "#0a0e14"
BG2 = "#0d1117"
BG3 = "#131921"
FG = "#c5cdd8"
FG_DIM = "#5a6577"
FG_BRIGHT = "#e6edf5"
GREEN = "#39ff14"
AMBER = "#ffb700"
RED = "#ff3b30"
CYAN = "#00d4ff"
BLUE = "#58a6ff"
BORDER = "#1e2a3a"
FONT = ("Consolas", 11)
FONT_SM = ("Consolas", 10)
FONT_XS = ("Consolas", 9)
FONT_LG = ("Consolas", 13)
FONT_TITLE = ("Consolas", 14, "bold")
FONT_ASCII = ("Consolas", 8)


def api_get(path):
    """GET request to the backend API."""
    try:
        req = urllib.request.Request(f"{API}{path}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def api_post(path, data=None):
    """POST request to the backend API."""
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            f"{API}{path}", data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def stream_post(path, data=None):
    """POST request that yields SSE lines."""
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            f"{API}{path}", data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=300)
        buffer = ""
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        pass
        resp.close()
    except Exception as e:
        yield {"type": "error", "message": str(e)}


class RAGApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("RAG Agent v2.0")
        self.geometry("1000x700")
        self.minsize(750, 500)
        self.configure(bg=BG)
        self.session_id = "default"
        self.is_querying = False

        # Window icon (optional, skip if not available)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        # Style
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()

        # Build UI
        self._build_topbar()
        self._build_tabs()
        self._build_panels()

        # Get session
        self.after(500, self._init_session)

    def _configure_styles(self):
        s = self.style
        s.configure(".", background=BG, foreground=FG, font=FONT)
        s.configure("Topbar.TFrame", background=BG2)
        s.configure("Topbar.TLabel", background=BG2, foreground=FG_DIM, font=FONT_SM)
        s.configure("Logo.TLabel", background=BG2, foreground=GREEN, font=FONT_TITLE)
        s.configure("TabBar.TFrame", background=BG)

        # Tab buttons
        s.configure("Tab.TButton", background=BG, foreground=FG_DIM, font=FONT_SM,
                     borderwidth=0, padding=(12, 6))
        s.map("Tab.TButton",
               foreground=[("active", FG_BRIGHT)],
               background=[("active", BG2)])

        s.configure("ActiveTab.TButton", background=BG, foreground=GREEN, font=FONT_SM,
                     borderwidth=0, padding=(12, 6))

        # Panels
        s.configure("Panel.TFrame", background=BG)
        s.configure("Section.TLabel", background=BG, foreground=GREEN, font=("Consolas", 12, "bold"))
        s.configure("Dim.TLabel", background=BG, foreground=FG_DIM, font=FONT_SM)
        s.configure("Bright.TLabel", background=BG, foreground=FG_BRIGHT, font=FONT)
        s.configure("Green.TLabel", background=BG, foreground=GREEN, font=FONT)
        s.configure("Amber.TLabel", background=BG, foreground=AMBER, font=FONT)
        s.configure("Cyan.TLabel", background=BG, foreground=CYAN, font=FONT)
        s.configure("Red.TLabel", background=BG, foreground=RED, font=FONT)

        # Buttons
        s.configure("Action.TButton", background=BG, foreground=GREEN,
                     font=FONT_SM, borderwidth=1, padding=(10, 4))
        s.map("Action.TButton",
               background=[("active", GREEN)],
               foreground=[("active", BG)])

        s.configure("Danger.TButton", background=BG, foreground=RED,
                     font=FONT_SM, borderwidth=1, padding=(10, 4))
        s.map("Danger.TButton",
               background=[("active", RED)],
               foreground=[("active", BG)])

    def _build_topbar(self):
        bar = ttk.Frame(self, style="Topbar.TFrame", height=36)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ttk.Label(bar, text="RAG_AGENT", style="Logo.TLabel").pack(side="left", padx=(12, 4))
        ttk.Label(bar, text="v2.0", style="Topbar.TLabel").pack(side="left")

        sep = ttk.Label(bar, text=" | ", style="Topbar.TLabel")
        sep.pack(side="left", padx=4)

        self.model_label = ttk.Label(bar, text="loading...", style="Topbar.TLabel")
        self.model_label.pack(side="left")

        # Right side status
        self.status_session = ttk.Label(bar, text="session: active", style="Topbar.TLabel")
        self.status_session.pack(side="right", padx=(8, 12))
        self.status_web = ttk.Label(bar, text="web: --", style="Topbar.TLabel")
        self.status_web.pack(side="right", padx=8)
        self.status_index = ttk.Label(bar, text="index: --", style="Topbar.TLabel")
        self.status_index.pack(side="right", padx=8)

    def _build_tabs(self):
        self.tabbar = ttk.Frame(self, style="TabBar.TFrame")
        self.tabbar.pack(fill="x", side="top")

        # Separator line
        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x", side="top")

        self.tabs = {}
        self.current_tab = "chat"
        tab_names = ["chat", "jobs", "docs", "models", "settings", "developer"]

        for name in tab_names:
            style = "ActiveTab.TButton" if name == "chat" else "Tab.TButton"
            btn = ttk.Button(self.tabbar, text=f"> {name.upper()}", style=style,
                             command=lambda n=name: self._switch_tab(n))
            btn.pack(side="left", padx=0)
            self.tabs[name] = btn

    def _switch_tab(self, name):
        self.current_tab = name
        for tname, btn in self.tabs.items():
            btn.configure(style="ActiveTab.TButton" if tname == name else "Tab.TButton")
        for pname, frame in self.panels.items():
            if pname == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        if name == "chat":
            self.chat_input.focus_set()

    def _build_panels(self):
        self.panels = {}
        self._build_chat_panel()
        self._build_jobs_panel()
        self._build_docs_panel()
        self._build_models_panel()
        self._build_settings_panel()
        self._build_dev_panel()

        # Show chat by default
        for name, frame in self.panels.items():
            if name != "chat":
                frame.pack_forget()

    # ========== CHAT PANEL ==========
    def _build_chat_panel(self):
        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        self.panels["chat"] = frame

        # Chat output
        self.chat_output = scrolledtext.ScrolledText(
            frame, wrap="word", bg=BG, fg=FG, font=FONT,
            insertbackground=GREEN, selectbackground=BORDER,
            borderwidth=0, highlightthickness=0, padx=16, pady=12,
            cursor="arrow", state="disabled"
        )
        self.chat_output.pack(fill="both", expand=True)

        # Configure text tags
        self.chat_output.tag_configure("user_prefix", foreground=CYAN, font=("Consolas", 10, "bold"))
        self.chat_output.tag_configure("bot_prefix", foreground=GREEN, font=("Consolas", 10, "bold"))
        self.chat_output.tag_configure("user_text", foreground=FG_BRIGHT, font=FONT)
        self.chat_output.tag_configure("bot_text", foreground=FG, font=FONT)
        self.chat_output.tag_configure("meta", foreground=FG_DIM, font=FONT_XS)
        self.chat_output.tag_configure("meta_good", foreground=GREEN, font=FONT_XS)
        self.chat_output.tag_configure("meta_warn", foreground=AMBER, font=FONT_XS)
        self.chat_output.tag_configure("meta_bad", foreground=RED, font=FONT_XS)
        self.chat_output.tag_configure("error", foreground=RED, font=FONT)
        self.chat_output.tag_configure("welcome", foreground=GREEN, font=FONT_ASCII, justify="center")
        self.chat_output.tag_configure("welcome_sub", foreground=FG_DIM, font=FONT_SM, justify="center")
        self.chat_output.tag_configure("source", foreground=AMBER, font=FONT_XS)

        # Welcome message
        ascii_art = r"""
  ____      _     ____        _                    _
 |  _ \    / \   / ___|      / \     __ _    ___  | |_
 | |_) |  / _ \ | |  _      / _ \   / _` |  / _ \ | __|
 |  _ <  / ___ \| |_| |    / ___ \ | (_| | |  __/ | |_
 |_| \_\/_/   \_\\____|   /_/   \_\ \__, |  \___|  \__|
                                     |___/
"""
        self.chat_output.configure(state="normal")
        self.chat_output.insert("end", ascii_art, "welcome")
        self.chat_output.insert("end", "\n  Local retrieval-augmented generation with verification layer.\n", "welcome_sub")
        self.chat_output.insert("end", "  Ask questions about your ingested documents.\n\n", "welcome_sub")
        self.chat_output.configure(state="disabled")

        # Input area
        input_frame = tk.Frame(frame, bg=BG2, padx=12, pady=10)
        input_frame.pack(fill="x", side="bottom")

        prompt = tk.Label(input_frame, text="$", fg=GREEN, bg=BG2, font=("Consolas", 14, "bold"))
        prompt.pack(side="left", padx=(0, 8))

        self.chat_input = tk.Entry(
            input_frame, bg=BG, fg=FG_BRIGHT, font=FONT,
            insertbackground=GREEN, selectbackground=BORDER,
            borderwidth=1, highlightthickness=1,
            highlightcolor=GREEN, highlightbackground=BORDER,
        )
        self.chat_input.pack(side="left", fill="x", expand=True, ipady=6)
        self.chat_input.bind("<Return>", lambda e: self._send_query())

        self.send_btn = tk.Button(
            input_frame, text="EXEC", bg=BG, fg=GREEN,
            font=("Consolas", 11, "bold"), borderwidth=1,
            highlightbackground=GREEN, activebackground=GREEN,
            activeforeground=BG, cursor="hand2", padx=12,
            command=self._send_query
        )
        self.send_btn.pack(side="right", padx=(8, 0))

    def _append_chat(self, text, tag="bot_text"):
        self.chat_output.configure(state="normal")
        self.chat_output.insert("end", text, tag)
        self.chat_output.see("end")
        self.chat_output.configure(state="disabled")

    def _send_query(self):
        if self.is_querying:
            return
        q = self.chat_input.get().strip()
        if not q:
            return

        self.is_querying = True
        self.chat_input.delete(0, "end")
        self.send_btn.configure(state="disabled")

        # Show user message
        self._append_chat("user@local $ ", "user_prefix")
        self._append_chat(q + "\n\n", "user_text")

        # Show bot prefix
        self._append_chat("rag-agent > ", "bot_prefix")

        # Stream in background
        threading.Thread(target=self._stream_query, args=(q,), daemon=True).start()

    def _stream_query(self, question):
        full_text = ""
        meta = None

        try:
            for chunk in stream_post("/api/query/stream",
                                     {"question": question, "session_id": self.session_id}):
                if chunk.get("type") == "token":
                    token = chunk["text"]
                    full_text += token
                    self.after(0, self._append_chat, token, "bot_text")
                elif chunk.get("type") == "meta":
                    meta = chunk
                elif chunk.get("type") == "error":
                    self.after(0, self._append_chat, f"\n[error] {chunk['message']}", "error")
        except Exception as e:
            self.after(0, self._append_chat, f"\n[error] {e}", "error")

        # Show metadata
        if meta:
            faith = meta.get("faithfulness", 0)
            faith_tag = "meta_good" if faith >= 0.8 else "meta_warn" if faith >= 0.5 else "meta_bad"

            def show_meta():
                self._append_chat(f"\n", "meta")
                self._append_chat(f"  faith: {faith*100:.0f}%", faith_tag)
                self._append_chat(f"  tokens: {meta.get('tokens', 0)}", "meta")
                self._append_chat(f"  speed: {meta.get('tps', 0):.1f} tok/s", "meta")
                self._append_chat(f"  retrieve: {meta.get('retrieve_time', 0)}s", "meta")
                self._append_chat(f"  generate: {meta.get('generate_time', 0)}s", "meta")
                sources = meta.get("sources", [])
                if sources:
                    self._append_chat(f"\n  sources:", "meta")
                    for s in sources:
                        self._append_chat(f"\n    {s['file']} chunk {s['chunk']} ({s['score']*100:.1f}%)", "source")
                self._append_chat("\n\n", "meta")

            self.after(0, show_meta)
        else:
            self.after(0, self._append_chat, "\n\n", "meta")

        self.after(0, self._finish_query)

    def _finish_query(self):
        self.is_querying = False
        self.send_btn.configure(state="normal")
        self.chat_input.focus_set()

    # ========== JOBS PANEL ==========
    def _build_jobs_panel(self):
        frame = ttk.Frame(self, style="Panel.TFrame")
        self.panels["jobs"] = frame

        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        tk.Label(inner, text="# JOB SEARCH AGENT", fg=GREEN, bg=BG, font=("Consolas", 12, "bold"),
                 anchor="w").pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(inner, text="Search Indeed for jobs matching your resume. LLM scores each listing 0-100.",
                 fg=FG_DIM, bg=BG, font=FONT_SM, anchor="w").pack(fill="x", padx=16, pady=4)

        # Resume
        tk.Label(inner, text="RESUME TEXT:", fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w").pack(fill="x", padx=16, pady=(12,2))
        self.resume_text = tk.Text(inner, bg=BG, fg=FG_BRIGHT, font=FONT_SM, height=4,
                                   insertbackground=GREEN, borderwidth=1, highlightbackground=BORDER)
        self.resume_text.pack(fill="x", padx=16, pady=2)

        btn_frame = tk.Frame(inner, bg=BG)
        btn_frame.pack(fill="x", padx=16, pady=4)
        tk.Button(btn_frame, text="UPLOAD RESUME", bg=BG, fg=GREEN, font=FONT_XS,
                  command=self._upload_resume, borderwidth=1, padx=8).pack(side="left")

        # Search inputs
        search_frame = tk.Frame(inner, bg=BG)
        search_frame.pack(fill="x", padx=16, pady=8)

        tk.Label(search_frame, text="Title:", fg=FG_DIM, bg=BG, font=FONT_XS).pack(side="left")
        self.job_title = tk.Entry(search_frame, bg=BG, fg=FG_BRIGHT, font=FONT_SM,
                                  insertbackground=GREEN, width=30, borderwidth=1,
                                  highlightbackground=BORDER)
        self.job_title.pack(side="left", padx=4, ipady=3)

        tk.Label(search_frame, text="Location:", fg=FG_DIM, bg=BG, font=FONT_XS).pack(side="left", padx=(8,0))
        self.job_location = tk.Entry(search_frame, bg=BG, fg=FG_BRIGHT, font=FONT_SM,
                                     insertbackground=GREEN, width=15, borderwidth=1,
                                     highlightbackground=BORDER)
        self.job_location.pack(side="left", padx=4, ipady=3)

        tk.Button(search_frame, text="SEARCH", bg=BG, fg=GREEN, font=("Consolas", 10, "bold"),
                  command=self._search_jobs, borderwidth=1, padx=10).pack(side="left", padx=8)

        self.job_status = tk.Label(inner, text="", fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w")
        self.job_status.pack(fill="x", padx=16, pady=2)

        self.job_results = tk.Text(inner, bg=BG, fg=FG, font=FONT_SM, height=20,
                                    state="disabled", borderwidth=0, highlightthickness=0, wrap="word")
        self.job_results.pack(fill="both", expand=True, padx=16, pady=4)
        self.job_results.tag_configure("title", foreground=GREEN, font=("Consolas", 11, "bold"))
        self.job_results.tag_configure("company", foreground=AMBER, font=FONT_SM)
        self.job_results.tag_configure("score_high", foreground=GREEN, font=FONT_SM)
        self.job_results.tag_configure("score_mid", foreground=AMBER, font=FONT_SM)
        self.job_results.tag_configure("score_low", foreground=RED, font=FONT_SM)
        self.job_results.tag_configure("dim", foreground=FG_DIM, font=FONT_XS)

    def _upload_resume(self):
        text = self.resume_text.get("1.0", "end").strip()
        if not text:
            return
        r = api_post("/api/jobs/upload-resume", {"text": text})
        if r.get("status") == "ok":
            self.job_status.configure(text=f"Resume uploaded ({r['length']} chars)", fg=GREEN)
        else:
            self.job_status.configure(text=r.get("error", "Upload failed"), fg=RED)

    def _search_jobs(self):
        title = self.job_title.get().strip()
        if not title:
            return
        location = self.job_location.get().strip()
        self.job_status.configure(text="Searching...", fg=AMBER)
        threading.Thread(target=self._do_job_search, args=(title, location), daemon=True).start()

    def _do_job_search(self, title, location):
        try:
            r = api_post("/api/jobs/search", {"title": title, "location": location, "num_results": 10})
            if r.get("error"):
                self.after(0, lambda: self.job_status.configure(text=r["error"], fg=RED))
                return

            jobs = r.get("jobs", [])
            self.after(0, lambda: self.job_status.configure(text=f"Found {len(jobs)} jobs", fg=GREEN))

            def show():
                self.job_results.configure(state="normal")
                self.job_results.delete("1.0", "end")
                for j in jobs:
                    score = j.get("match_score", 0)
                    stag = "score_high" if score >= 70 else "score_mid" if score >= 40 else "score_low"
                    self.job_results.insert("end", f"{j.get('title', 'Untitled')}\n", "title")
                    self.job_results.insert("end", f"  {j.get('company', '?')} | {j.get('location', '')}\n", "company")
                    self.job_results.insert("end", f"  Match: {score}/100", stag)
                    if j.get("salary"):
                        self.job_results.insert("end", f"  |  {j['salary']}", "dim")
                    self.job_results.insert("end", "\n", "dim")
                    if j.get("match_reason"):
                        self.job_results.insert("end", f"  {j['match_reason']}\n", "dim")
                    self.job_results.insert("end", "\n", "dim")
                self.job_results.configure(state="disabled")
            self.after(0, show)
        except Exception as e:
            self.after(0, lambda: self.job_status.configure(text=str(e), fg=RED))

    # ========== DOCS PANEL ==========
    def _build_docs_panel(self):
        frame = ttk.Frame(self, style="Panel.TFrame")
        self.panels["docs"] = frame

        top = tk.Frame(frame, bg=BG)
        top.pack(fill="x", padx=16, pady=12)

        tk.Label(top, text="# DOCUMENT INDEX", fg=GREEN, bg=BG, font=("Consolas", 12, "bold")).pack(side="left")

        btn_f = tk.Frame(frame, bg=BG)
        btn_f.pack(fill="x", padx=16)
        tk.Button(btn_f, text="RE-INDEX", bg=BG, fg=GREEN, font=FONT_XS,
                  command=self._reindex, borderwidth=1, padx=8).pack(side="left")
        tk.Button(btn_f, text="REFRESH", bg=BG, fg=FG, font=FONT_XS,
                  command=self._load_docs, borderwidth=1, padx=8).pack(side="left", padx=8)

        self.docs_info = tk.Label(frame, text="", fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w")
        self.docs_info.pack(fill="x", padx=16, pady=(8, 4))

        self.docs_list = tk.Text(frame, bg=BG, fg=FG, font=FONT_SM, state="disabled",
                                  borderwidth=0, highlightthickness=0)
        self.docs_list.pack(fill="both", expand=True, padx=16, pady=4)
        self.docs_list.tag_configure("filename", foreground=AMBER)
        self.docs_list.tag_configure("ext", foreground=CYAN)
        self.docs_list.tag_configure("size", foreground=FG_DIM)

    def _load_docs(self):
        def do():
            r = api_get("/api/docs/list")
            files = r.get("files", [])
            total = r.get("total_size", 0)
            def show():
                self.docs_info.configure(text=f"{len(files)} files, {self._fmt_bytes(total)} total")
                self.docs_list.configure(state="normal")
                self.docs_list.delete("1.0", "end")
                for f in files:
                    self.docs_list.insert("end", f"  {f['extension']:6s}", "ext")
                    self.docs_list.insert("end", f"  {f['name']}", "filename")
                    self.docs_list.insert("end", f"  ({self._fmt_bytes(f['size'])})\n", "size")
                self.docs_list.configure(state="disabled")
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _reindex(self):
        self.docs_info.configure(text="Re-indexing...", fg=AMBER)
        def do():
            r = api_post("/api/ingest")
            if r.get("status") == "ok":
                self.after(0, lambda: self.docs_info.configure(
                    text=f"Done! {r.get('vectors', 0)} vectors in index.", fg=GREEN))
                self.after(500, self._load_status)
                self.after(500, self._load_docs)
            else:
                self.after(0, lambda: self.docs_info.configure(
                    text=r.get("message", "Error"), fg=RED))
        threading.Thread(target=do, daemon=True).start()

    # ========== MODELS PANEL ==========
    def _build_models_panel(self):
        frame = ttk.Frame(self, style="Panel.TFrame")
        self.panels["models"] = frame

        tk.Label(frame, text="# MODEL MANAGER", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(frame, text="GGUF models for local inference. Download via download_model.bat.",
                 fg=FG_DIM, bg=BG, font=FONT_SM, anchor="w").pack(fill="x", padx=16, pady=(0, 8))

        self.models_list = tk.Text(frame, bg=BG, fg=FG, font=FONT_SM, state="disabled",
                                    borderwidth=0, highlightthickness=0, wrap="word")
        self.models_list.pack(fill="both", expand=True, padx=16, pady=4)
        self.models_list.tag_configure("name", foreground=GREEN, font=("Consolas", 11, "bold"))
        self.models_list.tag_configure("downloaded", foreground=GREEN)
        self.models_list.tag_configure("missing", foreground=RED)
        self.models_list.tag_configure("dim", foreground=FG_DIM, font=FONT_XS)

    def _load_models(self):
        def do():
            models = api_get("/api/models")
            if isinstance(models, dict) and models.get("error"):
                return
            def show():
                self.models_list.configure(state="normal")
                self.models_list.delete("1.0", "end")
                for m in models:
                    self.models_list.insert("end", f"  {m['name']}\n", "name")
                    self.models_list.insert("end", f"    file: {m['filename']}\n", "dim")
                    self.models_list.insert("end", f"    size: {m['size']}  |  RAM: {m['ram']}\n", "dim")
                    status = "downloaded" if m["downloaded"] else "not downloaded"
                    tag = "downloaded" if m["downloaded"] else "missing"
                    self.models_list.insert("end", f"    status: {status}\n\n", tag)
                self.models_list.configure(state="disabled")
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    # ========== SETTINGS PANEL ==========
    def _build_settings_panel(self):
        frame = ttk.Frame(self, style="Panel.TFrame")
        self.panels["settings"] = frame

        tk.Label(frame, text="# USER MEMORY", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(frame, text="Persistent preferences injected into every query context.",
                 fg=FG_DIM, bg=BG, font=FONT_SM, anchor="w").pack(fill="x", padx=16, pady=(0, 8))

        # Set key/value
        kv_frame = tk.Frame(frame, bg=BG)
        kv_frame.pack(fill="x", padx=16, pady=4)
        tk.Label(kv_frame, text="Key:", fg=FG_DIM, bg=BG, font=FONT_XS).pack(side="left")
        self.mem_key = tk.Entry(kv_frame, bg=BG, fg=FG_BRIGHT, font=FONT_SM, width=15,
                                insertbackground=GREEN, borderwidth=1, highlightbackground=BORDER)
        self.mem_key.pack(side="left", padx=4, ipady=3)
        tk.Label(kv_frame, text="Value:", fg=FG_DIM, bg=BG, font=FONT_XS).pack(side="left", padx=(8,0))
        self.mem_val = tk.Entry(kv_frame, bg=BG, fg=FG_BRIGHT, font=FONT_SM, width=25,
                                insertbackground=GREEN, borderwidth=1, highlightbackground=BORDER)
        self.mem_val.pack(side="left", padx=4, ipady=3)
        tk.Button(kv_frame, text="SET", bg=BG, fg=GREEN, font=FONT_XS,
                  command=self._set_memory, borderwidth=1, padx=8).pack(side="left", padx=4)

        # Instruction
        inst_frame = tk.Frame(frame, bg=BG)
        inst_frame.pack(fill="x", padx=16, pady=4)
        tk.Label(inst_frame, text="Instruction:", fg=FG_DIM, bg=BG, font=FONT_XS).pack(side="left")
        self.mem_inst = tk.Entry(inst_frame, bg=BG, fg=FG_BRIGHT, font=FONT_SM,
                                 insertbackground=GREEN, borderwidth=1, highlightbackground=BORDER)
        self.mem_inst.pack(side="left", fill="x", expand=True, padx=4, ipady=3)
        tk.Button(inst_frame, text="REMEMBER", bg=BG, fg=GREEN, font=FONT_XS,
                  command=self._add_instruction, borderwidth=1, padx=8).pack(side="left", padx=4)

        # Memory display
        tk.Label(frame, text="# CURRENT MEMORY", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 4))
        self.mem_display = tk.Text(frame, bg=BG, fg=FG, font=FONT_SM, height=10,
                                    state="disabled", borderwidth=0, highlightthickness=0)
        self.mem_display.pack(fill="both", expand=True, padx=16, pady=4)
        self.mem_display.tag_configure("key", foreground=CYAN)
        self.mem_display.tag_configure("val", foreground=FG_BRIGHT)

        btn_f = tk.Frame(frame, bg=BG)
        btn_f.pack(fill="x", padx=16, pady=8)
        tk.Button(btn_f, text="REFRESH", bg=BG, fg=FG, font=FONT_XS,
                  command=self._load_memory, borderwidth=1, padx=8).pack(side="left")
        tk.Button(btn_f, text="CLEAR MEMORY", bg=BG, fg=RED, font=FONT_XS,
                  command=self._clear_memory, borderwidth=1, padx=8).pack(side="left", padx=8)
        tk.Button(btn_f, text="CLEAR HISTORY", bg=BG, fg=RED, font=FONT_XS,
                  command=self._clear_history, borderwidth=1, padx=8).pack(side="left")

    def _set_memory(self):
        k, v = self.mem_key.get().strip(), self.mem_val.get().strip()
        if k and v:
            api_post("/api/memory", {"action": "set", "key": k, "value": v})
            self.mem_key.delete(0, "end")
            self.mem_val.delete(0, "end")
            self._load_memory()

    def _add_instruction(self):
        inst = self.mem_inst.get().strip()
        if inst:
            api_post("/api/memory", {"action": "remember", "instruction": inst})
            self.mem_inst.delete(0, "end")
            self._load_memory()

    def _load_memory(self):
        def do():
            r = api_get("/api/memory")
            def show():
                self.mem_display.configure(state="normal")
                self.mem_display.delete("1.0", "end")
                if r.get("location"):
                    self.mem_display.insert("end", "  location: ", "key")
                    self.mem_display.insert("end", f"{r['location']}\n", "val")
                self.mem_display.insert("end", "  units: ", "key")
                self.mem_display.insert("end", f"{r.get('units', 'imperial')}\n", "val")
                facts = r.get("learned_facts", {})
                if facts:
                    self.mem_display.insert("end", "\n  learned facts:\n", "key")
                    for k, v in facts.items():
                        self.mem_display.insert("end", f"    {k}: {v}\n", "val")
                instr = r.get("custom_instructions", [])
                if instr:
                    self.mem_display.insert("end", "\n  instructions:\n", "key")
                    for i in instr:
                        self.mem_display.insert("end", f"    {i}\n", "val")
                self.mem_display.configure(state="disabled")
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _clear_memory(self):
        if messagebox.askyesno("Clear Memory", "Clear all user memory?"):
            api_post("/api/memory", {"action": "clear"})
            self._load_memory()

    def _clear_history(self):
        api_post("/api/clear_history", {"session_id": self.session_id})

    # ========== DEVELOPER PANEL ==========
    def _build_dev_panel(self):
        frame = ttk.Frame(self, style="Panel.TFrame")
        self.panels["developer"] = frame

        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        tk.Label(inner, text="# SYSTEM INFO", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 8))

        self.sysinfo_text = tk.Text(inner, bg=BG, fg=FG, font=FONT_SM, height=18,
                                     state="disabled", borderwidth=0, highlightthickness=0)
        self.sysinfo_text.pack(fill="x", padx=16)
        self.sysinfo_text.tag_configure("key", foreground=FG_DIM)
        self.sysinfo_text.tag_configure("val", foreground=FG_BRIGHT)
        self.sysinfo_text.tag_configure("green", foreground=GREEN)
        self.sysinfo_text.tag_configure("amber", foreground=AMBER)
        self.sysinfo_text.tag_configure("cyan", foreground=CYAN)

        # Benchmark
        tk.Label(inner, text="# BENCHMARK", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 8))

        bench_f = tk.Frame(inner, bg=BG)
        bench_f.pack(fill="x", padx=16)
        tk.Button(bench_f, text="RUN BENCHMARK", bg=BG, fg=GREEN, font=("Consolas", 10, "bold"),
                  command=self._run_benchmark, borderwidth=1, padx=10).pack(side="left")

        self.bench_result = tk.Text(inner, bg=BG, fg=FG, font=FONT_SM, height=6,
                                     state="disabled", borderwidth=0, highlightthickness=0)
        self.bench_result.pack(fill="x", padx=16, pady=8)
        self.bench_result.tag_configure("key", foreground=FG_DIM)
        self.bench_result.tag_configure("val", foreground=FG_BRIGHT)
        self.bench_result.tag_configure("green", foreground=GREEN)

    def _load_sysinfo(self):
        def do():
            r = api_get("/api/system")
            if r.get("error"):
                return
            def show():
                t = self.sysinfo_text
                t.configure(state="normal")
                t.delete("1.0", "end")
                pairs = [
                    ("platform", r.get("platform", "?"), "val"),
                    ("python", r.get("python", "?"), "val"),
                    ("cpu", r.get("cpu", "?"), "val"),
                    ("threads", str(r.get("threads", "?")), "cyan"),
                    ("context window", str(r.get("context_window", "?")), "val"),
                    ("max tokens", str(r.get("max_tokens", "?")), "val"),
                    ("temperature", str(r.get("temperature", "?")), "val"),
                    ("active model", r.get("current_model", "?"), "green"),
                    ("use GGUF", str(r.get("use_gguf", "?")), "green"),
                    ("embedding", r.get("embedding_model", "?"), "val"),
                    ("index size", f"{r.get('index_size', 0)} vectors", "cyan"),
                    ("web search", str(r.get("web_search", "?")), "green"),
                    ("faithfulness", str(r.get("faithfulness_threshold", "?")), "amber"),
                ]
                for label, val, tag in pairs:
                    t.insert("end", f"  {label:>18s} : ", "key")
                    t.insert("end", f"{val}\n", tag)
                t.configure(state="disabled")
                self.model_label.configure(text=r.get("current_model", "?"))
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _run_benchmark(self):
        self.bench_result.configure(state="normal")
        self.bench_result.delete("1.0", "end")
        self.bench_result.insert("end", "  Running benchmark...", "key")
        self.bench_result.configure(state="disabled")

        def do():
            r = api_get("/api/benchmark")
            def show():
                t = self.bench_result
                t.configure(state="normal")
                t.delete("1.0", "end")
                if r.get("error"):
                    t.insert("end", f"  [error] {r['error']}", "val")
                else:
                    t.insert("end", f"  model   : ", "key"); t.insert("end", f"{r.get('model','?')}\n", "green")
                    t.insert("end", f"  answer  : ", "key"); t.insert("end", f"{r.get('answer','?')}\n", "val")
                    t.insert("end", f"  tokens  : ", "key"); t.insert("end", f"{r.get('tokens',0)}\n", "val")
                    t.insert("end", f"  speed   : ", "key"); t.insert("end", f"{r.get('tps',0):.1f} tok/s\n", "green")
                    t.insert("end", f"  elapsed : ", "key"); t.insert("end", f"{r.get('elapsed',0)}s\n", "val")
                t.configure(state="disabled")
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    # ========== UTILITY ==========
    def _fmt_bytes(self, n):
        for unit in ["B", "KB", "MB", "GB"]:
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def _init_session(self):
        def do():
            r = api_get("/api/session")
            self.session_id = r.get("session_id", "default")
            self.after(0, self._load_status)
            self.after(0, self._load_sysinfo)
            self.after(0, self._load_docs)
            self.after(0, self._load_models)
            self.after(0, self._load_memory)
        threading.Thread(target=do, daemon=True).start()

    def _load_status(self):
        def do():
            r = api_get("/api/status")
            def show():
                idx = r.get("index_size", 0)
                web = r.get("web_search", False)
                self.status_index.configure(text=f"index: {idx} vectors",
                                             foreground=GREEN if idx > 0 else RED)
                self.status_web.configure(text=f"web: {'on' if web else 'off'}",
                                           foreground=GREEN if web else RED)
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()


def main():
    port = PORT

    # Check if server is already running
    already_running = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            already_running = True
    except (ConnectionRefusedError, OSError):
        pass

    if not already_running:
        print()
        print("  Starting RAG Agent server...")
        print("  (Loading model, this may take a minute)")
        print()

        SRC_DIR_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
        sys.path.insert(0, SRC_DIR_path)
        os.chdir(SRC_DIR_path)

        import uvicorn
        from web_app import app

        def run_server():
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Wait for server
        start = time.time()
        while time.time() - start < 120:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.5)
        else:
            print("  ERROR: Server failed to start.")
            input("  Press Enter to exit...")
            sys.exit(1)

        print("  Server ready!")

    app_window = RAGApp()
    app_window.mainloop()


if __name__ == "__main__":
    main()
