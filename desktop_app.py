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
from tkinter import ttk, messagebox
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
# Two families, on purpose. Chrome (labels, prefixes, status, headings) is
# monospace, which is where the terminal identity lives. Body prose stays
# proportional, because a long answer set in monospace is genuinely harder
# to read and the aesthetic is not worth costing the user that.
#
# Georgia used to supply FONT_TITLE and the empty-state heading. A serif
# belongs to neither half and read as an accident rather than a choice.
MONO = "Consolas"
SANS = "Segoe UI"

FONT = (SANS, 11)
FONT_SM = (SANS, 10)
FONT_XS = (SANS, 9)
FONT_LG = (SANS, 13)
FONT_TITLE = (MONO, 14, "bold")
FONT_ASCII = (MONO, 22)
FONT_MONO_SM = (MONO, 10)
FONT_MONO_XS = (MONO, 9)

# The transcript is capped at a readable measure instead of stretching to
# the window. On a 2560px monitor a full-width line is roughly 300
# characters, which is unreadable; 820px lands near the 70-90 characters
# that prose is comfortable at.
CONTENT_MAX_W = 820
COMPOSER_MAX_W = 820


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

        # Thin, dark, no arrow buttons. The classic tk.Scrollbar that
        # ScrolledText creates ignores colour options on Windows and renders
        # as a light native widget against the dark panel; a ttk scrollbar
        # under clam does not.
        self.style.element_create("Chat.Vertical.Scrollbar.trough", "from", "clam")
        self.style.element_create("Chat.Vertical.Scrollbar.thumb", "from", "clam")
        self.style.layout("Chat.Vertical.TScrollbar", [
            ("Chat.Vertical.Scrollbar.trough", {
                "sticky": "ns",
                "children": [
                    ("Chat.Vertical.Scrollbar.thumb",
                     {"expand": "1", "sticky": "nswe"}),
                ],
            }),
        ])
        self.style.configure(
            "Chat.Vertical.TScrollbar",
            background=BG3, troughcolor=BG, bordercolor=BG,
            lightcolor=BG3, darkcolor=BG3, arrowcolor=FG_DIM,
            borderwidth=0, relief="flat", width=10,
        )
        self.style.map(
            "Chat.Vertical.TScrollbar",
            background=[("active", GREEN_DIM), ("pressed", GREEN_DIM)],
        )
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
        """Identity on the left, live status on the right.

        The status items used to be packed with 8px between them and no
        separators, so five of them ran together into one dense string in
        the corner. They are the same labels, given room and a divider.
        """
        bar = ttk.Frame(self, style="Topbar.TFrame", height=44)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ttk.Label(bar, text="omnigab", style="Logo.TLabel").pack(
            side="left", padx=(20, 10))

        self.model_label = ttk.Label(bar, text="loading...",
                                     style="Topbar.TLabel")
        self.model_label.pack(side="left")

        # Right side, packed right-to-left, so declare in reverse order.
        self.status_session = ttk.Label(bar, text="session: active",
                                        style="Topbar.TLabel")
        self.status_session.pack(side="right", padx=(0, 20))
        self.status_web = ttk.Label(bar, text="web: --", style="Topbar.TLabel")
        self.status_web.pack(side="right", padx=14)
        self.status_index = ttk.Label(bar, text="index: --",
                                      style="Topbar.TLabel")
        self.status_index.pack(side="right", padx=14)
        self.status_resume = ttk.Label(bar, text="resume: none",
                                       style="Topbar.TLabel")
        self.status_resume.pack(side="right", padx=14)
        # Tool-calling capability badge, set from the measured tier in
        # web_app._tool_calling_capability rather than from model size.
        self.status_tools = ttk.Label(bar, text="tools: --",
                                      style="Topbar.TLabel")
        self.status_tools.pack(side="right", padx=(14, 14))
        tk.Frame(bar, bg=BORDER, width=1).pack(
            side="right", fill="y", pady=12)

    def _build_tabs(self):
        """Tab strip with an underline on the active tab.

        Colour alone carried the active state before, which is a weak
        signal on a palette that is already mostly green, and invisible to
        anyone who cannot separate the two greens.
        """
        self.tabbar = ttk.Frame(self, style="TabBar.TFrame")
        self.tabbar.pack(fill="x", side="top")

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x", side="top")

        self.tabs = {}
        self.tab_indicators = {}
        self.current_tab = "chat"
        tab_names = ["chat", "docs", "models", "settings", "developer"]

        holder = tk.Frame(self.tabbar, bg=BG2)
        holder.pack(side="left", padx=(14, 0))

        for name in tab_names:
            cell = tk.Frame(holder, bg=BG2)
            cell.pack(side="left")
            style = "ActiveTab.TButton" if name == "chat" else "Tab.TButton"
            btn = ttk.Button(cell, text=name.title(), style=style,
                             command=lambda n=name: self._switch_tab(n))
            btn.pack(side="top")
            # 2px rule under the active tab. Packed always, coloured to
            # match the bar when inactive, so the strip never reflows.
            bar = tk.Frame(cell, bg=GREEN if name == "chat" else BG2, height=2)
            bar.pack(side="top", fill="x")
            self.tabs[name] = btn
            self.tab_indicators[name] = bar

    def _switch_tab(self, name):
        self.current_tab = name
        for tname, btn in self.tabs.items():
            btn.configure(style="ActiveTab.TButton" if tname == name else "Tab.TButton")
        for pname, frame in self.panels.items():
            if pname == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for tab_name, indicator in getattr(self, "tab_indicators", {}).items():
            indicator.configure(bg=GREEN if tab_name == name else BG2)
        if name == "chat":
            self.chat_input.focus_set()

    def _build_panels(self):
        self.panels = {}
        self._build_chat_panel()
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
        """Transcript and composer, both inside one centered reading column.

        The old layout let both run the full width of the window and pinned
        the composer to the bottom edge, so on a wide monitor you got a
        300-character measure above a 1900px input strip. Everything here
        sits in a column capped at CONTENT_MAX_W and kept centered by
        _center_chat_column on resize.
        """
        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        self.panels["chat"] = frame

        column = tk.Frame(frame, bg=BG)
        column.pack(fill="both", expand=True)
        self._chat_column = column
        frame.bind("<Configure>", self._center_chat_column)

        # Text plus an explicit ttk scrollbar, rather than ScrolledText.
        # ScrolledText builds a classic tk.Scrollbar, which on Windows
        # accepts colour options and then ignores them, drawing itself with
        # the native theme: a light grey bar down the side of a dark panel.
        transcript = tk.Frame(column, bg=BG)
        transcript.pack(fill="both", expand=True)

        self.chat_output = tk.Text(
            transcript, wrap="word", bg=BG, fg=FG, font=FONT,
            insertbackground=GREEN, selectbackground=BORDER,
            borderwidth=0, highlightthickness=0, padx=4, pady=24,
            cursor="arrow", state="disabled",
        )
        self.chat_scroll = ttk.Scrollbar(
            transcript, orient="vertical", style="Chat.Vertical.TScrollbar",
            command=self.chat_output.yview,
        )
        self.chat_output.configure(yscrollcommand=self.chat_scroll.set)
        self.chat_scroll.pack(side="right", fill="y")
        self.chat_output.pack(side="left", fill="both", expand=True)

        self._configure_chat_tags()
        self._link_targets = {}
        self._show_empty_state()

        # --- composer ---------------------------------------------------
        # Sits inside the column with room beneath it rather than welded to
        # the window edge, and reads as one bordered field that happens to
        # contain the attach and send controls.
        composer_wrap = tk.Frame(column, bg=BG)
        composer_wrap.pack(fill="x", pady=(0, 20))

        composer = tk.Frame(composer_wrap, bg=BG2,
                            highlightbackground=BORDER, highlightthickness=1)
        composer.pack(fill="x")

        self.attach_btn = tk.Button(
            composer, text="+", fg=FG_DIM, bg=BG2,
            activebackground=BG2, activeforeground=GREEN,
            font=(MONO, 16), borderwidth=0, highlightthickness=0,
            cursor="hand2", padx=10, pady=0,
            command=self._attach_file,
        )
        self.attach_btn.pack(side="left")

        # Borderless on purpose: the surrounding frame is the visible field,
        # so an entry with its own border would draw a box inside a box.
        self.chat_input = tk.Entry(
            composer, bg=BG2, fg=FG_BRIGHT, font=FONT,
            insertbackground=GREEN, selectbackground=GREEN_DIM,
            borderwidth=0, highlightthickness=0,
        )
        self.chat_input.pack(side="left", fill="x", expand=True,
                             ipady=10, padx=(2, 8))
        self.chat_input.bind("<Return>", lambda e: self._send_query())
        self.chat_input.bind(
            "<FocusIn>",
            lambda e: composer.configure(highlightbackground=GREEN_DIM))
        self.chat_input.bind(
            "<FocusOut>",
            lambda e: composer.configure(highlightbackground=BORDER))

        self.send_btn = tk.Button(
            composer, text="SEND", bg=BG2, fg=GREEN,
            font=(MONO, 9, "bold"), borderwidth=0, highlightthickness=0,
            activebackground=BG2, activeforeground=FG_BRIGHT,
            cursor="hand2", padx=14, pady=6,
            command=self._send_query,
        )
        self.send_btn.pack(side="right", padx=(0, 6))

        tk.Label(composer_wrap,
                 text="Enter to send   +  to attach a file",
                 fg=FG_DIM, bg=BG, font=FONT_MONO_XS, anchor="w").pack(
            anchor="w", pady=(6, 0))

    def _center_chat_column(self, event=None):
        """Keep the reading column centered and capped as the window resizes."""
        width = self.panels["chat"].winfo_width()
        pad = max(24, (width - CONTENT_MAX_W) // 2)
        self._chat_column.pack_configure(padx=pad)

    def _configure_chat_tags(self):
        """Text tags for the transcript. Chrome is mono, prose is not."""
        out = self.chat_output
        out.tag_configure("user_prefix", foreground=GREEN,
                          font=(MONO, 9, "bold"), spacing1=16)
        out.tag_configure("bot_prefix", foreground=FG_DIM,
                          font=(MONO, 9, "bold"), spacing1=16)
        # The user's turn is indented and tinted rather than boxed. A filled
        # bubble at this width drew a hard rectangle across the whole column
        # and fought the transcript for attention.
        out.tag_configure("user_text", foreground=USER_BUBBLE_FG, font=FONT,
                          lmargin1=14, lmargin2=14, rmargin=8, spacing3=4)
        out.tag_configure("bot_text", foreground=FG, font=FONT,
                          lmargin1=14, lmargin2=14, rmargin=8, spacing3=4)
        out.tag_configure("meta", foreground=FG_DIM, font=FONT_MONO_XS,
                          lmargin1=14, lmargin2=14)
        out.tag_configure("meta_good", foreground=GREEN, font=FONT_MONO_XS)
        out.tag_configure("meta_warn", foreground=AMBER, font=FONT_MONO_XS)
        out.tag_configure("meta_bad", foreground=RED, font=FONT_MONO_XS)
        out.tag_configure("error", foreground=RED, font=FONT,
                          lmargin1=14, lmargin2=14)
        out.tag_configure("welcome", foreground=FG_BRIGHT, font=FONT_ASCII,
                          justify="center", spacing1=8, spacing3=10)
        out.tag_configure("welcome_sub", foreground=FG_DIM, font=FONT_SM,
                          justify="center")
        out.tag_configure("source", foreground=AMBER, font=FONT_MONO_XS,
                          lmargin1=14, lmargin2=14)
        out.tag_configure("tool_call", foreground=CYAN, font=(MONO, 9),
                          lmargin1=14, lmargin2=14)
        # Reasoning blocks: dim, indented further than the answer so they
        # read as working rather than as the answer itself.
        out.tag_configure("thinking", foreground=FG_DIM,
                          font=(SANS, 10, "italic"),
                          lmargin1=24, lmargin2=24, rmargin=16,
                          spacing1=4, spacing3=4)
        out.tag_configure("tool_result", foreground=AMBER,
                          font=FONT_MONO_XS, lmargin1=14, lmargin2=14)
        out.tag_configure("bold", foreground=FG_BRIGHT,
                          font=(SANS, 11, "bold"))
        out.tag_configure("link", foreground=BLUE,
                          font=(SANS, 11, "underline"))
        out.tag_configure("salary", foreground=GREEN, font=(SANS, 10))
        out.tag_bind("link", "<Button-1>", self._on_link_click)
        out.tag_bind("link", "<Enter>", lambda e: out.configure(cursor="hand2"))
        out.tag_bind("link", "<Leave>", lambda e: out.configure(cursor="arrow"))

    def _show_empty_state(self):
        """Greeting shown before the first turn.

        The greeting used to be the literal string "Good evening" whatever
        the clock said, which is the sort of detail that quietly tells a
        user the software is not paying attention.
        """
        hour = time.localtime().tm_hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        self.chat_output.configure(state="normal")
        self.chat_output.insert("end", "\n" + greeting + "\n", "welcome")
        self.chat_output.insert(
            "end",
            "Ask about your documents, use a skill, or just talk.\n",
            "welcome_sub",
        )
        self.chat_output.configure(state="disabled")


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
                self.after(0, lambda e=exc: self.resume_status_label.configure(
                    text=f"Clear failed: {e}", fg=RED))

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
        self.models_status.pack(fill="x", padx=16, pady=(0, 4))

        # Download progress. Hidden until a download starts, because an
        # empty bar sitting on screen reads as a broken one.
        self.dl_frame = tk.Frame(frame, bg=BG)
        self.dl_bar = ttk.Progressbar(self.dl_frame, mode="determinate",
                                      maximum=100, length=420)
        self.dl_bar.pack(side="left")
        self.dl_label = tk.Label(self.dl_frame, text="", fg=FG_DIM, bg=BG,
                                 font=FONT_XS, anchor="w")
        self.dl_label.pack(side="left", padx=8)

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
            self.after(0, self._load_hardware)
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
        self._show_progress(True)
        self._dl_started = time.monotonic()

        def do():
            try:
                for chunk in stream_post("/api/models/download",
                                         {"filename": filename, "confirmed": True}):
                    ctype = chunk.get("type")
                    if ctype == "start":
                        total = chunk.get("total_bytes")
                        self.after(0, lambda t=total: self._dl_start(filename, t))
                    elif ctype == "progress":
                        self.after(0, lambda c=chunk: self._dl_progress(c))
                    elif ctype == "done":
                        self.after(0, lambda: self.models_status.configure(
                            text=f"Downloaded {filename}.", fg=GREEN))
                        self.after(0, lambda: self._show_progress(False))
                        self.after(0, self._load_models)
                    elif ctype == "error":
                        msg = chunk.get("message", "download failed")
                        self.after(0, lambda m=msg: self.models_status.configure(
                            text=f"Error: {m}", fg=RED))
                        self.after(0, lambda: self._show_progress(False))
            except Exception as e:
                self.after(0, lambda err=e: self.models_status.configure(
                    text=str(err), fg=RED))
                self.after(0, lambda: self._show_progress(False))

        threading.Thread(target=do, daemon=True).start()

    # ---------------- download progress helpers ----------------

    @staticmethod
    def _human_bytes(n):
        """Bytes as a short human string. Model files are GB-scale."""
        if not n:
            return "0 B"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(n) < 1024:
                return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
            n /= 1024
        return f"{n:.1f} PB"

    def _show_progress(self, visible):
        if visible:
            self.dl_frame.pack(fill="x", padx=16, pady=(0, 8))
            self.dl_bar.configure(value=0)
            self.dl_label.configure(text="starting…")
        else:
            self.dl_frame.pack_forget()

    def _dl_start(self, filename, total_bytes):
        self._dl_total = total_bytes
        if total_bytes:
            self.dl_bar.configure(mode="determinate", maximum=100, value=0)
            self.dl_label.configure(text=f"0% of {self._human_bytes(total_bytes)}")
        else:
            # Size unknown: sweep instead of lying about a percentage.
            self.dl_bar.configure(mode="indeterminate")
            self.dl_bar.start(12)
            self.dl_label.configure(text="downloading…")
        self.models_status.configure(text=f"Downloading {filename}…", fg=AMBER)

    def _dl_progress(self, chunk):
        done = chunk.get("downloaded_bytes", 0)
        total = chunk.get("total_bytes") or getattr(self, "_dl_total", None)
        elapsed = max(time.monotonic() - getattr(self, "_dl_started", 0), 0.001)
        rate = done / elapsed

        parts = [self._human_bytes(done)]
        if total:
            pct = min(100.0, 100.0 * done / total)
            self.dl_bar.configure(mode="determinate", value=pct)
            parts = [f"{pct:.1f}%", f"{self._human_bytes(done)} of "
                                    f"{self._human_bytes(total)}"]
            remaining = total - done
            if rate > 0 and remaining > 0:
                eta = int(remaining / rate)
                parts.append(f"about {eta // 60}m {eta % 60}s left"
                             if eta >= 60 else f"about {eta}s left")
        if rate > 0:
            parts.append(f"{self._human_bytes(rate)}/s")
        self.dl_label.configure(text="  ·  ".join(parts))

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

        # ---------------- Advanced ----------------
        tk.Label(frame, text="# ADVANCED", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(frame,
                 text="Context window: how much the model can hold at once "
                      "(prompt + documents + reply).",
                 fg=FG_DIM, bg=BG, font=FONT_SM, anchor="w",
                 wraplength=620, justify="left").pack(fill="x", padx=16, pady=(0, 2))
        tk.Label(frame,
                 text="Auto picks the largest size that fits your GPU. Raise it to "
                      "work with longer documents, at the cost of speed and memory. "
                      "Takes effect the next time the model loads.",
                 fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w",
                 wraplength=620, justify="left").pack(fill="x", padx=16, pady=(0, 8))

        ctx_frame = tk.Frame(frame, bg=BG)
        ctx_frame.pack(fill="x", padx=16, pady=4)

        self.ctx_mode = tk.StringVar(value="auto")
        tk.Radiobutton(ctx_frame, text="Auto (recommended)", variable=self.ctx_mode,
                       value="auto", bg=BG, fg=FG, font=FONT_XS, selectcolor=BG,
                       activebackground=BG, activeforeground=GREEN,
                       command=self._on_ctx_mode_change).pack(side="left")
        tk.Radiobutton(ctx_frame, text="Custom:", variable=self.ctx_mode,
                       value="custom", bg=BG, fg=FG, font=FONT_XS, selectcolor=BG,
                       activebackground=BG, activeforeground=GREEN,
                       command=self._on_ctx_mode_change).pack(side="left", padx=(12, 0))

        self.ctx_entry = tk.Entry(ctx_frame, bg=BG, fg=FG_BRIGHT, font=FONT_SM, width=8,
                                  insertbackground=GREEN, borderwidth=1,
                                  highlightbackground=BORDER, state="disabled")
        self.ctx_entry.pack(side="left", padx=4, ipady=3)
        tk.Label(ctx_frame, text="tokens", fg=FG_DIM, bg=BG,
                 font=FONT_XS).pack(side="left")
        tk.Button(ctx_frame, text="SAVE", bg=BG, fg=GREEN, font=FONT_XS,
                  command=self._save_context_setting,
                  borderwidth=1, padx=8).pack(side="left", padx=8)

        self.ctx_status = tk.Label(frame, text="", fg=FG_DIM, bg=BG, font=FONT_XS,
                                   anchor="w", wraplength=620, justify="left")
        self.ctx_status.pack(fill="x", padx=16, pady=(2, 0))

        tk.Label(frame,
                 text="Guide:  4096 = short chats  ·  8192 = default  ·  "
                      "16384 = long documents  ·  262144 = model maximum",
                 fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w").pack(fill="x", padx=16, pady=(4, 0))

        self._load_context_setting()

        # --- Resume ----------------------------------------------------
        # Lived in the Jobs tab until that was removed. It never belonged
        # there: the resume feeds usajobs_search's match scoring and the
        # federal resume drafter, neither of which had anything to do with
        # the Indeed search the tab was built around.
        tk.Label(frame, text="RESUME", fg=GREEN, bg=BG, font=FONT_SM,
                 anchor="w").pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(frame,
                 text=("Used to score USAJOBS results against your background "
                       "and to draft tailored federal resumes. PDF, DOCX, TXT "
                       "or MD."),
                 fg=FG_DIM, bg=BG, font=FONT_XS, anchor="w",
                 wraplength=620, justify="left").pack(fill="x", padx=16)
        resume_row = tk.Frame(frame, bg=BG)
        resume_row.pack(fill="x", padx=16, pady=(6, 0))
        self.resume_status_label = tk.Label(
            resume_row, text="", fg=FG_DIM, bg=BG, font=FONT_XS,
            anchor="w", wraplength=420, justify="left")
        self.resume_status_label.pack(side="left", fill="x", expand=True)
        self.resume_choose_btn = tk.Button(
            resume_row, text="CHOOSE FILE", bg=BG, fg=GREEN, font=FONT_XS,
            command=self._choose_resume, borderwidth=1, padx=8)
        self.resume_choose_btn.pack(side="left", padx=(8, 4))
        self.resume_clear_btn = tk.Button(
            resume_row, text="CLEAR", bg=BG, fg=RED, font=FONT_XS,
            command=self._clear_resume, borderwidth=1, padx=8)
        self.resume_clear_btn.pack(side="left")
        self._refresh_resume_status()

        # --- Reasoning block -------------------------------------------
        # Off by default. Measured on Qwen3.5 9B, "What is 2+2?" costs 1
        # token and 0.3s with this off, and 2048 tokens and 52s with it on,
        # where 2048 is MAX_NEW_TOKENS: the model is still reasoning when
        # the budget runs out and never reaches an answer. Enabling it is
        # only sensible alongside a much larger token ceiling, which is
        # what the warning below says.
        tk.Label(frame, text="REASONING", fg=GREEN, bg=BG, font=FONT_SM,
                 anchor="w").pack(fill="x", padx=16, pady=(12, 2))
        self.thinking_var = tk.BooleanVar(value=False)
        think_frame = tk.Frame(frame, bg=BG)
        think_frame.pack(fill="x", padx=16)
        tk.Checkbutton(think_frame,
                       text="Let the model think out loud before answering",
                       variable=self.thinking_var, command=self._save_thinking_setting,
                       fg=FG, bg=BG, selectcolor=BG, activebackground=BG,
                       activeforeground=GREEN, font=FONT_XS,
                       anchor="w").pack(side="left")
        self.thinking_status = tk.Label(frame, text="", fg=FG_DIM, bg=BG,
                                        font=FONT_XS, anchor="w",
                                        wraplength=620, justify="left")
        self.thinking_status.pack(fill="x", padx=16, pady=(2, 0))
        self._load_thinking_setting()

        btn_f = tk.Frame(frame, bg=BG)
        btn_f.pack(fill="x", padx=16, pady=8)
        tk.Button(btn_f, text="REFRESH", bg=BG, fg=FG, font=FONT_XS,
                  command=self._load_memory, borderwidth=1, padx=8).pack(side="left")
        tk.Button(btn_f, text="CLEAR MEMORY", bg=BG, fg=RED, font=FONT_XS,
                  command=self._clear_memory, borderwidth=1, padx=8).pack(side="left", padx=8)
        tk.Button(btn_f, text="CLEAR HISTORY", bg=BG, fg=RED, font=FONT_XS,
                  command=self._clear_history, borderwidth=1, padx=8).pack(side="left")

    # ---------------- Advanced: context window ----------------

    def _on_ctx_mode_change(self):
        """Enable the entry only in custom mode, and prefill a sane default."""
        if self.ctx_mode.get() == "custom":
            self.ctx_entry.configure(state="normal")
            if not self.ctx_entry.get().strip():
                self.ctx_entry.insert(0, "8192")
            self.ctx_entry.focus_set()
        else:
            self.ctx_entry.configure(state="disabled")

    @staticmethod
    def _safe_ctx_for(vram_gb, model_name):
        """Largest context that keeps weights + KV cache inside VRAM.

        Reads both numbers from the catalog rather than matching "14B" and
        "7B" as substrings of the filename, which is what this did while
        the catalog was Qwen2.5. That version returned None for any name it
        did not recognise, so every Qwen3.5 filename would have silently
        blanked the "what your card could handle" figure in Settings.

        KV cache is quantized to q8_0. The per-token cost is measured, not
        derived, and is the same for every model in this family; see
        KV_CACHE_GB_PER_1K. Returns None when we cannot tell.
        """
        if not vram_gb or not model_name:
            return None
        # Local import: the desktop shell talks to the API over HTTP and
        # deliberately does not pull the model stack in at startup.
        try:
            from core.model_manager import MODEL_PROFILE, KV_CACHE_GB_PER_1K
        except ImportError:
            return None
        profile = MODEL_PROFILE.get(model_name)
        if profile is None:
            return None
        # Leave 1 GB for compute buffers and the desktop.
        free = vram_gb - profile["weight_gb"] - 1.0
        if free <= 0:
            return 2048
        tokens = int((free / KV_CACHE_GB_PER_1K) * 1024)
        # Ladder stops at the trained window; past it quality falls off
        # even when the card could hold more.
        for step in (262144, 131072, 65536, 32768, 16384, 8192, 4096, 2048):
            if tokens >= step:
                return step
        return 2048

    def _load_context_setting(self):
        """Reflect the saved override, and report what is actually running."""
        try:
            import config
            current = config.load_context_override()
        except Exception as exc:
            self.ctx_status.configure(text=f"Could not read setting: {exc}", fg=RED)
            return

        if current is None:
            self.ctx_mode.set("auto")
            self.ctx_entry.configure(state="normal")
            self.ctx_entry.delete(0, "end")
            self.ctx_entry.configure(state="disabled")
            saved_text = "Auto-sized to fit your GPU."
        else:
            self.ctx_mode.set("custom")
            self.ctx_entry.configure(state="normal")
            self.ctx_entry.delete(0, "end")
            self.ctx_entry.insert(0, str(current))
            saved_text = f"Custom: {current} tokens."
        self.ctx_status.configure(text=saved_text, fg=FG_DIM)

        # Fetch the live value so the user does not have to read the console
        # to find out what context the model actually loaded with.
        def do():
            payload = api_get("/api/models")
            if not isinstance(payload, dict):
                return
            st = payload.get("status") or {}
            live = st.get("context_window")
            vram = st.get("vram_gb")
            model = st.get("current_model") or ""
            if not live:
                return
            bits = [saved_text, f"Running now: {live} tokens."]
            headroom = self._safe_ctx_for(vram, model)
            if headroom and vram:
                if headroom > live:
                    bits.append(f"Your {vram} GB GPU could handle about "
                                f"{headroom} with this model.")
                elif headroom < live:
                    bits.append(f"Warning: about {headroom} is what your "
                                f"{vram} GB GPU fits comfortably. Above that "
                                f"it spills to system RAM and slows down.")
            text = "  ".join(bits)
            self.after(0, lambda: self.ctx_status.configure(text=text, fg=FG_DIM))

        threading.Thread(target=do, daemon=True).start()

    def _load_thinking_setting(self):
        try:
            import config
            enabled = config.load_thinking_enabled()
        except Exception as exc:
            self.thinking_status.configure(text=f"Could not load: {exc}", fg=RED)
            return
        self.thinking_var.set(enabled)
        self._describe_thinking(enabled)

    def _describe_thinking(self, enabled):
        if enabled:
            self.thinking_status.configure(
                text=("On. Answers are slower and spend most of the token "
                      "budget reasoning first; on short questions the model "
                      "can run out before it answers. Raise max tokens if "
                      "you keep this on."),
                fg=AMBER)
        else:
            self.thinking_status.configure(
                text=("Off. The model answers directly, which is what the "
                      "context and token budgets are sized for."),
                fg=FG_DIM)

    def _save_thinking_setting(self):
        enabled = bool(self.thinking_var.get())
        try:
            import config
            config.save_thinking_enabled(enabled)
        except Exception as exc:
            self.thinking_status.configure(text=f"Could not save: {exc}", fg=RED)
            return
        self._describe_thinking(enabled)

    def _save_context_setting(self):
        """Validate and persist. Bad input gets a message, never a crash."""
        try:
            import config
        except Exception as exc:
            self.ctx_status.configure(text=f"Could not load config: {exc}", fg=RED)
            return

        if self.ctx_mode.get() == "auto":
            try:
                config.save_context_override(None)
            except Exception as exc:
                self.ctx_status.configure(text=f"Could not save: {exc}", fg=RED)
                return
            self.ctx_status.configure(
                text="Saved. Auto-sizing restored. Reload the model to apply.",
                fg=GREEN)
            return

        raw = self.ctx_entry.get().strip()
        if not raw.isdigit():
            self.ctx_status.configure(
                text="Enter a whole number of tokens, for example 8192.", fg=RED)
            return

        try:
            config.save_context_override(int(raw))
        except ValueError as exc:
            self.ctx_status.configure(text=str(exc), fg=RED)
            return
        except Exception as exc:
            self.ctx_status.configure(text=f"Could not save: {exc}", fg=RED)
            return

        self.ctx_status.configure(
            text=f"Saved: {raw} tokens. Reload the model in the Models tab to apply.",
            fg=GREEN)

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

        # Hardware. Answers "what can this machine run", which is what
        # people expect a benchmark button to tell them and what the old
        # one never did: it only ever timed the model already loaded.
        tk.Label(inner, text="# HARDWARE", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(16, 8))

        self.hw_text = tk.Text(inner, bg=BG, fg=FG, font=FONT_SM, height=10,
                               state="disabled", borderwidth=0,
                               highlightthickness=0)
        self.hw_text.pack(fill="x", padx=16)
        for tag, colour in (("key", FG_DIM), ("val", FG_BRIGHT),
                            ("green", GREEN), ("amber", AMBER),
                            ("red", RED), ("cyan", CYAN)):
            self.hw_text.tag_configure(tag, foreground=colour)

        # Benchmark
        tk.Label(inner, text="# BENCHMARK", fg=GREEN, bg=BG,
                 font=("Consolas", 12, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 8))

        bench_f = tk.Frame(inner, bg=BG)
        bench_f.pack(fill="x", padx=16)
        tk.Button(bench_f, text="RUN BENCHMARK", bg=BG, fg=GREEN, font=("Consolas", 10, "bold"),
                  command=self._run_benchmark, borderwidth=1, padx=10).pack(side="left")

        self.bench_result = tk.Text(inner, bg=BG, fg=FG, font=FONT_SM, height=8,
                                     state="disabled", borderwidth=0, highlightthickness=0)
        self.bench_result.pack(fill="x", padx=16, pady=8)
        self.bench_result.tag_configure("key", foreground=FG_DIM)
        self.bench_result.tag_configure("val", foreground=FG_BRIGHT)
        self.bench_result.tag_configure("green", foreground=GREEN)
        self.bench_result.tag_configure("amber", foreground=AMBER)

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

    def _load_hardware(self):
        """Render the capability table. Needs no model loaded."""
        def do():
            r = api_get("/api/hardware")

            def show():
                w = self.hw_text
                w.configure(state="normal")
                w.delete("1.0", "end")
                if r.get("error"):
                    w.insert("end", f"  {r['error']}\n", "red")
                    w.configure(state="disabled")
                    return
                gpu = r.get("gpu") or "none detected"
                w.insert("end", f"  {'gpu':>14s} : ", "key")
                w.insert("end", f"{gpu}\n", "green" if r.get("cuda") else "amber")
                w.insert("end", f"  {'vram':>14s} : ", "key")
                w.insert("end", f"{r.get('vram_gb', 0)} GB\n", "val")
                w.insert("end", f"  {'system ram':>14s} : ", "key")
                w.insert("end", f"{r.get('ram_gb', 0)} GB\n", "val")
                w.insert("end", f"  {'kv cache':>14s} : ", "key")
                w.insert("end", f"{r.get('kv_gb_per_1k', 0)} GB per 1024 tokens "
                                f"(measured)\n", "cyan")
                w.insert("end", "\n  models this machine can run:\n", "key")
                for m in r.get("models", []):
                    tag = {"gpu": "green", "cpu": "amber"}.get(m["verdict"], "red")
                    w.insert("end", f"    {m['name']:<26} ", "val")
                    w.insert("end", f"{m['note']}\n", tag)
                w.configure(state="disabled")
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
                    t.configure(state="disabled")
                    return
                rows = [
                    ("model", r.get("model", "?"), "green"),
                    ("tokens", f"{r.get('tokens', 0)} of "
                               f"{r.get('requested_tokens', 0)} requested", "val"),
                    ("speed", f"{r.get('tps', 0):.1f} tok/s",
                     "green" if r.get("complete") else "amber"),
                    ("elapsed", f"{r.get('elapsed', 0)}s", "val"),
                ]
                for label, value, tag in rows:
                    t.insert("end", f"  {label:>8s} : ", "key")
                    t.insert("end", f"{value}\n", tag)
                if not r.get("complete"):
                    # A run that stopped early measured mostly fixed
                    # overhead, so the speed above is not a throughput
                    # figure. Say so rather than let it read as one.
                    t.insert("end", "\n  short run, speed is not reliable\n",
                             "amber")
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
            self.after(0, self._load_hardware)
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
                         "poor": "tools: untested on this model"}.get(tier, "tools: --")
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
