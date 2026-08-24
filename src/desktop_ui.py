"""Shared UI components for the tkinter desktop shell.

Every panel in ``desktop_app.py`` was built ad hoc. Each one re-declared
its own padding, spelled its own heading font tuple, hand-rolled its own
scroll plumbing, and invented its own idea of what a button looks like.
That is not only why the tabs drift apart visually, it is the root of a
recurring bug class:

* Both panels that scroll built a ``Canvas`` by hand and both forgot the
  mouse wheel, so the only way to reach the bottom of the Developer tab
  was to drag a 10px scrollbar.
* Both panels that do not scroll silently clip themselves. Settings is
  taller than the 700px default window, so its last three buttons were
  unreachable at the default geometry.
* The heading font tuple ``("Consolas", 12, "bold")`` is written out
  eight times. A change to one leaves the other seven behind.
* Read-only output blocks were set in a proportional font while their
  content was padded with ``f"{label:>18s}"``, which only lines up in a
  monospaced one, so every key/value table in the app was ragged.

This module is the single place those decisions live. It holds the design
tokens (colour, type, spacing) and the components built from them: pages,
cards, headings, labelled rows, entries, buttons, status lines,
scrollable areas, and read-only text readouts.

Two rules for anything added here:

1. Nothing in this module imports ``desktop_app``. It knows about tkinter
   and about the tokens below, which is what makes it importable from a
   test on a machine with no running app.
2. Colours and fonts are named here, never spelled inline anywhere else.
   ``tests/test_desktop_ui.py`` reads ``desktop_app.py`` as source and
   fails if a hex colour or a font family string appears in it.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

# ============ COLOUR ============
# The terminal aesthetic is deliberate. Backgrounds step BG -> BG2 -> BG3
# from page to card to raised control, so depth reads from value alone and
# no component needs a drop shadow tkinter cannot draw.
BG = "#1f1f1c"
BG2 = "#262522"
BG3 = "#30302b"
FG = "#d8d4c9"
FG_DIM = "#8f8a80"
FG_BRIGHT = "#f4f0e6"

# Unified green palette (replaces the old orange brand color). All accents,
# borders, button highlights, status pills, and active-tab indicators read
# from these. The naming is preserved (GREEN/AMBER) so existing code keeps
# working, only the hex values have shifted hue.
GREEN = "#7ec890"          # primary accent  (was #d97757 orange)
GREEN_DEEP = "#4ea36b"     # hover / active state for primary buttons
GREEN_DIM = "#3a5a48"      # subtle borders and dividers tinted green
AMBER = "#a8c879"          # secondary / warning (was orange-yellow)
RED = "#e06c62"
CYAN = "#9ab7a5"           # already greenish, kept
BLUE = "#a9b7d0"
BORDER = "#324035"         # slightly green-tinted border (was #3a3833)

# User-message bubble. Distinct dark-green block so the user's turn is
# visually separated from the assistant's turn.
USER_BUBBLE_BG = "#1c3a2e"
USER_BUBBLE_BG_DARK = "#162d24"
USER_BUBBLE_FG = "#e6f0e2"

# ============ TYPE ============
# Two families, on purpose. Chrome (labels, prefixes, status, headings) is
# monospace, which is where the terminal identity lives. Body prose stays
# proportional, because a long answer set in monospace is genuinely harder
# to read and the aesthetic is not worth costing the user that.
#
# Georgia used to supply FONT_TITLE and the empty-state heading. A serif
# belongs to neither half and read as an accident rather than a choice. Do
# not add a third family; test_desktop_ui asserts there are exactly two.
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

# Three levels of heading, and no fourth. Page > card > field label is the
# whole hierarchy, which is as much as a five-tab desktop app needs.
FONT_HEAD = (MONO, 12, "bold")     # page title, one per tab
FONT_CARD = (MONO, 10, "bold")     # card title
FONT_LABEL = (MONO, 9)             # field label inside a card
FONT_BTN = (MONO, 9, "bold")       # every button in the app

# ============ SPACING ============
# One scale. Every pad in a panel is one of these five numbers, so vertical
# rhythm holds without anyone counting pixels at the call site.
PAD_XS = 4
PAD_SM = 8
PAD_MD = 12
PAD_LG = 16
PAD_XL = 24

# The reading column is capped instead of stretching to the window. On a
# 2560px monitor a full-width line is roughly 300 characters, which is
# unreadable; 820px lands near the 70 to 90 characters that prose is
# comfortable at. Chat sizes its transcript and composer from this too.
CONTENT_MAX_W = 820
COMPOSER_MAX_W = 820

# Width of the label column in a field row, in characters. Mono, so a
# character count is a reliable measure. Fits "instruction".
LABEL_COL = 12

# ttk style names owned by this module.
SCROLLBAR_STYLE = "Omni.Vertical.TScrollbar"
PROGRESS_STYLE = "Omni.Horizontal.TProgressbar"

# Tone vocabulary shared by StatusLine, Readout, and badge(). One name per
# meaning, so a status message cannot be green in one panel and cyan in
# the next for the same condition.
TONES = {
    "key": FG_DIM,
    "val": FG_BRIGHT,
    "dim": FG_DIM,
    "body": FG,
    "ok": GREEN,
    "green": GREEN,
    "warn": AMBER,
    "amber": AMBER,
    "busy": AMBER,
    "error": RED,
    "red": RED,
    "info": FG_DIM,
    "cyan": CYAN,
    "blue": BLUE,
}


def tone_color(tone: str) -> str:
    """Colour for a tone name, falling back to body text."""
    return TONES.get(tone, FG)


# ============ ttk STYLES ============

def install_styles(style: ttk.Style) -> None:
    """Register the ttk styles the components need.

    Only two widgets here are ttk: the scrollbar and the progress bar.
    Everything else is classic tk, because on Windows ttk resolves colour
    options against the native theme and quietly ignores half of them.
    The scrollbar has to be ttk for exactly the mirror-image reason: the
    classic ``tk.Scrollbar`` accepts ``bg`` and ``troughcolor`` without
    error and then draws itself with the native theme anyway, so it lands
    as a light grey bar down the side of a dark panel. clam honours the
    colours, and clam is already the active theme.

    Safe to call more than once; element_create raises if the element name
    already exists.
    """
    try:
        style.element_create("Omni.Vertical.Scrollbar.trough", "from", "clam")
        style.element_create("Omni.Vertical.Scrollbar.thumb", "from", "clam")
    except tk.TclError:
        pass

    # No arrow buttons. A 10px thumb on a flat trough is all the affordance
    # a dark panel wants, and the wheel is the real control.
    style.layout(SCROLLBAR_STYLE, [
        ("Omni.Vertical.Scrollbar.trough", {
            "sticky": "ns",
            "children": [
                ("Omni.Vertical.Scrollbar.thumb",
                 {"expand": "1", "sticky": "nswe"}),
            ],
        }),
    ])
    style.configure(
        SCROLLBAR_STYLE,
        background=BG3, troughcolor=BG, bordercolor=BG,
        lightcolor=BG3, darkcolor=BG3, arrowcolor=FG_DIM,
        borderwidth=0, relief="flat", width=10,
    )
    style.map(
        SCROLLBAR_STYLE,
        background=[("active", GREEN_DIM), ("pressed", GREEN_DIM)],
    )

    style.configure(
        PROGRESS_STYLE,
        background=GREEN, troughcolor=BG, bordercolor=BORDER,
        lightcolor=GREEN, darkcolor=GREEN_DEEP,
        borderwidth=0, thickness=6,
    )


# ============ MOUSE WHEEL ============
# The wheel is dispatched from a single application-wide binding rather
# than bound onto each scrollable canvas. Binding the canvas alone does
# nothing useful, because the pointer is almost always over a label or a
# card inside it and the event is delivered to that widget, not the
# canvas. The alternative (walk the tree and bind every descendant) has to
# be re-run every time a panel re-renders its rows, and the models panel
# rebuilds its list on every refresh, so it would rot immediately.
#
# Instead: bind once on "all", then walk up from the widget that received
# the event until a ScrollArea claims it. Nothing to re-bind, ever.

_WHEEL_ATTR = "_omnigab_scroll_area"


def _wheel_steps(event) -> int:
    """Notches scrolled, positive for up. Handles all three conventions."""
    num = getattr(event, "num", None)
    if num == 4:
        return 1
    if num == 5:
        return -1
    delta = getattr(event, "delta", 0) or 0
    if abs(delta) >= 120:
        return int(delta / 120)
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def _dispatch_wheel(event):
    widget = getattr(event, "widget", None)
    # Tk hands back a widget name string for widgets it cannot resolve.
    if isinstance(widget, str):
        return None
    while widget is not None:
        area = getattr(widget, _WHEEL_ATTR, None)
        if area is not None:
            return area.on_wheel(event)
        widget = getattr(widget, "master", None)
    return None


def _install_wheel_dispatch(widget: tk.Misc) -> None:
    top = widget.winfo_toplevel()
    if getattr(top, "_omnigab_wheel_bound", False):
        return
    top._omnigab_wheel_bound = True
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        top.bind_all(sequence, _dispatch_wheel, add="+")


# ============ LAYOUT ============

def column_pad(available: int, max_width: int = CONTENT_MAX_W) -> int:
    """Left inset that centres a column of at most ``max_width``.

    One function so the page header and the scrolling body cannot drift
    apart by a few pixels, which is the sort of thing nobody sees but
    everybody feels.
    """
    return max(PAD_XL, (available - max_width) // 2)


class ScrollArea(tk.Frame):
    """Vertical scroller holding one centred column of at most ``max_width``.

    Pack content into ``.body``. The scrollbar hides itself when the
    content fits, which cannot oscillate: hiding the bar only ever makes
    the column wider, and a wider column is never taller, so a layout that
    fits without the bar still fits.
    """

    def __init__(self, parent: tk.Misc, max_width: int = CONTENT_MAX_W,
                 bg: str = BG) -> None:
        super().__init__(parent, bg=bg)
        self.max_width = max_width

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0,
                                borderwidth=0, takefocus=0)
        # Scroll in pixels rather than the canvas default of a tenth of the
        # visible height per unit, which overshoots badly on a tall window.
        self.canvas.configure(yscrollincrement=1)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical",
                                       style=SCROLLBAR_STYLE,
                                       command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll_set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self._bar_visible = False

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # Wheel dispatch anchor. Widgets inside body are descendants of the
        # canvas, so walking up from any of them reaches this attribute.
        setattr(self.canvas, _WHEEL_ATTR, self)
        _install_wheel_dispatch(self)

    # ----- internals -----

    def _on_body_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event=None) -> None:
        width = event.width if event is not None else self.canvas.winfo_width()
        column = min(width - 2 * PAD_XL, self.max_width)
        column = max(column, 160)
        self.canvas.itemconfigure(self._window, width=column)
        self.canvas.coords(self._window, max(0, (width - column) // 2), 0)

    def _on_scroll_set(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self._bar_visible:
            self.scrollbar.pack(side="right", fill="y", before=self.canvas)
            self._bar_visible = True
        elif not needed and self._bar_visible:
            self.scrollbar.pack_forget()
            self._bar_visible = False

    # ----- public -----

    def on_wheel(self, event):
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return None
        steps = _wheel_steps(event)
        if steps:
            # 48px is three 16px lines, the Windows default for one notch.
            self.canvas.yview_scroll(-steps * 48, "units")
        return "break"

    def refresh(self) -> None:
        """Recompute the scroll region. Call after a panel re-renders."""
        self.update_idletasks()
        self._on_canvas_configure()
        self._on_body_configure()

    def to_top(self) -> None:
        self.canvas.yview_moveto(0.0)


class Page(tk.Frame):
    """A whole tab: title, optional subtitle, then a scrolling card column.

    The header scrolls with the body rather than being pinned above it.
    Pinning it would mean centring two independent widgets against two
    different widths, since the scrolling half loses 10px to its
    scrollbar, and the two columns would sit a few pixels apart. The tab
    strip already names the current page, so a title that scrolls away
    costs nothing.
    """

    def __init__(self, parent: tk.Misc, title: str, subtitle: str | None = None,
                 max_width: int = CONTENT_MAX_W) -> None:
        super().__init__(parent, bg=BG)
        self.area = ScrollArea(self, max_width=max_width)
        self.area.pack(fill="both", expand=True)
        self.body = self.area.body
        page_header(self.body, title, subtitle).pack(
            fill="x", pady=(PAD_XL, PAD_LG))

    def refresh(self) -> None:
        self.area.refresh()


# ============ COMPONENTS ============

def page_header(parent: tk.Misc, title: str, subtitle: str | None = None,
                bg: str = BG) -> tk.Frame:
    """Page title, optional one-line explanation, and a rule beneath both."""
    head = tk.Frame(parent, bg=bg)
    tk.Label(head, text=title, fg=GREEN, bg=bg, font=FONT_HEAD,
             anchor="w").pack(fill="x")
    if subtitle:
        tk.Label(head, text=subtitle, fg=FG_DIM, bg=bg, font=FONT_SM,
                 anchor="w", justify="left", wraplength=CONTENT_MAX_W).pack(
            fill="x", pady=(PAD_XS, 0))
    tk.Frame(head, bg=BORDER, height=1).pack(fill="x", pady=(PAD_MD, 0))
    return head


class Card(tk.Frame):
    """A bordered block of related controls. Pack children into ``.body``.

    One card is one idea. The panels used to run every control together on
    the page background with nothing but a heading between groups, which
    is why they read as a settings dump rather than as a screen.
    """

    def __init__(self, parent: tk.Misc, title: str | None = None,
                 subtitle: str | None = None, accent: str = GREEN,
                 pad: int = PAD_LG) -> None:
        super().__init__(parent, bg=BG2, highlightbackground=BORDER,
                         highlightcolor=BORDER, highlightthickness=1)
        self.head: tk.Frame | None = None
        if title:
            self.head = tk.Frame(self, bg=BG2)
            self.head.pack(fill="x", padx=pad, pady=(pad, 0))
            tk.Label(self.head, text=title, fg=accent, bg=BG2, font=FONT_CARD,
                     anchor="w").pack(side="left")
            if subtitle:
                tk.Label(self, text=subtitle, fg=FG_DIM, bg=BG2, font=FONT_XS,
                         anchor="w", justify="left",
                         wraplength=CONTENT_MAX_W - 2 * pad).pack(
                    fill="x", padx=pad, pady=(PAD_XS, 0))
            tk.Frame(self, bg=BORDER, height=1).pack(
                fill="x", padx=pad, pady=(PAD_MD, 0))
        self.body = tk.Frame(self, bg=BG2)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)

    def head_right(self, widget: tk.Widget) -> None:
        """Park a badge or a small control at the right of the card title."""
        if self.head is not None:
            widget.pack(in_=self.head, side="right")


def section_label(parent: tk.Misc, text: str, bg: str = BG2) -> tk.Label:
    """Sub-heading inside a card, for a card that holds two groups."""
    return tk.Label(parent, text=text, fg=FG_DIM, bg=bg, font=FONT_LABEL,
                    anchor="w")


def hint(parent: tk.Misc, text: str, bg: str = BG2, tone: str = "dim",
         width: int = CONTENT_MAX_W - 2 * PAD_LG) -> tk.Label:
    """Wrapped explanatory prose. Sans, because it is prose."""
    return tk.Label(parent, text=text, fg=tone_color(tone), bg=bg,
                    font=FONT_XS, anchor="w", justify="left",
                    wraplength=width)


def divider(parent: tk.Misc, bg: str = BG2) -> tk.Frame:
    """One-pixel rule. ``bg`` is the surrounding colour, not the rule's."""
    del bg
    return tk.Frame(parent, bg=BORDER, height=1)


def field_row(parent: tk.Misc, label: str, bg: str = BG2,
              width: int = LABEL_COL) -> tk.Frame:
    """A row whose label occupies a fixed column so rows align.

    Returns the row; pack the controls into it with ``side="left"``.
    """
    row = tk.Frame(parent, bg=bg)
    tk.Label(row, text=label, fg=FG_DIM, bg=bg, font=FONT_LABEL,
             width=width, anchor="w").pack(side="left")
    return row


def entry(parent: tk.Misc, bg: str = BG, width: int | None = None,
          font=FONT_SM) -> tk.Entry:
    """Text input with a focus ring, matching the chat composer.

    Borderless with a one-pixel highlight rather than a tk relief: the
    default raised relief is drawn by Windows in the system colour and
    lands as a light bevel on a dark panel.
    """
    kwargs = {}
    if width is not None:
        kwargs["width"] = width
    field = tk.Entry(
        parent, bg=bg, fg=FG_BRIGHT, font=font, insertbackground=GREEN,
        selectbackground=GREEN_DIM, selectforeground=FG_BRIGHT,
        borderwidth=0, highlightthickness=1, highlightbackground=BORDER,
        highlightcolor=GREEN_DIM, disabledbackground=BG2,
        disabledforeground=FG_DIM, readonlybackground=BG2, **kwargs)
    return field


# Foreground, border, hover background. "quiet" has no border at all.
_BUTTON_KINDS = {
    "primary": (GREEN, GREEN_DIM, BG3),
    "secondary": (FG, BORDER, BG3),
    "danger": (RED, BORDER, BG3),
    "quiet": (FG_DIM, None, BG3),
}


def button(parent: tk.Misc, text: str, command, kind: str = "secondary",
           bg: str = BG2, pad: tuple[int, int] = (14, 6)) -> tk.Button:
    """A button that looks the same everywhere it appears.

    ``bg`` is the colour of whatever the button sits on, because tk draws
    the highlight ring in the widget's own background and a button on a
    card needs BG2 where one on the page needs BG.
    """
    fg, border, hover_bg = _BUTTON_KINDS.get(kind, _BUTTON_KINDS["secondary"])
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg,
        activebackground=hover_bg, activeforeground=fg,
        disabledforeground=FG_DIM, font=FONT_BTN, relief="flat",
        borderwidth=0, highlightthickness=1 if border else 0,
        highlightbackground=border or bg, highlightcolor=border or bg,
        cursor="hand2", padx=pad[0], pady=pad[1],
    )

    def on_enter(_event, w=btn, hover=hover_bg, accent=fg, has_border=bool(border)):
        if str(w["state"]) == "disabled":
            return
        w.configure(bg=hover)
        if has_border:
            w.configure(highlightbackground=accent)

    def on_leave(_event, w=btn, rest=bg, edge=border):
        w.configure(bg=rest)
        if edge:
            w.configure(highlightbackground=edge)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


def button_row(parent: tk.Misc, specs, bg: str = BG2) -> tk.Frame:
    """A row of buttons from ``(text, command, kind)`` triples.

    The built buttons are on ``row.buttons`` for the few callers that need
    to enable or disable one later.
    """
    row = tk.Frame(parent, bg=bg)
    built = []
    for index, (text, command, kind) in enumerate(specs):
        btn = button(row, text, command, kind=kind, bg=bg)
        btn.pack(side="left", padx=(0 if index == 0 else PAD_SM, 0))
        built.append(btn)
    row.buttons = built
    return row


def radio(parent: tk.Misc, text: str, variable: tk.Variable, value,
          command=None, bg: str = BG2) -> tk.Radiobutton:
    """Radio button on a card. ``selectcolor`` is the indicator's own fill,
    which tk leaves white unless it is told otherwise."""
    return tk.Radiobutton(
        parent, text=text, variable=variable, value=value, command=command,
        bg=bg, fg=FG, font=FONT_XS, selectcolor=BG, activebackground=bg,
        activeforeground=GREEN, highlightthickness=0, borderwidth=0,
        anchor="w", cursor="hand2")


def check(parent: tk.Misc, text: str, variable: tk.Variable, command=None,
          bg: str = BG2) -> tk.Checkbutton:
    """Checkbox on a card. Same indicator caveat as radio()."""
    return tk.Checkbutton(
        parent, text=text, variable=variable, command=command, bg=bg, fg=FG,
        font=FONT_XS, selectcolor=BG, activebackground=bg,
        activeforeground=GREEN, highlightthickness=0, borderwidth=0,
        anchor="w", cursor="hand2")


def badge(parent: tk.Misc, text: str, tone: str = "ok",
          bg: str = BG2) -> tk.Label:
    """Short state marker, such as the ACTIVE flag on a model."""
    colour = tone_color(tone)
    return tk.Label(parent, text=f" {text} ", fg=colour, bg=bg,
                    font=FONT_MONO_XS, highlightthickness=1,
                    highlightbackground=colour, highlightcolor=colour)


def link(parent: tk.Misc, text: str, url: str, bg: str = BG2) -> tk.Label:
    """Clickable external link. Opens in the user's real browser."""
    label = tk.Label(parent, text=text, fg=BLUE, bg=bg, font=FONT_MONO_XS,
                     anchor="w", cursor="hand2")
    label.bind("<Button-1>", lambda _e, target=url: webbrowser.open(target))
    label.bind("<Enter>", lambda _e: label.configure(font=(MONO, 9, "underline")))
    label.bind("<Leave>", lambda _e: label.configure(font=FONT_MONO_XS))
    return label


class StatusLine(tk.Label):
    """One line of feedback under a control, with a fixed tone vocabulary.

    Every panel used to pass a colour by hand at each call site
    (``configure(text=..., fg=RED)``), so the same condition was amber in
    one panel and red in the next. Here the caller names the meaning and
    the colour follows.
    """

    def __init__(self, parent: tk.Misc, bg: str = BG2, font=FONT_XS,
                 width: int = CONTENT_MAX_W - 2 * PAD_LG) -> None:
        super().__init__(parent, text="", fg=FG_DIM, bg=bg, font=font,
                         anchor="w", justify="left", wraplength=width)

    def set(self, text: str, tone: str = "info") -> None:
        self.configure(text=text, fg=tone_color(tone))

    def info(self, text: str) -> None:
        self.set(text, "info")

    def ok(self, text: str) -> None:
        self.set(text, "ok")

    def warn(self, text: str) -> None:
        self.set(text, "warn")

    def busy(self, text: str) -> None:
        self.set(text, "busy")

    def error(self, text: str) -> None:
        self.set(text, "error")

    def clear(self) -> None:
        self.set("", "info")


class Readout(tk.Text):
    """Read-only block of aligned output, sized to its own content.

    Monospaced, because every caller pads its key column with a format
    spec and that only lines up in a fixed-width font. Set to the number
    of lines it actually holds rather than a guessed height, because a
    fixed height either leaves dead space under short output or clips long
    output behind a scrollbar that was never added. The enclosing
    ScrollArea handles overflow for the page as a whole.

    ``wrap="none"``: the content is tabular, and a wrapped row in a table
    is worse than a truncated one.
    """

    def __init__(self, parent: tk.Misc, bg: str = BG2, key_width: int = 16,
                 max_lines: int = 400, font=FONT_MONO_SM) -> None:
        super().__init__(parent, bg=bg, fg=FG, font=font, height=1,
                         wrap="none", state="disabled", borderwidth=0,
                         highlightthickness=0, padx=0, pady=0,
                         cursor="arrow", takefocus=0)
        self.key_width = key_width
        self.max_lines = max_lines
        for name, colour in TONES.items():
            self.tag_configure(name, foreground=colour)

    # ----- writing -----

    def begin(self) -> "Readout":
        self.configure(state="normal")
        self.delete("1.0", "end")
        return self

    def write(self, text: str, tone: str = "val") -> "Readout":
        self.insert("end", text, tone)
        return self

    def line(self, text: str = "", tone: str = "val") -> "Readout":
        self.insert("end", text + "\n", tone)
        return self

    def row(self, label: str, value: str, tone: str = "val",
            indent: int = 2) -> "Readout":
        self.insert("end", " " * indent + f"{label:>{self.key_width}s} : ",
                    "key")
        self.insert("end", f"{value}\n", tone)
        return self

    def blank(self) -> "Readout":
        self.insert("end", "\n")
        return self

    def end(self) -> "Readout":
        # A Text widget always carries a trailing newline of its own, so
        # content written as complete lines lands one line short of where
        # "end-1c" reports. Column 0 is the tell.
        last = self.index("end-1c")
        lines = int(last.split(".")[0])
        if last.endswith(".0") and lines > 1:
            lines -= 1
        self.configure(height=max(1, min(lines, self.max_lines)),
                       state="disabled")
        return self

    def show(self, text: str, tone: str = "dim") -> "Readout":
        """Replace the whole block with one line. For empty and error states."""
        return self.begin().line(text, tone).end()


def truncate(text: str, limit: int) -> str:
    """Shorten for a fixed-width column without wrapping the row."""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[:limit - 3] + "..."
