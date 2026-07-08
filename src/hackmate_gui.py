"""
HackMate GUI — Tkinter frontend for the same backend used by hackmate.py (Textual TUI).
Run with: sudo .venv/bin/python3 src/hackmate_gui.py   (or .venv\\Scripts\\python.exe on Windows)
"""

import sys
import os
import shutil
import shlex
import json
import queue
import threading
import subprocess
import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from compat import (
    require_admin, IS_WINDOWS, get_usb_drives, format_usb, mount_usb,
    unmount_usb, get_mount_path, get_tmp_dir,
)
require_admin()

from updater import check_and_update
if check_and_update():
    os.execv(sys.executable, [sys.executable] + sys.argv)

from hardware import scan, HardwareProfile
from kexts import select_kexts, get_alc_layout
from smbios import generate as gen_smbios, SMBIOSData
from config_gen import generate as gen_config, write_plist, _required_ssdts
from recovery import compatible_versions, download_recovery, MacOSVersion

# ─────────────────────────────────────────────────────────────────────────────
# Theme
# ─────────────────────────────────────────────────────────────────────────────

BG      = "#0d0d0d"
PANEL   = "#111111"
PANEL2  = "#0a0a0a"
FG      = "#cccccc"
ACCENT  = "#00ff88"
DIM     = "#555555"
WARN    = "#ff4444"
CAUTION = "#ffaa00"
INFOC   = "#888888"
BLACK   = "#000000"
WHITE   = "#ffffff"
BORDER  = "#2a2a2a"

FONT       = ("TkDefaultFont", 11)
FONT_SMALL = ("TkDefaultFont", 9)
FONT_BOLD  = ("TkDefaultFont", 11, "bold")
MONO       = ("TkFixedFont", 10)
MONO_SMALL = ("TkFixedFont", 9)
TITLE_FONT = ("TkFixedFont", 13, "bold")

BANNER_FONT = ("TkFixedFont", 40, "bold")


def draw_banner(parent) -> tk.Frame:
    """Terminal-style box-drawing ASCII art doesn't have guaranteed fixed-width
    glyph metrics in Tk's font rendering (unlike an actual terminal), so it
    overlaps and garbles. Use a plain letter-spaced wordmark instead."""
    wrap = tk.Frame(parent, bg=BG)
    tk.Label(wrap, text="H A C K M A T E", bg=BG, fg=ACCENT, font=BANNER_FONT).pack()
    tk.Frame(wrap, bg=ACCENT, height=3, width=460).pack(pady=(8, 0))
    return wrap


def _get_version() -> str:
    try:
        sha = (Path(__file__).parent / ".version").read_text().strip()[:7]
        return f"v1.4.1 ({sha})"
    except Exception:
        return "v1.4.1"


VERSION = _get_version()

# ─────────────────────────────────────────────────────────────────────────────
# Widget helpers
# ─────────────────────────────────────────────────────────────────────────────


def title(parent, text):
    return tk.Label(parent, text=text, bg=BG, fg=ACCENT, font=TITLE_FONT,
                     anchor="w", justify="left")


def info(parent, text, fg=INFOC, wraplength=880, font=FONT):
    return tk.Label(parent, text=text, bg=BG, fg=fg, font=font,
                     anchor="w", justify="left", wraplength=wraplength)


def warn_label(parent, text, **kw):
    return info(parent, text, fg=WARN, **kw)


def ok_label(parent, text, **kw):
    return info(parent, text, fg=ACCENT, **kw)


_BUTTON_STYLES = {
    "primary":  "Primary.TButton",
    "danger":   "Danger.TButton",
    "back":     "Back.TButton",
    "advanced": "Advanced.TButton",
}


def button(parent, text, command, kind="primary", width=None):
    b = ttk.Button(parent, text=text, command=command, cursor="hand2",
                    style=_BUTTON_STYLES.get(kind, "Primary.TButton"))
    if width:
        b.config(width=width)
    return b


def configure_dark_theme(root: "tk.Tk"):
    """macOS's native Aqua theme ignores custom colors on Button/Checkbutton/
    Radiobutton/Scrollbar — switch to the cross-platform 'clam' theme so the
    dark palette actually renders on every OS."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("Primary.TButton", background=ACCENT, foreground=BLACK,
                     font=FONT_BOLD, borderwidth=0, padding=(12, 8))
    style.map("Primary.TButton",
              background=[("active", "#00cc6e"), ("pressed", "#00b87d")],
              foreground=[("disabled", DIM)])

    style.configure("Danger.TButton", background=WARN, foreground=WHITE,
                     font=FONT_BOLD, borderwidth=0, padding=(12, 8))
    style.map("Danger.TButton", background=[("active", "#cc3333"), ("pressed", "#b82e2e")])

    style.configure("Back.TButton", background="#222222", foreground=INFOC,
                     font=FONT_BOLD, borderwidth=0, padding=(12, 8))
    style.map("Back.TButton",
              background=[("active", "#333333"), ("pressed", "#3a3a3a")],
              foreground=[("active", FG)])

    style.configure("Advanced.TButton", background=PANEL, foreground="#3a3a3a",
                     font=FONT_BOLD, borderwidth=0, padding=(6, 2))
    style.map("Advanced.TButton",
              background=[("active", "#1a1a1a")],
              foreground=[("active", ACCENT)])

    style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT_SMALL)
    style.map("TCheckbutton",
              background=[("active", BG)],
              foreground=[("active", ACCENT)],
              indicatorcolor=[("selected", ACCENT), ("!selected", "#1a1a1a")])

    style.configure("TRadiobutton", background=BG, foreground=FG, font=FONT_SMALL)
    style.map("TRadiobutton",
              background=[("active", BG)],
              foreground=[("selected", ACCENT), ("active", ACCENT)],
              indicatorcolor=[("selected", ACCENT), ("!selected", "#1a1a1a")])

    style.configure("TProgressbar", background=ACCENT, troughcolor=PANEL,
                     bordercolor=PANEL, lightcolor=ACCENT, darkcolor=ACCENT)

    style.configure("TCombobox", fieldbackground="#1a1a1a", background="#1a1a1a",
                     foreground=FG, arrowcolor=FG, bordercolor=BORDER,
                     lightcolor="#1a1a1a", darkcolor="#1a1a1a")
    style.map("TCombobox",
              fieldbackground=[("readonly", "#1a1a1a")],
              foreground=[("readonly", FG)])

    style.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG,
                     bordercolor=BG, arrowcolor=FG)
    style.map("Vertical.TScrollbar", background=[("active", "#333333")])


class Entry(tk.Entry):
    """tk.Entry with placeholder-text support and a .value property."""

    def __init__(self, parent, placeholder="", value="", width=40, **kw):
        self.var = tk.StringVar()
        super().__init__(parent, textvariable=self.var, font=MONO, bg="#1a1a1a", fg=FG,
                          insertbackground=FG, relief="flat", width=width,
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=ACCENT, **kw)
        self.placeholder = placeholder
        self._has_placeholder = False
        if value:
            self.insert(0, value)
        elif placeholder:
            self._show_placeholder()
        self.bind("<FocusIn>", self._clear_placeholder)
        self.bind("<FocusOut>", self._restore_placeholder)

    def _show_placeholder(self):
        self.insert(0, self.placeholder)
        self.config(fg=DIM)
        self._has_placeholder = True

    def _clear_placeholder(self, _e=None):
        if self._has_placeholder:
            self.delete(0, "end")
            self.config(fg=FG)
            self._has_placeholder = False

    def _restore_placeholder(self, _e=None):
        if not self.get() and self.placeholder:
            self._show_placeholder()

    @property
    def value(self) -> str:
        return "" if self._has_placeholder else self.get().strip()

    @value.setter
    def value(self, v: str):
        self._clear_placeholder()
        self.delete(0, "end")
        self.insert(0, v)

    def set_placeholder(self, text: str):
        self.placeholder = text
        if self._has_placeholder:
            self.delete(0, "end")
            self._show_placeholder()


class Switch(ttk.Checkbutton):
    """Boolean toggle, mirrors Textual's Switch widget."""

    def __init__(self, parent, value=False, **kw):
        self.var = tk.BooleanVar(value=value)
        super().__init__(parent, variable=self.var, onvalue=True, offvalue=False, **kw)

    @property
    def value(self) -> bool:
        return self.var.get()

    @value.setter
    def value(self, v: bool):
        self.var.set(bool(v))


class ListBox(tk.Listbox):
    """tk.Listbox with an .index property matching Textual's ListView.index."""

    def __init__(self, parent, items=None, height=10, **kw):
        super().__init__(parent, height=height, bg=PANEL, fg=FG, font=MONO,
                          selectbackground="#003322", selectforeground=ACCENT,
                          relief="flat", highlightthickness=1, highlightbackground=BORDER,
                          activestyle="none", **kw)
        for it in (items or []):
            self.insert("end", it)

    @property
    def index(self):
        sel = self.curselection()
        return sel[0] if sel else None

    def set_items(self, items):
        self.delete(0, "end")
        for it in items:
            self.insert("end", it)


class LogView(tk.Text):
    """Scrolling colored log, mirrors Textual's RichLog with markup levels."""

    LEVEL_COLORS = {
        "ok": ACCENT, "warn": CAUTION, "warning": CAUTION, "error": WARN,
        "critical": WARN, "info": INFOC, "header": "#00cccc", "cmd": "#44ff88",
        "cmd_out": "#444466", "cmd_err": "#ff6666", "context": "#2a2a2a",
    }

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=PANEL2, fg=INFOC, font=MONO, relief="flat",
                          wrap="word", state="disabled", bd=0, highlightthickness=1,
                          highlightbackground=BORDER, **kw)
        for lvl, color in self.LEVEL_COLORS.items():
            self.tag_config(lvl, foreground=color)

    def write(self, msg: str, level: str = "info"):
        self.config(state="normal")
        self.insert("end", msg + "\n", level if level in self.LEVEL_COLORS else "info")
        self.config(state="disabled")
        self.see("end")

    def clear(self):
        self.config(state="normal")
        self.delete("1.0", "end")
        self.config(state="disabled")


class ScrollFrame(tk.Frame):
    """A scrollable content area (canvas + inner frame), mousewheel-aware only while hovered."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _e=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _unbind_wheel(self, _e=None):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


def hr(parent, text):
    return title(parent, f"── {text} " + "─" * max(0, 50 - len(text)))


def section(parent, text):
    return tk.Label(parent, text=f"  ── {text} " + "─" * max(0, 40 - len(text)),
                     bg=BG, fg=ACCENT, font=FONT_BOLD, anchor="w")


def row(parent):
    return tk.Frame(parent, bg=BG)


# ─────────────────────────────────────────────────────────────────────────────
# Screen base + app shell
# ─────────────────────────────────────────────────────────────────────────────


class Screen(tk.Frame):
    def __init__(self, app):
        super().__init__(app.container, bg=BG)
        self.app = app

    def on_show(self):
        """Called once, right after the screen is pushed (mirrors Textual's on_mount)."""
        pass

    def footer_bar(self):
        bar = tk.Frame(self, bg=PANEL, height=26)
        tk.Label(bar, text=f"  HackMate {VERSION}", bg=PANEL, fg=DIM, font=FONT_SMALL,
                 anchor="w").pack(side="left")
        return bar


class HackMateApp(tk.Tk):
    profile: HardwareProfile | None = None
    macos_version: MacOSVersion | None = None
    wifi_kext_mode: str = "itlwm"
    disable_dgpu: bool = False
    dual_boot: str = ""
    efi_output_path: str = ""

    def __init__(self):
        super().__init__()
        self.title(f"HackMate {VERSION}")
        self.geometry("1000x740")
        self.minsize(860, 600)
        self.configure(bg=BG)
        configure_dark_theme(self)

        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self._toast = tk.Label(self, text="", bg=PANEL, fg=FG, font=FONT_SMALL,
                                anchor="w", padx=10, pady=4)
        self._toast.pack(side="bottom", fill="x")
        self._toast_job = None

        self._stack: list[Screen] = []
        self._queue: "queue.Queue" = queue.Queue()
        self._poll_queue()

        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.push_screen(WelcomeScreen)
        self.after(3_600_000, self._check_for_update_loop)

    # ── navigation ──────────────────────────────────────────────────────
    def push_screen(self, screen_cls, *args, **kwargs):
        screen = screen_cls(self, *args, **kwargs)
        screen.grid(in_=self.container, row=0, column=0, sticky="nsew")
        self._stack.append(screen)
        screen.tkraise()
        screen.on_show()

    def pop_screen(self):
        if len(self._stack) <= 1:
            return
        top = self._stack.pop()
        top.destroy()
        self._stack[-1].tkraise()

    def exit(self):
        self.destroy()

    # ── thread-safe UI updates (mirrors Textual's call_from_thread) ────
    def call_from_thread(self, func, *args, **kwargs):
        self._queue.put((func, args, kwargs))

    def _poll_queue(self):
        try:
            while True:
                func, args, kwargs = self._queue.get_nowait()
                try:
                    func(*args, **kwargs)
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.after(30, self._poll_queue)

    def notify(self, message, severity="information", timeout=5, title=None):
        colors = {"information": ACCENT, "warning": CAUTION, "error": WARN}
        color = colors.get(severity, ACCENT)
        prefix = f"{title}: " if title else ""

        def _show():
            self._toast.config(text=f"  {prefix}{message}", fg=color)
            if self._toast_job:
                self.after_cancel(self._toast_job)
            self._toast_job = self.after(int(max(timeout, 1) * 1000),
                                          lambda: self._toast.config(text=""))
        _show()

    # ── background updater ──────────────────────────────────────────────
    def _check_for_update_loop(self):
        threading.Thread(target=self._check_for_update, daemon=True).start()
        self.after(3_600_000, self._check_for_update_loop)

    def _check_for_update(self):
        from updater import check_update_silent, _download_file, FILES, VERSION_FILE
        has_update, remote_sha, changelog = check_update_silent()
        if not has_update:
            return
        short = remote_sha[:7]
        summary = changelog[0] if changelog else "improvements and fixes"
        self.call_from_thread(self.notify, f"Downloading update {short}...",
                               "information", 5, "HackMate Update")
        failed = [f for f in FILES if not _download_file(f, remote_sha)]
        if not failed:
            VERSION_FILE.write_text(remote_sha)
            self.call_from_thread(self.notify, f"{short}: {summary} — restart to apply",
                                   "information", 30, "Update ready")
        else:
            self.call_from_thread(self.notify,
                                   f"Update {short} failed ({len(failed)} file(s)) — will retry next hour",
                                   "warning", 10, None)


# ─────────────────────────────────────────────────────────────────────────────
# Welcome / Scan / Manual hardware / Version
# ─────────────────────────────────────────────────────────────────────────────


class WelcomeScreen(Screen):
    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        draw_banner(wrap).pack(pady=(0, 6))
        tk.Label(wrap, text="Automated OpenCore EFI builder — any hardware",
                 bg=BG, fg=INFOC, font=FONT).pack(pady=(0, 18))
        btns = [
            ("Build EFI",             lambda: self.app.push_screen(ScanScreen), "primary"),
            ("Build EFI (Manual)",    lambda: self.app.push_screen(ManualHardwareScreen), "primary"),
            ("Restore EFI",           lambda: self.app.push_screen(RestoreScreen), "primary"),
            ("Dual Boot / Disk Map",  lambda: self.app.push_screen(DiskMapScreen), "primary"),
            ("USB Mapping",           lambda: self.app.push_screen(USBMappingScreen), "primary"),
            ("Edit Config",           lambda: self.app.push_screen(ConfigEditorUSBScreen), "primary"),
            ("Check Logs",            lambda: self.app.push_screen(LogCheckerScreen), "primary"),
            ("Quit",                  self.app.destroy, "danger"),
        ]
        for label, cmd, kind in btns:
            button(wrap, label, cmd, kind).pack(fill="x", pady=3, ipady=2)


class ScanScreen(Screen):
    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Scanning Hardware ──────────────────────────────────").pack(anchor="w")
        self.status = info(wrap, "  Detecting CPU, GPU, audio, network...")
        self.status.pack(anchor="w", pady=(10, 4))
        self.result = info(wrap, "")
        self.result.pack(anchor="w")
        self.btn_row = tk.Frame(wrap, bg=BG)
        self.btn_row.pack(anchor="w", pady=(16, 0), fill="x")
        button(self.btn_row, "← Back", self.app.pop_screen, "back").pack(anchor="w")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self):
        self.app.call_from_thread(self.status.config, text="  Detecting CPU, GPU, audio, network...")
        profile = scan()
        self.app.call_from_thread(self._show_results, profile)

    def _show_results(self, profile: HardwareProfile):
        kexts = select_kexts(profile, wifi_kext_mode=self.app.wifi_kext_mode)
        layout = get_alc_layout(profile.audio_codec)
        lines = [
            f"  CPU       {profile.cpu_name}",
            f"  Codename  {profile.cpu_codename}  (Gen {profile.cpu_generation})",
            f"  Platform  {profile.platform}  —  {profile.oc_platform}",
            f"  GPU       {profile.gpu_name} [{profile.gpu_vendor}]",
            f"  Audio     {profile.audio_name}  /  codec: {profile.audio_codec}  →  layout-id {layout}",
            f"  Ethernet  {profile.ethernet_name or 'None'}",
            f"  WiFi      {profile.wifi_name or 'None'}",
            f"  SMBIOS    {profile.smbios_model}",
            f"  Kexts     {len(kexts)} selected",
            f"  NVMe      {'Yes' if profile.nvme_present else 'No'}   Thunderbolt: {'Yes' if profile.has_thunderbolt else 'No'}",
        ]
        self.status.config(text="")
        self.result.config(text="\n".join(lines))
        self.app.profile = profile
        for w in self.btn_row.winfo_children():
            w.destroy()
        button(self.btn_row, "Continue → Select macOS",
               lambda: self.app.push_screen(VersionScreen), "primary").pack(anchor="w", pady=(0, 4))
        button(self.btn_row, "← Back", self.app.pop_screen, "back").pack(anchor="w")


class ManualHardwareScreen(Screen):
    CPU_OPTIONS = [
        ("intel-2",    "Intel Core i3/i5/i7-2xxx  —  Sandy Bridge (2nd gen desktop)"),
        ("intel-3",    "Intel Core i3/i5/i7-3xxx  —  Ivy Bridge (3rd gen desktop)"),
        ("intel-4",    "Intel Core i3/i5/i7-4xxx  —  Haswell (4th gen desktop)"),
        ("intel-5d",   "Intel Core i5/i7-5xxx  —  Broadwell (5th gen desktop)"),
        ("intel-6d",   "Intel Core i3/i5/i7-6xxx  —  Skylake (6th gen desktop)"),
        ("intel-7d",   "Intel Core i3/i5/i7-7xxx  —  Kaby Lake (7th gen desktop)"),
        ("intel-8d",   "Intel Core i3/i5/i7/i9-8xxx  —  Coffee Lake (8th gen desktop)"),
        ("intel-9d",   "Intel Core i5/i7/i9-9xxx  —  Coffee Lake Refresh (9th gen desktop)"),
        ("intel-10d",  "Intel Core i3/i5/i7/i9-10xxx  —  Comet Lake (10th gen desktop)"),
        ("intel-2m",   "Intel Core i5/i7-2xxx  —  Sandy Bridge (2nd gen laptop)"),
        ("intel-3m",   "Intel Core i5/i7-3xxx  —  Ivy Bridge (3rd gen laptop)"),
        ("intel-4m",   "Intel Core i5/i7-4xxx  —  Haswell (4th gen laptop)"),
        ("intel-5m",   "Intel Core i5/i7-5xxx  —  Broadwell (5th gen laptop)"),
        ("intel-6m",   "Intel Core i3/i5/i7-6xxx  —  Skylake (6th gen laptop)"),
        ("intel-7m",   "Intel Core i3/i5/i7-7xxx  —  Kaby Lake (7th gen laptop)"),
        ("intel-8kr",  "Intel Core i5/i7-8xxx U  —  Kaby Lake-R (8th gen, 4-core laptop)"),
        ("intel-8wl",  "Intel Core i5/i7-8xxx U  —  Whiskey Lake (8th gen, 4-core laptop)"),
        ("intel-8cl",  "Intel Core i7/i9-8xxx H  —  Coffee Lake-H (8th gen, 6-core laptop)"),
        ("intel-9m",   "Intel Core i5/i7/i9-9xxx H  —  Coffee Lake Refresh (9th gen laptop)"),
        ("intel-10cm", "Intel Core i3/i5/i7-10xxx H  —  Comet Lake-H (10th gen laptop)"),
        ("intel-10il", "Intel Core i3/i5/i7-10xxx U/Y  —  Ice Lake (10th gen laptop, Iris Plus)"),
        ("intel-11tl", "Intel Core i5/i7-11xxx  —  Tiger Lake (11th gen laptop, limited support)"),
        ("amd-zen1d",  "AMD Ryzen 3/5/7 1xxx  —  Zen (desktop)"),
        ("amd-zenpd",  "AMD Ryzen 3/5/7 2xxx  —  Zen+ (desktop)"),
        ("amd-zen2d",  "AMD Ryzen 5/7/9 3xxx  —  Zen 2 (desktop)"),
        ("amd-tr3",    "AMD Threadripper 3xxx  —  Zen 2 (HEDT)"),
        ("amd-zen3d",  "AMD Ryzen 5/7/9 5xxx  —  Zen 3 (desktop)"),
        ("amd-tr5",    "AMD Threadripper 5xxx  —  Zen 3 (HEDT)"),
        ("amd-zen4d",  "AMD Ryzen 5/7/9 7xxx  —  Zen 4 (desktop, AM5)"),
        ("amd-zen5d",  "AMD Ryzen 5/7/9 9xxx  —  Zen 5 (desktop, AM5)"),
        ("amd-zen1m",  "AMD Ryzen 3/5/7 2xxx U  —  Zen (laptop APU)"),
        ("amd-zenpm",  "AMD Ryzen 3/5/7 3xxx U  —  Zen+ (laptop APU)"),
        ("amd-zen2m",  "AMD Ryzen 4xxx / 5xxx U  —  Zen 2 (laptop APU)"),
        ("amd-zen3m",  "AMD Ryzen 5xxx / PRO 5xxx  —  Zen 3 (laptop APU)"),
        ("amd-zen3pm", "AMD Ryzen 6xxx  —  Zen 3+ (laptop APU)"),
        ("amd-zen4m",  "AMD Ryzen 7xxx / AI 3xx  —  Zen 4 (laptop APU)"),
        ("amd-zen5m",  "AMD Ryzen AI 3xx / 9xxx  —  Zen 5 (laptop APU)"),
    ]

    GPU_OPTIONS = [
        ("",         "Auto / same as CPU iGPU"),
        ("5916",     "Intel HD 620 (Kaby Lake)"),
        ("591b",     "Intel HD 630 (Kaby Lake)"),
        ("5917",     "Intel UHD 620 (Kaby Lake-R)"),
        ("3ea0",     "Intel UHD 620 (Whiskey Lake)"),
        ("3e98",     "Intel UHD 630 (Coffee Lake)"),
        ("9bca",     "Intel UHD 620 (Comet Lake)"),
        ("9bc4",     "Intel UHD 630 (Comet Lake)"),
        ("0166",     "Intel HD 4000 (Ivy Bridge)"),
        ("0416",     "Intel HD 4600 (Haswell)"),
        ("1916",     "Intel HD 520 (Skylake)"),
        ("amd",      "AMD Radeon (iGPU / dGPU)"),
        ("nvidia",   "Nvidia (must disable in BIOS for macOS)"),
    ]

    ETHERNET_OPTIONS = [
        ("",        "None / Unknown"),
        ("rtl8111", "Realtek RTL8111 / RTL8168"),
        ("rtl8125", "Realtek RTL8125 (2.5G)"),
        ("i219",    "Intel I219-V / I219-LM"),
        ("i225",    "Intel I225-V (2.5G)"),
        ("i226",    "Intel I226-V (2.5G)"),
        ("i211",    "Intel I211-AT"),
    ]

    WIFI_OPTIONS = [
        ("",         "None"),
        ("intel",    "Intel (AX200 / AX210 / AC-9260 / AC-8265)"),
        ("broadcom", "Broadcom (BCM94360 / BCM943602)"),
        ("atheros",  "Atheros / Qualcomm"),
        ("realtek",  "Realtek (limited support)"),
    ]

    _CPU_META = {
        "intel-2":    (2,  "Sandy Bridge",        "intel", "Sandy Bridge"),
        "intel-3":    (3,  "Ivy Bridge",          "intel", "Ivy Bridge"),
        "intel-4":    (4,  "Haswell",             "intel", "Haswell"),
        "intel-5d":   (5,  "Broadwell",           "intel", "Broadwell"),
        "intel-6d":   (6,  "Skylake",             "intel", "Skylake"),
        "intel-7d":   (7,  "Kaby Lake",           "intel", "Kaby Lake"),
        "intel-8d":   (8,  "Coffee Lake",         "intel", "Coffee Lake"),
        "intel-9d":   (9,  "Coffee Lake Refresh", "intel", "Coffee Lake Refresh"),
        "intel-10d":  (10, "Comet Lake",          "intel", "Comet Lake"),
        "intel-2m":   (2,  "Sandy Bridge",        "intel", "Sandy Bridge"),
        "intel-3m":   (3,  "Ivy Bridge",          "intel", "Ivy Bridge"),
        "intel-4m":   (4,  "Haswell",             "intel", "Haswell"),
        "intel-5m":   (5,  "Broadwell",           "intel", "Broadwell"),
        "intel-6m":   (6,  "Skylake",             "intel", "Skylake"),
        "intel-7m":   (7,  "Kaby Lake",           "intel", "Kaby Lake"),
        "intel-8kr":  (8,  "Kaby Lake-R",         "intel", "Kaby Lake"),
        "intel-8wl":  (8,  "Whiskey Lake",        "intel", "Coffee Lake"),
        "intel-8cl":  (8,  "Coffee Lake-H",       "intel", "Coffee Lake"),
        "intel-9m":   (9,  "Coffee Lake Refresh", "intel", "Coffee Lake Refresh"),
        "intel-10cm": (10, "Comet Lake-H",        "intel", "Comet Lake"),
        "intel-10il": (10, "Ice Lake",            "intel", "Ice Lake"),
        "intel-11tl": (11, "Tiger Lake",          "intel", "Tiger Lake"),
        "amd-zen1d":  (8,  "Zen",                "amd",   "Ryzen"),
        "amd-zenpd":  (8,  "Zen+",               "amd",   "Ryzen"),
        "amd-zen2d":  (10, "Zen 2",              "amd",   "Ryzen"),
        "amd-tr3":    (10, "Zen 2 Threadripper", "amd",   "Threadripper"),
        "amd-zen3d":  (11, "Zen 3",              "amd",   "Ryzen"),
        "amd-tr5":    (11, "Zen 3 Threadripper", "amd",   "Threadripper"),
        "amd-zen4d":  (12, "Zen 4",              "amd",   "Ryzen"),
        "amd-zen5d":  (12, "Zen 5",              "amd",   "Ryzen"),
        "amd-zen1m":  (8,  "Zen APU",            "amd",   "Ryzen"),
        "amd-zenpm":  (8,  "Zen+ APU",           "amd",   "Ryzen"),
        "amd-zen2m":  (10, "Zen 2 APU",          "amd",   "Ryzen"),
        "amd-zen3m":  (11, "Zen 3 APU",          "amd",   "Ryzen"),
        "amd-zen3pm": (11, "Zen 3+ APU",         "amd",   "Ryzen"),
        "amd-zen4m":  (12, "Zen 4 APU",          "amd",   "Ryzen"),
        "amd-zen5m":  (12, "Zen 5 APU",          "amd",   "Ryzen"),
    }

    def __init__(self, app):
        super().__init__(app)
        self.cpu_var = tk.StringVar(value=self.CPU_OPTIONS[6][0])   # default: Intel 7th gen desktop
        self.gpu_var = tk.StringVar(value="")
        self.eth_var = tk.StringVar(value="")
        self.wifi_var = tk.StringVar(value="")

    def _radio_group(self, parent, heading, options, var, none_value=""):
        section(parent, heading).pack(anchor="w", pady=(10, 2), fill="x")
        for key, label in options:
            ttk.Radiobutton(
                parent, text=f"  {label}", variable=var, value=key,
            ).pack(anchor="w", fill="x")

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Manual Hardware Setup ──────────────────────────────────").pack(anchor="w")
        info(wrap, "  Building a USB for a different machine? Set its hardware here.").pack(anchor="w", pady=(2, 6))

        scroll = ScrollFrame(wrap)
        scroll.pack(fill="both", expand=True)
        inner = scroll.inner

        def by(prefix, suffix_excl=(), suffix_incl=None):
            out = []
            for k, l in self.CPU_OPTIONS:
                if not k.startswith(prefix):
                    continue
                if suffix_incl is not None:
                    if any(k.endswith(s) for s in suffix_incl):
                        out.append((k, l))
                else:
                    if not any(k.endswith(s) for s in suffix_excl):
                        out.append((k, l))
            return out

        intel_desktop = [(k, l) for k, l in self.CPU_OPTIONS
                         if k.startswith("intel-") and not k.endswith("m")
                         and not any(k.endswith(s) for s in ("kr", "wl", "cl", "cm", "il", "tl"))]
        intel_laptop = [(k, l) for k, l in self.CPU_OPTIONS
                        if k.startswith("intel-") and (k.endswith("m") or
                            any(k.endswith(s) for s in ("kr", "wl", "cl", "cm", "il", "tl")))]
        amd_desktop = [(k, l) for k, l in self.CPU_OPTIONS if k.startswith("amd-") and k.endswith("d")]
        amd_tr = [(k, l) for k, l in self.CPU_OPTIONS if k.startswith("amd-tr")]
        amd_laptop = [(k, l) for k, l in self.CPU_OPTIONS if k.startswith("amd-") and k.endswith("m")]

        self._radio_group(inner, "CPU — Intel Desktop", intel_desktop, self.cpu_var)
        self._radio_group(inner, "CPU — Intel Laptop", intel_laptop, self.cpu_var)
        self._radio_group(inner, "CPU — AMD Desktop", amd_desktop, self.cpu_var)
        self._radio_group(inner, "CPU — AMD Threadripper", amd_tr, self.cpu_var)
        self._radio_group(inner, "CPU — AMD Laptop / APU", amd_laptop, self.cpu_var)

        section(inner, "Platform").pack(anchor="w", pady=(10, 2), fill="x")
        r = row(inner); r.pack(anchor="w", fill="x")
        self.sw_laptop = Switch(r, value=True)
        self.sw_laptop.pack(side="left")
        self.platform_label = info(r, "  laptop")
        self.platform_label.pack(side="left")
        self.sw_laptop.config(command=lambda: self.platform_label.config(
            text="  laptop" if self.sw_laptop.value else "  desktop"))

        section(inner, "CPU Cores").pack(anchor="w", pady=(10, 2), fill="x")
        r = row(inner); r.pack(anchor="w", fill="x")
        info(r, "  Core count:").pack(side="left")
        self.in_cores = Entry(r, value="4", width=8)
        self.in_cores.pack(side="left")

        self._radio_group(inner, "GPU", self.GPU_OPTIONS, self.gpu_var)

        section(inner, "Audio Codec").pack(anchor="w", pady=(10, 2), fill="x")
        info(inner, "  e.g. ALC256, ALC269, ALC1220").pack(anchor="w")
        r = row(inner); r.pack(anchor="w", fill="x")
        info(r, "  Codec:").pack(side="left")
        self.in_audio = Entry(r, placeholder="ALC256", width=12)
        self.in_audio.pack(side="left")

        self._radio_group(inner, "Ethernet", self.ETHERNET_OPTIONS, self.eth_var)
        self._radio_group(inner, "WiFi", self.WIFI_OPTIONS, self.wifi_var)

        section(inner, "Other").pack(anchor="w", pady=(10, 2), fill="x")
        r = row(inner); r.pack(anchor="w", fill="x")
        self.sw_nvme = Switch(r, value=True)
        self.sw_nvme.pack(side="left")
        info(r, "  NVMe drive").pack(side="left")
        r = row(inner); r.pack(anchor="w", fill="x")
        self.sw_tb = Switch(r, value=False)
        self.sw_tb.pack(side="left")
        info(r, "  Thunderbolt").pack(side="left")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Continue →", self._build_profile, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")
        self.status = info(wrap, "")
        self.status.pack(anchor="w", pady=(4, 0))

    def _build_profile(self):
        from hardware import HardwareProfile as HWP, SMBIOS_MAP

        cpu_key = self.cpu_var.get()
        gen, codename, vendor, oc_platform = self._CPU_META[cpu_key]

        gpu_key = self.gpu_var.get()
        gpu_vendor = "intel"
        if gpu_key == "amd":
            gpu_vendor = "amd"
        elif gpu_key == "nvidia":
            gpu_vendor = "nvidia"

        eth_key = self.eth_var.get()
        wifi_key = self.wifi_var.get()
        is_laptop = self.sw_laptop.value
        platform = "laptop" if is_laptop else "desktop"
        audio = self.in_audio.value.upper()

        try:
            cores = int(self.in_cores.value)
        except ValueError:
            cores = 4

        gpu_label = next((l for k, l in self.GPU_OPTIONS if k == gpu_key), "")

        profile = HWP(
            cpu_name=f"{vendor.title()} {codename}",
            cpu_vendor=vendor,
            cpu_generation=gen,
            cpu_codename=codename,
            oc_platform=oc_platform,
            core_count=cores,
            gpu_vendor=gpu_vendor,
            gpu_name=gpu_label,
            gpu_device_id=gpu_key if gpu_key not in ("amd", "nvidia", "") else "",
            audio_codec=audio,
            ethernet_chipset=eth_key,
            wifi_chipset=wifi_key,
            platform=platform,
            nvme_present=self.sw_nvme.value,
            has_thunderbolt=self.sw_tb.value,
            has_touchpad=is_laptop,
        )
        try:
            profile.smbios_model = SMBIOS_MAP.get((gen, platform), "")
        except Exception:
            pass

        self.app.profile = profile
        self.app.push_screen(VersionScreen)


class VersionScreen(Screen):
    def on_show(self):
        profile: HardwareProfile = self.app.profile
        versions = compatible_versions(profile.cpu_generation, profile.gpu_vendor, profile.cpu_vendor)
        self.versions = versions

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Select macOS Version ────────────────────────────────").pack(anchor="w")
        info(wrap, f"  {len(versions)} versions compatible with your hardware").pack(anchor="w", pady=(4, 8))

        list_frame = tk.Frame(wrap, bg=BG)
        list_frame.pack(fill="both", expand=True)
        items = []
        for v in versions:
            note = f"  ({v.notes})" if v.notes else ""
            items.append(f"  {v.name}{note}")
        self.listbox = ListBox(list_frame, items=items, height=14)
        self.listbox.pack(fill="both", expand=True)
        if items:
            self.listbox.selection_set(0)

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Continue → Select USB", self._next, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

    def _next(self):
        idx = self.listbox.index
        if idx is not None and self.versions:
            self.app.macos_version = self.versions[idx]
            self.app.push_screen(USBScreen)


# ─────────────────────────────────────────────────────────────────────────────
# USB select / build mode / wifi / dGPU / dual boot
# ─────────────────────────────────────────────────────────────────────────────


class USBScreen(Screen):
    def on_show(self):
        drives = get_usb_drives()
        self.drives = drives
        version: MacOSVersion = self.app.macos_version

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Select Target USB Drive ─────────────────────────────").pack(anchor="w")
        info(wrap, f"  Installing: {version.name}").pack(anchor="w", pady=(4, 0))
        warn_label(wrap, "  WARNING: The selected drive will be completely erased").pack(anchor="w", pady=(0, 8))

        items = [f"  {name}   {size}   {label}" for name, size, label in drives]
        if not items:
            items = ["  No USB drives detected — plug one in and re-open this screen"]
        list_frame = tk.Frame(wrap, bg=BG)
        list_frame.pack(fill="both", expand=True)
        self.listbox = ListBox(list_frame, items=items, height=12)
        self.listbox.pack(fill="both", expand=True)
        if drives:
            self.listbox.selection_set(0)

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Build & Install EFI", self._install, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "Don't have USB", lambda: self.app.push_screen(NoUSBPathScreen), "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

    def _install(self):
        idx = self.listbox.index
        if idx is not None and self.drives:
            selected = self.drives[idx][0]
            self.app.push_screen(BuildModeScreen, selected)


class NoUSBPathScreen(Screen):
    """Let the user pick a folder to save the EFI into instead of a USB."""

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Generate EFI Folder (No USB) ────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        for line in [
            "  HackMate will generate the EFI folder (OpenCore, kexts,",
            "  SSDTs, config.plist) and save it to the folder you choose.",
            "  No macOS recovery is downloaded — copy the EFI folder to",
            "  your drive's EFI partition when you're ready.",
        ]:
            info(wrap, line).pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  Folder path:").pack(anchor="w")

        r = row(wrap); r.pack(anchor="w", fill="x", pady=(2, 8))
        self.path_input = Entry(r, placeholder="e.g. /home/user/Desktop", width=60)
        self.path_input.pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(4, 0))
        button(btn_row, "Browse…", self._browse, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "Continue →", self._continue, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self, title="Choose folder to save EFI")
        if chosen:
            self.path_input.value = chosen

    def _continue(self):
        path = self.path_input.value
        if path:
            self._next(path)

    def _next(self, path: str) -> None:
        self.app.efi_output_path = path
        profile: HardwareProfile = self.app.profile
        has_dgpu = getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel"
        if getattr(profile, "wifi_chipset", "") == "intel":
            self.app.push_screen(WiFiKextScreen, "local", False, True)
        elif has_dgpu:
            self.app.push_screen(DGPUScreen, "local", False, True)
        else:
            self.app.push_screen(DualBootScreen, "local", False, True)


class WiFiKextScreen(Screen):
    """WiFi kext selection."""

    def __init__(self, app, device: str, repair: bool, skip_format: bool):
        super().__init__(app)
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Intel WiFi Mode ──────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        for line in [
            "  Standard (itlwm + HeliPort)",
            "    Works with ALL macOS versions including Tahoe.",
            "    Use HeliPort (saved to EFI/HackMate-Extras/) to connect.",
            "    Note: during the Tahoe installer, use ethernet — itlwm",
            "    needs HeliPort which cannot run in the recovery env.",
            "",
            "  Native AirportBSD (AirportItlwm)",
            "    Shows as built-in WiFi — no HeliPort needed.",
            "    No Tahoe build yet — use for Sonoma or earlier only.",
        ]:
            info(wrap, line).pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "Standard (itlwm + HeliPort)", lambda: self._choose("itlwm"), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Native (AirportItlwm)", lambda: self._choose("AirportItlwm"), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(anchor="w")

    def _choose(self, mode: str):
        self.app.wifi_kext_mode = mode
        profile: HardwareProfile = self.app.profile
        if getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel":
            self.app.push_screen(DGPUScreen, self.device, self.repair, self.skip_format)
        else:
            self.app.push_screen(DualBootScreen, self.device, self.repair, self.skip_format)


class BuildModeScreen(Screen):
    def __init__(self, app, device: str):
        super().__init__(app)
        self.device = device

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Build Mode ───────────────────────────────────────────").pack(anchor="w")
        info(wrap, f"  Device: {self.device}").pack(anchor="w", pady=(4, 8))
        for line in [
            "  Full Build        — formats USB, downloads recovery (~600 MB), installs everything fresh",
            "  Already Formatted — USB is already FAT32, skips format, downloads recovery + installs",
            "  Repair EFI        — keeps recovery on USB, updates OpenCore + kexts + SSDTs + config.plist",
        ]:
            info(wrap, line).pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "Full Build", lambda: self._next(False, False), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Already Formatted", lambda: self._next(False, True), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Repair EFI", lambda: self._next(True, False), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(anchor="w")

    def _next(self, repair: bool, skip_format: bool):
        profile: HardwareProfile = self.app.profile
        has_dgpu = getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel"
        if getattr(profile, "wifi_chipset", "") == "intel":
            self.app.push_screen(WiFiKextScreen, self.device, repair, skip_format)
        elif has_dgpu:
            self.app.push_screen(DGPUScreen, self.device, repair, skip_format)
        else:
            self.app.push_screen(DualBootScreen, self.device, repair, skip_format)


class DGPUScreen(Screen):
    """Ask user whether to disable discrete GPU for macOS (Optimus laptops)."""

    def __init__(self, app, device: str, repair: bool, skip_format: bool):
        super().__init__(app)
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def on_show(self):
        profile: HardwareProfile = self.app.profile
        dgpu = getattr(profile, "dgpu_name", "Discrete GPU")

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Discrete GPU Detected ───────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  {dgpu}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        for line in [
            "  macOS does not support Optimus (Intel + Nvidia/AMD switching).",
            "  The discrete GPU must be disabled, otherwise you will get:",
            "    • Black screen on boot",
            "    • Reduced battery life",
            "    • System instability",
            "",
            "  Disable via DeviceProperties (recommended)?",
            "  This adds 'disable-gpu' to your config.plist for the dGPU path.",
            "",
            "  Note: You can also disable it in BIOS under 'Switchable Graphics'.",
        ]:
            info(wrap, line).pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "Yes — disable in config.plist", lambda: self._choose(True), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "No — I'll handle it myself", lambda: self._choose(False), "back").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(anchor="w")

    def _choose(self, disable: bool):
        self.app.disable_dgpu = disable
        self.app.push_screen(DualBootScreen, self.device, self.repair, self.skip_format)


class DualBootScreen(Screen):
    """Ask if the user is dual-booting alongside Windows or Linux."""

    def __init__(self, app, device: str, repair: bool = False, skip_format: bool = False):
        super().__init__(app)
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Dual Boot Setup ──────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  Is this machine dual-booting with another OS?").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        for line in [
            "  Windows: OpenCore will show a Windows entry in the picker.",
            "  Linux:   Adds OpenLinuxBoot.efi so Linux EFI entries appear.",
            "  Both:    Both of the above.",
            "",
            "  If unsure, choose 'No dual boot'.",
        ]:
            info(wrap, line).pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "No dual boot", lambda: self._proceed(""), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Windows + macOS", lambda: self._proceed("windows"), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Linux + macOS", lambda: self._proceed("linux"), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Windows + Linux + macOS", lambda: self._proceed("both"), "primary").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "Scan disks first",
               lambda: self.app.push_screen(DiskMapScreen, self.device, self.repair, self.skip_format),
               "back").pack(anchor="w", pady=(0, 4), fill="x")
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(anchor="w")

    def _proceed(self, choice: str):
        self.app.dual_boot = choice
        self.app.push_screen(ConfirmScreen, self.device, self.repair, self.skip_format)


# ─────────────────────────────────────────────────────────────────────────────
# Confirm + Install (core build process)
# ─────────────────────────────────────────────────────────────────────────────


class ConfirmScreen(Screen):
    def __init__(self, app, device: str, repair: bool = False, skip_format: bool = False):
        super().__init__(app)
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def on_show(self):
        import re
        disk = re.sub(r'p?\d+$', '', self.device) if re.search(r'\d$', self.device) else self.device

        try:
            if IS_WINDOWS:
                model = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-Partition -DriveLetter {self.device.rstrip(':')} | Get-Disk).FriendlyName"],
                    capture_output=True, text=True, timeout=8
                ).stdout.strip() or "Unknown"
                size = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-Partition -DriveLetter {self.device.rstrip(':')} | Get-Disk).Size"],
                    capture_output=True, text=True, timeout=8
                ).stdout.strip()
                if size and size.isdigit():
                    size = f"{int(size) // 1024 // 1024 // 1024}GB"
                else:
                    size = "?"
            else:
                model = subprocess.run(
                    ["lsblk", "-dno", "MODEL", disk], capture_output=True, text=True
                ).stdout.strip() or "Unknown"
                size = subprocess.run(
                    ["lsblk", "-dno", "SIZE", disk], capture_output=True, text=True
                ).stdout.strip() or "?"
        except Exception:
            model, size = "Unknown", "?"

        self.confirm_phrase = f"WRITE {self.device}"
        if self.repair:
            action = "Repair EFI on"
            warn_text = "This will update OpenCore, kexts, and config on the existing USB."
        elif self.skip_format:
            action = "WRITE TO (no format)"
            warn_text = "USB must already be FAT32 formatted. No data will be erased."
        else:
            action = "FORMAT AND WRITE TO"
            warn_text = "ALL DATA ON THIS DRIVE WILL BE PERMANENTLY ERASED."

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Confirm ───────────────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  Target device:  {self.device}").pack(anchor="w")
        info(wrap, f"  Disk model:     {model}").pack(anchor="w")
        info(wrap, f"  Disk size:      {size}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  Action: {action} {self.device}").pack(anchor="w")
        warn_label(wrap, f"  ⚠  {warn_text}").pack(anchor="w")
        if getattr(self.app, "dual_boot", ""):
            info(wrap, f"  Dual boot: {self.app.dual_boot}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  To continue, type:  {self.confirm_phrase}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        self.confirm_input = Entry(wrap, placeholder=self.confirm_phrase, width=40)
        self.confirm_input.pack(anchor="w", pady=(0, 4))
        self.mismatch_label = warn_label(wrap, "")
        self.mismatch_label.pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Proceed", self._confirm, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Cancel", self.app.pop_screen, "back").pack(side="left")

    def _confirm(self):
        typed = self.confirm_input.value
        if typed != self.confirm_phrase:
            self.mismatch_label.config(text=f"  Type exactly: {self.confirm_phrase}")
            return
        self.app.push_screen(InstallScreen, self.device, self.repair, self.skip_format)


class InstallScreen(Screen):
    def __init__(self, app, device: str, repair: bool = False, skip_format: bool = False):
        super().__init__(app)
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        action = "Repairing" if self.repair else "Building"
        title(wrap, f"── {action} EFI → {self.device} ──────────────────────").pack(anchor="w")

        self.status_label = info(wrap, "")
        self.status_label.pack(anchor="w", pady=(6, 2))
        self.progress = ttk.Progressbar(wrap, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))

        log_area = tk.Frame(wrap, bg=BG)
        log_area.pack(fill="both", expand=True)
        log_row = tk.Frame(log_area, bg=BG)
        log_row.pack(fill="both", expand=True)

        self.log = LogView(log_row, height=22)
        self.log.pack(side="left", fill="both", expand=True)

        self.cmd_log = LogView(log_row, height=22, width=50)
        # cmd log hidden until "Advanced" is toggled

        bar = tk.Frame(log_area, bg=PANEL)
        bar.pack(fill="x")
        self._cmd_visible = False
        self.advanced_btn = button(bar, "Advanced ▶", self._toggle_advanced, "advanced")
        self.advanced_btn.pack(side="right")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

        threading.Thread(target=self.run_install, daemon=True).start()

    def _toggle_advanced(self):
        self._cmd_visible = not self._cmd_visible
        if self._cmd_visible:
            self.cmd_log.pack(side="left", fill="both", expand=True)
            self.advanced_btn.config(text="Advanced ✕")
        else:
            self.cmd_log.pack_forget()
            self.advanced_btn.config(text="Advanced ▶")

    def _status(self, pct: int, msg: str):
        self.status_label.config(text=f"  {msg}")
        self.progress["value"] = pct

    def _log(self, msg: str, level: str = "info"):
        self.log.write(msg, level)

    def _cmd_log_write(self, cmd: list):
        cmd_str = " ".join(shlex.quote(str(c)) for c in cmd)
        prompt = "hackmate@admin" if IS_WINDOWS else "hackmate@root"
        sym = ">" if IS_WINDOWS else "$"
        self.cmd_log.write(f"{prompt}{sym} {cmd_str}", "cmd")

    def _cmd_out(self, line: str, is_err: bool = False):
        self.cmd_log.write(f"  {line}", "cmd_err" if is_err else "cmd_out")

    def run_install(self):
        profile: HardwareProfile = self.app.profile
        version: MacOSVersion = self.app.macos_version
        device: str = self.device
        repair: bool = self.repair
        skip_format: bool = self.skip_format
        tmp = Path(get_tmp_dir())
        tmp.mkdir(parents=True, exist_ok=True)
        mount = get_mount_path(device, skip_format=skip_format)

        def ui(pct, msg):
            self.app.call_from_thread(self._status, pct, msg)

        def log(msg, level="info"):
            self.app.call_from_thread(self._log, msg, level)

        import urllib.request
        import zipfile

        local_mode = (device == "local")
        if local_mode:
            mount = self.app.efi_output_path

        try:
            if local_mode:
                ui(2, "Preparing EFI output folder...")
                log("── Local EFI mode: generating EFI folder without USB", "header")
                Path(mount).mkdir(parents=True, exist_ok=True)
                log(f"Output folder: {mount}", "ok")
            elif repair or skip_format:
                ui(2, "Mounting USB partition...")
                if repair:
                    log("── Repair mode: skipping format and recovery download", "header")
                else:
                    log("── Already formatted: skipping format step", "header")
                if not IS_WINDOWS:
                    if not mount_usb(device, mount):
                        raise RuntimeError(f"Failed to mount {device}")
                log(f"Mounted at {mount}", "ok")

                existing_efi = Path(f"{mount}") / "EFI" if not IS_WINDOWS else Path(f"{mount}\\EFI")
                if repair and existing_efi.exists():
                    import zipfile as zf
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_dir = Path.home() / "HackMate" / "backups"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_zip = backup_dir / f"EFI_backup_{ts}.zip"
                    file_count = 0
                    with zf.ZipFile(backup_zip, "w", zf.ZIP_DEFLATED) as z:
                        for f in existing_efi.rglob("*"):
                            if f.is_file():
                                z.write(f, f.relative_to(mount))
                                file_count += 1
                    size_mb = backup_zip.stat().st_size / 1024 / 1024
                    log(f"── EFI backed up: {file_count} files, {size_mb:.1f} MB → {backup_zip}", "ok")
            else:
                ui(2, f"Formatting {device} as FAT32...")
                log(f"── Formatting {device}...", "header")
                self.app.call_from_thread(self._cmd_log_write, ["format_usb"] if IS_WINDOWS else ["parted", "mkfs.fat"])
                fmt_ok = format_usb(device, mount)
                if not fmt_ok:
                    raise RuntimeError(f"Failed to format {device}")
                log(f"Formatted {device} as FAT32 (GPT+ESP)", "ok")

            ui(8, "Creating EFI structure...")
            efi = Path(f"{mount}") / "EFI" if not IS_WINDOWS else Path(f"{mount}\\EFI")
            oc_dir = efi / "OC"
            boot_dir = efi / "BOOT"
            kext_dir = oc_dir / "Kexts"
            acpi_dir = oc_dir / "ACPI"
            driver_dir = oc_dir / "Drivers"
            for d in [efi, oc_dir, boot_dir, kext_dir, acpi_dir, driver_dir]:
                d.mkdir(parents=True, exist_ok=True)
            log("EFI folder structure ready.", "ok")

            if not repair and not local_mode:
                ui(10, f"Downloading {version.name} recovery from Apple...")
                log(f"── Fetching {version.name} from Apple CDN...", "header")
                recovery_dest = tmp / "recovery"
                self.app.call_from_thread(self._cmd_log_write, [
                    "python3" if not IS_WINDOWS else "python", "macrecovery.py",
                    "-b", version.board_id, "-m", version.mlb,
                    *(version.os_flag.split() if version.os_flag else []),
                    "download", "--outdir", str(recovery_dest),
                ])

                def recovery_progress(msg):
                    level = "ok" if ("complete" in msg.lower() or "verification" in msg.lower()) else "info"
                    self.app.call_from_thread(self._log, f"  {msg}", level)
                    self.app.call_from_thread(self._cmd_out, msg)

                ok, msg = download_recovery(version, recovery_dest, progress_cb=recovery_progress)
                if not ok:
                    raise RuntimeError(f"Recovery download failed: {msg}")
                log(msg, "ok")

                ui(28, "Copying recovery to USB...")
                log("── Copying recovery to USB (may take 1-2 min for large images)...", "header")
                files = list(recovery_dest.iterdir())
                total_bytes = sum(f.stat().st_size for f in files if f.is_file())
                log(f"  {len(files)} file(s), {total_bytes // 1024 // 1024} MB to write", "info")
                com_apple = efi.parent / "com.apple.recovery.boot"
                if com_apple.exists():
                    shutil.rmtree(str(com_apple))
                com_apple.mkdir(parents=True)
                for i, src in enumerate(files, 1):
                    mb = src.stat().st_size // 1024 // 1024
                    log(f"  Writing {src.name} ({mb} MB)...", "info")
                    shutil.copy2(str(src), str(com_apple / src.name))
                    log(f"  {src.name} written", "ok")
                log("Recovery copied to USB.", "ok")
            else:
                log("  Skipping recovery download (repair mode)", "info")

            ui(35, "Generating SMBIOS...")
            log("── Generating SMBIOS...", "header")
            from smbios import generate as gen_smbios_local, SMBIOSData as SMBIOSDataLocal
            smbios = None

            if repair:
                existing_config = oc_dir / "config.plist"
                if existing_config.exists():
                    try:
                        import plistlib
                        with open(str(existing_config), "rb") as f:
                            old_cfg = plistlib.load(f)
                        pi = old_cfg.get("PlatformInfo", {}).get("Generic", {})
                        if pi.get("SystemSerialNumber") and pi.get("MLB"):
                            smbios = SMBIOSDataLocal(
                                model=pi.get("SystemProductName", profile.smbios_model),
                                serial=pi["SystemSerialNumber"],
                                board_serial=pi["MLB"],
                                system_uuid=pi.get("SystemUUID", ""),
                                rom=pi.get("ROM", b"").hex() if isinstance(pi.get("ROM"), bytes) else pi.get("ROM", ""),
                            )
                            log("  Reusing existing SMBIOS (serial preserved)", "ok")
                    except Exception as e:
                        log(f"  Could not read existing SMBIOS ({e}), generating fresh", "info")

            if smbios is None:
                smbios = gen_smbios_local(profile)

            log(f"  Model:   {smbios.model}", "ok")
            log(f"  Serial:  {smbios.serial}", "ok")
            log(f"  MLB:     {smbios.board_serial}", "ok")
            log(f"  UUID:    {smbios.system_uuid}", "ok")

            ui(40, "Generating config.plist...")
            log("── Generating config.plist...", "header")
            macos_major = int(version.version) if version and version.version.isdigit() else 0
            dual_boot = getattr(self.app, "dual_boot", "")
            config = gen_config(profile, smbios, macos_major, wifi_kext_mode=self.app.wifi_kext_mode, dual_boot=dual_boot)
            if self.app.disable_dgpu:
                from config_editor import set_dgpu_disabled
                set_dgpu_disabled(config, True)
                log("  dGPU disabled in DeviceProperties", "ok")
            config_path = oc_dir / "config.plist"
            write_plist(config, config_path)
            log(f"  config.plist written ({config_path.stat().st_size} bytes)", "ok")

            ui(45, "Selecting kexts...")
            log("── Selecting kexts...", "header")
            from kexts import select_kexts as select_kexts_local, download_kexts
            kexts = select_kexts_local(profile, wifi_kext_mode=self.app.wifi_kext_mode)
            log(f"  {len(kexts)} kexts selected for this hardware", "ok")

            ui(50, f"{'Verifying' if repair else 'Downloading'} {len(kexts)} kexts...")
            log(f"── {'Verifying and updating' if repair else 'Downloading'} kexts from GitHub...", "header")

            def kext_progress(i, n, msg):
                pct = 50 + int((i / n) * 30)
                self.app.call_from_thread(self._status, pct, msg)
                self.app.call_from_thread(self._log, f"  [{i+1}/{n}] {msg}", "info")

            results = download_kexts(kexts, kext_dir, progress_cb=kext_progress, verify=repair)
            ok_count = sum(1 for v in results.values() if v.startswith("OK"))
            log(f"  {ok_count} kexts downloaded successfully", "ok")
            failed_kexts = {name for name, res in results.items() if res.startswith("ERROR")}
            for name, result in results.items():
                if result.startswith("ERROR"):
                    log(f"  WARN: {name} — {result}", "warn")

            if failed_kexts:
                import plistlib
                cfg = plistlib.loads(config_path.read_bytes())
                before = len(cfg["Kernel"]["Add"])
                cfg["Kernel"]["Add"] = [
                    k for k in cfg["Kernel"]["Add"]
                    if not any(name in k.get("BundlePath", "") for name in failed_kexts)
                ]
                removed = before - len(cfg["Kernel"]["Add"])
                if removed:
                    config_path.write_bytes(plistlib.dumps(cfg, fmt=plistlib.FMT_XML))
                    log(f"  Removed {removed} failed kext(s) from config.plist to keep EFI bootable", "warn")

            from kexts import download_heliport, download_usbtoolbox_app
            extras_dir = Path(mount) / "EFI" / "HackMate-Extras"
            if self.app.wifi_kext_mode == "itlwm":
                ok = download_heliport(extras_dir, progress_cb=lambda m: log(f"  {m}", "info"))
                if ok:
                    log("  HeliPort saved to EFI/HackMate-Extras/", "ok")
                else:
                    log("  HeliPort download failed — get it from github.com/OpenIntelWireless/HeliPort", "warn")
            ok = download_usbtoolbox_app(extras_dir, progress_cb=lambda m: log(f"  {m}", "info"))
            if ok:
                log("  USBToolBox app saved to EFI/HackMate-Extras/", "ok")
            else:
                log("  USBToolBox download failed — get it from github.com/USBToolBox/Tool", "warn")

            MIN_EFI = 50 * 1024
            oc_required = [
                boot_dir / "BOOTx64.efi",
                oc_dir / "OpenCore.efi",
                driver_dir / "OpenRuntime.efi",
                driver_dir / "HfsPlus.efi",
            ]
            oc_valid = repair and all(f.exists() and f.stat().st_size > MIN_EFI for f in oc_required)

            if oc_valid:
                ui(88, "OpenCore files valid — skipping download")
                log("── OpenCore already valid, skipping download", "ok")
            else:
                ui(82, "Downloading OpenCore...")
                log("── Downloading OpenCore...", "header")
                oc_url = "https://api.github.com/repos/acidanthera/OpenCorePkg/releases/latest"
                req = urllib.request.Request(oc_url, headers={"User-Agent": "HackMate/1.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    oc_data = json.loads(r.read())

                oc_asset = None
                for asset in oc_data.get("assets", []):
                    name = asset["name"].lower()
                    if "opencore-" in name and "release" in name and name.endswith(".zip"):
                        oc_asset = asset
                        break

                if oc_asset:
                    oc_zip = tmp / oc_asset["name"]
                    urllib.request.urlretrieve(oc_asset["browser_download_url"], str(oc_zip))
                    log(f"  Downloaded {oc_asset['name']}", "ok")

                    oc_extract = tmp / "oc_extracted"
                    with zipfile.ZipFile(str(oc_zip)) as z:
                        z.extractall(str(oc_extract))

                    x64_root = oc_extract / "X64"
                    search_root = x64_root if x64_root.exists() else oc_extract

                    for fname, fdest in [
                        ("BOOTx64.efi", boot_dir / "BOOTx64.efi"),
                        ("OpenCore.efi", oc_dir / "OpenCore.efi"),
                    ]:
                        found = list(search_root.rglob(fname))
                        if found:
                            shutil.copy(str(found[0]), str(fdest))
                            log(f"  {fname} copied", "ok")

                    base_drivers = ["OpenRuntime.efi", "HfsPlus.efi", "ResetNvramEntry.efi"]
                    if dual_boot in ("linux", "both"):
                        base_drivers.append("OpenLinuxBoot.efi")
                    for driver in base_drivers:
                        found = list(search_root.rglob(driver))
                        if found:
                            shutil.copy(str(found[0]), str(driver_dir / driver))
                            log(f"  Driver: {driver}", "ok")

                    hfsplus_dest = driver_dir / "HfsPlus.efi"
                    if not hfsplus_dest.exists():
                        log("  HfsPlus.efi not in OC zip — fetching from OcBinaryData...", "info")
                        hfsplus_url = "https://raw.githubusercontent.com/acidanthera/OcBinaryData/master/Drivers/HfsPlus.efi"
                        try:
                            req = urllib.request.Request(hfsplus_url, headers={"User-Agent": "HackMate/1.0"})
                            with urllib.request.urlopen(req, timeout=15) as r:
                                hfsplus_dest.write_bytes(r.read())
                            log("  HfsPlus.efi downloaded", "ok")
                        except Exception as e:
                            log(f"  HfsPlus.efi download failed: {e}", "error")
                else:
                    log("  Could not find OpenCore release asset", "error")

            ssdt_backup_dir = None
            if repair and acpi_dir.exists() and any(acpi_dir.iterdir()):
                ssdt_backup_dir = tmp / "acpi_backup"
                shutil.copytree(str(acpi_dir), str(ssdt_backup_dir))
                shutil.rmtree(str(acpi_dir))
                acpi_dir.mkdir(parents=True)

            ui(90, "Generating SSDTs with SSDTTime...")
            log("── Generating SSDTs with SSDTTime...", "header")
            ssdts = _required_ssdts(profile, kexts)
            log(f"  Need: {', '.join(ssdts)}", "info")

            from ssdt import generate as gen_ssdts
            ssdt_results = gen_ssdts(
                needed=ssdts,
                acpi_dir=acpi_dir,
                tmp=tmp,
                progress_cb=lambda m: log(f"  {m}", "info"),
                cpu_generation=profile.cpu_generation,
            )

            ok_ssdts = [n for n, s in ssdt_results.items() if s == "OK"]
            skip_ssdts = [n for n, s in ssdt_results.items() if s.startswith("SKIP")]
            err_ssdts = [n for n, s in ssdt_results.items() if s.startswith("ERROR")]

            if repair and ssdt_backup_dir and not ok_ssdts:
                log("  All SSDTs failed — restoring previous SSDTs", "warn")
                shutil.rmtree(str(acpi_dir))
                shutil.copytree(str(ssdt_backup_dir), str(acpi_dir))

            if skip_ssdts or err_ssdts:
                import plistlib
                with open(str(config_path), "rb") as f:
                    cfg = plistlib.load(f)
                bad = {f"{n}.aml" for n in skip_ssdts + err_ssdts
                       if not (acpi_dir / f"{n}.aml").exists()}
                cfg["ACPI"]["Add"] = [e for e in cfg["ACPI"]["Add"] if e.get("Path", "") not in bad]
                with open(str(config_path), "wb") as f:
                    plistlib.dump(cfg, f)

            for n in ok_ssdts:
                log(f"  {n}.aml", "ok")
            for n in skip_ssdts:
                reason = ssdt_results.get(n, "")
                not_required = "not required" in reason or "not present" in reason
                log(f"  {n} — {reason}", "info" if not_required else "warn")
            for n in err_ssdts:
                log(f"  {n} — {ssdt_results[n]}", "error")

            truly_manual = [n for n in skip_ssdts + err_ssdts
                            if not ("not required" in ssdt_results.get(n, "") or
                                    "not present" in ssdt_results.get(n, ""))]
            if truly_manual:
                note = acpi_dir / "README_MANUAL_SSDTS.txt"
                note.write_text(
                    "These SSDTs need manual installation:\n\n" +
                    "\n".join(f"  - {n}.aml" for n in truly_manual) +
                    "\n\nDownload prebuilt SSDTs from:\n"
                    "  https://dortania.github.io/Getting-Started-With-ACPI/\n"
                )
                log(f"  {len(truly_manual)} SSDTs need manual install — see README_MANUAL_SSDTS.txt", "warn")

            ui(97, "Running EFI sanity check...")
            log("", "info")
            log("── EFI Sanity Check ──────────────────────────────", "header")
            from efi_check import check as efi_check
            issues = efi_check(efi, profile)
            errors = [m for lvl, m in issues if lvl == "error"]
            warnings = [m for lvl, m in issues if lvl == "warn"]
            infos = [m for lvl, m in issues if lvl == "info"]
            oks = [m for lvl, m in issues if lvl == "ok"]
            for lvl, m in issues:
                if lvl != "ok":
                    prefix = {"error": "✗", "warn": "⚠", "info": "ℹ"}.get(lvl, "•")
                    log(f"  {prefix} {m}", lvl)
            if oks:
                log(f"  ✓ {len(oks)} checks passed", "ok")
            log("──────────────────────────────────────────────────", "header")
            if errors:
                log(f"  {len(errors)} error(s) — must fix before booting", "error")
                if warnings:
                    log(f"  {len(warnings)} warning(s)", "warn")
                if infos:
                    log(f"  {len(infos)} recommendation(s)", "info")
            elif warnings:
                log(f"  {len(warnings)} warning(s) — review before booting", "warn")
                if infos:
                    log(f"  {len(infos)} recommendation(s)", "info")
            elif infos:
                log(f"  {len(infos)} recommendation(s) — {len(oks)} checks passed", "info")
            else:
                log(f"  All {len(oks)} checks passed", "ok")

            if not local_mode:
                ui(99, "Unmounting USB...")
                unmount_usb(mount)
            shutil.rmtree(str(tmp), ignore_errors=True)

            if local_mode:
                ui(100, "EFI folder ready!")
                log("", "info")
                log("══════════════════════════════════════════════════", "header")
                log("  EFI folder generated!", "ok")
                log(f"  Saved to: {mount}", "info")
                if truly_manual:
                    log("  ! Some SSDTs need manual install (see README_MANUAL_SSDTS.txt)", "warn")
                log("  Copy the EFI folder to your drive's EFI partition.", "info")
                log("══════════════════════════════════════════════════", "header")
            else:
                mode_label = "Repair complete" if repair else f"Done! {version.name} EFI ready"
                ui(100, f"{mode_label} on {device}")
                log("", "info")
                log("══════════════════════════════════════════════════", "header")
                log("  USB is ready!", "ok")
                if truly_manual:
                    log("  ! Some SSDTs need manual install (see README_MANUAL_SSDTS.txt)", "warn")
                log("  Configure BIOS settings, then boot from the USB.", "info")
                log("══════════════════════════════════════════════════", "header")
                if not repair:
                    self.app.call_from_thread(
                        self.app.push_screen, BIOSChecklistScreen, version.name, device
                    )

        except Exception as e:
            ui(0, f"Error: {e}")
            log(f"FATAL: {e}", "error")
            import traceback
            log(traceback.format_exc(), "error")
            try:
                unmount_usb(mount)
            except Exception:
                pass
            shutil.rmtree(str(tmp), ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Restore / repair flow
# ─────────────────────────────────────────────────────────────────────────────


class RestoreScreen(Screen):
    def on_show(self):
        backup_dir = Path.home() / "HackMate" / "backups"
        self.backups = sorted(backup_dir.glob("EFI_backup_*.zip"), reverse=True) if backup_dir.exists() else []
        self.usb_drives = get_usb_drives()

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Restore EFI from Backup ──────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  Select backup:").pack(anchor="w")

        backup_items = [f"  {b.stem}  ({b.stat().st_size // 1024}KB)" for b in self.backups] or ["  No backups found"]
        self.backup_list = ListBox(wrap, items=backup_items, height=6)
        self.backup_list.pack(fill="x", pady=(2, 8))
        if self.backups:
            self.backup_list.selection_set(0)

        info(wrap, "  Restore to USB:").pack(anchor="w")
        usb_items = [f"  {name}   {size}   {label}" for name, size, label in self.usb_drives] or ["  No USB drives detected"]
        self.usb_list = ListBox(wrap, items=usb_items, height=6)
        self.usb_list.pack(fill="x", pady=(2, 8))
        if self.usb_drives:
            self.usb_list.selection_set(0)

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "Restore", self._restore, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

    def _restore(self):
        if not self.backups or not self.usb_drives:
            return
        b_idx = self.backup_list.index or 0
        u_idx = self.usb_list.index or 0
        backup = self.backups[b_idx]
        device = self.usb_drives[u_idx][0]
        self.app.push_screen(RestoreConfirmScreen, backup, device)


class RestoreConfirmScreen(Screen):
    def __init__(self, app, backup: Path, device: str):
        super().__init__(app)
        self.backup = backup
        self.device = device

    def on_show(self):
        self.confirm_phrase = f"RESTORE {self.device}"
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Confirm Restore ───────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  Backup:  {self.backup.stem}").pack(anchor="w")
        info(wrap, f"  Target:  {self.device}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        warn_label(wrap, "  ⚠  This will overwrite the EFI partition on the target USB.").pack(anchor="w")
        info(wrap, f"  To continue, type:  {self.confirm_phrase}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        self.confirm_input = Entry(wrap, placeholder=self.confirm_phrase, width=40)
        self.confirm_input.pack(anchor="w", pady=(0, 4))
        self.mismatch_label = warn_label(wrap, "")
        self.mismatch_label.pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Restore", self._confirm, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Cancel", self.app.pop_screen, "back").pack(side="left")

    def _confirm(self):
        typed = self.confirm_input.value
        if typed != self.confirm_phrase:
            self.mismatch_label.config(text=f"  Type exactly: {self.confirm_phrase}")
            return
        threading.Thread(target=self._do_restore, daemon=True).start()

    def _do_restore(self):
        import zipfile as zf
        mount = get_mount_path(self.device)

        def notify(msg):
            self.app.call_from_thread(self.app.notify, msg)

        try:
            if not IS_WINDOWS:
                mnt_path = Path("/tmp/hackmate_restore")
                mnt_path.mkdir(parents=True, exist_ok=True)
                if not mount_usb(self.device, str(mnt_path)):
                    raise RuntimeError("Failed to mount USB for restore")
                efi_dest = mnt_path / "EFI"
            else:
                efi_dest = Path(f"{mount}\\EFI")

            if efi_dest.exists():
                shutil.rmtree(str(efi_dest))
            with zf.ZipFile(self.backup, "r") as z:
                z.extractall(str(efi_dest.parent) if not IS_WINDOWS else str(Path(f"{mount}\\")))

            if not IS_WINDOWS:
                unmount_usb(str(mnt_path))

            notify(f"Restore complete — EFI from {self.backup.stem} written to {self.device}")
        except Exception as e:
            notify(f"Restore failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Config editor
# ─────────────────────────────────────────────────────────────────────────────


class ConfigEditorUSBScreen(Screen):
    """Pick which USB / config.plist to edit."""

    def on_show(self):
        from config_editor import find_configs
        self._configs = find_configs()

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=20)
        title(wrap, "── Edit Config.plist ────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  Select a config.plist to edit:").pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        items = [str(p) for p in self._configs] or ["  No config.plist found on any mounted USB"]
        self.listbox = ListBox(wrap, items=items, height=10)
        self.listbox.pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>", self._select)
        self.listbox.bind("<Double-Button-1>", self._select)

        info(wrap, "").pack(anchor="w")
        info(wrap, "  Mount your USB first if it doesn't appear above.").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        button(wrap, "← Back", self.app.pop_screen, "back").pack(anchor="w")

    def _select(self, _e=None):
        idx = self.listbox.index
        if idx is not None and self._configs:
            self.app.push_screen(ConfigEditorScreen, self._configs[idx])


class ConfigEditorScreen(Screen):
    """Simple / Advanced config.plist editor."""

    def __init__(self, app, config_path):
        super().__init__(app)
        self._path = config_path
        self._mode = "simple"
        self._cfg = None
        self._changes: list[str] = []

    def _load(self):
        from config_editor import load_config
        self._cfg = load_config(self._path)

    def on_show(self):
        self._load()
        from config_editor import (
            get_boot_args, get_timeout, get_hide_auxiliary, get_oc_logging,
            get_sip_enabled, get_secure_boot_model, get_smbios,
            get_igpu_platform_id, suggest_framebuffers, BOOT_ARG_PRESETS,
            suggest_audio_layouts, get_dgpu_disabled,
        )
        cfg = self._cfg
        args = get_boot_args(cfg)
        profile = self.app.profile

        alcid_val = str(args.get("alcid", ""))
        timeout_val = str(get_timeout(cfg))
        smbios_val = get_smbios(cfg)
        sbm_val = get_secure_boot_model(cfg)

        gpu_id = getattr(profile, "gpu_device_id", "").lower() if profile else ""
        fb_opts = suggest_framebuffers(gpu_id)
        cur_fb = get_igpu_platform_id(cfg)
        gpu_label = getattr(profile, "gpu_name", "") if profile else ""

        codec = getattr(profile, "audio_codec", "") if profile else ""
        alc_opts = suggest_audio_layouts(codec)

        dgpu_name = getattr(profile, "dgpu_name", "") if profile else ""
        dgpu_vendor = getattr(profile, "dgpu_vendor", "") if profile else ""
        has_dgpu = bool(dgpu_vendor and getattr(profile, "gpu_vendor", "") == "intel")

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Config Editor ──────────────────────────────────────").pack(anchor="w")
        self.mode_btn = button(wrap, "Switch to Advanced mode", self._toggle_mode, "back")
        self.mode_btn.pack(anchor="w", pady=(4, 4))
        info(wrap, f"  {self._path}").pack(anchor="w", pady=(0, 8))

        scroll = ScrollFrame(wrap)
        scroll.pack(fill="both", expand=True)
        inner = scroll.inner

        self.simple_panel = tk.Frame(inner, bg=BG)
        self.simple_panel.pack(fill="both", expand=True)
        self.advanced_panel = tk.Frame(inner, bg=BG)
        # advanced panel packed only when toggled

        sp = self.simple_panel
        section(sp, "Boot Arg Presets").pack(anchor="w", fill="x", pady=(4, 2))
        r = row(sp); r.pack(anchor="w", fill="x")
        for name in BOOT_ARG_PRESETS:
            button(r, name, lambda n=name: self._apply_preset(n), "advanced").pack(side="left", padx=(0, 4))

        section(sp, "Boot Args").pack(anchor="w", fill="x", pady=(10, 2))
        r = row(sp); r.pack(anchor="w", fill="x")
        self.sw_verbose = Switch(r, value="-v" in args)
        self.sw_verbose.pack(side="left"); info(r, "  Verbose (-v)").pack(side="left")
        r = row(sp); r.pack(anchor="w", fill="x")
        self.sw_nocompat = Switch(r, value="-no_compat_check" in args)
        self.sw_nocompat.pack(side="left"); info(r, "  No compat check").pack(side="left")
        r = row(sp); r.pack(anchor="w", fill="x")
        self.sw_debug = Switch(r, value="debug" in args)
        self.sw_debug.pack(side="left"); info(r, "  Debug logging").pack(side="left")
        r = row(sp); r.pack(anchor="w", fill="x")
        info(r, "  alcid (audio layout):").pack(side="left")
        self.in_alcid = Entry(r, value=alcid_val, placeholder="11", width=8)
        self.in_alcid.pack(side="left")
        if alc_opts:
            info(sp, "  Suggestions for " + codec + ": " +
                 "  ".join(f"[{lid}] {desc}" for lid, desc in alc_opts)).pack(anchor="w")
            r = row(sp); r.pack(anchor="w", fill="x")
            for lid, _desc in alc_opts[:4]:
                button(r, str(lid), lambda l=lid: self._set_alcid(l), "advanced").pack(side="left", padx=(0, 4))

        section(sp, "OpenCore").pack(anchor="w", fill="x", pady=(10, 2))
        r = row(sp); r.pack(anchor="w", fill="x")
        info(r, "  Picker timeout (sec):").pack(side="left")
        self.in_timeout = Entry(r, value=timeout_val, placeholder="5", width=8)
        self.in_timeout.pack(side="left")
        r = row(sp); r.pack(anchor="w", fill="x")
        self.sw_recovery = Switch(r, value=not get_hide_auxiliary(cfg))
        self.sw_recovery.pack(side="left"); info(r, "  Show recovery").pack(side="left")
        r = row(sp); r.pack(anchor="w", fill="x")
        self.sw_oclog = Switch(r, value=get_oc_logging(cfg))
        self.sw_oclog.pack(side="left"); info(r, "  OC file logging").pack(side="left")

        section(sp, "Security").pack(anchor="w", fill="x", pady=(10, 2))
        r = row(sp); r.pack(anchor="w", fill="x")
        self.sw_sip = Switch(r, value=get_sip_enabled(cfg))
        self.sw_sip.pack(side="left"); info(r, "  SIP enabled").pack(side="left")
        r = row(sp); r.pack(anchor="w", fill="x")
        info(r, "  SecureBootModel:").pack(side="left")
        self.in_sbm = Entry(r, value=sbm_val, placeholder="Disabled", width=14)
        self.in_sbm.pack(side="left")

        section(sp, "System").pack(anchor="w", fill="x", pady=(10, 2))
        r = row(sp); r.pack(anchor="w", fill="x")
        info(r, "  SMBIOS model:").pack(side="left")
        self.in_smbios = Entry(r, value=smbios_val, placeholder="MacBookPro15,2", width=20)
        self.in_smbios.pack(side="left")

        self.sw_dgpu = None
        if has_dgpu:
            section(sp, "Discrete GPU").pack(anchor="w", fill="x", pady=(10, 2))
            info(sp, f"  {dgpu_name}").pack(anchor="w")
            r = row(sp); r.pack(anchor="w", fill="x")
            self.sw_dgpu = Switch(r, value=get_dgpu_disabled(cfg))
            self.sw_dgpu.pack(side="left"); info(r, "  Disable dGPU (Optimus fix)").pack(side="left")

        self.in_fb = None
        if fb_opts or gpu_id:
            section(sp, "iGPU Framebuffer").pack(anchor="w", fill="x", pady=(10, 2))
            info(sp, f"  Detected: {gpu_label} ({gpu_id})").pack(anchor="w")
            self.fb_current = info(sp, f"  Current:  {cur_fb or '(not set)'}")
            self.fb_current.pack(anchor="w")
            info(sp, "  Suggestions:").pack(anchor="w")
            for hex_id, label in fb_opts:
                r = row(sp); r.pack(anchor="w", fill="x")
                info(r, f"  {label}").pack(side="left")
                button(r, "Apply", lambda h=hex_id: self._apply_fb(h), "advanced").pack(side="left", padx=(6, 0))
            r = row(sp); r.pack(anchor="w", fill="x")
            info(r, "  Custom platform-id:").pack(side="left")
            self.in_fb = Entry(r, value=cur_fb, placeholder="e.g. 0000c087", width=12)
            self.in_fb.pack(side="left")

        ap = self.advanced_panel
        section(ap, "Advanced: raw plist key editor").pack(anchor="w", fill="x", pady=(4, 2))
        info(ap, "  Key path (dot-separated):").pack(anchor="w")
        self.adv_key = Entry(ap, placeholder="e.g. Misc.Debug.Target", width=50)
        self.adv_key.pack(anchor="w", pady=(0, 6))
        info(ap, "  Value:").pack(anchor="w")
        self.adv_val = Entry(ap, placeholder="value", width=50)
        self.adv_val.pack(anchor="w", pady=(0, 6))
        info(ap, "  Type:").pack(anchor="w")
        self.adv_type = Entry(ap, value="string", placeholder="string / bool / int / data", width=30)
        self.adv_type.pack(anchor="w", pady=(0, 6))
        r = row(ap); r.pack(anchor="w", fill="x", pady=(0, 6))
        button(r, "Get", self._adv_get, "primary").pack(side="left", padx=(0, 8))
        button(r, "Set", self._adv_set, "primary").pack(side="left")
        section(ap, "Recent changes").pack(anchor="w", fill="x", pady=(6, 2))
        self.adv_log = info(ap, "  (none yet)")
        self.adv_log.pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Save", self._save, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")
        self.save_status = info(wrap, "")
        self.save_status.pack(anchor="w", pady=(4, 0))

    def _toggle_mode(self):
        self._mode = "advanced" if self._mode == "simple" else "simple"
        if self._mode == "advanced":
            self.simple_panel.pack_forget()
            self.advanced_panel.pack(fill="both", expand=True)
            self.mode_btn.config(text="Switch to Simple mode")
        else:
            self.advanced_panel.pack_forget()
            self.simple_panel.pack(fill="both", expand=True)
            self.mode_btn.config(text="Switch to Advanced mode")

    def _set_alcid(self, layout_id):
        self.in_alcid.value = str(layout_id)
        self.save_status.config(text=f"  alcid set to {layout_id} — save to write.")

    def _apply_preset(self, preset_key):
        from config_editor import get_boot_args, set_boot_args, BOOT_ARG_PRESETS
        self._apply_simple()
        args = get_boot_args(self._cfg)
        args.update(BOOT_ARG_PRESETS[preset_key])
        set_boot_args(self._cfg, args)
        self.save_status.config(text=f"  Preset '{preset_key}' applied — save to write.")

    def _apply_fb(self, hex_id):
        from config_editor import set_igpu_platform_id
        set_igpu_platform_id(self._cfg, hex_id)
        try:
            self.fb_current.config(text=f"  Current:  {hex_id}")
            self.in_fb.value = hex_id
        except Exception:
            pass
        self.save_status.config(text=f"  Framebuffer set to {hex_id} — save to write.")

    def _adv_get(self):
        from config_editor import get_value
        key = self.adv_key.value
        try:
            val = get_value(self._cfg, key)
            self.adv_val.value = str(val)
        except Exception as e:
            self.adv_val.value = f"ERROR: {e}"

    def _adv_set(self):
        from config_editor import set_value, coerce_value
        key = self.adv_key.value
        raw = self.adv_val.value
        typ = self.adv_type.value or "string"
        try:
            val = coerce_value(raw, typ)
            set_value(self._cfg, key, val)
            entry = f"  • {key} → {raw}"
            self._changes.append(entry)
            self.adv_log.config(text="\n".join(self._changes[-8:]))
        except Exception as e:
            self.adv_log.config(text=f"  ERROR: {e}")

    def _save(self):
        self._apply_simple()
        from config_editor import save_config
        try:
            save_config(self._path, self._cfg)
            self.save_status.config(text="  ✓ Saved.")
        except Exception as e:
            self.save_status.config(text=f"  ✗ Save failed: {e}")

    def _apply_simple(self):
        from config_editor import (
            get_boot_args, set_boot_args, set_sip, set_hide_auxiliary,
            set_timeout, set_oc_logging, set_secure_boot_model, set_smbios,
            set_igpu_platform_id, set_dgpu_disabled,
        )
        cfg = self._cfg
        args = get_boot_args(cfg)

        for flag, sw in [("-v", self.sw_verbose), ("-no_compat_check", self.sw_nocompat)]:
            if sw.value:
                args[flag] = True
            else:
                args.pop(flag, None)

        if self.sw_debug.value:
            args["debug"] = "0x100"
            args["keepsyms"] = "1"
        else:
            args.pop("debug", None)
            args.pop("keepsyms", None)

        alcid = self.in_alcid.value
        if alcid.isdigit():
            args["alcid"] = alcid
        else:
            args.pop("alcid", None)

        set_boot_args(cfg, args)

        t = self.in_timeout.value
        if t.isdigit():
            set_timeout(cfg, int(t))

        set_hide_auxiliary(cfg, not self.sw_recovery.value)
        set_oc_logging(cfg, self.sw_oclog.value)
        set_sip(cfg, self.sw_sip.value)

        sbm = self.in_sbm.value
        if sbm:
            set_secure_boot_model(cfg, sbm)

        smbios = self.in_smbios.value
        if smbios:
            set_smbios(cfg, smbios)

        if self.in_fb is not None:
            fb = self.in_fb.value
            if fb and len(fb) == 8:
                try:
                    set_igpu_platform_id(cfg, fb)
                except Exception:
                    pass

        if self.sw_dgpu is not None:
            try:
                set_dgpu_disabled(cfg, self.sw_dgpu.value)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Disk map + partition wizard
# ─────────────────────────────────────────────────────────────────────────────


class DiskMapScreen(Screen):
    """Show disk layout, detected OSes, and conflicts."""

    def __init__(self, app, device: str = "", repair: bool = False, skip_format: bool = False):
        super().__init__(app)
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Disk Map ─────────────────────────────────────────────").pack(anchor="w")
        self.status = info(wrap, "  Scanning disks…")
        self.status.pack(anchor="w", pady=(4, 4))

        self.log = LogView(wrap, height=18)
        self.log.pack(fill="both", expand=True, pady=(0, 8))
        self.conflict_area = warn_label(wrap, "")
        self.conflict_area.pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "Resize / Free Space →",
               lambda: self.app.push_screen(PartitionWizardScreen), "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        from dualboot import scan_disks, scan_all_bootloaders, check_conflicts, build_disk_tree
        disks = scan_disks()
        bootloaders = scan_all_bootloaders(disks)
        tree = build_disk_tree(disks, bootloaders)
        conflicts = check_conflicts(disks, bootloaders)

        def _update():
            self.status.config(text="  Disks found:")
            self.log.write(tree)
            if conflicts:
                self.conflict_area.config(text="\n".join(f"  ⚠  {c}" for c in conflicts))
        self.app.call_from_thread(_update)


class PartitionWizardScreen(Screen):
    """Pick a disk and partition to shrink."""

    def __init__(self, app):
        super().__init__(app)
        self._parts: list = []

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Resize Partition ─────────────────────────────────────").pack(anchor="w")
        info(wrap, "  Select a disk:").pack(anchor="w", pady=(8, 2))

        self.disk_var = tk.StringVar()
        self.disk_select = ttk.Combobox(wrap, textvariable=self.disk_var, state="readonly", width=60)
        self.disk_select.pack(anchor="w", pady=(0, 8))
        self.disk_select.bind("<<ComboboxSelected>>", self._on_disk_selected)
        self._disk_options = []

        info(wrap, "  Select a partition to shrink:").pack(anchor="w")
        self.part_list = ListBox(wrap, height=10)
        self.part_list.pack(fill="x", pady=(2, 4))
        self.part_list.bind("<<ListboxSelect>>", self._on_part_selected)
        self.part_info = info(wrap, "")
        self.part_info.pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Next →", self._next, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

        threading.Thread(target=self._load_disks, daemon=True).start()

    def _load_disks(self):
        from dualboot import scan_disks
        disks = scan_disks()
        options = [(f"{d.device}  {d.model}  {d.size}", d.device) for d in disks if d.is_gpt]

        def _set():
            self._disk_options = options
            self.disk_select["values"] = [label for label, _ in options]
            if options:
                self.disk_select.current(0)
                self._load_partitions(options[0][1])
        self.app.call_from_thread(_set)

    def _on_disk_selected(self, _e=None):
        idx = self.disk_select.current()
        if 0 <= idx < len(self._disk_options):
            threading.Thread(target=self._load_partitions, args=(self._disk_options[idx][1],), daemon=True).start()

    def _load_partitions(self, disk: str):
        from partutil import list_partitions
        parts = [
            p for p in list_partitions(disk)
            if p.fs_type not in ("", "fat32", "fat16", "vfat")
            and p.size_bytes > 500 * 1024 * 1024
        ]
        self._parts = parts

        def _set():
            self.part_list.set_items([
                f"  {p.device}  {p.size_gb:.1f} GB  {p.fs_type.upper()}  {p.label or '?'}" for p in parts
            ])
        self.app.call_from_thread(_set)

    def _on_part_selected(self, _e=None):
        idx = self.part_list.index
        if idx is not None and idx < len(self._parts):
            p = self._parts[idx]
            self.part_info.config(text=f"  {p.device}  {p.size_gb:.1f} GB  {p.fs_type.upper()}")

    def _next(self):
        idx = self.part_list.index
        if idx is None or idx >= len(self._parts):
            self.app.notify("Select a partition first", severity="warning")
            return
        self.app.push_screen(PartSizeScreen, self._parts[idx])


class PartSizeScreen(Screen):
    """Enter how much space to free."""

    def __init__(self, app, part):
        super().__init__(app)
        self._part = part

    def on_show(self):
        p = self._part
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── How Much Space to Free ───────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  Partition:    {p.device}").pack(anchor="w")
        info(wrap, f"  Filesystem:   {p.fs_type.upper()}").pack(anchor="w")
        info(wrap, f"  Current size: {p.size_gb:.1f} GB").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  How much space do you want to FREE for macOS?").pack(anchor="w")
        info(wrap, "  macOS needs at least 40 GB. Example: 60 GB").pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        self.free_input = Entry(wrap, placeholder="e.g. 60 GB", width=20)
        self.free_input.pack(anchor="w")
        self.free_input.bind("<KeyRelease>", self._on_change)
        self.preview = info(wrap, "")
        self.preview.pack(anchor="w", pady=(4, 0))
        info(wrap, "").pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        button(btn_row, "Next →", self._next, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

    def _on_change(self, _e=None):
        from partutil import parse_size_input
        val = parse_size_input(self.free_input.value)
        p = self._part
        if val is None:
            self.preview.config(text="")
            return
        new_size = p.size_bytes - val
        new_gb = new_size / (1024 ** 3)
        freed_gb = val / (1024 ** 3)
        if new_size < 5 * 1024 ** 3:
            self.preview.config(text=f"  ⚠  Remaining size would be {new_gb:.1f} GB — dangerously small", fg=WARN)
        else:
            self.preview.config(text=f"  {p.device} → {new_gb:.1f} GB   ({freed_gb:.1f} GB freed for macOS)", fg=INFOC)

    def _next(self):
        from partutil import parse_size_input
        free_bytes = parse_size_input(self.free_input.value)
        if not free_bytes:
            self.app.notify("Enter a valid size (e.g. 60 GB)", severity="warning")
            return
        new_size = self._part.size_bytes - free_bytes
        if new_size < 5 * 1024 ** 3:
            self.app.notify("Remaining size too small — need at least 5 GB", severity="error")
            return
        if free_bytes >= self._part.size_bytes:
            self.app.notify("Cannot free more than the full partition size", severity="error")
            return
        self.app.push_screen(PartResizeConfirmScreen, self._part, new_size)


class PartResizeConfirmScreen(Screen):
    """Stern warning + typed confirmation before resizing."""

    def __init__(self, app, part, new_size_bytes: int):
        super().__init__(app)
        self._part = part
        self._new_size = new_size_bytes
        self._confirm_phrase = f"SHRINK {part.device}"

    def on_show(self):
        p = self._part
        old_gb = p.size_gb
        new_gb = self._new_size / (1024 ** 3)
        freed_gb = old_gb - new_gb

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Confirm Resize ───────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  Partition:    {p.device}  ({p.fs_type.upper()})").pack(anchor="w")
        info(wrap, f"  Current size: {old_gb:.1f} GB").pack(anchor="w")
        info(wrap, f"  New size:     {new_gb:.1f} GB").pack(anchor="w")
        info(wrap, f"  Space freed:  {freed_gb:.1f} GB  (unallocated — macOS installer will use it)").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        warn_label(wrap, "  ⚠  BACK UP YOUR DATA BEFORE CONTINUING.").pack(anchor="w")
        warn_label(wrap, "  ⚠  Power loss during resize may corrupt the partition.").pack(anchor="w")
        warn_label(wrap, "  ⚠  This cannot be undone automatically.").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, f"  To continue, type:  {self._confirm_phrase}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        self.confirm_input = Entry(wrap, placeholder=self._confirm_phrase, width=40)
        self.confirm_input.pack(anchor="w", pady=(0, 4))
        self.mismatch_label = warn_label(wrap, "")
        self.mismatch_label.pack(anchor="w")

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        button(btn_row, "Resize", self._confirm, "danger").pack(side="left", padx=(0, 8))
        button(btn_row, "← Cancel", self.app.pop_screen, "back").pack(side="left")

    def _confirm(self):
        typed = self.confirm_input.value
        if typed != self._confirm_phrase:
            self.mismatch_label.config(text=f"  Type exactly: {self._confirm_phrase}")
            return
        self.app.push_screen(PartResizeRunScreen, self._part, self._new_size)


class PartResizeRunScreen(Screen):
    """Execute the partition resize and stream progress."""

    def __init__(self, app, part, new_size_bytes: int):
        super().__init__(app)
        self._part = part
        self._new_size = new_size_bytes
        self._done = False

    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, f"── Resizing {self._part.device} ──────────────────────────────").pack(anchor="w")
        self.status = info(wrap, "")
        self.status.pack(anchor="w", pady=(4, 4))
        self.log = LogView(wrap, height=18)
        self.log.pack(fill="both", expand=True, pady=(0, 8))
        button(wrap, "← Back", self._back, "back").pack(anchor="w")

        threading.Thread(target=self._run, daemon=True).start()

    def _back(self):
        if not self._done:
            self.app.notify("Resize in progress — please wait", severity="warning")
            return
        self.app.pop_screen()

    def _run(self):
        from partutil import resize_partition

        def log(msg: str):
            self.app.call_from_thread(self.log.write, msg)

        self.app.call_from_thread(self.status.config, text="  Resizing — do not interrupt…")

        result = resize_partition(self._part, self._new_size, log_cb=log)
        self._done = True
        freed_gb = self._part.size_gb - self._new_size / (1024 ** 3)

        if result == "OK":
            self.app.call_from_thread(
                self.status.config, text=f"  ✓  Done — {freed_gb:.1f} GB freed. Unallocated space is ready for macOS.")
            self.app.call_from_thread(self.app.notify, "Resize complete", "information")
        else:
            self.app.call_from_thread(self.status.config, text=f"  ✗  {result}")
            self.app.call_from_thread(self.app.notify, "Resize failed", "error")


# ─────────────────────────────────────────────────────────────────────────────
# Log checker + enable OC logging + USB mapping + BIOS checklist
# ─────────────────────────────────────────────────────────────────────────────


class EnableOCLoggingScreen(Screen):
    """Pick a USB, patch its config.plist to enable OpenCore file logging."""

    def on_show(self):
        drives = get_usb_drives()
        self._drives = drives
        self._selected = 0

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Enable OC Logging ────────────────────────────────────────").pack(anchor="w")
        info(wrap, "  Patches config.plist on your USB so OpenCore writes a log file on next boot.").pack(anchor="w", pady=(4, 0))
        info(wrap, "  After rebooting (even if it fails), plug USB back in and use Analyze to read the log.").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        section(wrap, "Select your USB").pack(anchor="w", fill="x")

        if drives:
            items = [f"  {d[0]}  {d[1]}  {d[2]}" for d in drives]
            self.listbox = ListBox(wrap, items=items, height=8)
            self.listbox.pack(fill="x", pady=(2, 8))
            self.listbox.selection_set(0)
            self.listbox.bind("<<ListboxSelect>>", self._on_select)
        else:
            warn_label(wrap, "  No USB drives detected. Insert your HackMate USB and reopen this screen.").pack(anchor="w")
            self.listbox = None

        info(wrap, "").pack(anchor="w")
        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(4, 0))
        button(btn_row, "Patch config.plist", self._patch, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")
        self.status = info(wrap, "")
        self.status.pack(anchor="w", pady=(8, 0))

    def _on_select(self, _e=None):
        if self.listbox and self.listbox.index is not None:
            self._selected = self.listbox.index

    def _patch(self):
        if not self._drives:
            self.status.config(text="  No USB drives found.")
            return
        threading.Thread(target=self._do_patch, daemon=True).start()

    def _do_patch(self):
        from oc_log import enable_oc_logging

        drive = self._drives[self._selected]
        device = drive[0]

        self.app.call_from_thread(self.status.config, text="  Mounting USB…")
        mount = get_mount_path(device, skip_format=True)
        mount_usb(device, mount)

        cfg_path = Path(mount) / "EFI" / "OC" / "config.plist"
        if not cfg_path.exists():
            unmount_usb(mount)
            self.app.call_from_thread(
                self.status.config,
                text=f"  config.plist not found at {cfg_path}\n"
                     "  Make sure this is a HackMate USB with EFI/OC/config.plist on it.",
            )
            return

        self.app.call_from_thread(self.status.config, text="  Patching config.plist…")
        ok = enable_oc_logging(cfg_path)
        unmount_usb(mount)

        if ok:
            self.app.call_from_thread(
                self.status.config,
                text="  ✓ OC logging enabled.\n"
                     "  Reboot with this USB. Even if it fails, plug it back in.\n"
                     "  Log will be at: EFI/OC/opencore-<date>.txt on the USB.\n"
                     "  Then use Check Logs → Analyze to read it.",
            )
        else:
            self.app.call_from_thread(
                self.status.config, text=f"  ✗ Failed to patch {cfg_path} — check permissions.")


class LogCheckerScreen(Screen):
    def on_show(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Log Analyzer ─────────────────────────────────────────────").pack(anchor="w")
        info(wrap, "  Paste the path to an OpenCore log, kernel panic (.panic), or any boot log.").pack(anchor="w", pady=(4, 8))

        r = row(wrap); r.pack(fill="x")
        info(r, "  Path: ").pack(side="left")
        self.path_input = Entry(r, placeholder="/path/to/opencore-2026-06-25.txt", width=60)
        self.path_input.pack(side="left", fill="x", expand=True)
        self.path_input.bind("<Return>", lambda e: self._run_analysis(self.path_input.value))

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(8, 4))
        button(btn_row, "Analyze", lambda: self._run_analysis(self.path_input.value), "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "Enable OC Logging", lambda: self.app.push_screen(EnableOCLoggingScreen), "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")
        info(wrap, "  Enable OC Logging: patches config.plist on your USB so OpenCore writes a log file on next boot.").pack(anchor="w")

        self.summary = info(wrap, "")
        self.summary.pack(anchor="w", pady=(6, 4))
        self.log = LogView(wrap, height=20)
        self.log.pack(fill="both", expand=True)

        threading.Thread(target=self._scan_usbs, daemon=True).start()

    def _scan_usbs(self):
        """Mount all USBs, find OC logs and panic files, auto-fill the most recent."""
        self.app.call_from_thread(self.summary.config, text="  Scanning USB drives for logs…")

        drives = get_usb_drives()
        found: list[Path] = []

        def _already_mounted(device: str):
            try:
                for line in Path("/proc/mounts").read_text().splitlines():
                    parts = line.split()
                    if parts and parts[0] == device:
                        return parts[1]
            except Exception:
                pass
            return None

        for i, (device, size, label) in enumerate(drives):
            existing = _already_mounted(device)
            if existing:
                base = Path(existing)
            else:
                mount = f"/tmp/hackmate_scan_{i}"
                Path(mount).mkdir(parents=True, exist_ok=True)
                if not mount_usb(device, mount):
                    continue
                base = Path(mount)

            for search in [base, base / "EFI" / "OC"]:
                if search.exists():
                    found += sorted(search.glob("opencore-*.txt"), reverse=True)
            found += sorted(base.glob("**/*.panic"), reverse=True)[:3]

        found.sort(key=lambda p: p.name, reverse=True)

        if found:
            self.app.call_from_thread(setattr, self.path_input, "value", str(found[0]))
            self.app.call_from_thread(
                self.summary.config,
                text=f"  Found {len(found)} log(s) on USB — most recent auto-filled. Click Analyze.")
        else:
            self.app.call_from_thread(
                self.summary.config,
                text="  No logs found on USB. Paste a path manually or use Enable OC Logging first.")

    def _run_analysis(self, path: str):
        path = (path or "").strip()
        if not path:
            return
        threading.Thread(target=self._analyze, args=(path,), daemon=True).start()

    def _analyze(self, path: str):
        from log_checker import analyze_file
        self.app.call_from_thread(self.summary.config, text="  Analyzing…")
        self.app.call_from_thread(self.log.clear)

        profile = getattr(self.app, "profile", None)
        findings = analyze_file(path, profile)

        n_crit = sum(1 for f in findings if f.severity == "critical")
        n_warn = sum(1 for f in findings if f.severity == "warning")
        n_info = sum(1 for f in findings if f.severity == "info")

        parts = []
        if n_crit:
            parts.append(f"{n_crit} critical")
        if n_warn:
            parts.append(f"{n_warn} warning{'s' if n_warn != 1 else ''}")
        if n_info:
            parts.append(f"{n_info} info")
        summary = "  " + "  •  ".join(parts) if parts else "  No issues found"
        self.app.call_from_thread(self.summary.config, text=summary)

        for f in findings:
            level = {"critical": "critical", "warning": "warn", "info": "info"}.get(f.severity, "info")
            icon = {"critical": "✗", "warning": "⚠", "info": "ℹ"}.get(f.severity, "•")
            conf = f" [{f.confidence}]" if f.confidence != "likely" else ""
            self.app.call_from_thread(self.log.write, f"{icon}  {f.title}{conf}", level)
            self.app.call_from_thread(self.log.write, f"   {f.explanation}", "info")
            for step in f.fix_steps:
                self.app.call_from_thread(self.log.write, f"   → {step}", "info")
            if f.context_lines:
                self.app.call_from_thread(self.log.write, "   ┄", "context")
                for ctx in f.context_lines:
                    self.app.call_from_thread(self.log.write, f"   {ctx}", "context")
            self.app.call_from_thread(self.log.write, "")


class USBMappingScreen(Screen):
    def on_show(self):
        drives = get_usb_drives()
        self._drives = drives

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── USB Port Mapping (Post-Install) ─────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  1. Boot into macOS, then run USBToolBox from your USB:").pack(anchor="w")
        info(wrap, "     EFI/HackMate-Extras/  →  map your ports  →  Export").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        info(wrap, "  2. Select the drive with your OpenCore EFI:").pack(anchor="w")

        items = [f"  {n}   {s}   {l}" for n, s, l in drives] or ["  No USB drives detected"]
        self.drive_list = ListBox(wrap, items=items, height=6)
        self.drive_list.pack(fill="x", pady=(2, 8))
        if drives:
            self.drive_list.selection_set(0)

        info(wrap, "  3. Path to your generated UTBMap.kext:").pack(anchor="w")
        self.kext_path = Entry(wrap, placeholder="e.g. /Users/you/Desktop/UTBMap.kext", width=60)
        self.kext_path.pack(anchor="w", pady=(2, 4))
        button(wrap, "Browse…", self._browse, "primary").pack(anchor="w", pady=(0, 8))

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(4, 0))
        button(btn_row, "Apply USB Map", self._apply, "primary").pack(side="left", padx=(0, 8))
        button(btn_row, "← Back", self.app.pop_screen, "back").pack(side="left")

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self, title="Select UTBMap.kext folder")
        if chosen:
            self.kext_path.value = chosen

    def _apply(self):
        threading.Thread(target=self._do_apply, daemon=True).start()

    def _do_apply(self):
        kext_src = Path(self.kext_path.value)
        idx = self.drive_list.index

        if not kext_src.exists():
            self.app.call_from_thread(self.app.notify, "UTBMap.kext path not found", "error")
            return
        if not kext_src.name.lower().startswith("utbmap"):
            self.app.call_from_thread(self.app.notify, "Select the UTBMap.kext folder, not a file inside it", "warning")
            return
        if idx is None or not self._drives:
            self.app.call_from_thread(self.app.notify, "Select a drive first", "warning")
            return

        device = self._drives[idx][0]
        mount = get_mount_path(device, skip_format=True)

        try:
            if not IS_WINDOWS:
                mount_usb(device, mount)
            kext_dest = Path(mount) / "EFI" / "OC" / "Kexts" / "UTBMap.kext"
            if kext_dest.exists():
                shutil.rmtree(str(kext_dest))
            shutil.copytree(str(kext_src), str(kext_dest))

            config_path = Path(mount) / "EFI" / "OC" / "config.plist"
            if config_path.exists():
                try:
                    import plistlib
                    with open(config_path, "rb") as f:
                        cfg = plistlib.load(f)
                    for entry in cfg.get("Kernel", {}).get("Add", []):
                        name = entry.get("BundlePath", "").split("/")[0]
                        if name == "UTBMap.kext":
                            entry["Enabled"] = True
                        elif name == "USBToolBox.kext":
                            entry["Enabled"] = False
                    with open(config_path, "wb") as f:
                        plistlib.dump(cfg, f)
                except Exception:
                    pass

            if not IS_WINDOWS:
                unmount_usb(mount)
            self.app.call_from_thread(
                self.app.notify, f"UTBMap.kext applied to {device} — reboot to take effect", "information")
        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"Failed: {e}", "error")


class BIOSChecklistScreen(Screen):
    """Show what BIOS settings to configure before booting the USB."""

    def __init__(self, app, version_name: str, device: str):
        super().__init__(app)
        self.version_name = version_name
        self.device = device

    def on_show(self):
        profile: HardwareProfile = self.app.profile
        is_amd = getattr(profile, "cpu_vendor", "") == "amd"
        has_nvidia = getattr(profile, "gpu_vendor", "") == "nvidia"

        items = [
            ("Disable Secure Boot",       "Security > Secure Boot → Disabled"),
            ("Disable Fast Boot",         "Boot > Fast Boot → Disabled  (or Thorough)"),
            ("Set USB as first boot",     "Boot Order → move your USB to top"),
            ("Enable XHCI Handoff",       "USB > XHCI Hand-off → Enabled  (USB 3.0 in macOS)"),
            ("Disable CSM / Legacy Boot", "Boot > CSM → Disabled  (UEFI only)"),
            ("Set DVMT pre-alloc ≥ 64MB", "Advanced > Video > DVMT Pre-Allocated → 64M or higher"),
        ]
        if is_amd:
            items.append(("Disable Above 4G Decoding", "Advanced > PCI > Above 4G Decoding → Disabled  (AMD boot fix)"))
        if has_nvidia:
            items.append(("Disable dGPU (if dual GPU)", "Advanced > GPU → Discrete GPU Disabled  (Nvidia unsupported)"))

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)
        title(wrap, "── Before You Boot ──────────────────────────────────────").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        ok_label(wrap, f"  USB ready: {self.version_name} on {self.device}").pack(anchor="w")
        info(wrap, "").pack(anchor="w")
        warn_label(wrap, "  Configure these BIOS settings first:").pack(anchor="w")
        info(wrap, "  (Location varies by motherboard — check your manual)").pack(anchor="w")
        info(wrap, "").pack(anchor="w")

        scroll = ScrollFrame(wrap)
        scroll.pack(fill="both", expand=True)
        for text_, detail in items:
            info(scroll.inner, f"  ◻  {text_}").pack(anchor="w")
            info(scroll.inner, f"       {detail}").pack(anchor="w")
            info(scroll.inner, "").pack(anchor="w")

        info(wrap, "  Then boot from USB. At OpenCore picker, select the macOS installer.").pack(anchor="w", pady=(4, 8))
        button(wrap, "Got it — I'm done", self.app.pop_screen, "primary").pack(anchor="w")


if __name__ == "__main__":
    HackMateApp().mainloop()
