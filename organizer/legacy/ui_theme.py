"""Shared presentation styles for the campus desktop app."""
import tkinter as tk
import ctypes
import sys
from fractions import Fraction
from organizer import APP_ROOT
from tkinter import ttk
from tkinter import font as tkfont

BG = "#F5F4F9"
WHITE = "#FFFFFF"
INK = "#262336"
TEXT = "#403D50"
MUTED = "#605D72"
LINE = "#DEDBE7"
TEAL = "#6448B5"
PALE = "#EEE9FA"
NAVY = "#262238"
RAIL_TEXT = "#D4CFE0"
RAIL_LINE = "#454051"
RAIL_ACTIVE = "#514268"
AMBER = "#87551F"
GREEN = "#246B59"
FONT = "맑은 고딕"

def create_window():
    if sys.platform == "win32":
        # Set awareness before Tk creates any HWND or caches the display DPI.
        ctypes.windll.user32.SetProcessDPIAware()
    return tk.Tk()


def font(size=10, bold=False):
    return (FONT, size, "bold" if bold else "normal")


def label(parent, text="", size=10, bold=False, fg=TEXT, bg=WHITE, **options):
    return tk.Label(parent, text=text, font=font(size, bold), fg=fg, bg=bg,
                    anchor="w", justify="left", bd=0, padx=0, pady=0, **options)


def button(parent, text, command, primary=False, dark=False):
    if dark:
        bg, fg, hover = RAIL_LINE, WHITE, RAIL_ACTIVE
    elif primary:
        bg, fg, hover = TEAL, WHITE, "#513797"
    else:
        bg, fg, hover = "#ECEAF2", TEXT, "#E3DEEE"
    return tk.Button(parent, text=text, command=command, font=font(10, True),
                     relief="flat", bd=0, bg=bg, fg=fg, activebackground=hover,
                     activeforeground=fg, padx="10.5p", pady="5.25p", cursor="hand2",
                     disabledforeground="#8B8598", highlightthickness=0)


def card(parent, bg=WHITE):
    return tk.Frame(parent, bg=bg, highlightbackground=LINE, highlightthickness=1)


def scrollbar(parent, widget, orient, row, column):
    vertical = orient == "vertical"
    bar = ttk.Scrollbar(parent, orient=orient, command=widget.yview if vertical else widget.xview)
    bar.grid(row=row, column=column, sticky="ns" if vertical else "ew")

    def update(first, last):
        bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            bar.grid_remove()
        else:
            bar.grid()

    widget.configure(**{"yscrollcommand" if vertical else "xscrollcommand": update})
    return bar


def fit_text(text, pixels, face, middle=False):
    if face.measure(text) <= pixels:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        count = (lo + hi + 1) // 2
        tail = count * 2 // 3 if middle else 0
        trial = text[:count-tail] + "…" + (text[-tail:] if tail else "")
        if face.measure(trial) <= pixels:
            lo = count
        else:
            hi = count - 1
    tail = lo * 2 // 3 if middle else 0
    return text[:lo-tail] + "…" + (text[-tail:] if tail else "")


def setup_theme(window, scale):
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure(".", font=font(10))
    line = tkfont.Font(window, font=font(10)).metrics("linespace")
    style.configure("Treeview", font=font(11), rowheight=max(round(41*scale), line+round(16*scale)),
                    background=WHITE, fieldbackground=WHITE, foreground=TEXT,
                    borderwidth=0, relief="flat", lightcolor=WHITE, darkcolor=WHITE)
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.layout("Treeview.Item", [
        ("Treeitem.padding", {"sticky":"nswe", "children":[
            ("Treeitem.image", {"side":"left","sticky":""}),
            ("Treeitem.text", {"side":"left","sticky":""})]})])
    style.map("Treeview", background=[("selected", "#ECE6F9")], foreground=[("selected", INK)])
    style.configure("Treeview.Heading", background="#F1F0F6", foreground=MUTED,
                    font=font(9, True), padding=("3.75p","5.25p"), relief="flat", borderwidth=0)
    style.map("Treeview.Heading", background=[("active", "#E9E6F0")])
    style.configure("Rail.Treeview", background=NAVY, fieldbackground=NAVY,
                    foreground=RAIL_TEXT, rowheight=max(round(34*scale),line+round(11*scale)), borderwidth=0)
    style.map("Rail.Treeview", background=[("selected", RAIL_ACTIVE)], foreground=[("selected", WHITE)])
    style.map("Quiet.Rail.Treeview", background=[("selected", NAVY)], foreground=[("selected", RAIL_TEXT)])
    style.configure("TCombobox", padding=3)
    for axis in ("Vertical", "Horizontal"):
        style.configure(axis+".TScrollbar", background="#C8C4D4", troughcolor="#F5F3F8",
                        borderwidth=0, arrowsize=round(12*scale), relief="flat")
    window.option_add("*Menu.font", font(10))
    icons_path = APP_ROOT / "icons"
    if scale <= 1:
        return {p.stem: tk.PhotoImage(master=window, file=str(p)) for p in icons_path.glob("*.png")}
    # High-density originals retain fine strokes at fractional Windows scales.
    ratio = Fraction(round(scale*4), 12)
    icons = {}
    for path in (icons_path/"3x").glob("*.png"):
        source = tk.PhotoImage(master=window, file=str(path))
        icon = tk.PhotoImage(master=window)
        window.tk.call(str(icon), "copy", str(source), "-zoom", ratio.numerator,
                       "-subsample", ratio.denominator)
        icons[path.stem] = icon
    return icons
