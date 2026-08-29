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

from core.model_catalog import HUGGINGFACE_BROWSE_URL

# The design tokens and the shared components both live in desktop_ui, so
# there is one place a colour, a font, or a card border is decided. The
# names below are re-exported here unchanged, which is why nothing in the
# chat panel had to move when the other four panels were rebuilt.
import desktop_ui as ui
from desktop_ui import (
    AMBER, BG, BG2, BLUE, BORDER, CONTENT_MAX_W, CYAN, FG, FG_BRIGHT,
    FG_DIM, FONT, FONT_ASCII, FONT_MONO_XS, FONT_SM, FONT_TITLE, FONT_XS,
    GREEN, GREEN_DIM, MONO, RED, SANS, USER_BUBBLE_FG,
)

# ============ CONFIG ============
PORT = 8080
API = f"http://127.0.0.1:{PORT}"
API_TOKEN = ""


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
        # under clam does not. Chat defined this style itself and named it
        # Chat.Vertical.TScrollbar; it now comes from desktop_ui under a
        # neutral name, because every scrolling panel needs the same one and
        # a second copy of it is a second thing to keep in step.
        ui.install_styles(self.style)
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

        # Panels. Only the frame style survives here: the seven ttk label
        # styles and the two ttk button styles that used to sit below were
        # defined and never referenced by a single widget, because every
        # panel reached for a raw tk widget with inline colours instead.
        # desktop_ui.button and the tone vocabulary replace them.
        s.configure("Panel.TFrame", background=BG)

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
        else:
            # A panel that was hidden while its content changed has a stale
            # scroll region, which shows up as a scrollbar sized for the
            # wrong height until the next resize.
            panel = self.panels.get(name)
            if isinstance(panel, ui.Page):
                panel.refresh()

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
            transcript, orient="vertical", style=ui.SCROLLBAR_STYLE,
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
            self.resume_status_label.error(f"Read failed: {exc}")
            return

        if len(data) > 5 * 1024 * 1024:
            self.resume_status_label.error("File too large (5 MB max).")
            return

        self.resume_status_label.busy("Uploading...")

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
                    msg += f"  |  drafter base updated ({drafter.get('chars', 0)} chars)"
                elif drafter.get("error"):
                    # Upload succeeded but extract failed (e.g. image-only PDF).
                    msg += f"  |  drafter extract failed: {drafter['error']}"
                self.after(0, lambda: self.resume_status_label.ok(msg))
                self.after(0, self._refresh_resume_status)
            else:
                err = r.get("error", "Upload failed")
                self.after(0, lambda: self.resume_status_label.error(f"Failed: {err}"))

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
                self.after(0, lambda: self.resume_status_label.info(
                    "No resume selected."))
                self.after(0, self._refresh_resume_status)
            except Exception as exc:
                self.after(0, lambda e=exc: self.resume_status_label.error(
                    f"Clear failed: {e}"))

        threading.Thread(target=do_clear, daemon=True).start()

    def _refresh_resume_status(self):
        """Update the Settings card AND the topbar resume indicator."""
        def do():
            r = api_get("/api/resume")

            def show():
                if r.get("active"):
                    name = r.get("filename", "active")
                    size_kb = max(1, r.get("size", 0) // 1024)
                    self.resume_status_label.ok(
                        f"Active resume: {name} ({size_kb} KB)")
                    self.status_resume.configure(text=f"resume: {name}", foreground=GREEN)
                else:
                    self.resume_status_label.info("No resume selected.")
                    self.status_resume.configure(text="resume: none", foreground=FG_DIM)
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()


    # ========== DOCS PANEL ==========
    def _build_docs_panel(self):
        """What is indexed, and the files behind it.

        The old version put the file list in a bare Text with no scrollbar,
        so a folder holding more files than the window was tall had no way
        to reach the rest of them. It also had one label carrying both the
        file count and the result of a re-index, which meant starting an
        index wiped the count. Those are two facts and they now have two
        widgets.
        """
        page = ui.Page(self, "# DOCUMENTS",
                       "Files under data/docs, split into chunks and "
                       "embedded into a local index. Nothing is uploaded.")
        self.panels["docs"] = page

        index_card = ui.Card(page.body, "INDEX")
        index_card.pack(fill="x", pady=(0, ui.PAD_MD))

        self.docs_summary = ui.Readout(index_card.body, key_width=11)
        self.docs_summary.pack(fill="x")
        self.docs_summary.show("Loading...")

        ui.button_row(index_card.body, [
            ("RE-INDEX", self._reindex, "primary"),
            ("REFRESH", self._load_docs, "secondary"),
        ]).pack(anchor="w", pady=(ui.PAD_MD, 0))

        self.docs_status = ui.StatusLine(index_card.body)
        self.docs_status.pack(fill="x", pady=(ui.PAD_SM, 0))

        files_card = ui.Card(page.body, "FILES")
        files_card.pack(fill="x", pady=(0, ui.PAD_XL))
        self.docs_list = ui.Readout(files_card.body)
        self.docs_list.pack(fill="x")
        self.docs_list.show("Loading...")

    def _load_docs(self):
        def do():
            r = api_get("/api/docs/list")
            files = r.get("files", [])
            total = r.get("total_size", 0)

            def show():
                self.docs_summary.begin()
                self.docs_summary.row("files", str(len(files)),
                                      "val" if files else "warn")
                self.docs_summary.row("total size", self._fmt_bytes(total))
                self.docs_summary.end()
                if not files:
                    # Naming the folder is the whole answer to "why is this
                    # empty", and the old blank list did not give it.
                    self.docs_list.show(
                        "  Nothing indexed yet. Put PDF, DOCX, TXT or MD "
                        "files in data/docs, then press RE-INDEX.", "warn")
                    return
                self.docs_list.begin()
                for f in files:
                    self.docs_list.write(f"  {f['extension'] or '--':<7s}",
                                         "cyan")
                    self.docs_list.write(f"{ui.truncate(f['name'], 58):<60s}",
                                         "val")
                    self.docs_list.line(self._fmt_bytes(f["size"]), "dim")
                self.docs_list.end()
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _reindex(self):
        self.docs_status.busy("Re-indexing. This reads every file and "
                              "rebuilds the vector index.")

        def do():
            r = api_post("/api/ingest")
            if r.get("status") == "ok":
                vectors = r.get("vectors", 0)
                self.after(0, lambda: self.docs_status.ok(
                    f"Indexed. {vectors} vectors."))
                self.after(500, self._load_status)
                self.after(500, self._load_docs)
            else:
                msg = r.get("message") or r.get("error") or "Index failed."
                self.after(0, lambda m=msg: self.docs_status.error(m))
        threading.Thread(target=do, daemon=True).start()

    # ========== MODELS PANEL ==========
    def _build_models_panel(self):
        """Runtime facts, the Hugging Face adder, then one card per model.

        The panel used to nest its own Canvas and Scrollbar inside the tab
        so the model list could scroll, while the two sections above it
        stayed fixed and the wheel did nothing anywhere. The whole page now
        scrolls as one, from the Page component, and the hand-rolled canvas
        is gone.
        """
        page = ui.Page(self, "# MODELS",
                       "GGUF models run locally through llama.cpp. "
                       "Switching unloads the current model before it "
                       "loads the new one.")
        self.panels["models"] = page

        runtime = ui.Card(page.body, "RUNTIME")
        runtime.pack(fill="x", pady=(0, ui.PAD_MD))
        self.models_runtime = ui.Readout(runtime.body, key_width=10)
        self.models_runtime.pack(fill="x")
        self.models_runtime.show("Loading...")
        self.models_status = ui.StatusLine(runtime.body)
        self.models_status.pack(fill="x", pady=(ui.PAD_SM, 0))

        # Download progress. Hidden until a download starts, because an
        # empty bar sitting on screen reads as a broken one.
        self.dl_frame = tk.Frame(runtime.body, bg=BG2)
        self.dl_bar = ttk.Progressbar(self.dl_frame, mode="determinate",
                                      maximum=100, length=420,
                                      style=ui.PROGRESS_STYLE)
        self.dl_bar.pack(fill="x")
        self.dl_label = tk.Label(self.dl_frame, text="", fg=FG_DIM, bg=BG2,
                                 font=FONT_MONO_XS, anchor="w")
        self.dl_label.pack(fill="x", pady=(ui.PAD_XS, 0))

        # --- add from Hugging Face -------------------------------------
        # The catalog used to be a fixed list, so the only models the app
        # could run were the ones written into config.py. Anything on the
        # Hub in GGUF form works; what it needed was a way to say which.
        add_card = ui.Card(page.body, "ADD FROM HUGGING FACE")
        add_card.pack(fill="x", pady=(0, ui.PAD_MD))

        ui.hint(add_card.body,
                "Browse huggingface.co for a model in GGUF format, copy the "
                "address from your browser, and paste it below. Quantized "
                "files ending Q4_K_M are the usual balance of size and "
                "quality.").pack(fill="x")
        ui.link(add_card.body, HUGGINGFACE_BROWSE_URL,
                HUGGINGFACE_BROWSE_URL).pack(fill="x", pady=(ui.PAD_SM, 0))

        row = ui.field_row(add_card.body, "repo url")
        row.pack(fill="x", pady=(ui.PAD_MD, 0))
        self.hf_entry = ui.entry(row, font=FONT)
        self.hf_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.hf_entry.bind("<Return>", lambda e: self._browse_hf_repo())
        ui.button(row, "BROWSE", self._browse_hf_repo,
                  kind="primary").pack(side="left", padx=(ui.PAD_SM, 0))

        self.hf_status = ui.StatusLine(add_card.body)
        self.hf_status.pack(fill="x", pady=(ui.PAD_SM, 0))

        # Results of a browse: one row per quant, each with its size.
        self.hf_results = tk.Frame(add_card.body, bg=BG2)
        self.hf_results.pack(fill="x")

        # One card per model, rebuilt on every refresh.
        self.models_inner = tk.Frame(page.body, bg=BG)
        self.models_inner.pack(fill="x", pady=(0, ui.PAD_XL))

    def _load_models(self):
        def do():
            payload = api_get("/api/models")
            if isinstance(payload, dict) and payload.get("error"):
                self.after(0, lambda: self.models_status.error(payload["error"]))
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
        """One card per model, plus the runtime facts above them.

        GPU state used to be written into the same label that reports the
        result of a switch or a download, so starting a download replaced
        the only statement of whether the GPU was even in use.
        """
        for w in self.models_inner.winfo_children():
            w.destroy()

        gpu = status.get("gpu_supported")
        out = self.models_runtime.begin()
        out.row("model", status.get("current_model") or "none loaded",
                "ok" if status.get("loaded") else "warn")
        if gpu:
            out.row("gpu", "enabled", "ok")
            # default_gpu_layers() returns 999 as "offload everything";
            # llama.cpp caps it at the model's real layer count. Printing
            # the sentinel, which is what this did, tells the user nothing.
            layers = status.get("gpu_layers", 0)
            out.row("layers", "all offloaded" if layers >= 999
                    else f"{layers} offloaded")
        elif gpu is False:
            out.row("gpu", "not available", "warn")
            out.row("reason", "llama-cpp built without CUDA, or no NVIDIA "
                              "GPU", "dim")
        if status.get("context_window"):
            out.row("context", f"{status['context_window']} tokens")
        if status.get("vram_gb"):
            out.row("vram", f"{status['vram_gb']} GB")
        out.end()

        for m in models:
            active = bool(m.get("active"))
            card = ui.Card(self.models_inner, m["name"],
                           accent=GREEN if active else FG_BRIGHT)
            card.pack(fill="x", pady=(0, ui.PAD_MD))
            if active:
                card.head_right(ui.badge(card.head, "ACTIVE", "ok"))

            facts = ui.Readout(card.body, key_width=8).begin()
            facts.row("file", ui.truncate(m["filename"], 84), "dim")
            facts.row("size", f"{m['size']}, needs {m['ram']} RAM")
            if m.get("repo"):
                facts.row("repo", ui.truncate(m["repo"], 84), "dim")
            facts.row("status",
                      "downloaded" if m["downloaded"] else "not downloaded",
                      "ok" if m["downloaded"] else "warn")
            facts.end()
            facts.pack(fill="x")

            if not m["downloaded"]:
                ui.button(card.body, "DOWNLOAD",
                          lambda f=m["filename"], i=m: self._download_model(f, i),
                          kind="primary").pack(anchor="w", pady=(ui.PAD_MD, 0))
            elif not active:
                ui.button(card.body, "SWITCH",
                          lambda f=m["filename"], n=m["name"]: self._switch_model(f, n),
                          kind="secondary").pack(anchor="w", pady=(ui.PAD_MD, 0))

        self.panels["models"].refresh()

    def _browse_hf_repo(self):
        """Ask the backend what quants a pasted repo offers."""
        ref = self.hf_entry.get().strip()
        if not ref:
            self.hf_status.warn("Paste a model URL first.")
            return
        for child in self.hf_results.winfo_children():
            child.destroy()
        self.hf_status.busy("Looking up the repo...")

        def do():
            r = api_post("/api/models/browse", {"ref": ref})

            def show():
                if r.get("error"):
                    self.hf_status.error(r["error"])
                    return
                files = r.get("files", [])
                self.hf_status.ok(
                    f"{r.get('repo')}  ({r.get('license', 'unknown')} "
                    f"license)  {len(files)} file(s)")
                # Largest first: the better quants are the bigger ones, and
                # they are what someone with room should be choosing.
                for f in sorted(files, key=lambda x: -x.get("size_gb", 0))[:14]:
                    self._render_hf_file(r["repo"], f)
                self.panels["models"].refresh()
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _render_hf_file(self, repo, f):
        row = tk.Frame(self.hf_results, bg=BG2)
        row.pack(fill="x", pady=(ui.PAD_XS, 0))
        label = f"{f['size_gb']:>6.2f} GB   {ui.truncate(f['filename'], 64)}"
        tk.Label(row, text=label, fg=FG, bg=BG2, font=FONT_MONO_XS,
                 anchor="w").pack(side="left", fill="x", expand=True)
        if f.get("downloadable"):
            ui.button(row, "DOWNLOAD",
                      lambda: self._add_hf_model(repo, f["filename"]),
                      kind="primary", pad=(8, 2)).pack(side="right")
        else:
            # A split quant needs every part; hf_hub_download fetches one
            # file by name, so say why rather than offering a button that
            # cannot work.
            tk.Label(row, text="split, not supported", fg=AMBER, bg=BG2,
                     font=FONT_MONO_XS).pack(side="right", padx=ui.PAD_SM)

    def _add_hf_model(self, repo, filename):
        self.hf_status.busy(
            f"Downloading {filename}. This can take several minutes.")

        def do():
            r = api_post("/api/models/add", {"repo": repo, "filename": filename})

            def show():
                if r.get("error"):
                    self.hf_status.error(r["error"])
                    return
                profile = (r.get("entry") or {}).get("profile", {})
                self.hf_status.ok(
                    f"Added {filename}: {profile.get('architecture', '?')}, "
                    f"{profile.get('weight_gb', '?')} GB, trained context "
                    f"{profile.get('trained_context', '?')}.")
                # The new model changes both lists, and the hardware panel
                # can now say whether it fits.
                self._load_models()
                self._load_hardware()
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _switch_model(self, filename, friendly_name):
        if not messagebox.askyesno("Switch model",
                                    f"Unload current model and load {friendly_name}?\n\nThis frees the active model from RAM/VRAM before loading the new one."):
            return
        self.models_status.busy(f"Loading {friendly_name}...")

        def do():
            r = api_post("/api/models/switch", {"filename": filename})
            if r.get("error"):
                self.after(0, lambda: self.models_status.error(r["error"]))
                return
            self.after(0, lambda: self.models_status.ok(
                f"Loaded {friendly_name}"))
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

        self.models_status.busy(f"Downloading {info['name']}...")
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
                        self.after(0, lambda: self.models_status.ok(
                            f"Downloaded {filename}."))
                        self.after(0, lambda: self._show_progress(False))
                        self.after(0, self._load_models)
                    elif ctype == "error":
                        msg = chunk.get("message", "download failed")
                        self.after(0, lambda m=msg: self.models_status.error(
                            f"Error: {m}"))
                        self.after(0, lambda: self._show_progress(False))
            except Exception as e:
                self.after(0, lambda err=e: self.models_status.error(str(err)))
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
            self.dl_frame.pack(fill="x", pady=(ui.PAD_MD, 0))
            self.dl_bar.configure(value=0)
            self.dl_label.configure(text="starting...")
        else:
            self.dl_bar.stop()
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
            self.dl_label.configure(text="downloading...")
        self.models_status.busy(f"Downloading {filename}...")

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
        """Five cards, one per thing the user can change.

        This panel held the most content and the least structure: two page
        headings, four unheaded groups, and one row of three destructive
        buttons at the very bottom that mixed a harmless REFRESH with two
        that delete things. It also did not scroll, and it is taller than
        the 700px default window, so those bottom buttons could not be
        reached at all without resizing. Each concern is now a card, the
        destructive actions sit with the thing they destroy, and the page
        scrolls.
        """
        page = ui.Page(self, "# SETTINGS",
                       "What the assistant remembers between sessions, and "
                       "the knobs that change how the model runs.")
        self.panels["settings"] = page

        # --- memory ----------------------------------------------------
        mem_card = ui.Card(page.body, "MEMORY",
                           "Preferences and facts injected into the context "
                           "of every query.")
        mem_card.pack(fill="x", pady=(0, ui.PAD_MD))

        kv_row = ui.field_row(mem_card.body, "key")
        kv_row.pack(fill="x")
        self.mem_key = ui.entry(kv_row, width=18)
        self.mem_key.pack(side="left", ipady=3)

        val_row = ui.field_row(mem_card.body, "value")
        val_row.pack(fill="x", pady=(ui.PAD_SM, 0))
        self.mem_val = ui.entry(val_row)
        self.mem_val.pack(side="left", fill="x", expand=True, ipady=3)
        ui.button(val_row, "SET", self._set_memory, kind="primary").pack(
            side="left", padx=(ui.PAD_SM, 0))

        inst_row = ui.field_row(mem_card.body, "instruction")
        inst_row.pack(fill="x", pady=(ui.PAD_SM, 0))
        self.mem_inst = ui.entry(inst_row)
        self.mem_inst.pack(side="left", fill="x", expand=True, ipady=3)
        ui.button(inst_row, "REMEMBER", self._add_instruction,
                  kind="primary").pack(side="left", padx=(ui.PAD_SM, 0))

        ui.divider(mem_card.body).pack(fill="x", pady=ui.PAD_MD)
        ui.section_label(mem_card.body, "CURRENTLY REMEMBERED").pack(fill="x")
        self.mem_display = ui.Readout(mem_card.body, key_width=12)
        self.mem_display.pack(fill="x", pady=(ui.PAD_SM, 0))
        self.mem_display.show("Loading...")
        ui.button_row(mem_card.body, [
            ("REFRESH", self._load_memory, "secondary"),
            ("CLEAR MEMORY", self._clear_memory, "danger"),
        ]).pack(anchor="w", pady=(ui.PAD_MD, 0))

        # --- context window --------------------------------------------
        ctx_card = ui.Card(page.body, "CONTEXT WINDOW",
                           "How much the model can hold at once: prompt, "
                           "documents, and reply together.")
        ctx_card.pack(fill="x", pady=(0, ui.PAD_MD))
        ui.hint(ctx_card.body,
                "Auto picks the largest size that fits your GPU. Raise it to "
                "work with longer documents, at the cost of speed and "
                "memory. Takes effect the next time the model loads.").pack(
            fill="x")

        ctx_frame = tk.Frame(ctx_card.body, bg=BG2)
        ctx_frame.pack(fill="x", pady=(ui.PAD_MD, 0))
        self.ctx_mode = tk.StringVar(value="auto")
        ui.radio(ctx_frame, "Auto (recommended)", self.ctx_mode, "auto",
                 self._on_ctx_mode_change).pack(side="left")
        ui.radio(ctx_frame, "Custom", self.ctx_mode, "custom",
                 self._on_ctx_mode_change).pack(side="left", padx=(ui.PAD_MD, 0))
        self.ctx_entry = ui.entry(ctx_frame, width=8)
        self.ctx_entry.configure(state="disabled")
        self.ctx_entry.pack(side="left", padx=ui.PAD_SM, ipady=3)
        tk.Label(ctx_frame, text="tokens", fg=FG_DIM, bg=BG2,
                 font=FONT_XS).pack(side="left")
        ui.button(ctx_frame, "SAVE", self._save_context_setting,
                  kind="primary").pack(side="left", padx=(ui.PAD_MD, 0))

        self.ctx_status = ui.StatusLine(ctx_card.body)
        self.ctx_status.pack(fill="x", pady=(ui.PAD_SM, 0))
        ui.hint(ctx_card.body,
                "4096 short chats   8192 default   16384 long documents   "
                "262144 model maximum").pack(fill="x", pady=(ui.PAD_SM, 0))
        self._load_context_setting()

        # --- resume ----------------------------------------------------
        # Lived in the Jobs tab until that was removed. It never belonged
        # there: the resume feeds usajobs_search's match scoring and the
        # federal resume drafter, neither of which had anything to do with
        # the Indeed search the tab was built around.
        resume_card = ui.Card(page.body, "RESUME",
                              "Scores USAJOBS results against your "
                              "background and feeds the federal resume "
                              "drafter. PDF, DOCX, TXT or MD.")
        resume_card.pack(fill="x", pady=(0, ui.PAD_MD))
        self.resume_status_label = ui.StatusLine(resume_card.body)
        self.resume_status_label.pack(fill="x")
        resume_buttons = ui.button_row(resume_card.body, [
            ("CHOOSE FILE", self._choose_resume, "primary"),
            ("CLEAR", self._clear_resume, "danger"),
        ])
        resume_buttons.pack(anchor="w", pady=(ui.PAD_MD, 0))
        self.resume_choose_btn, self.resume_clear_btn = resume_buttons.buttons
        self._refresh_resume_status()

        # --- job eligibility -------------------------------------------
        # Federal postings are gated on hiring path, and the gate is a fact
        # about the person that no amount of reading their resume will
        # produce: a resume does not say whether somebody is a veteran, a
        # current federal employee, or still enrolled. Before this existed
        # the search ranked by resume similarity alone, which put a
        # federal-employees-only vacancy above a Pathways posting the user
        # was actually eligible for.
        elig_card = ui.Card(page.body, "JOB ELIGIBILITY",
                            "Tick anything that applies to you. Federal "
                            "postings state who may apply, and the search "
                            "uses this to hide the ones you cannot.")
        elig_card.pack(fill="x", pady=(0, ui.PAD_MD))
        ui.hint(elig_card.body,
                "Everyone can apply to postings open to the public, so that "
                "one is always on and is not listed here.").pack(fill="x")

        self.elig_vars = {}
        try:
            from jobs.eligibility import PROFILE_CHOICES
            active = set(self._load_job_profile())
        except Exception as exc:
            ui.hint(elig_card.body, f"Could not load: {exc}",
                    tone="error").pack(fill="x", pady=(ui.PAD_SM, 0))
            PROFILE_CHOICES, active = (), set()

        for key, label, explanation in PROFILE_CHOICES:
            var = tk.BooleanVar(value=key in active)
            self.elig_vars[key] = var
            ui.check(elig_card.body, label, var,
                     self._save_job_profile).pack(fill="x",
                                                  pady=(ui.PAD_SM, 0))
            ui.hint(elig_card.body, explanation).pack(
                fill="x", padx=(ui.PAD_XL, 0))

        self.elig_status = ui.StatusLine(elig_card.body)
        self.elig_status.pack(fill="x", pady=(ui.PAD_MD, 0))
        self._describe_job_profile(active)

        # --- reasoning -------------------------------------------------
        # Off by default. Measured on Qwen3.5 9B, "What is 2+2?" costs 1
        # token and 0.3s with this off, and 2048 tokens and 52s with it on,
        # where 2048 is MAX_NEW_TOKENS: the model is still reasoning when
        # the budget runs out and never reaches an answer. Enabling it is
        # only sensible alongside a much larger token ceiling, which is
        # what the warning below says.
        think_card = ui.Card(page.body, "REASONING",
                             "Whether the model works through a problem "
                             "out loud before it answers.")
        think_card.pack(fill="x", pady=(0, ui.PAD_MD))
        self.thinking_var = tk.BooleanVar(value=False)
        ui.check(think_card.body,
                 "Let the model think out loud before answering",
                 self.thinking_var, self._save_thinking_setting).pack(
            fill="x")
        self.thinking_status = ui.StatusLine(think_card.body)
        self.thinking_status.pack(fill="x", pady=(ui.PAD_SM, 0))
        self._load_thinking_setting()

        # --- session ---------------------------------------------------
        session_card = ui.Card(page.body, "SESSION")
        session_card.pack(fill="x", pady=(0, ui.PAD_XL))
        ui.hint(session_card.body,
                "Forgets the running conversation. Indexed documents and "
                "everything under MEMORY are untouched.").pack(fill="x")
        ui.button_row(session_card.body, [
            ("CLEAR HISTORY", self._clear_history, "danger"),
        ]).pack(anchor="w", pady=(ui.PAD_MD, 0))
        self.session_status = ui.StatusLine(session_card.body)
        self.session_status.pack(fill="x", pady=(ui.PAD_SM, 0))

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
            self.ctx_status.error(f"Could not read setting: {exc}")
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
        self.ctx_status.info(saved_text)

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
            tone = "info"
            headroom = self._safe_ctx_for(vram, model)
            if headroom and vram:
                if headroom > live:
                    bits.append(f"Your {vram} GB GPU could handle about "
                                f"{headroom} with this model.")
                elif headroom < live:
                    tone = "warn"
                    bits.append(f"About {headroom} is what your {vram} GB "
                                f"GPU fits comfortably. Above that it spills "
                                f"to system RAM and slows down.")
            text = "  ".join(bits)
            self.after(0, lambda: self.ctx_status.set(text, tone))

        threading.Thread(target=do, daemon=True).start()

    # ---------------- job eligibility ----------------

    @staticmethod
    def _load_job_profile():
        import config
        return config.load_job_profile()

    def _save_job_profile(self):
        """Persist the ticked hiring paths and say what they now mean."""
        chosen = [key for key, var in self.elig_vars.items() if var.get()]
        try:
            import config
            config.save_job_profile(chosen)
        except Exception as exc:
            self.elig_status.error(f"Could not save: {exc}")
            return
        self._describe_job_profile(set(chosen) | {"public"})

    def _describe_job_profile(self, active):
        """Say what the current selection does, in postings rather than flags."""
        claimed = sorted(key for key in active if key != "public")
        if not claimed:
            self.elig_status.info(
                "Public postings only. Anything open solely to federal "
                "employees or a special authority will be hidden from "
                "federal searches.")
            return
        try:
            from jobs.eligibility import PATH_LABELS
            names = ", ".join(PATH_LABELS.get(k, k).lower() for k in claimed)
        except Exception:
            names = ", ".join(claimed)
        self.elig_status.ok(f"Also matching postings open to {names}.")

    def _load_thinking_setting(self):
        try:
            import config
            enabled = config.load_thinking_enabled()
        except Exception as exc:
            self.thinking_status.error(f"Could not load: {exc}")
            return
        self.thinking_var.set(enabled)
        self._describe_thinking(enabled)

    def _describe_thinking(self, enabled):
        if enabled:
            self.thinking_status.warn(
                "On. Answers are slower and spend most of the token budget "
                "reasoning first; on short questions the model can run out "
                "before it answers. Raise max tokens if you keep this on.")
        else:
            self.thinking_status.info(
                "Off. The model answers directly, which is what the context "
                "and token budgets are sized for.")

    def _save_thinking_setting(self):
        enabled = bool(self.thinking_var.get())
        try:
            import config
            config.save_thinking_enabled(enabled)
        except Exception as exc:
            self.thinking_status.error(f"Could not save: {exc}")
            return
        self._describe_thinking(enabled)

    def _save_context_setting(self):
        """Validate and persist. Bad input gets a message, never a crash."""
        try:
            import config
        except Exception as exc:
            self.ctx_status.error(f"Could not load config: {exc}")
            return

        if self.ctx_mode.get() == "auto":
            try:
                config.save_context_override(None)
            except Exception as exc:
                self.ctx_status.error(f"Could not save: {exc}")
                return
            self.ctx_status.ok(
                "Saved. Auto-sizing restored. Reload the model to apply.")
            return

        raw = self.ctx_entry.get().strip()
        if not raw.isdigit():
            self.ctx_status.error(
                "Enter a whole number of tokens, for example 8192.")
            return

        try:
            config.save_context_override(int(raw))
        except ValueError as exc:
            self.ctx_status.error(str(exc))
            return
        except Exception as exc:
            self.ctx_status.error(f"Could not save: {exc}")
            return

        self.ctx_status.ok(
            f"Saved: {raw} tokens. Reload the model in the Models tab to apply.")

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
                out = self.mem_display.begin()
                if r.get("location"):
                    out.row("location", r["location"])
                out.row("units", r.get("units", "imperial"))
                facts = r.get("learned_facts", {})
                if facts:
                    out.blank().line("  learned facts", "key")
                    for k, v in facts.items():
                        out.row(k, str(v), indent=4)
                instr = r.get("custom_instructions", [])
                if instr:
                    out.blank().line("  instructions", "key")
                    for i in instr:
                        out.line(f"    {ui.truncate(str(i), 90)}")
                out.end()
                self.panels["settings"].refresh()
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _clear_memory(self):
        if messagebox.askyesno("Clear Memory", "Clear all user memory?"):
            api_post("/api/memory", {"action": "clear"})
            self._load_memory()

    def _clear_history(self):
        r = api_post("/api/clear_history", {"session_id": self.session_id})
        # This used to fire and say nothing at all, so the only way to tell
        # a cleared history from a dead backend was to ask the model what
        # you had just said.
        if isinstance(r, dict) and r.get("error"):
            self.session_status.error(r["error"])
        else:
            self.session_status.ok("Conversation history cleared.")

    # ========== DEVELOPER PANEL ==========
    def _build_dev_panel(self):
        """System, hardware, and benchmark, one card each.

        The three blocks rendered correctly before, so the content below is
        unchanged. What changed is the container: the hand-rolled canvas is
        replaced by the shared Page, so the wheel works here, and the three
        Text widgets are Readouts, so they size to their own content
        instead of holding a guessed 18, 10, and 8 lines whether or not
        that is what they hold. They are also monospaced now. Every row
        here is written with a right-aligned key column
        (``f"{label:>14s}"``), which lines up only in a fixed-width font,
        and these were set in Segoe UI.
        """
        page = ui.Page(self, "# DEVELOPER",
                       "What this machine is, what it could run, and how "
                       "fast the loaded model actually is.")
        self.panels["developer"] = page

        sys_card = ui.Card(page.body, "SYSTEM")
        sys_card.pack(fill="x", pady=(0, ui.PAD_MD))
        self.sysinfo_text = ui.Readout(sys_card.body, key_width=18)
        self.sysinfo_text.pack(fill="x")
        self.sysinfo_text.show("Loading...")

        # Hardware. Answers "what can this machine run", which is what
        # people expect a benchmark button to tell them and what the old
        # one never did: it only ever timed the model already loaded.
        hw_card = ui.Card(page.body, "HARDWARE",
                          "Read from nvidia-smi and psutil. Needs no model "
                          "loaded.")
        hw_card.pack(fill="x", pady=(0, ui.PAD_MD))
        self.hw_text = ui.Readout(hw_card.body, key_width=14)
        self.hw_text.pack(fill="x")
        self.hw_text.show("Loading...")

        bench_card = ui.Card(page.body, "BENCHMARK",
                             "Times a fixed prompt against the model that "
                             "is loaded right now.")
        bench_card.pack(fill="x", pady=(0, ui.PAD_XL))
        ui.button(bench_card.body, "RUN BENCHMARK", self._run_benchmark,
                  kind="primary").pack(anchor="w")
        self.bench_result = ui.Readout(bench_card.body, key_width=8)
        self.bench_result.pack(fill="x", pady=(ui.PAD_MD, 0))
        self.bench_result.show("Not run yet.")

    def _load_sysinfo(self):
        def do():
            r = api_get("/api/system")
            if r.get("error"):
                # Returning quietly left the block reading "Loading..."
                # forever, which is the one thing it definitely was not
                # doing any more.
                self.after(0, lambda m=r["error"]: self.sysinfo_text.show(
                    f"  {m}", "red"))
                return
            def show():
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
                out = self.sysinfo_text.begin()
                for label, val, tag in pairs:
                    out.row(label, str(val), tag)
                out.end()
                self.model_label.configure(text=r.get("current_model", "?"))
                self.panels["developer"].refresh()
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _load_hardware(self):
        """Render the capability table. Needs no model loaded."""
        def do():
            r = api_get("/api/hardware")

            def show():
                w = self.hw_text
                if r.get("error"):
                    w.show(f"  {r['error']}", "red")
                    return
                w.begin()
                w.row("gpu", r.get("gpu") or "none detected",
                      "green" if r.get("cuda") else "amber")
                w.row("vram", f"{r.get('vram_gb', 0)} GB")
                w.row("system ram", f"{r.get('ram_gb', 0)} GB")
                w.row("kv cache",
                      f"{r.get('kv_gb_per_1k', 0)} GB per 1024 tokens "
                      f"(measured)", "cyan")
                w.blank().line("  models this machine can run:", "key")
                for m in r.get("models", []):
                    tag = {"gpu": "green", "cpu": "amber"}.get(m["verdict"], "red")
                    w.write(f"    {ui.truncate(m['name'], 26):<28}", "val")
                    w.line(m["note"], tag)
                w.end()
                self.panels["developer"].refresh()
            self.after(0, show)
        threading.Thread(target=do, daemon=True).start()

    def _run_benchmark(self):
        self.bench_result.show("  Running benchmark...", "key")

        def do():
            r = api_get("/api/benchmark")

            def show():
                t = self.bench_result
                if r.get("error"):
                    t.show(f"  {r['error']}", "red")
                    return
                rows = [
                    ("model", r.get("model", "?"), "green"),
                    ("tokens", f"{r.get('tokens', 0)} of "
                               f"{r.get('requested_tokens', 0)} requested", "val"),
                    ("speed", f"{r.get('tps', 0):.1f} tok/s",
                     "green" if r.get("complete") else "amber"),
                    ("elapsed", f"{r.get('elapsed', 0)}s", "val"),
                ]
                t.begin()
                for label, value, tag in rows:
                    t.row(label, value, tag)
                if not r.get("complete"):
                    # A run that stopped early measured mostly fixed
                    # overhead, so the speed above is not a throughput
                    # figure. Say so rather than let it read as one.
                    t.blank().line("  short run, speed is not reliable",
                                   "amber")
                t.end()
                self.panels["developer"].refresh()
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
