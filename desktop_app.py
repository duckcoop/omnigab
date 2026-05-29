"""
omnigab - Native Desktop Application
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
API_TOKEN = ""
BG = "#1f1f1c"
BG2 = "#262522"
BG3 = "#30302b"
FG = "#d8d4c9"
FG_DIM = "#8f8a80"
FG_BRIGHT = "#f4f0e6"
# --- Unified green palette (replaces the old orange brand color) ---
# All accents, borders, button highlights, status pills, and active-tab
# indicators read from these. The naming is preserved (GREEN/AMBER) so
# existing code keeps working — only the hex values have shifted hue.
GREEN = "#7ec890"          # primary accent  (was #d97757 orange)
GREEN_DEEP = "#4ea36b"     # hover / active state for primary buttons
GREEN_DIM = "#3a5a48"      # subtle borders and dividers tinted green
AMBER = "#a8c879"          # secondary / warning (was orange-yellow)
RED = "#e06c62"
CYAN = "#9ab7a5"           # already greenish — kept
BLUE = "#a9b7d0"
BORDER = "#324035"         # slightly green-tinted border (was #3a3833)

# User-message bubble — distinct dark-green block so the user's turn is
# visually separated from the assistant's turn.
USER_BUBBLE_BG = "#1c3a2e"
USER_BUBBLE_BG_DARK = "#162d24"
USER_BUBBLE_FG = "#e6f0e2"
FONT = ("Segoe UI", 11)
FONT_SM = ("Segoe UI", 10)
FONT_XS = ("Segoe UI", 9)
FONT_LG = ("Segoe UI", 13)
FONT_TITLE = ("Georgia", 15, "bold")
FONT_ASCII = ("Georgia", 28)


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
        headers = {"Content-Type": "application/json"}
        if API_TOKEN:
            headers["Authorization"] = "Bearer " + API_TOKEN
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            f"{API}{path}", data=body,
            headers=headers,
            method="POST"
        )
        # 240s budget: USAJOBS deep-fetch can take ~30s (parallel) + model
        # generation on the 14B model adds another 30-60s of streaming.
        with urllib.request.urlopen(req, timeout=240) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def stream_post(path, data=None):
    """POST request that yields SSE lines."""
    try:
        headers = {"Content-Type": "application/json"}
        if API_TOKEN:
            headers["Authorization"] = "Bearer " + API_TOKEN
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            f"{API}{path}", data=body,
            headers=headers,
            method="POST"
        )
        # 10-minute ceiling. The actual budget that matters is the per-chunk
        # read below: SSE keeps the socket alive as long as the server sends
        # at least one byte before this elapses. The Agent emits tool_start /
        # tool_end / token events frequently enough that 600s is generous.
        resp = urllib.request.urlopen(req, timeout=600)
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

        self.title("omnigab")
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

        ttk.Label(bar, text="omnigab", style="Logo.TLabel").pack(side="left", padx=(12, 4))

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
        self.status_resume = ttk.Label(bar, text="resume: none", style="Topbar.TLabel")
        self.status_resume.pack(side="right", padx=8)
        # Tool-calling capability badge. Red on 1.5B (can't tool-call),
        # amber on 3B (marginal), green on 7B/14B.
        self.status_tools = ttk.Label(bar, text="tools: --", style="Topbar.TLabel")
        self.status_tools.pack(side="right", padx=8)

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
            btn = ttk.Button(self.tabbar, text=name.title(), style=style,
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
        self.chat_output.tag_configure(
            "user_prefix",
            foreground=USER_BUBBLE_FG, background=USER_BUBBLE_BG_DARK,
            font=("Consolas", 10, "bold"),
            lmargin1=10, lmargin2=10, rmargin=10, spacing1=6,
        )
        self.chat_output.tag_configure("bot_prefix", foreground=GREEN, font=("Consolas", 10, "bold"))
        self.chat_output.tag_configure(
            "user_text",
            foreground=USER_BUBBLE_FG, background=USER_BUBBLE_BG, font=FONT,
            lmargin1=10, lmargin2=10, rmargin=10, spacing3=6,
        )
        self.chat_output.tag_configure("bot_text", foreground=FG, font=FONT)
        self.chat_output.tag_configure("meta", foreground=FG_DIM, font=FONT_XS)
        self.chat_output.tag_configure("meta_good", foreground=GREEN, font=FONT_XS)
        self.chat_output.tag_configure("meta_warn", foreground=AMBER, font=FONT_XS)
        self.chat_output.tag_configure("meta_bad", foreground=RED, font=FONT_XS)
        self.chat_output.tag_configure("error", foreground=RED, font=FONT)
        self.chat_output.tag_configure("welcome", foreground=FG_BRIGHT, font=FONT_ASCII, justify="center")
        self.chat_output.tag_configure("welcome_sub", foreground=FG_DIM, font=FONT_SM, justify="center")
        self.chat_output.tag_configure("source", foreground=AMBER, font=FONT_XS)
        self.chat_output.tag_configure("tool_call", foreground=CYAN, font=("Consolas", 10, "italic"))
        # `<thinking>` blocks: dim italic so the reasoning is visible but
        # clearly separated from the final answer.
        self.chat_output.tag_configure(
            "thinking", foreground=FG_DIM, font=("Segoe UI", 10, "italic"),
            lmargin1=12, lmargin2=12, rmargin=12, spacing1=4, spacing3=4,
        )
        self.chat_output.tag_configure("tool_result", foreground=AMBER, font=FONT_XS)
        self.chat_output.tag_configure("bold", foreground=FG_BRIGHT, font=("Segoe UI", 11, "bold"))
        self.chat_output.tag_configure("link", foreground=BLUE, font=("Segoe UI", 11, "underline"))
        self.chat_output.tag_configure("salary", foreground=GREEN, font=("Segoe UI", 10))
        self.chat_output.tag_bind("link", "<Button-1>", self._on_link_click)
        self.chat_output.tag_bind("link", "<Enter>",
                                  lambda e: self.chat_output.configure(cursor="hand2"))
        self.chat_output.tag_bind("link", "<Leave>",
                                  lambda e: self.chat_output.configure(cursor="arrow"))
        # Map text indices -> URLs for click handling.
        self._link_targets: dict[str, str] = {}

        # Welcome message
        self.chat_output.configure(state="normal")
        self.chat_output.insert("end", "\n\nGood evening\n", "welcome")
        self.chat_output.insert(
            "end",
            "\nAsk about your documents, use skills, or start with a normal conversation.\n\n",
            "welcome_sub",
        )
        self.chat_output.configure(state="disabled")

        # Input area
        input_frame = tk.Frame(frame, bg=BG2, padx=12, pady=10)
        input_frame.pack(fill="x", side="bottom")

        # "+" attach button: opens a file picker, uploads the file to
        # data/docs/ via /api/docs/upload, then inserts a "[Attached: name]"
        # hint into the chat input so the agent knows to look it up.
        self.attach_btn = tk.Button(
            input_frame, text="+", fg=GREEN, bg=BG2,
            activebackground=BG3, activeforeground=FG_BRIGHT,
            font=("Segoe UI", 18, "bold"), borderwidth=0,
            cursor="hand2", padx=8, pady=0,
            command=self._attach_file,
        )
        self.attach_btn.pack(side="left", padx=(0, 8))

        self.chat_input = tk.Entry(
            input_frame, bg=BG, fg=FG_BRIGHT, font=FONT,
            insertbackground=GREEN, selectbackground=BORDER,
            borderwidth=1, highlightthickness=1,
            highlightcolor=GREEN, highlightbackground=BORDER,
        )
        self.chat_input.pack(side="left", fill="x", expand=True, ipady=6)
        self.chat_input.bind("<Return>", lambda e: self._send_query())

        self.send_btn = tk.Button(
            input_frame, text="Send", bg=BG3, fg=FG_BRIGHT,
            font=("Segoe UI", 10, "bold"), borderwidth=1,
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

    # ----- markdown rendering for the streamed bot response -----
    # The model emits markdown: **bold** and [text](url). Tokens arrive one at
    # a time, so we buffer the trailing partial token until we know whether
    # it's part of a markdown construct, then flush in chunks with tags.

    _MD_RE = __import__("re").compile(
        r"\*\*(.+?)\*\*"           # bold
        r"|\[([^\]]+)\]\(([^)]+)\)"  # [text](url) link
    )

    def _reset_md_buffer(self):
        self._md_buffer = ""
        self._in_thinking = False

    def _flush_md_safe_prefix(self):
        """Render everything in the buffer up to a point where a markdown
        construct or `<thinking>` tag could not still be opening. Hold back
        any trailing chars that could be the START of one of these:
          * `**bold**`         (signaled by `*`)
          * `[text](url)`      (signaled by `[`)
          * `<thinking>` /     (signaled by `<` IF the tail could still
            `</thinking>`       complete one of those literal tags)
        """
        buf = self._md_buffer
        if not buf:
            return

        # Earliest position where an unfinished construct could begin.
        last_safe = len(buf)

        for needle in ("*", "["):
            i = buf.find(needle)
            if i != -1 and i < last_safe:
                last_safe = i

        # `<` is trickier — most `<` characters in normal text aren't tag
        # openers (e.g. "a<b" arithmetic). Only hold back if the tail
        # starting at the `<` could plausibly still complete `<thinking>`
        # or `</thinking>`. Scan every `<` in the buffer and find the
        # earliest one whose suffix is a valid prefix of either tag.
        lt = buf.find("<")
        while lt != -1:
            tail = buf[lt:]
            if any(tag.startswith(tail) or tail.startswith(tag)
                   for tag in ("<thinking>", "</thinking>")):
                if lt < last_safe:
                    last_safe = lt
                break
            lt = buf.find("<", lt + 1)

        # Safety valve: if we've been holding the entire buffer for too
        # long, give up and flush as plain so the UI doesn't stall.
        if last_safe == 0 and len(buf) > 1000:
            self._render_plain(buf)
            self._md_buffer = ""
            return
        if last_safe <= 0:
            return
        head = buf[:last_safe]
        self._render_plain(head)
        self._md_buffer = buf[last_safe:]

    def _stream_token_md(self, token: str):
        """Called for every streamed token. Appends to buffer, then walks
        through three layers:
          1. `<thinking>` / `</thinking>` tags toggle the dimmed-italic mode.
          2. Complete markdown constructs (**bold**, [text](url)) are
             rendered inline as they appear.
          3. Anything left that is definitely outside an open construct is
             flushed to the chat (`thinking` tag if we're inside one).
        """
        self._md_buffer += token
        # Initialize the thinking-mode flag on first call.
        if not hasattr(self, "_in_thinking"):
            self._in_thinking = False

        # 1) Consume any complete <thinking> / </thinking> tags first.
        while True:
            buf = self._md_buffer
            open_idx = buf.find("<thinking>")
            close_idx = buf.find("</thinking>")
            # Prefer whichever tag comes first in the buffer.
            next_idx = -1
            next_tag = None
            if open_idx >= 0 and (close_idx < 0 or open_idx < close_idx):
                next_idx, next_tag = open_idx, "open"
            elif close_idx >= 0:
                next_idx, next_tag = close_idx, "close"
            if next_idx < 0:
                break
            # Flush whatever comes before the tag, in the current style.
            if next_idx > 0:
                pre = buf[:next_idx]
                self._render_plain(pre)
            # Toggle mode and strip the tag itself from the buffer.
            self._in_thinking = (next_tag == "open")
            self._md_buffer = buf[next_idx + (len("<thinking>")
                                              if next_tag == "open"
                                              else len("</thinking>")):]

        # 2) Drain complete markdown constructs (only matters outside thinking).
        while True:
            m = self._MD_RE.search(self._md_buffer)
            if not m:
                break
            head = self._md_buffer[:m.start()]
            if head:
                self._render_plain(head)
            if m.group(1) is not None:
                # **bold**
                tag = "thinking" if self._in_thinking else "bold"
                self._append_chat(m.group(1), tag)
            else:
                # [text](url) — render as link even inside thinking.
                self._render_link(m.group(2), m.group(3))
            self._md_buffer = self._md_buffer[m.end():]

        # 3) Flush safe prefix in the current style.
        self._flush_md_safe_prefix()

    def _flush_md_final(self):
        """End-of-turn: render whatever is left, treating partial markdown
        as plain text.
        """
        if self._md_buffer:
            self._render_md(self._md_buffer)
            self._md_buffer = ""

    def _render_md(self, text: str):
        """Render a chunk of text, expanding any complete markdown constructs."""
        idx = 0
        for m in self._MD_RE.finditer(text):
            if m.start() > idx:
                self._render_plain(text[idx:m.start()])
            if m.group(1) is not None:
                self._append_chat(m.group(1), "bold")
            else:
                self._render_link(m.group(2), m.group(3))
            idx = m.end()
        if idx < len(text):
            self._render_plain(text[idx:])

    def _render_plain(self, text: str):
        if not text:
            return
        # Route plain text through the dimmed "thinking" tag while we're
        # inside a <thinking>…</thinking> block, otherwise standard.
        tag = "thinking" if getattr(self, "_in_thinking", False) else "bot_text"
        self._append_chat(text, tag)

    def _render_link(self, label: str, url: str):
        self.chat_output.configure(state="normal")
        start = self.chat_output.index("end-1c")
        self.chat_output.insert("end", label, "link")
        end = self.chat_output.index("end-1c")
        # Tag a unique mark for this link so we can look up its URL on click.
        link_tag = f"link_{len(self._link_targets)}"
        self.chat_output.tag_add(link_tag, start, end)
        self.chat_output.tag_configure(link_tag)  # no styling; just for lookup
        self._link_targets[link_tag] = url
        self.chat_output.see("end")
        self.chat_output.configure(state="disabled")

    def _on_link_click(self, event):
        idx = self.chat_output.index(f"@{event.x},{event.y}")
        for tag in self.chat_output.tag_names(idx):
            if tag in self._link_targets:
                import webbrowser
                webbrowser.open_new_tab(self._link_targets[tag])
                return

    def _attach_file(self):
        """Open a file picker, upload the file's content to /api/docs/upload
        (it gets stored under data/docs/ and becomes available to rag_search
        on the next ingest). Drop a hint into the chat input so the user can
        ask about it immediately.
        """
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Attach a file to chat",
            filetypes=[
                ("Text & Markdown", "*.txt *.md *.log *.cfg *.ini *.yaml *.yml *.json *.csv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError as exc:
            messagebox.showerror("Attach failed", f"Could not read file:\n{exc}")
            return

        if not content.strip():
            messagebox.showwarning("Attach", "File is empty.")
            return
        if len(content) > 2_000_000:
            messagebox.showwarning("Attach",
                "File is over 2 MB. Only the first 2 MB will be uploaded.")
            content = content[:2_000_000]

        import os
        filename = os.path.basename(path)

        def do_upload():
            r = api_post("/api/docs/upload", {"filename": filename, "content": content})
            if r.get("status") == "ok":
                stored = r.get("filename", filename)
                self.after(0, lambda: self.attach_btn.configure(text="✓", fg=GREEN))
                self.after(1500, lambda: self.attach_btn.configure(text="+", fg=GREEN))
                # Prefill the input with a reference the user can edit/extend.
                self.after(0, lambda: self._prefill_input(
                    f"I just attached `{stored}`. Please use rag_search to look at it and "))
            else:
                err = r.get("error", "upload failed")
                self.after(0, lambda: messagebox.showerror("Attach failed", err))

        threading.Thread(target=do_upload, daemon=True).start()

    def _prefill_input(self, text: str):
        self.chat_input.delete(0, "end")
        self.chat_input.insert(0, text)
        self.chat_input.focus_set()
        self.chat_input.icursor("end")

    def _send_query(self):
        if self.is_querying:
            return
        q = self.chat_input.get().strip()
        if not q:
            return

        # Slash-command shortcuts that bypass the LLM entirely so users
        # can manage long-term memory without burning tokens.
        if q.startswith("/"):
            self.chat_input.delete(0, "end")
            self._handle_slash_command(q)
            return

        self.is_querying = True
        self.chat_input.delete(0, "end")
        self.send_btn.configure(state="disabled")

        # Show user message
        self._append_chat("You\n", "user_prefix")
        self._append_chat(q + "\n\n", "user_text")

        # Show bot prefix
        self._append_chat("Assistant\n", "bot_prefix")

        # Reset the markdown buffer for the upcoming response.
        self._reset_md_buffer()

        # Stream in background
        threading.Thread(target=self._stream_query, args=(q,), daemon=True).start()

    # ---------- slash-command handler ----------

    SLASH_HELP = (
        "Memory commands (handled locally, no model call):\n"
        "  /memory                 list all saved facts\n"
        "  /memory <search-term>   search saved facts by keyword\n"
        "  /remember <text>        save a fact to long-term memory\n"
        "  /forget <id>            delete fact with that numeric id\n"
        "  /clear memory           wipe all stored memory (DESTRUCTIVE)\n"
        "  /clear history          clear the current chat scrollback\n"
        "  /help                   show this list"
    )

    def _handle_slash_command(self, raw: str):
        parts = raw.strip().split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Always echo the command so the chat reads naturally.
        self._append_chat("You\n", "user_prefix")
        self._append_chat(raw + "\n\n", "user_text")

        def out(text: str, tag: str = "bot_text"):
            self._append_chat("omnigab\n", "bot_prefix")
            self._append_chat(text + "\n\n", tag)

        if cmd == "/help":
            out(self.SLASH_HELP)
            return

        if cmd == "/memory":
            params = {}
            if arg:
                params = {"action": "search", "term": arg}
            else:
                params = {"action": "list"}
            r = self._call_memory_via_api(params)
            self._render_memory_response(r, out)
            return

        if cmd == "/remember":
            if not arg:
                out("Usage: /remember <text to save>", "error")
                return
            r = self._call_memory_via_api({"action": "remember",
                                            "category": "fact",
                                            "value": arg})
            if r.get("ok"):
                out(f"Saved (id={r.get('id', '?')}):  {arg}", "bot_text")
            else:
                out(f"Save failed: {r.get('error', 'unknown')}", "error")
            return

        if cmd == "/forget":
            if not arg or not arg.isdigit():
                out("Usage: /forget <numeric id>  (use /memory to list ids)",
                    "error")
                return
            r = self._call_memory_via_api({"action": "forget", "id": int(arg)})
            if r.get("ok"):
                out(f"Forgot row {arg}.", "bot_text")
            else:
                out(f"Forget failed: {r.get('error', 'unknown')}", "error")
            return

        if cmd == "/clear":
            target = arg.lower()
            if target == "history":
                self.chat_output.configure(state="normal")
                self.chat_output.delete("1.0", "end")
                self.chat_output.configure(state="disabled")
                out("Chat scrollback cleared.")
                return
            if target == "memory":
                if not messagebox.askyesno(
                    "Clear all memory?",
                    "This deletes every stored fact, preference, and instruction. "
                    "It cannot be undone. Continue?"
                ):
                    out("Cancelled. Memory unchanged.", "bot_text")
                    return
                r = self._call_memory_via_api({"action": "clear_all"})
                if r.get("ok"):
                    out(f"Memory cleared ({r.get('removed', 0)} rows).",
                        "bot_text")
                else:
                    out(f"Clear failed: {r.get('error', 'unknown')}", "error")
                return
            out("Usage: /clear history  OR  /clear memory", "error")
            return

        out(f"Unknown command: {cmd}\n\n{self.SLASH_HELP}", "error")

    def _call_memory_via_api(self, arguments: dict) -> dict:
        """Direct hit on the persistent_memory tool through the backend so the
        UI doesn't need its own SQLite handle. POSTs to /api/tool/run."""
        try:
            r = api_post("/api/tool/run",
                         {"name": "persistent_memory", "arguments": arguments})
            return r if isinstance(r, dict) else {"ok": False, "error": "bad response"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _render_memory_response(self, r: dict, out):
        if r.get("error"):
            out(f"Memory error: {r['error']}", "error")
            return
        rows = r.get("rows") or r.get("matches") or []
        if not rows:
            out("(no saved memory)", "bot_text")
            return
        lines = []
        for row in rows:
            row_id = row.get("id", "?")
            cat = row.get("category", "?")
            key = row.get("key") or ""
            val = row.get("value") or row.get("text") or ""
            head = f"  #{row_id}  [{cat}]"
            if key:
                head += f"  {key}"
            head += f"  →  {val}"
            lines.append(head)
        out("\n".join(lines))

    def _stream_query(self, question):
        meta = None
        tool_calls = []

        try:
            for chunk in stream_post("/api/query/stream",
                                     {"question": question, "session_id": self.session_id}):
                ctype = chunk.get("type")
                if ctype == "token":
                    token = chunk["text"]
                    self.after(0, self._stream_token_md, token)
                elif ctype == "tool_start":
                    name = chunk.get("name", "?")
                    args = chunk.get("arguments", {})
                    args_preview = json.dumps(args, separators=(",", ":"))[:80]
                    tool_calls.append(name)
                    self.after(0, self._append_chat,
                               f"\n  → using {name}({args_preview})\n", "tool_call")
                elif ctype == "tool_end":
                    name = chunk.get("name", "?")
                    ok = chunk.get("ok", True)
                    marker = "✓" if ok else "✗"
                    self.after(0, self._append_chat,
                               f"  {marker} {name} returned\n", "tool_result")
                elif ctype == "meta":
                    meta = chunk
                elif ctype == "error":
                    self.after(0, self._append_chat, f"\n[error] {chunk['message']}", "error")
        except Exception as e:
            self.after(0, self._append_chat, f"\n[error] {e}", "error")

        # Flush any tail-of-stream markdown BEFORE rendering meta,
        # otherwise an unclosed `[link](url)` in the buffer ends up
        # below the timing info instead of inline with the answer.
        self.after(0, self._flush_md_final)

        if meta:
            def show_meta():
                self._append_chat("\n", "meta")
                if tool_calls:
                    self._append_chat(f"  tools: {', '.join(tool_calls)}", "meta_good")
                if meta.get("model"):
                    self._append_chat(f"  model: {meta.get('model')}", "meta")
                self._append_chat(f"  tokens: {meta.get('tokens', 0)}", "meta")
                self._append_chat(f"  speed: {meta.get('tps', 0):.1f} tok/s", "meta")
                self._append_chat(f"  elapsed: {meta.get('elapsed', 0)}s", "meta")
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
        """Cleaner card-based layout inspired by the Claude settings page.

        Two cards stacked vertically inside a scrollable container:
          1. Resume       — file picker, status, change/clear actions
          2. Quick Search — title + location + search button + results

        Each card is a Frame with BG2 background sitting on the main BG so
        it reads as a discrete grouped section, similar to how Claude's
        settings page groups Profile / Preferences / Notifications.
        """
        frame = ttk.Frame(self, style="Panel.TFrame")
        self.panels["jobs"] = frame

        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        outer = tk.Frame(canvas, bg=BG)

        outer.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        outer_window = canvas.create_window((0, 0), window=outer, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        # Resize the inner frame to match the canvas width so cards stretch.
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(outer_window, width=e.width))
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # ----- Page header (above cards) -----
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", padx=32, pady=(24, 16))
        tk.Label(header, text="Jobs", fg=FG_BRIGHT, bg=BG,
                 font=("Georgia", 18, "bold"), anchor="w").pack(anchor="w")
        tk.Label(header,
                 text="Manage the resume the agent uses to score Indeed listings, "
                      "or run a quick title/location search without leaving this tab.",
                 fg=FG_DIM, bg=BG, font=FONT_SM, anchor="w",
                 wraplength=820, justify="left").pack(anchor="w", pady=(4, 0))

        # ===== CARD 1: Resume =====
        card1 = self._jobs_card(outer)
        card1.pack(fill="x", padx=32, pady=(0, 16))
        self._card_title(card1, "Resume",
                         "Drop a PDF, DOCX, TXT, or MD. The agent uses it to score "
                         "every Indeed result against your background.")

        # Single row: left = filename status, right = buttons.
        row = tk.Frame(card1, bg=BG2)
        row.pack(fill="x", padx=20, pady=(8, 18))

        self.resume_status_label = tk.Label(
            row, text="No resume selected.",
            fg=FG_DIM, bg=BG2, font=FONT, anchor="w",
        )
        self.resume_status_label.pack(side="left", fill="x", expand=True)

        # Right-aligned button group, primary green button + small Clear.
        btn_group = tk.Frame(row, bg=BG2)
        btn_group.pack(side="right")
        self.resume_choose_btn = tk.Button(
            btn_group, text="Choose file...", bg=GREEN, fg=BG,
            activebackground=FG_BRIGHT, activeforeground=BG,
            font=("Segoe UI", 10, "bold"), borderwidth=0,
            padx=14, pady=6, cursor="hand2",
            command=self._choose_resume,
        )
        self.resume_choose_btn.pack(side="left", padx=(0, 8))
        self.resume_clear_btn = tk.Button(
            btn_group, text="Clear", bg=BG2, fg=FG_DIM,
            activebackground=BG3, activeforeground=RED,
            font=FONT_SM, borderwidth=1, padx=10, pady=5, cursor="hand2",
            highlightbackground=BORDER,
            command=self._clear_resume,
        )
        self.resume_clear_btn.pack(side="left")

        # ===== CARD 2: Quick Indeed Search =====
        card2 = self._jobs_card(outer)
        card2.pack(fill="x", padx=32, pady=(0, 16))
        self._card_title(card2, "Quick Indeed Search",
                         "Direct title/location search. For richer agent-driven "
                         "queries with resume-match scoring, use the Chat tab.")

        # Title row
        self._labeled_entry_row(card2, "Title", "job_title", width=42, padx=20, pady=(8, 6))
        # Location row
        self._labeled_entry_row(card2, "Location", "job_location", width=42, padx=20, pady=(0, 6))

        # Bottom action row
        action_row = tk.Frame(card2, bg=BG2)
        action_row.pack(fill="x", padx=20, pady=(8, 18))
        self.job_status = tk.Label(action_row, text="", fg=FG_DIM, bg=BG2, font=FONT_XS, anchor="w")
        self.job_status.pack(side="left", fill="x", expand=True)
        tk.Button(action_row, text="Search", bg=GREEN, fg=BG,
                  activebackground=FG_BRIGHT, activeforeground=BG,
                  font=("Segoe UI", 10, "bold"), borderwidth=0,
                  padx=18, pady=6, cursor="hand2",
                  command=self._search_jobs).pack(side="right")

        # ===== Results area =====
        results_card = self._jobs_card(outer)
        results_card.pack(fill="x", expand=False, padx=32, pady=(0, 24))
        self._card_title(results_card, "Results", None)

        self.job_results = tk.Text(
            results_card, bg=BG2, fg=FG, font=FONT_SM, height=14,
            state="disabled", borderwidth=0, highlightthickness=0,
            wrap="word", padx=20, pady=4,
        )
        self.job_results.pack(fill="both", expand=True, padx=0, pady=(0, 18))
        self.job_results.tag_configure("title", foreground=GREEN, font=("Segoe UI", 11, "bold"))
        self.job_results.tag_configure("company", foreground=AMBER, font=FONT_SM)
        self.job_results.tag_configure("score_high", foreground=GREEN, font=FONT_SM)
        self.job_results.tag_configure("score_mid", foreground=AMBER, font=FONT_SM)
        self.job_results.tag_configure("score_low", foreground=RED, font=FONT_SM)
        self.job_results.tag_configure("dim", foreground=FG_DIM, font=FONT_XS)

    # ----- card helpers used by _build_jobs_panel -----

    def _jobs_card(self, parent):
        """A grouped section: BG2 panel with a 1px border.

        Single Frame so callers can pack the returned widget into the parent
        AND pack their children into the same widget. The border is drawn
        via highlight* options — no outer/inner trick needed.
        """
        return tk.Frame(
            parent, bg=BG2,
            highlightbackground=BORDER, highlightthickness=1,
        )

    def _card_title(self, card, title: str, subtitle: str | None):
        head = tk.Frame(card, bg=BG2)
        head.pack(fill="x", padx=20, pady=(18, 2))
        tk.Label(head, text=title, fg=FG_BRIGHT, bg=BG2,
                 font=("Segoe UI", 13, "bold"), anchor="w").pack(anchor="w")
        if subtitle:
            tk.Label(card, text=subtitle, fg=FG_DIM, bg=BG2, font=FONT_SM,
                     anchor="w", justify="left", wraplength=820).pack(
                anchor="w", padx=20, pady=(2, 0))

    def _labeled_entry_row(self, card, label_text: str, attr: str,
                            width: int = 30, padx=20, pady=(6, 6)):
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", padx=padx, pady=pady)
        tk.Label(row, text=label_text, fg=FG, bg=BG2, font=FONT,
                 anchor="w", width=10).pack(side="left")
        entry = tk.Entry(row, bg=BG, fg=FG_BRIGHT, font=FONT,
                         insertbackground=GREEN, borderwidth=1,
                         highlightthickness=1, highlightcolor=GREEN,
                         highlightbackground=BORDER, width=width)
        entry.pack(side="left", padx=(12, 0), ipady=5, fill="x", expand=True)
        setattr(self, attr, entry)

    def _upload_resume(self):
        """Legacy text-paste upload (deprecated; UI no longer exposes a textbox).
        Kept for backward compat with /api/jobs/upload-resume callers.
        """
        return None

    def _upload_resume(self):
        text = self.resume_text.get("1.0", "end").strip()
        if not text:
            return
        r = api_post("/api/jobs/upload-resume", {"text": text})
        if r.get("status") == "ok":
            self.job_status.configure(text=f"Resume uploaded ({r['length']} chars)", fg=GREEN)
        else:
            self.job_status.configure(text=r.get("error", "Upload failed"), fg=RED)

    # ----- active resume file selection -----

    def _choose_resume(self):
        """Open a file dialog, read the picked file, base64 it, POST to
        /api/resume/upload. The server saves it as data/docs/active_resume.<ext>
        so the indeed_apply tool finds it on its next run.
        """
        from tkinter import filedialog
        import base64
        path = filedialog.askopenfilename(
            title="Choose your resume",
            filetypes=[
                ("Resume files", "*.pdf *.docx *.txt *.md"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Text", "*.txt"),
                ("Markdown", "*.md"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            self.resume_status_label.configure(text=f"Read failed: {exc}", fg=RED)
            return

        if len(data) > 5 * 1024 * 1024:
            self.resume_status_label.configure(text="File too large (5 MB max).", fg=RED)
            return

        self.resume_status_label.configure(text="Uploading...", fg=AMBER)

        def do_upload():
            import os
            filename = os.path.basename(path)
            r = api_post("/api/resume/upload", {
                "filename": filename,
                "content_b64": base64.b64encode(data).decode("ascii"),
            })
            if r.get("status") == "ok":
                msg = f"Loaded: {r.get('original_filename', filename)} ({r.get('size', len(data))} bytes)"
                drafter = r.get("drafter_baseresume") or {}
                if drafter.get("updated"):
                    msg += f"  •  drafter base updated ({drafter.get('chars', 0)} chars)"
                elif drafter.get("error"):
                    # Upload succeeded but extract failed (e.g. image-only PDF).
                    msg += f"  •  drafter extract failed: {drafter['error']}"
                self.after(0, lambda: self.resume_status_label.configure(text=msg, fg=GREEN))
                self.after(0, self._refresh_resume_status)
            else:
                err = r.get("error", "Upload failed")
                self.after(0, lambda: self.resume_status_label.configure(text=f"Failed: {err}", fg=RED))

        threading.Thread(target=do_upload, daemon=True).start()

    def _clear_resume(self):
        if not messagebox.askyesno("Clear resume",
                                    "Remove the active resume? Indeed match scoring will be disabled."):
            return

        def do_clear():
            # api_post only supports GET/POST; use a small inline DELETE.
            import json, urllib.request
            try:
                req = urllib.request.Request(
                    f"{API}/api/resume",
                    headers={"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {},
                    method="DELETE",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    json.loads(resp.read().decode())
                self.after(0, lambda: self.resume_status_label.configure(
                    text="No resume selected.", fg=FG_DIM))
                self.after(0, self._refresh_resume_status)
            except Exception as exc:
                self.after(0, lambda: self.resume_status_label.configure(
                    text=f"Clear failed: {exc}", fg=RED))

        threading.Thread(target=do_clear, daemon=True).start()

    def _refresh_resume_status(self):
        """Update the Jobs-tab label AND the topbar resume indicator."""
        def do():
            r = api_get("/api/resume")
            def show():
                if r.get("active"):
                    name = r.get("filename", "active")
                    size_kb = max(1, r.get("size", 0) // 1024)
                    self.resume_status_label.configure(
                        text=f"Active resume: {name} ({size_kb} KB)", fg=GREEN)
                    self.status_resume.configure(text=f"resume: {name}", foreground=GREEN)
                else:
                    self.resume_status_label.configure(text="No resume selected.", fg=FG_DIM)
                    self.status_resume.configure(text="resume: none", foreground=FG_DIM)
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

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
        tk.Label(frame, text="GGUF models. Click DOWNLOAD or SWITCH next to each entry.",
                 fg=FG_DIM, bg=BG, font=FONT_SM, anchor="w").pack(fill="x", padx=16, pady=(0, 4))

        self.models_status = tk.Label(frame, text="", fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w")
        self.models_status.pack(fill="x", padx=16, pady=(0, 8))

        # Scrollable container for per-model rows.
        outer = tk.Frame(frame, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=4)
        self.models_canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self.models_canvas.yview)
        self.models_inner = tk.Frame(self.models_canvas, bg=BG)
        self.models_inner.bind("<Configure>",
                               lambda e: self.models_canvas.configure(scrollregion=self.models_canvas.bbox("all")))
        self.models_canvas.create_window((0, 0), window=self.models_inner, anchor="nw")
        self.models_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.models_canvas.pack(side="left", fill="both", expand=True)

    def _load_models(self):
        def do():
            payload = api_get("/api/models")
            if isinstance(payload, dict) and payload.get("error"):
                self.after(0, lambda: self.models_status.configure(
                    text=payload["error"], fg=RED))
                return
            # New API returns {models: [...], status: {...}}; tolerate the old shape.
            if isinstance(payload, dict) and "models" in payload:
                models = payload["models"]
                status = payload.get("status", {})
            else:
                models = payload
                status = {}
            self.after(0, self._render_models, models, status)
        threading.Thread(target=do, daemon=True).start()

    def _render_models(self, models, status):
        for w in self.models_inner.winfo_children():
            w.destroy()

        gpu = status.get("gpu_supported")
        layers = status.get("gpu_layers")
        if gpu:
            self.models_status.configure(
                text=f"GPU: enabled  |  layers offloaded: {layers}", fg=GREEN)
        elif gpu is False:
            self.models_status.configure(
                text="GPU: not available (llama-cpp built without CUDA, or no NVIDIA GPU)",
                fg=AMBER)

        for m in models:
            row = tk.Frame(self.models_inner, bg=BG, pady=8)
            row.pack(fill="x", padx=4)

            head = tk.Frame(row, bg=BG)
            head.pack(fill="x")
            tk.Label(head, text=m["name"], fg=GREEN, bg=BG,
                     font=("Consolas", 11, "bold")).pack(side="left")
            if m.get("active"):
                tk.Label(head, text="  [ACTIVE]", fg=GREEN, bg=BG, font=FONT_XS).pack(side="left")

            tk.Label(row, text=f"  file: {m['filename']}", fg=FG_DIM, bg=BG,
                     font=FONT_XS, anchor="w").pack(fill="x")
            tk.Label(row, text=f"  size: {m['size']}  |  RAM: {m['ram']}",
                     fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w").pack(fill="x")
            status_color = GREEN if m["downloaded"] else RED
            status_text = "downloaded" if m["downloaded"] else "not downloaded"
            tk.Label(row, text=f"  status: {status_text}", fg=status_color, bg=BG,
                     font=FONT_XS, anchor="w").pack(fill="x")

            btns = tk.Frame(row, bg=BG)
            btns.pack(fill="x", pady=(4, 0))
            if m["downloaded"]:
                if not m.get("active"):
                    tk.Button(btns, text="SWITCH", bg=BG, fg=GREEN, font=("Consolas", 9, "bold"),
                              borderwidth=1, padx=10,
                              command=lambda f=m["filename"], n=m["name"]: self._switch_model(f, n)
                              ).pack(side="left", padx=(0, 6))
            else:
                tk.Button(btns, text="DOWNLOAD", bg=BG, fg=AMBER, font=("Consolas", 9, "bold"),
                          borderwidth=1, padx=10,
                          command=lambda f=m["filename"], i=m: self._download_model(f, i)
                          ).pack(side="left", padx=(0, 6))

    def _switch_model(self, filename, friendly_name):
        if not messagebox.askyesno("Switch model",
                                    f"Unload current model and load {friendly_name}?\n\nThis frees the active model from RAM/VRAM before loading the new one."):
            return
        self.models_status.configure(text=f"Loading {friendly_name}…", fg=AMBER)

        def do():
            r = api_post("/api/models/switch", {"filename": filename})
            if r.get("error"):
                self.after(0, lambda: self.models_status.configure(text=r["error"], fg=RED))
                return
            self.after(0, lambda: self.models_status.configure(
                text=f"Loaded {friendly_name}", fg=GREEN))
            self.after(0, self._load_models)
            self.after(0, self._load_sysinfo)
            # Refresh the topbar status badge — the tool-calling tier just
            # changed because the model did. Without this, the badge keeps
            # whatever stale value (often "broken (switch to 7B/14B)") it
            # picked up during the brief window before the model finished
            # loading on first boot.
            self.after(0, self._load_status)
        threading.Thread(target=do, daemon=True).start()

    def _download_model(self, filename, info):
        # Two-phase: first call gets info, then prompt, then second call streams download.
        proceed = messagebox.askyesno(
            "Download model?",
            f"Download {info['name']}?\n\n"
            f"File: {info['filename']}\n"
            f"Size: {info['size']}\n"
            f"Repo: {info['repo']}\n\n"
            "This will download from Hugging Face into the models/ folder."
        )
        if not proceed:
            return

        self.models_status.configure(text=f"Downloading {info['name']}…", fg=AMBER)

        def do():
            try:
                for chunk in stream_post("/api/models/download",
                                         {"filename": filename, "confirmed": True}):
                    ctype = chunk.get("type")
                    if ctype == "start":
                        self.after(0, lambda: self.models_status.configure(
                            text=f"Downloading {filename} from {chunk.get('repo')}…", fg=AMBER))
                    elif ctype == "done":
                        self.after(0, lambda: self.models_status.configure(
                            text=f"Downloaded {filename}.", fg=GREEN))
                        self.after(0, self._load_models)
                    elif ctype == "error":
                        msg = chunk.get("message", "download failed")
                        self.after(0, lambda m=msg: self.models_status.configure(
                            text=f"Error: {m}", fg=RED))
            except Exception as e:
                self.after(0, lambda: self.models_status.configure(text=str(e), fg=RED))

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
            global API_TOKEN
            r = api_get("/api/session")
            self.session_id = r.get("session_id", "default")
            API_TOKEN = r.get("api_token", "")
            self.after(0, self._load_status)
            self.after(0, self._load_sysinfo)
            self.after(0, self._load_docs)
            self.after(0, self._load_models)
            self.after(0, self._load_memory)
            self.after(0, self._refresh_resume_status)
            # Slow background poll: refreshes the topbar badges every 20s
            # so the tool-status tier reflects the currently-loaded model
            # even after model swaps or first-boot loading races.
            self._schedule_status_poll()
        threading.Thread(target=do, daemon=True).start()

    def _schedule_status_poll(self, interval_ms: int = 20000):
        self.after(interval_ms, self._tick_status_poll, interval_ms)

    def _tick_status_poll(self, interval_ms: int):
        self._load_status()
        self.after(interval_ms, self._tick_status_poll, interval_ms)

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
                tc = r.get("tool_calling") or {}
                tier = tc.get("tier", "?")
                color = {"good": GREEN, "marginal": AMBER, "poor": RED}.get(tier, FG_DIM)
                label = {"good": "tools: ready",
                         "marginal": "tools: weak (upgrade model)",
                         "poor": "tools: broken (switch to 7B/14B)"}.get(tier, "tools: --")
                self.status_tools.configure(text=label, foreground=color)
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
        print("  Starting omnigab server...")
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
