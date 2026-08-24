"""The desktop shell's component layer, and the rules that keep it the only one.

Two kinds of test live here.

The first kind exercises `src/desktop_ui.py` directly: the pure helpers with
no widget behind them, and the widget classes against a hidden Tk root. The
widget tests never depend on a realized window, because a test suite that
needs a mapped toplevel to pass cannot run on a headless CI runner and would
end up deleted. Geometry-driven code paths are called with a synthetic
Configure event instead.

The second kind reads `desktop_app.py` as source, the way
`test_console_encoding.py` reads `src/`. It is the half that has teeth: a
component layer is only worth having while it is the single place a colour
or a font is decided, and nothing else stops someone dropping a raw
`fg="#7ec890"` into a panel six months from now. Source rules cover the
paths no test exercises, which for a tkinter app is nearly all of them.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import desktop_ui as ui

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_APP = REPO_ROOT / "desktop_app.py"

COLOUR_TOKENS = [
    "BG", "BG2", "BG3", "FG", "FG_DIM", "FG_BRIGHT", "GREEN", "GREEN_DEEP",
    "GREEN_DIM", "AMBER", "RED", "CYAN", "BLUE", "BORDER", "USER_BUBBLE_BG",
    "USER_BUBBLE_BG_DARK", "USER_BUBBLE_FG",
]
FONT_TOKENS = [
    "FONT", "FONT_SM", "FONT_XS", "FONT_LG", "FONT_TITLE", "FONT_ASCII",
    "FONT_MONO_SM", "FONT_MONO_XS", "FONT_HEAD", "FONT_CARD", "FONT_LABEL",
    "FONT_BTN",
]

HEX = re.compile(r"#[0-9a-fA-F]{3,8}")


# ---------------------------------------------------------------- tokens

@pytest.mark.parametrize("name", COLOUR_TOKENS)
def test_colour_tokens_are_six_digit_hex(name):
    value = getattr(ui, name)
    assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{name} = {value!r}"


def test_exactly_two_font_families():
    """A serif was removed once because it belonged to neither half.

    Chrome is monospace and prose is proportional. A third family is not a
    tweak, it is a different design, so it should fail here and be argued
    for rather than arrive inside an unrelated change.
    """
    families = {getattr(ui, name)[0] for name in FONT_TOKENS}
    assert families == {ui.MONO, ui.SANS}, families


@pytest.mark.parametrize("name", FONT_TOKENS)
def test_font_tokens_are_well_formed(name):
    value = getattr(ui, name)
    assert isinstance(value, tuple) and 2 <= len(value) <= 3
    assert isinstance(value[0], str) and isinstance(value[1], int)


def test_every_tone_resolves_to_a_defined_colour():
    palette = {getattr(ui, name) for name in COLOUR_TOKENS}
    for tone, colour in ui.TONES.items():
        assert colour in palette, f"tone {tone!r} uses an off-palette colour"


def test_tone_color_falls_back_to_body_text():
    assert ui.tone_color("ok") == ui.GREEN
    assert ui.tone_color("no-such-tone") == ui.FG


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize("available,expected", [
    (2560, (2560 - ui.CONTENT_MAX_W) // 2),   # wide monitor, real centring
    (1000, (1000 - ui.CONTENT_MAX_W) // 2),
    (820, ui.PAD_XL),                         # exactly the cap, floor applies
    (400, ui.PAD_XL),                         # narrower than the cap
])
def test_column_pad_centres_and_never_goes_below_the_floor(available, expected):
    assert ui.column_pad(available) == expected


@pytest.mark.parametrize("event,expected", [
    (SimpleNamespace(delta=120, num=None), 1),      # Windows, one notch up
    (SimpleNamespace(delta=-120, num=None), -1),
    (SimpleNamespace(delta=-360, num=None), -3),    # three notches at once
    (SimpleNamespace(delta=0, num=4), 1),           # X11 button events
    (SimpleNamespace(delta=0, num=5), -1),
    (SimpleNamespace(delta=3, num=None), 1),        # macOS, no 120 multiplier
    (SimpleNamespace(delta=0, num=None), 0),
])
def test_wheel_steps_covers_all_three_conventions(event, expected):
    assert ui._wheel_steps(event) == expected


@pytest.mark.parametrize("text,limit,expected", [
    ("short", 10, "short"),
    ("exactly-10", 10, "exactly-10"),
    ("far-too-long-to-fit", 10, "far-too..."),
    ("abc", 2, "ab"),
])
def test_truncate_keeps_the_column_width(text, limit, expected):
    assert ui.truncate(text, limit) == expected
    assert len(ui.truncate(text, limit)) <= limit


# ---------------------------------------------------------------- widgets

@pytest.fixture(scope="module")
def root():
    """A hidden Tk root, or a skip on a machine with no display.

    Never mapped: the tests below drive geometry through the same handlers
    Tk would call, so nothing here needs a window on screen.
    """
    tk = pytest.importorskip("tkinter")
    try:
        window = tk.Tk()
    except tk.TclError as exc:            # headless runner, no display
        pytest.skip(f"no Tk display: {exc}")
    window.withdraw()
    yield window
    window.destroy()


def test_install_styles_is_idempotent(root):
    """Called once per app today, but element_create raises on a repeat.

    A second call happens the moment anything builds a second Tk root, which
    is exactly what a test suite does.
    """
    from tkinter import ttk
    style = ttk.Style(root)
    style.theme_use("clam")
    ui.install_styles(style)
    ui.install_styles(style)
    assert style.lookup(ui.SCROLLBAR_STYLE, "background") == ui.BG3
    assert style.lookup(ui.PROGRESS_STYLE, "background") == ui.GREEN


def test_readout_sizes_itself_to_its_content(root):
    out = ui.Readout(root)
    out.begin()
    for index in range(6):
        out.row(f"key{index}", f"value {index}")
    out.end()
    assert int(out.cget("height")) == 6
    assert str(out.cget("state")) == "disabled"

    # Shrinking has to work too. A readout that only ever grows leaves a
    # block of dead space after a refresh returns fewer rows.
    out.begin().row("only", "one").end()
    assert int(out.cget("height")) == 1


def test_readout_row_alignment_and_tones(root):
    out = ui.Readout(root, key_width=8)
    out.begin().row("gpu", "yes", "ok").line("  free text", "amber").end()
    body = out.get("1.0", "end-1c")
    assert body.splitlines()[0] == "       gpu : yes"
    assert "ok" in out.tag_names("1.13")
    assert out.tag_cget("amber", "foreground") == ui.AMBER


def test_readout_show_replaces_everything(root):
    out = ui.Readout(root)
    out.begin().line("first").line("second").end()
    out.show("just this", "warn")
    # Text keeps a trailing newline of its own; end-1c strips that one only.
    assert out.get("1.0", "end-1c") == "just this\n"
    assert int(out.cget("height")) == 1


def test_readout_caps_at_max_lines(root):
    out = ui.Readout(root, max_lines=5)
    out.begin()
    for index in range(40):
        out.line(f"row {index}")
    out.end()
    assert int(out.cget("height")) == 5


def test_status_line_tones(root):
    status = ui.StatusLine(root)
    for method, colour in (("ok", ui.GREEN), ("warn", ui.AMBER),
                           ("error", ui.RED), ("info", ui.FG_DIM),
                           ("busy", ui.AMBER)):
        getattr(status, method)("message")
        assert status.cget("text") == "message"
        assert status.cget("fg") == colour
    status.clear()
    assert status.cget("text") == ""


def test_card_exposes_a_body_and_a_head(root):
    card = ui.Card(root, "TITLE", "subtitle")
    assert card.head is not None
    assert card.body.master is card
    assert card.cget("bg") == ui.BG2
    # head_right is how a badge reaches the title row.
    card.head_right(ui.badge(card.head, "ACTIVE"))
    assert len(card.head.winfo_children()) == 2

    plain = ui.Card(root)
    assert plain.head is None


def test_button_kinds_and_hover(root):
    primary = ui.button(root, "GO", lambda: None, kind="primary")
    assert primary.cget("fg") == ui.GREEN
    assert primary.cget("bg") == ui.BG2

    primary.event_generate  # bindings exist rather than being no-ops
    assert primary.bind("<Enter>") and primary.bind("<Leave>")

    danger = ui.button(root, "DELETE", lambda: None, kind="danger")
    assert danger.cget("fg") == ui.RED

    quiet = ui.button(root, "SKIP", lambda: None, kind="quiet")
    assert int(quiet.cget("highlightthickness")) == 0

    unknown = ui.button(root, "?", lambda: None, kind="not-a-kind")
    assert unknown.cget("fg") == ui.FG, "unknown kinds fall back, never raise"


def test_button_row_returns_its_buttons(root):
    row = ui.button_row(root, [
        ("ONE", lambda: None, "primary"),
        ("TWO", lambda: None, "danger"),
    ])
    assert [b.cget("text") for b in row.buttons] == ["ONE", "TWO"]


def test_field_row_reserves_a_fixed_label_column(root):
    row = ui.field_row(root, "instruction")
    label = row.winfo_children()[0]
    assert int(label.cget("width")) == ui.LABEL_COL
    assert label.cget("text") == "instruction"


def test_scroll_area_centres_a_capped_column(root):
    area = ui.ScrollArea(root)
    area._on_canvas_configure(SimpleNamespace(width=2560))
    assert int(float(area.canvas.itemcget(area._window, "width"))) == ui.CONTENT_MAX_W
    x_offset = area.canvas.coords(area._window)[0]
    assert x_offset == pytest.approx((2560 - ui.CONTENT_MAX_W) / 2, abs=1)

    # Narrower than the cap: fill the width less the page gutter.
    area._on_canvas_configure(SimpleNamespace(width=600))
    assert int(float(area.canvas.itemcget(area._window, "width"))) == 600 - 2 * ui.PAD_XL


def test_scroll_area_hides_the_scrollbar_when_content_fits(root):
    area = ui.ScrollArea(root)
    area._on_scroll_set("0.0", "1.0")
    assert area._bar_visible is False
    area._on_scroll_set("0.0", "0.4")
    assert area._bar_visible is True
    area._on_scroll_set("0.0", "1.0")
    assert area._bar_visible is False


def test_wheel_dispatch_walks_up_to_the_owning_area(root):
    """A label deep inside a card has to scroll the page it sits in.

    Binding the canvas alone does nothing, because the pointer is over the
    label and that is where Tk delivers the event.
    """
    import tkinter as tk

    area = ui.ScrollArea(root)
    card = ui.Card(area.body, "CARD")
    leaf = tk.Label(card.body, text="deep")

    seen = []
    area.on_wheel = lambda event: seen.append(event) or "break"
    assert ui._dispatch_wheel(SimpleNamespace(widget=leaf, delta=-120, num=None)) == "break"
    assert len(seen) == 1

    # Outside any scroll area, the event is left alone so the widget's own
    # class binding still runs. The chat transcript depends on this.
    orphan = tk.Label(root, text="not in a scroll area")
    assert ui._dispatch_wheel(SimpleNamespace(widget=orphan, delta=-120, num=None)) is None
    # Tk hands back a name string for widgets it cannot resolve.
    assert ui._dispatch_wheel(SimpleNamespace(widget=".unknown", delta=-120, num=None)) is None


def test_page_puts_a_header_above_a_scrolling_body(root):
    page = ui.Page(root, "# TITLE", "subtitle")
    assert page.body is page.area.body
    header = page.body.winfo_children()[0]
    labels = [w.cget("text") for w in header.winfo_children()
              if "text" in w.keys()]
    assert labels == ["# TITLE", "subtitle"]


# ------------------------------------------------- desktop_app source rules

def _app_source() -> str:
    return DESKTOP_APP.read_text(encoding="utf-8")


def test_desktop_app_exists_where_the_rules_below_expect_it():
    # Guards the three tests underneath: a bad path would make them all
    # pass by reading nothing.
    assert DESKTOP_APP.is_file()
    assert "class RAGApp" in _app_source()


def test_no_hex_colour_is_spelled_in_the_app():
    offenders = [
        (number, line.strip())
        for number, line in enumerate(_app_source().splitlines(), 1)
        if HEX.search(line)
    ]
    assert not offenders, (
        "colours belong to desktop_ui, not to a panel: "
        + "; ".join(f"line {n}: {text[:70]!r}" for n, text in offenders)
    )


def test_no_font_family_is_spelled_in_the_app():
    """Font tuples must be built from MONO and SANS, never from a literal.

    Eight panels used to write out ("Consolas", 12, "bold") by hand, which
    is why three of them drifted to different sizes for the same heading.
    """
    offenders = [
        (number, line.strip())
        for number, line in enumerate(_app_source().splitlines(), 1)
        if re.search(r'"(Consolas|Segoe UI|Georgia|Arial|Helvetica)"', line)
    ]
    assert not offenders, (
        "use the MONO and SANS tokens: "
        + "; ".join(f"line {n}: {text[:70]!r}" for n, text in offenders)
    )


def test_no_classic_scrollbar_or_hand_rolled_canvas():
    """Both of these cost a debugging cycle before the component layer.

    A classic tk.Scrollbar accepts bg and troughcolor on Windows and then
    draws with the native theme anyway, landing as a light grey bar on a
    dark panel. A hand-rolled Canvas scroller is where the missing mouse
    wheel came from, twice. ScrollArea is the answer to both.
    """
    source = _app_source()
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    # Negative lookbehind: ttk.Scrollbar is the correct one and contains
    # the string we are banning.
    assert not re.search(r"(?<!t)tk\.Scrollbar\(", code)
    assert "ScrolledText" not in code
    assert not re.search(r"tk\.Canvas\(", code)
