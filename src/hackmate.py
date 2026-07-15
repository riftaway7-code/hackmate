import subprocess
import os
import sys
import shutil
import shlex
import json
from pathlib import Path


def _enable_windows_vt_mode() -> None:
    """Legacy conhost.exe (plain cmd.exe / non-Windows-Terminal PowerShell)
    doesn't interpret ANSI escape codes unless ENABLE_VIRTUAL_TERMINAL_PROCESSING
    is explicitly turned on for the console — without it, both Textual's
    output and this file's own raw \\033[...m prints (DEMO_MODE below) show up
    as literal escape sequences instead of color."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

_enable_windows_vt_mode()

DEMO_MODE = "--demo" in sys.argv

if DEMO_MODE:
    import time as _time

    def _c(code, text): return f"\033[{code}m{text}\033[0m"
    def _green(t):  return _c("32", t)
    def _cyan(t):   return _c("36", t)
    def _grey(t):   return _c("90", t)
    def _yellow(t): return _c("33", t)

    BANNER = """
\033[36m██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗
██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝
███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗
██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝
██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝\033[0m
  Automated OpenCore EFI builder — any hardware
"""

    def _line(msg, ok=False, warn=False, header=False, grey=False):
        if ok:     print(_green(f"  ✓  {msg}"))
        elif warn: print(_yellow(f"  ⚠  {msg}"))
        elif header: print(_cyan(f"\n  {msg}"))
        elif grey: print(_grey(f"  {msg}"))
        else:      print(f"  {msg}")

    print(BANNER)
    _time.sleep(0.6)

    _line("── Scanning Hardware ─────────────────────────────────────", header=True)
    _time.sleep(0.5)
    for row in [
        ("CPU       Intel Core i5-8350U", True),
        ("Codename  Kaby Lake-R  (Gen 8)", True),
        ("Platform  laptop  —  Laptop", True),
        ("GPU       Intel UHD Graphics 620", True),
        ("Audio     Realtek ALC257  →  layout-id 11", True),
        ("Ethernet  Intel I219-V", True),
        ("WiFi      Intel Wireless-AC 8265", True),
        ("SMBIOS    MacBookPro15,2", True),
        ("Kexts     22 selected", True),
        ("NVMe      Yes   Thunderbolt: Yes", True),
    ]:
        _line(row[0], ok=row[1])
        _time.sleep(0.07)

    _time.sleep(0.5)
    _line("── Downloading Kexts ─────────────────────────────────────", header=True)
    _time.sleep(0.3)
    for k in ["Lilu","VirtualSMC","WhateverGreen","AppleALC","IntelMausiEthernet",
              "itlwm","IntelBluetoothFirmware","VoodooPS2Controller","VoodooI2C",
              "VoodooI2CELAN","USBToolBox","UTBMap","NVMeFix","CPUFriend"]:
        _line(f"{k}.kext", ok=True)
        _time.sleep(0.09)
    _line("HeliPort saved to EFI/HackMate-Extras/", ok=True)
    _line("USBToolBox app saved to EFI/HackMate-Extras/", ok=True)

    _time.sleep(0.4)
    _line("── Generating SSDTs from DSDT ────────────────────────────", header=True)
    _time.sleep(0.3)
    for name, method in [("SSDT-PLUG","SSDTTime"),("SSDT-EC-USBX","SSDTTime"),
                          ("SSDT-PNLF","SSDTTime"),("SSDT-GPI0","SSDTTime"),
                          ("SSDT-XOSI","bundled")]:
        _line(f"{name:<16} [{method}]", ok=True)
        _time.sleep(0.15)

    _time.sleep(0.4)
    _line("── OpenCore + Config ─────────────────────────────────────", header=True)
    _time.sleep(0.4)
    _line("OpenCore 1.0.4 extracted", ok=True)
    _time.sleep(0.2)
    _line("SMBIOS generated  (MacBookPro15,2)", ok=True)
    _time.sleep(0.2)
    _line("config.plist generated  (42 quirks configured)", ok=True)

    _time.sleep(0.4)
    _line("── EFI Sanity Check ──────────────────────────────────────", header=True)
    _time.sleep(0.4)
    _line("42 checks passed", ok=True)

    _time.sleep(0.3)
    print()
    print(_cyan("  ══════════════════════════════════════════════════════"))
    print(_green("  ✓  USB is ready!  Boot from it to install macOS Tahoe."))
    print(_grey("     Configure BIOS settings, then select the installer."))
    print(_cyan("  ══════════════════════════════════════════════════════"))
    print()
    _time.sleep(1.5)
    sys.exit(0)

from compat import require_admin, IS_WINDOWS, get_usb_drives, format_usb, mount_usb, unmount_usb, get_mount_path, get_tmp_dir

if "--doctor" in sys.argv:
    # Auditing only reads an EFI folder, so it needs neither root nor the TUI.
    from efi_doctor import main as _doctor_main
    sys.exit(_doctor_main(sys.argv))

require_admin()

from updater import check_and_update
if check_and_update():
    os.execv(sys.executable, [sys.executable] + sys.argv)

try:
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Label, Button, ListView, ListItem, ProgressBar, Static, RichLog, LoadingIndicator, Input, Switch, Select
    from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
    from textual.screen import Screen
    from textual import work
except ModuleNotFoundError:
    print("\nERROR: 'textual' is not installed.")
    print("Run setup first:\n")
    print("  python3 setup.py   (from the hackmate/ folder)\n")
    print("Or install manually:")
    print(f"  {sys.executable} -m pip install textual\n")
    sys.exit(1)

from hardware import scan, HardwareProfile
from kexts import select_kexts, get_alc_layout
from smbios import generate as gen_smbios
from config_gen import generate as gen_config, write_plist, _required_ssdts
from recovery import compatible_versions, download_recovery, MacOSVersion
from project_stats import fetch_project_stats, format_stats_panel

CSS = """
Screen                { background: #0d0d0d; }
Header                { background: #111111; color: #00ff88; }
Footer                { background: #111111; }
.screen-inner         { padding: 1 3; height: 1fr; }
Container             { height: 1fr; }
Vertical              { height: 1fr; }
.title                { color: #00ff88; margin-bottom: 1; }
.dim                  { color: #555555; }
.warn                 { color: #ff4444; }
.ok                   { color: #00ff88; }
.info                 { color: #888888; }
Button                { margin: 0 0 1 0; }
Button.primary        { background: #00ff88; color: #000000; }
Button.danger         { background: #ff4444; color: #ffffff; }
Button.back           { background: #222222; color: #888888; }
ListView              { height: 14; border: solid #333333; background: #111111; }
ListItem              { color: #cccccc; padding: 0 1; }
ListItem:hover        { background: #1a1a1a; }
ListItem.--highlight  { background: #003322; color: #00ff88; }
ProgressBar              { margin: 1 0; }
ProgressBar > .bar--bar  { color: #00ff88; }
LoadingIndicator         { height: 1; color: #00ff88; }
Static                   { color: #cccccc; }
#log-area                { height: 1fr; border: solid #222222; background: #0a0a0a; }
#log-row                 { height: 1fr; }
#log                     { width: 1fr; border: none; background: #0a0a0a; color: #888888; }
#cmd-log                 { width: 1fr; border-left: solid #1e1e1e; background: #070710;
                           color: #44ff88; display: none; }
#log-bar                 { height: 1; background: #0b0b0b; border-top: solid #1a1a1a; }
#log-bar-space           { width: 1fr; }
Button.advanced-btn      { height: 1; border: none; min-width: 14; padding: 0 1;
                           background: transparent; color: #3a3a3a; }
Button.advanced-btn:hover { color: #00ff88; }
.hw-row               { margin-bottom: 0; }
.hw-key               { color: #555555; width: 12; }
.hw-val               { color: #cccccc; }
.cfg-section          { color: #00ff88; height: 1; margin-top: 1; }
.cfg-label            { color: #aaaaaa; width: 32; content-align: left middle; }
.cfg-row              { height: 3; align: left middle; }
.manual-row           { height: 1; align: left middle; }
Switch                { margin: 0 1 0 0; }
#editor-scroll        { height: 1fr; border: solid #1a1a1a; }
#manual-scroll        { height: 1fr; border: solid #1a1a1a; }
#simple-panel         { height: auto; }
#advanced-panel       { height: auto; }
.short-input          { width: 16; }
#checker-scroll       { height: 1fr; border: solid #1a1a1a; }
#checker-summary      { height: 1; }
.finding-critical     { color: #ff4444; }
.finding-warn         { color: #ffaa00; }
.finding-info         { color: #888888; }
.finding-context      { color: #2a2a2a; }
#welcome-row          { height: 1fr; }
#welcome-stats        { width: 26; padding: 1 0 0 3; border-left: solid #333333; }
#health-targets       { height: 8; border: solid #333333; background: #111111; }
#health-log           { height: 1fr; border: solid #222222; background: #0a0a0a; }
#health-summary       { height: 2; }
"""

BANNER = (
    "██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗\n"
    "██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝\n"
    "███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗  \n"
    "██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝  \n"
    "██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗\n"
    "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝"
)

class EnableOCLoggingScreen(Screen):
    """Pick a USB, patch its config.plist to enable OpenCore file logging."""

    def compose(self) -> ComposeResult:
        from compat import get_usb_drives
        drives = get_usb_drives()
        yield Header()
        yield Container(
            Vertical(
                Static("── Enable OC Logging ────────────────────────────────────────", classes="title"),
                Static("  Patches config.plist on your USB so OpenCore writes a log file on next boot.", classes="info"),
                Static("  After rebooting (even if it fails), plug USB back in and use Analyze to read the log.", classes="info"),
                Static(""),
                Static("  ── Select your USB ───────────────────────────────────────", classes="cfg-section"),
                *(
                    [ListView(
                        *[ListItem(Label(f"  {d[0]}  {d[1]}  {d[2]}"), id=f"drv-{i}")
                          for i, d in enumerate(drives)],
                        id="log-usb-list"
                    )] if drives else
                    [Static("  No USB drives detected. Insert your HackMate USB and reopen this screen.", classes="warn")]
                ),
                Static(""),
                Horizontal(
                    Button("Patch config.plist", id="patch", classes="primary"),
                    Button("← Back",             id="back",  classes="back"),
                ),
                Static("", id="log-status"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def __init__(self):
        super().__init__()
        from compat import get_usb_drives
        self._drives = get_usb_drives()
        self._selected = 0

    def on_list_view_selected(self, event) -> None:
        try:
            idx = int(event.item.id.split("-")[1])
            self._selected = idx
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "patch":
            if not self._drives:
                self.query_one("#log-status", Static).update("  [red]No USB drives found.[/red]")
                return
            self._do_patch()
        elif event.button.id == "back":
            self.app.pop_screen()

    @work(thread=True)
    def _do_patch(self) -> None:
        from oc_log import enable_oc_logging
        from compat import get_mount_path, mount_usb, unmount_usb

        drive = self._drives[self._selected]
        device = drive[0]  # (device, size, label)
        status = self.query_one("#log-status", Static)

        self.app.call_from_thread(status.update, "  Mounting USB…")
        mount = get_mount_path(device, skip_format=True)
        mount_usb(device, mount)

        cfg_path = Path(mount) / "EFI" / "OC" / "config.plist"
        if not cfg_path.exists():
            unmount_usb(mount)
            self.app.call_from_thread(
                status.update,
                f"  [red]config.plist not found at {cfg_path}[/red]\n"
                "  Make sure this is a HackMate USB with EFI/OC/config.plist on it."
            )
            return

        self.app.call_from_thread(status.update, "  Patching config.plist…")
        ok = enable_oc_logging(cfg_path)
        unmount_usb(mount)

        if ok:
            self.app.call_from_thread(
                status.update,
                "  [green]✓ OC logging enabled.[/green]\n"
                "  Reboot with this USB. Even if it fails, plug it back in.\n"
                "  Log will be at: EFI/OC/opencore-<date>.txt on the USB.\n"
                "  Then use Check Logs → Analyze to read it."
            )
        else:
            self.app.call_from_thread(
                status.update,
                f"  [red]✗ Failed to patch {cfg_path} — check permissions.[/red]"
            )

class LogCheckerScreen(Screen):

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Log Analyzer ─────────────────────────────────────────────", classes="title"),
                Static("  Paste the path to an OpenCore log, kernel panic (.panic), or any boot log.", classes="info"),
                Static(""),
                Horizontal(
                    Static("  Path: ", classes="cfg-label"),
                    Input(placeholder="/path/to/opencore-2026-06-25.txt", id="log-path"),
                    classes="cfg-row",
                ),
                Static(""),
                Horizontal(
                    Button("Analyze",           id="analyze",    classes="primary"),
                    Button("Enable OC Logging", id="enable-log", classes="primary"),
                    Button("← Back",            id="back",       classes="back"),
                ),
                Static("  Enable OC Logging: patches config.plist on your USB so OpenCore writes a log file on next boot.", classes="info"),
                Static("", id="checker-summary"),
                Static(""),
                ScrollableContainer(
                    RichLog(id="checker-log", auto_scroll=False, markup=True),
                    id="checker-scroll",
                ),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self._scan_usbs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "analyze":
            path = self.query_one("#log-path", Input).value.strip()
            if path:
                self._run_analysis(path)
        elif event.button.id == "enable-log":
            self.app.push_screen(EnableOCLoggingScreen())
        elif event.button.id == "back":
            self.app.pop_screen()

    def on_input_submitted(self, event) -> None:
        path = event.value.strip()
        if path:
            self._run_analysis(path)

    @work(thread=True)
    def _scan_usbs(self) -> None:
        """Mount all USBs, find OC logs and panic files, auto-fill the most recent."""
        from compat import get_usb_drives, mount_usb
        from pathlib import Path

        self.app.call_from_thread(
            self.query_one("#checker-summary", Static).update,
            "  Scanning USB drives for logs…"
        )

        drives = get_usb_drives()
        found: list[Path] = []

        def _already_mounted(device: str) -> str | None:
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
            self.app.call_from_thread(self._set_log_path, str(found[0]))
            self.app.call_from_thread(
                self.query_one("#checker-summary", Static).update,
                f"  Found {len(found)} log(s) on USB — most recent auto-filled. Click Analyze."
            )
        else:
            self.app.call_from_thread(
                self.query_one("#checker-summary", Static).update,
                "  No logs found on USB. Paste a path manually or use Enable OC Logging first."
            )

    def _set_log_path(self, path: str) -> None:
        inp = self.query_one("#log-path", Input)
        inp.value = path

    @work(thread=True)
    def _run_analysis(self, path: str) -> None:
        from log_checker import analyze_file
        self.app.call_from_thread(self._set_summary, "  Analyzing…", "info")
        self.app.call_from_thread(self._clear)

        profile = getattr(self.app, "profile", None)
        findings = analyze_file(path, profile)

        n_crit = sum(1 for f in findings if f.severity == "critical")
        n_warn = sum(1 for f in findings if f.severity == "warning")
        n_info = sum(1 for f in findings if f.severity == "info")

        parts = []
        if n_crit: parts.append(f"[bold red]{n_crit} critical[/bold red]")
        if n_warn: parts.append(f"[bold yellow]{n_warn} warning{'s' if n_warn != 1 else ''}[/bold yellow]")
        if n_info: parts.append(f"[dim]{n_info} info[/dim]")
        summary = "  " + "  •  ".join(parts) if parts else "  No issues found"
        self.app.call_from_thread(self._set_summary, summary, "ok")

        SEV_COLOR = {"critical": "red", "warning": "yellow", "info": "#888888"}
        SEV_ICON  = {"critical": "✗", "warning": "⚠", "info": "ℹ"}

        for f in findings:
            color = SEV_COLOR.get(f.severity, "#888888")
            icon  = SEV_ICON.get(f.severity, "•")
            conf  = f" [{f.confidence}]" if f.confidence != "likely" else ""
            self.app.call_from_thread(
                self._write,
                f"[{color}]{icon}  {f.title}{conf}[/{color}]"
            )
            self.app.call_from_thread(
                self._write,
                f"[#aaaaaa]   {f.explanation}[/#aaaaaa]"
            )
            for step in f.fix_steps:
                self.app.call_from_thread(self._write, f"[#555555]   → {step}[/#555555]")
            if f.context_lines:
                self.app.call_from_thread(self._write, "[#2a2a2a]   ┄[/#2a2a2a]")
                for ctx in f.context_lines:
                    self.app.call_from_thread(self._write, f"[#2a2a2a]   {ctx}[/#2a2a2a]")
            self.app.call_from_thread(self._write, "")

    def _clear(self) -> None:
        self.query_one("#checker-log", RichLog).clear()

    def _write(self, msg: str) -> None:
        self.query_one("#checker-log", RichLog).write(msg)

    def _set_summary(self, msg: str, level: str = "info") -> None:
        self.query_one("#checker-summary", Static).update(msg)

class USBMappingScreen(Screen):

    def compose(self) -> ComposeResult:
        drives = get_usb_drives()
        self._drives = drives
        items = [ListItem(Label(f"  {n}   {s}   {l}")) for n, s, l in drives]
        if not items:
            items = [ListItem(Label("  No USB drives detected"))]
        yield Header()
        yield Container(
            Vertical(
                Static("── USB Port Mapping (Post-Install) ─────────────────────", classes="title"),
                Static(""),
                Static("  1. Boot into macOS, then run USBToolBox from your USB:", classes="info"),
                Static("     EFI/HackMate-Extras/  →  map your ports  →  Export", classes="info"),
                Static(""),
                Static("  2. Select the drive with your OpenCore EFI:", classes="info"),
                ListView(*items, id="drive-list"),
                Static(""),
                Static("  3. Path to your generated UTBMap.kext:", classes="info"),
                Input(placeholder="e.g. /Users/you/Desktop/UTBMap.kext", id="kext-path"),
                Button("Browse…",      id="browse",  classes="primary"),
                Static(""),
                Button("Apply USB Map", id="apply",   classes="primary"),
                Button("← Back",        id="back",    classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "browse":
            try:
                import tkinter as _tk
                from tkinter import filedialog as _fd
                root = _tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen = _fd.askdirectory(parent=root, title="Select UTBMap.kext folder")
                root.destroy()
                if chosen:
                    self.query_one("#kext-path", Input).value = str(chosen)
            except Exception:
                pass
        elif event.button.id == "apply":
            self._apply()
        elif event.button.id == "back":
            self.app.pop_screen()

    @work(thread=True)
    def _apply(self) -> None:
        kext_src = Path(self.query_one("#kext-path", Input).value.strip())
        idx = self.query_one("#drive-list", ListView).index
        if not kext_src.exists():
            self.app.call_from_thread(self.notify, "UTBMap.kext path not found", severity="error")
            return
        if not kext_src.name.lower().startswith("utbmap"):
            self.app.call_from_thread(self.notify, "Select the UTBMap.kext folder, not a file inside it", severity="warning")
            return
        if idx is None or not self._drives:
            self.app.call_from_thread(self.notify, "Select a drive first", severity="warning")
            return

        device = self._drives[idx][0]
        mount  = get_mount_path(device, skip_format=True)

        try:
            if not IS_WINDOWS:
                mount_usb(device, mount)
            kext_dest = Path(mount) / "EFI" / "OC" / "Kexts" / "UTBMap.kext"
            if kext_dest.exists():
                shutil.rmtree(str(kext_dest))
            shutil.copytree(str(kext_src), str(kext_dest))

            # Enable UTBMap in config.plist. USBToolBox.kext stays enabled — it is
            # the driver that consumes the map, so disabling it leaves UTBMap inert.
            config_path = Path(mount) / "EFI" / "OC" / "config.plist"
            if config_path.exists():
                try:
                    import plistlib
                    from config_gen import sync_executable_paths
                    with open(config_path, "rb") as f:
                        cfg = plistlib.load(f)
                    for entry in cfg.get("Kernel", {}).get("Add", []):
                        name = entry.get("BundlePath", "").split("/")[0]
                        if name in ("UTBMap.kext", "USBToolBox.kext"):
                            entry["Enabled"] = True
                    # A USBToolBox map is a plist-only bundle; make the config say so.
                    sync_executable_paths(cfg, Path(mount) / "EFI" / "OC" / "Kexts")
                    with open(config_path, "wb") as f:
                        plistlib.dump(cfg, f)
                except Exception:
                    pass

            if not IS_WINDOWS:
                unmount_usb(mount)
            self.app.call_from_thread(
                self.notify,
                f"UTBMap.kext applied to {device} — reboot to take effect",
                severity="information",
            )
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Failed: {e}", severity="error")

class HwdbConsentScreen(Screen):
    """Shown once, on first launch. A real no — declining changes nothing
    else about how HackMate works, it only skips log submission."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Help Improve HackMate? ───────────────────────────────", classes="title"),
                Static(""),
                Static("  HackMate can optionally send a short hardware log after", classes="info"),
                Static("  each build to github.com/riftaway7-code/hackmate-hwdb —", classes="info"),
                Static("  a public, browsable database used to improve compatibility", classes="info"),
                Static("  checks and kext selection for real hardware over time.", classes="info"),
                Static(""),
                Static("  What's sent: cpu/gpu/audio/wifi/ethernet chipset, touchpad", classes="info"),
                Static("  type, nvme/thunderbolt presence, and whether the build", classes="info"),
                Static("  succeeded. Nothing else — no name, no serial number, no", classes="info"),
                Static("  file paths, nothing that identifies you personally.", classes="info"),
                Static(""),
                Static("  This is entirely optional. Choosing No changes nothing", classes="info"),
                Static("  else — every feature works identically either way. You", classes="info"),
                Static("  can change this later from the welcome screen.", classes="info"),
                Static(""),
                Button("Yes, share build logs", id="consent-yes", classes="primary"),
                Button("No, don't share anything", id="consent-no", classes="primary"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        import hwdb_submit
        if event.button.id == "consent-yes":
            hwdb_submit.set_consent(True)
        elif event.button.id == "consent-no":
            hwdb_submit.set_consent(False)
        self.app.pop_screen()
        self.app.push_screen(WelcomeScreen())


class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        import hwdb_submit
        yield Header()
        yield Container(
            Horizontal(
                Vertical(
                    Static(BANNER,     classes="title",    id="banner"),
                    Static("Automated OpenCore EFI builder — any hardware", classes="info", id="subtitle"),
                    Static(""),
                    Button("Build EFI",              id="start",      classes="primary"),
                    Button("Build EFI (Manual)",     id="manual",     classes="primary"),
                    Button("EFI Health Check",       id="health",     classes="primary"),
                    Button("Restore EFI",            id="restore",    classes="primary"),
                    Button("Dual Boot / Disk Map",   id="diskmap",    classes="primary"),
                    Button("USB Mapping",            id="usb_map",    classes="primary"),
                    Button("Edit Config",            id="edit_cfg",   classes="primary"),
                    Button("Check Logs",             id="check_logs", classes="primary"),
                    Button(
                        "Sharing build logs: ON" if hwdb_submit.has_consented() else "Sharing build logs: OFF",
                        id="hwdb_toggle", classes="primary"
                    ),
                    Button("Quit",                   id="quit",       classes="danger"),
                    id="welcome-inner"
                ),
                Vertical(
                    Static("[#888888]loading stats…[/]", id="stats-body"),
                    id="welcome-stats"
                ),
                id="welcome-row"
            ),
            id="welcome"
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_stats()

    @work(thread=True)
    def _load_stats(self) -> None:
        data = fetch_project_stats()
        panel = format_stats_panel(data)
        self.app.call_from_thread(self.query_one("#stats-body", Static).update, panel)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.app.push_screen(ScanScreen())
        elif event.button.id == "manual":
            self.app.push_screen(ManualHardwareScreen())
        elif event.button.id == "health":
            self.app.push_screen(HealthCheckScreen())
        elif event.button.id == "restore":
            self.app.push_screen(RestoreScreen())
        elif event.button.id == "edit_cfg":
            self.app.push_screen(ConfigEditorUSBScreen())
        elif event.button.id == "usb_map":
            self.app.push_screen(USBMappingScreen())
        elif event.button.id == "diskmap":
            self.app.push_screen(DiskMapScreen())
        elif event.button.id == "check_logs":
            self.app.push_screen(LogCheckerScreen())
        elif event.button.id == "hwdb_toggle":
            import hwdb_submit
            hwdb_submit.set_consent(not hwdb_submit.has_consented())
            self.app.pop_screen()
            self.app.push_screen(WelcomeScreen())
        elif event.button.id == "quit":
            self.app.exit()

class HealthCheckScreen(Screen):
    """Audit any OpenCore EFI — a mounted partition, a USB, or a folder path."""

    LEVEL_STYLE = {
        "critical": ("red",      "✗"),
        "warn":     ("yellow",   "⚠"),
        "info":     ("#5599ff",  "ℹ"),
        "ok":       ("green",    "✓"),
    }

    def compose(self) -> ComposeResult:
        from efi_doctor import find_efi_candidates
        self._mounted = find_efi_candidates()
        self._drives  = get_usb_drives()

        items = [ListItem(Label(f"  {p}"), id=f"efi-{i}")
                 for i, p in enumerate(self._mounted)]
        items += [ListItem(Label(f"  USB: {n}   {s}   {l}"), id=f"usb-{i}")
                  for i, (n, s, l) in enumerate(self._drives)]
        if not items:
            items = [ListItem(Label("  Nothing detected — type a path below"))]

        yield Header()
        yield Container(
            Vertical(
                Static("── EFI Health Check ─────────────────────────────────────", classes="title"),
                Static("  Inspects an OpenCore EFI for problems that still let it boot:", classes="info"),
                Static("  orphaned ACPI renames, kexts that never inject, unmapped USB, SIP state.", classes="info"),
                Static(""),
                ListView(*items, id="health-targets"),
                Static("  Or enter a path to an EFI folder:", classes="info"),
                Input(placeholder="/Volumes/EFI/EFI", id="health-path"),
                Horizontal(
                    Button("Run Health Check", id="run",  classes="primary"),
                    Button("← Back",           id="back", classes="back"),
                ),
                Static("", id="health-summary"),
                RichLog(id="health-log", markup=True, auto_scroll=False),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self._run_check()
        elif event.button.id == "back":
            self.app.pop_screen()

    def _selected_target(self):
        """(path, usb_device) — usb_device is set when the EFI must be mounted first."""
        typed = self.query_one("#health-path", Input).value.strip()
        if typed:
            return Path(typed), None

        index = self.query_one("#health-targets", ListView).index
        if index is None:
            return None, None
        if index < len(self._mounted):
            return self._mounted[index], None
        usb_index = index - len(self._mounted)
        if usb_index < len(self._drives):
            return None, self._drives[usb_index][0]
        return None, None

    @work(thread=True)
    def _run_check(self) -> None:
        from efi_health import audit, summarise

        log     = self.query_one("#health-log", RichLog)
        summary = self.query_one("#health-summary", Static)
        self.app.call_from_thread(log.clear)

        path, usb = self._selected_target()
        if path is None and usb is None:
            self.app.call_from_thread(summary.update, "  [yellow]Pick a target or enter a path.[/yellow]")
            return

        mounted_here = False
        try:
            if usb:
                mount = get_mount_path(usb, skip_format=True)
                if not IS_WINDOWS:
                    mount_usb(usb, mount)
                mounted_here = True
                path = Path(mount) / "EFI"

            if not path.is_dir():
                self.app.call_from_thread(summary.update, f"  [red]Not found: {path}[/red]")
                return

            findings = audit(path)
            counts   = summarise(findings)

            self.app.call_from_thread(log.write, f"[#666666]{path}[/#666666]\n")
            for level in ("critical", "warn", "info", "ok"):
                for lvl, title, detail in findings:
                    if lvl != level:
                        continue
                    color, symbol = self.LEVEL_STYLE[lvl]
                    self.app.call_from_thread(log.write, f"[{color}]{symbol} {title}[/{color}]")
                    if detail:
                        self.app.call_from_thread(log.write, f"[#666666]   {detail}[/#666666]")

            if counts["critical"]:
                text = (f"  [red]{counts['critical']} critical[/red] · "
                        f"[yellow]{counts['warn']} warning(s)[/yellow] · "
                        f"[#666666]{counts['info']} note(s)[/#666666] — this EFI will not boot correctly")
            elif counts["warn"]:
                text = (f"  [yellow]{counts['warn']} warning(s)[/yellow] · "
                        f"[#666666]{counts['info']} note(s)[/#666666] · "
                        f"[green]{counts['ok']} passed[/green]")
            else:
                text = f"  [green]No problems found[/green] — {counts['ok']} checks passed"
            self.app.call_from_thread(summary.update, text)

            profile = getattr(self.app, "profile", None)
            if profile is not None:
                try:
                    import hwdb_submit
                    worked = "build failed" if counts["critical"] else (
                        "partial" if counts["warn"] else "build completed")
                    issues = "; ".join(
                        title for lvl, title, _ in findings if lvl in ("critical", "warn")
                    ) or "none"
                    log_text = hwdb_submit.build_log(
                        profile, "efi_health_check", "n/a (existing EFI audit)",
                        worked=worked, issues=issues,
                    )
                    hwdb_submit.submit_log(profile, "efi_health_check", log_text)
                except Exception:
                    pass

        except Exception as e:
            self.app.call_from_thread(summary.update, f"  [red]Health check failed: {e}[/red]")
        finally:
            if mounted_here and not IS_WINDOWS:
                try:
                    unmount_usb(get_mount_path(usb, skip_format=True))
                except Exception:
                    pass


class RestoreScreen(Screen):
    def compose(self) -> ComposeResult:
        backup_dir = Path.home() / "HackMate" / "backups"
        self.backups = sorted(backup_dir.glob("EFI_backup_*.zip"), reverse=True) if backup_dir.exists() else []
        self.usb_drives = get_usb_drives()

        backup_items = [
            ListItem(Label(f"  {b.stem}  ({b.stat().st_size // 1024}KB)"))
            for b in self.backups
        ] or [ListItem(Label("  No backups found"))]

        usb_items = [
            ListItem(Label(f"  {name}   {size}   {label}"))
            for name, size, label in self.usb_drives
        ] or [ListItem(Label("  No USB drives detected"))]

        yield Header()
        yield Container(
            Vertical(
                Static("── Restore EFI from Backup ──────────────────────────────", classes="title"),
                Static(""),
                Static("  Select backup:", classes="info"),
                ListView(*backup_items, id="backup-list"),
                Static(""),
                Static("  Restore to USB:", classes="info"),
                ListView(*usb_items, id="usb-list"),
                Static(""),
                Button("Restore",  id="restore", classes="primary"),
                Button("← Back",   id="back",    classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "restore":
            if not self.backups or not self.usb_drives:
                return
            b_idx = self.query_one("#backup-list", ListView).index or 0
            u_idx = self.query_one("#usb-list",    ListView).index or 0
            backup = self.backups[b_idx]
            device = self.usb_drives[u_idx][0]
            self.app.push_screen(RestoreConfirmScreen(backup, device))
        elif event.button.id == "back":
            self.app.pop_screen()

class RestoreConfirmScreen(Screen):
    def __init__(self, backup: Path, device: str):
        super().__init__()
        self.backup = backup
        self.device = device

    def compose(self) -> ComposeResult:
        self.confirm_phrase = f"RESTORE {self.device}"
        yield Header()
        yield Container(
            Vertical(
                Static("── Confirm Restore ───────────────────────────────────────", classes="title"),
                Static(""),
                Static(f"  Backup:  {self.backup.stem}", classes="info"),
                Static(f"  Target:  {self.device}", classes="info"),
                Static(""),
                Static("  ⚠  This will overwrite the EFI partition on the target USB.", classes="warn"),
                Static(f"  To continue, type:  {self.confirm_phrase}", classes="info"),
                Static(""),
                Input(placeholder=self.confirm_phrase, id="confirm-input"),
                Static(""),
                Button("Restore",   id="confirm", classes="primary"),
                Button("← Cancel",  id="cancel",  classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            typed = self.query_one("#confirm-input", Input).value.strip()
            if typed != self.confirm_phrase:
                self.query_one("#confirm-input", Input).placeholder = f"Type exactly: {self.confirm_phrase}"
                return
            self._do_restore()
        elif event.button.id == "cancel":
            self.app.pop_screen()

    @work(thread=True)
    def _do_restore(self) -> None:
        import zipfile as zf
        mount = get_mount_path(self.device)

        def notify(msg, level="info"):
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
        # (gen, codename, vendor, oc_platform)
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

    def __init__(self):
        super().__init__()
        self._cpu_idx = 6   # default: Intel 7th gen
        self._gpu_idx = 0
        self._eth_idx = 0
        self._wifi_idx = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Manual Hardware Setup ──────────────────────────────────", classes="title"),
                Static("  Building a USB for a different machine? Set its hardware here.", classes="info"),
                Static(""),
                ScrollableContainer(
                    Vertical(
                        Static("  ── CPU — Intel Desktop ───────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._cpu_idx else "  ") + label, id=f"cpu-{key}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.CPU_OPTIONS) if key.startswith("intel-") and not key.endswith("m") and not any(key.endswith(s) for s in ("kr","wl","cl","cm","il","tl"))],
                        Static("  ── CPU — Intel Laptop ────────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._cpu_idx else "  ") + label, id=f"cpu-{key}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.CPU_OPTIONS) if key.startswith("intel-") and (key.endswith("m") or any(key.endswith(s) for s in ("kr","wl","cl","cm","il","tl")))],
                        Static("  ── CPU — AMD Desktop ─────────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._cpu_idx else "  ") + label, id=f"cpu-{key}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.CPU_OPTIONS) if key.startswith("amd-") and key.endswith("d")],
                        Static("  ── CPU — AMD Threadripper ────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._cpu_idx else "  ") + label, id=f"cpu-{key}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.CPU_OPTIONS) if key.startswith("amd-tr")],
                        Static("  ── CPU — AMD Laptop / APU ────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._cpu_idx else "  ") + label, id=f"cpu-{key}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.CPU_OPTIONS) if key.startswith("amd-") and key.endswith("m")],

                        Static("  ── Platform ──────────────────────────────────", classes="cfg-section"),
                        Horizontal(
                            Static("  Type:", classes="cfg-label"),
                            Switch(value=True, id="sw-laptop"),
                            Static("  laptop", id="platform-label", classes="info"),
                            classes="cfg-row",
                        ),

                        Static("  ── CPU Cores ─────────────────────────────────", classes="cfg-section"),
                        Horizontal(Static("  Core count:", classes="cfg-label"), Input(value="4", placeholder="4", id="in-cores", classes="short-input"), classes="cfg-row"),

                        Static("  ── GPU ───────────────────────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._gpu_idx else "  ") + label, id=f"gpu-{key if key else 'auto'}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.GPU_OPTIONS)],

                        Static("  ── Audio Codec ───────────────────────────────", classes="cfg-section"),
                        Static("  e.g. ALC256, ALC269, ALC1220", classes="info"),
                        Horizontal(Static("  Codec:", classes="cfg-label"), Input(value="", placeholder="ALC256", id="in-audio", classes="short-input"), classes="cfg-row"),

                        Static("  ── Ethernet ──────────────────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._eth_idx else "  ") + label, id=f"eth-{key if key else 'none'}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.ETHERNET_OPTIONS)],

                        Static("  ── WiFi ──────────────────────────────────────", classes="cfg-section"),
                        *[Horizontal(
                            Button(("▶ " if i == self._wifi_idx else "  ") + label, id=f"wifi-{key if key else 'none'}", classes="advanced-btn"),
                            classes="manual-row",
                        ) for i, (key, label) in enumerate(self.WIFI_OPTIONS)],

                        Static("  ── Other ─────────────────────────────────────", classes="cfg-section"),
                        Horizontal(Static("  NVMe drive:", classes="cfg-label"), Switch(value=True, id="sw-nvme"), classes="cfg-row"),
                        Horizontal(Static("  Thunderbolt:", classes="cfg-label"), Switch(value=False, id="sw-tb"), classes="cfg-row"),

                        id="manual-inner"
                    ),
                    id="manual-scroll"
                ),
                Static(""),
                Horizontal(
                    Button("Continue →", id="next", classes="primary"),
                    Button("← Back",     id="back", classes="back"),
                ),
                Static("", id="manual-status"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def _select(self, group: str, key: str, options: list) -> None:
        for k, _ in options:
            btn_id = f"{group}-{k if k else ('auto' if group == 'gpu' else 'none')}"
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                label = btn.label.plain.lstrip("▶ ").strip()
                btn.label = ("▶ " if k == key else "  ") + label
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        if bid.startswith("cpu-"):
            key = bid[4:]
            self._cpu_idx = next((i for i, (k, _) in enumerate(self.CPU_OPTIONS) if k == key), 0)
            self._select("cpu", key, self.CPU_OPTIONS)

        elif bid.startswith("gpu-"):
            key = bid[4:]
            if key == "auto": key = ""
            self._gpu_idx = next((i for i, (k, _) in enumerate(self.GPU_OPTIONS) if k == key), 0)
            self._select("gpu", key, self.GPU_OPTIONS)

        elif bid.startswith("eth-"):
            key = bid[4:]
            if key == "none": key = ""
            self._eth_idx = next((i for i, (k, _) in enumerate(self.ETHERNET_OPTIONS) if k == key), 0)
            self._select("eth", key, self.ETHERNET_OPTIONS)

        elif bid.startswith("wifi-"):
            key = bid[5:]
            if key == "none": key = ""
            self._wifi_idx = next((i for i, (k, _) in enumerate(self.WIFI_OPTIONS) if k == key), 0)
            self._select("wifi", key, self.WIFI_OPTIONS)

        elif bid == "next":
            self._build_profile()

        elif bid == "back":
            self.app.pop_screen()

    def on_switch_changed(self, event) -> None:
        if event.switch.id == "sw-laptop":
            self.query_one("#platform-label", Static).update(
                "  laptop" if event.value else "  desktop"
            )

    def _build_profile(self) -> None:
        from hardware import HardwareProfile, SMBIOS_MAP

        cpu_key = self.CPU_OPTIONS[self._cpu_idx][0]
        gen, codename, vendor, oc_platform = self._CPU_META[cpu_key]

        gpu_key = self.GPU_OPTIONS[self._gpu_idx][0]
        gpu_vendor = "intel"
        if gpu_key == "amd":    gpu_vendor = "amd"
        elif gpu_key == "nvidia": gpu_vendor = "nvidia"

        eth_key  = self.ETHERNET_OPTIONS[self._eth_idx][0]
        wifi_key = self.WIFI_OPTIONS[self._wifi_idx][0]
        is_laptop = self.query_one("#sw-laptop", Switch).value
        platform  = "laptop" if is_laptop else "desktop"
        audio     = self.query_one("#in-audio", Input).value.strip().upper() or ""

        try:
            cores = int(self.query_one("#in-cores", Input).value.strip())
        except ValueError:
            cores = 4

        profile = HardwareProfile(
            cpu_name        = f"{vendor.title()} {codename}",
            cpu_vendor      = vendor,
            cpu_generation  = gen,
            cpu_codename    = codename,
            oc_platform     = oc_platform,
            core_count      = cores,
            gpu_vendor      = gpu_vendor,
            gpu_name        = self.GPU_OPTIONS[self._gpu_idx][1],
            gpu_device_id   = gpu_key if gpu_key not in ("amd", "nvidia", "") else "",
            audio_codec     = audio,
            ethernet_chipset= eth_key,
            wifi_chipset    = wifi_key,
            platform        = platform,
            nvme_present    = self.query_one("#sw-nvme", Switch).value,
            has_thunderbolt = self.query_one("#sw-tb",   Switch).value,
            has_touchpad    = is_laptop,
        )

        # derive SMBIOS
        try:
            profile.smbios_model = SMBIOS_MAP.get((gen, platform), "")
        except Exception:
            pass

        self.app.profile = profile
        self.app.push_screen(VersionScreen())

class ScanScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Scanning Hardware ──────────────────────────────────", classes="title"),
                Static("", id="scan-status"),
                Static("", id="scan-result"),
                Button("← Back", id="back", classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self.run_scan()

    @work(thread=True)
    def run_scan(self) -> None:
        self.app.call_from_thread(
            self.query_one("#scan-status", Static).update,
            "  Detecting CPU, GPU, audio, network..."
        )
        profile = scan()
        self.app.call_from_thread(self._show_results, profile)

    def _show_results(self, profile: HardwareProfile) -> None:
        kexts = select_kexts(profile, wifi_kext_mode=self.app.wifi_kext_mode)
        layout = get_alc_layout(profile.audio_codec)
        gen_suffix = f"  (Gen {profile.cpu_generation})" if profile.cpu_vendor != "amd" else ""
        lines = [
            f"  CPU       {profile.cpu_name}",
            f"  Codename  {profile.cpu_codename}{gen_suffix}",
            f"  Platform  {profile.platform}  —  {profile.oc_platform}",
            f"  GPU       {profile.gpu_name} [{profile.gpu_vendor}]",
            f"  Audio     {profile.audio_name}  /  codec: {profile.audio_codec}  →  layout-id {layout}",
            f"  Ethernet  {profile.ethernet_name or 'None'}",
            f"  WiFi      {profile.wifi_name or 'None'}",
            f"  SMBIOS    {profile.smbios_model}",
            f"  Kexts     {len(kexts)} selected",
            f"  NVMe      {'Yes' if profile.nvme_present else 'No'}   Thunderbolt: {'Yes' if profile.has_thunderbolt else 'No'}",
        ]
        self.query_one("#scan-status", Static).update("")
        self.query_one("#scan-result", Static).update("\n".join(lines))
        self.app.profile = profile
        # Replace Back button with Continue
        self.query_one("#back", Button).remove()
        self.mount(
            Vertical(
                Static(""),
                Button("Continue → Select macOS", id="next",  classes="primary"),
                Button("← Back",                  id="back2", classes="back"),
            ),
            after=self.query_one("#scan-result")
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next":
            self.app.push_screen(VersionScreen())
        elif event.button.id in ("back", "back2"):
            self.app.pop_screen()

class VersionScreen(Screen):
    def compose(self) -> ComposeResult:
        profile: HardwareProfile = self.app.profile
        versions = compatible_versions(profile.cpu_generation, profile.gpu_vendor, profile.cpu_vendor)
        self.versions = versions

        items = []
        for v in versions:
            note = f"  ({v.notes})" if v.notes else ""
            items.append(ListItem(Label(f"  {v.name}{note}")))

        yield Header()
        yield Container(
            Vertical(
                Static("── Select macOS Version ────────────────────────────────", classes="title"),
                Static(f"  {len(versions)} versions compatible with your hardware", classes="info"),
                Static(""),
                ListView(*items, id="version-list"),
                Static(""),
                Button("Continue → Select USB", id="next",  classes="primary"),
                Button("← Back",               id="back",  classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next":
            lv = self.query_one("#version-list", ListView)
            idx = lv.index
            if idx is not None and self.versions:
                self.app.macos_version = self.versions[idx]
                self.app.push_screen(USBScreen())
        elif event.button.id == "back":
            self.app.pop_screen()

class USBScreen(Screen):
    def compose(self) -> ComposeResult:
        drives = get_usb_drives()
        self.drives = drives
        version: MacOSVersion = self.app.macos_version

        items = [ListItem(Label(f"  {name}   {size}   {label}")) for name, size, label in drives]
        if not items:
            items = [ListItem(Label("  No USB drives detected — plug one in and re-open this screen"))]

        yield Header()
        yield Container(
            Vertical(
                Static("── Select Target USB Drive ─────────────────────────────", classes="title"),
                Static(f"  Installing: {version.name}", classes="info"),
                Static("  WARNING: The selected drive will be completely erased", classes="warn"),
                Static(""),
                ListView(*items, id="usb-list"),
                Static(""),
                Button("Build & Install EFI", id="install", classes="primary"),
                Button("Don't have USB",      id="no-usb",  classes="primary"),
                Button("← Back",              id="back",    classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "install":
            lv = self.query_one("#usb-list", ListView)
            idx = lv.index
            if idx is not None and self.drives:
                selected = self.drives[idx][0]
                self.app.push_screen(BuildModeScreen(selected))
        elif event.button.id == "no-usb":
            self.app.push_screen(NoUSBPathScreen())
        elif event.button.id == "back":
            self.app.pop_screen()

def _expand_user_path(path: str) -> str:
    """Expand a leading ~ against the real user's home, even under sudo
    (plain os.path.expanduser would resolve to root's home instead)."""
    if not path.startswith("~"):
        return path
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        import pwd
        home = pwd.getpwnam(sudo_user).pw_dir
        return home + path[1:] if path == "~" or path.startswith("~/") else os.path.expanduser(path)
    return os.path.expanduser(path)


class NoUSBPathScreen(Screen):
    """Let the user pick a folder to save the EFI into instead of a USB."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Generate EFI Folder (No USB) ────────────────────────", classes="title"),
                Static(""),
                Static("  HackMate will generate the EFI folder (OpenCore, kexts,", classes="info"),
                Static("  SSDTs, config.plist) and save it to the folder you choose.", classes="info"),
                Static("  No macOS recovery is downloaded — copy the EFI folder to", classes="info"),
                Static("  your drive's EFI partition when you're ready.", classes="info"),
                Static(""),
                Static("  Folder path:", classes="info"),
                Input(placeholder="e.g. C:\\Users\\You\\Desktop  or  /home/user/Desktop", id="path-input"),
                Static(""),
                Button("Browse…",   id="browse",   classes="primary"),
                Button("Continue →", id="continue", classes="primary"),
                Button("← Back",    id="back",     classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def _next(self, path: str) -> None:
        self.app.efi_output_path = _expand_user_path(path)
        profile: HardwareProfile = self.app.profile
        has_dgpu = getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel"
        if getattr(profile, "wifi_chipset", ""):
            self.app.push_screen(WiFiKextScreen("local", repair=False, skip_format=True))
        elif has_dgpu:
            self.app.push_screen(DGPUScreen("local", repair=False, skip_format=True))
        else:
            self.app.push_screen(DualBootScreen("local", repair=False, skip_format=True))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "browse":
            try:
                import tkinter as _tk
                from tkinter import filedialog as _fd
                root = _tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                chosen = _fd.askdirectory(parent=root, title="Choose folder to save EFI")
                root.destroy()
                if chosen:
                    self.query_one("#path-input", Input).value = str(chosen)
            except Exception:
                pass
        elif event.button.id == "continue":
            path = self.query_one("#path-input", Input).value.strip()
            if path:
                self._next(path)
        elif event.button.id == "back":
            self.app.pop_screen()

class WiFiKextScreen(Screen):
    """WiFi/Bluetooth kext selection."""
    def __init__(self, device: str, repair: bool, skip_format: bool):
        super().__init__()
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def compose(self) -> ComposeResult:
        profile: HardwareProfile = self.app.profile
        is_intel = getattr(profile, "wifi_chipset", "") == "intel"
        yield Header()
        rows = [
            Static("── WiFi / Bluetooth ─────────────────────────────────────", classes="title"),
            Static(""),
        ]
        if is_intel:
            rows += [
                Static("  Standard (itlwm + HeliPort)", classes="info"),
                Static("    Works with ALL macOS versions including Tahoe.", classes="info"),
                Static("    Use HeliPort (saved to EFI/HackMate-Extras/) to connect.", classes="info"),
                Static("    Note: during the Tahoe installer, use ethernet — itlwm", classes="info"),
                Static("    needs HeliPort which cannot run in the recovery env.", classes="info"),
                Static(""),
                Static("  Native AirportBSD (AirportItlwm)", classes="info"),
                Static("    Shows as built-in WiFi — no HeliPort needed.", classes="info"),
                Static("    No Tahoe build yet — use for Sonoma or earlier only.", classes="info"),
                Static(""),
                Static("  None", classes="info"),
                Static("    Don't inject any WiFi/BT kexts — use this if you have a", classes="info"),
                Static("    separate WiFi/BT card or dongle and want the onboard", classes="info"),
                Static("    radio left completely alone.", classes="info"),
                Static(""),
                Button("Standard (itlwm + HeliPort)", id="itlwm",        classes="primary"),
                Button("Native (AirportItlwm)",        id="airportitlwm", classes="primary"),
                Button("None (disable onboard WiFi/BT)", id="none",      classes="primary"),
            ]
        else:
            rows += [
                Static("  Keep onboard WiFi/BT", classes="info"),
                Static("    Injects the kexts your detected chipset needs.", classes="info"),
                Static(""),
                Static("  None", classes="info"),
                Static("    Don't inject any WiFi/BT kexts — use this if you have a", classes="info"),
                Static("    separate WiFi/BT card or dongle and want the onboard", classes="info"),
                Static("    radio left completely alone.", classes="info"),
                Static(""),
                Button("Keep onboard WiFi/BT",           id="auto",      classes="primary"),
                Button("None (disable onboard WiFi/BT)", id="none",      classes="primary"),
            ]
        rows.append(Button("← Back", id="back", classes="back"))
        yield Container(Vertical(*rows, classes="screen-inner"))
        yield Footer()

    def _next(self) -> None:
        profile: HardwareProfile = self.app.profile
        if getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel":
            self.app.push_screen(DGPUScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        else:
            self.app.push_screen(DualBootScreen(self.device, repair=self.repair, skip_format=self.skip_format))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "itlwm":
            self.app.wifi_kext_mode = "itlwm"
            self._next()
        elif event.button.id == "airportitlwm":
            self.app.wifi_kext_mode = "AirportItlwm"
            self._next()
        elif event.button.id == "auto":
            self.app.wifi_kext_mode = "itlwm"  # unused for non-Intel chipsets, kept as the default
            self._next()
        elif event.button.id == "none":
            self.app.wifi_kext_mode = "none"
            self._next()
        elif event.button.id == "back":
            self.app.pop_screen()

class BuildModeScreen(Screen):
    def __init__(self, device: str):
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Build Mode ───────────────────────────────────────────", classes="title"),
                Static(f"  Device: {self.device}", classes="info"),
                Static(""),
                Static("  Full Build        — formats USB, downloads recovery (~600 MB), installs everything fresh", classes="info"),
                Static("  Already Formatted — USB is already FAT32, skips format, downloads recovery + installs", classes="info"),
                Static("  Repair EFI        — keeps recovery on USB, updates OpenCore + kexts + SSDTs + config.plist", classes="info"),
                Static(""),
                Button("Full Build",        id="full",        classes="primary"),
                Button("Already Formatted", id="skip_format", classes="primary"),
                Button("Repair EFI",        id="repair",      classes="primary"),
                Button("← Back",            id="back",        classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def _next_screen(self, repair: bool, skip_format: bool) -> None:
        profile: HardwareProfile = self.app.profile
        has_dgpu = getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel"
        if getattr(profile, "wifi_chipset", ""):
            self.app.push_screen(WiFiKextScreen(self.device, repair=repair, skip_format=skip_format))
        elif has_dgpu:
            self.app.push_screen(DGPUScreen(self.device, repair=repair, skip_format=skip_format))
        else:
            self.app.push_screen(DualBootScreen(self.device, repair=repair, skip_format=skip_format))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "full":
            self._next_screen(repair=False, skip_format=False)
        elif event.button.id == "skip_format":
            self._next_screen(repair=False, skip_format=True)
        elif event.button.id == "repair":
            self._next_screen(repair=True, skip_format=False)
        elif event.button.id == "back":
            self.app.pop_screen()

class DGPUScreen(Screen):
    """Ask user whether to disable discrete GPU for macOS (Optimus laptops)."""
    def __init__(self, device: str, repair: bool, skip_format: bool):
        super().__init__()
        self.device      = device
        self.repair      = repair
        self.skip_format = skip_format

    def compose(self) -> ComposeResult:
        profile: HardwareProfile = self.app.profile
        dgpu   = getattr(profile, "dgpu_name",   "Discrete GPU")
        vendor = getattr(profile, "dgpu_vendor",  "nvidia")
        yield Header()
        yield Container(
            Vertical(
                Static("── Discrete GPU Detected ───────────────────────────────", classes="title"),
                Static(""),
                Static(f"  {dgpu}", classes="info"),
                Static(""),
                Static("  macOS does not support Optimus (Intel + Nvidia/AMD switching).", classes="info"),
                Static("  The discrete GPU must be disabled, otherwise you will get:", classes="info"),
                Static("    • Black screen on boot", classes="info"),
                Static("    • Reduced battery life", classes="info"),
                Static("    • System instability", classes="info"),
                Static(""),
                Static("  Disable via DeviceProperties (recommended)?", classes="info"),
                Static("  This adds 'disable-gpu' to your config.plist for the dGPU path.", classes="info"),
                Static(""),
                Static("  Note: You can also disable it in BIOS under 'Switchable Graphics'.", classes="info"),
                Static(""),
                Button("Yes — disable in config.plist",  id="disable",  classes="primary"),
                Button("No — I'll handle it myself",     id="skip",     classes="back"),
                Button("← Back",                         id="back",     classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "disable":
            self.app.disable_dgpu = True
            self.app.push_screen(DualBootScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        elif event.button.id == "skip":
            self.app.disable_dgpu = False
            self.app.push_screen(DualBootScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        elif event.button.id == "back":
            self.app.pop_screen()

class DualBootScreen(Screen):
    """Ask if the user is dual-booting alongside Windows or Linux."""

    def __init__(self, device: str, repair: bool = False, skip_format: bool = False):
        super().__init__()
        self.device      = device
        self.repair      = repair
        self.skip_format = skip_format

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Dual Boot Setup ──────────────────────────────────────", classes="title"),
                Static(""),
                Static("  Is this machine dual-booting with another OS?", classes="info"),
                Static(""),
                Static("  Windows: OpenCore will show a Windows entry in the picker.", classes="info"),
                Static("  Linux:   Adds OpenLinuxBoot.efi so Linux EFI entries appear.", classes="info"),
                Static("  Both:    Both of the above.", classes="info"),
                Static(""),
                Static("  If unsure, choose 'No dual boot'.", classes="info"),
                Static(""),
                Button("No dual boot",           id="none",    classes="primary"),
                Button("Windows + macOS",        id="windows", classes="primary"),
                Button("Linux + macOS",          id="linux",   classes="primary"),
                Button("Windows + Linux + macOS",id="both",    classes="primary"),
                Button("Scan disks first",       id="scan",    classes="back"),
                Button("← Back",                 id="back",    classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def _proceed(self, choice: str) -> None:
        self.app.dual_boot = choice
        self.app.push_screen(ConfirmScreen(self.device, repair=self.repair, skip_format=self.skip_format))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "none":
            self._proceed("")
        elif event.button.id == "windows":
            self._proceed("windows")
        elif event.button.id == "linux":
            self._proceed("linux")
        elif event.button.id == "both":
            self._proceed("both")
        elif event.button.id == "scan":
            self.app.push_screen(DiskMapScreen(
                device=self.device, repair=self.repair, skip_format=self.skip_format
            ))
        elif event.button.id == "back":
            self.app.pop_screen()


class DiskMapScreen(Screen):
    """Show disk layout, detected OSes, and conflicts."""

    def __init__(self, device: str = "", repair: bool = False, skip_format: bool = False):
        super().__init__()
        self.device      = device
        self.repair      = repair
        self.skip_format = skip_format

    DEFAULT_CSS = """
    DiskMapScreen #disk-scroll {
        height: 1fr;
        border: solid $panel;
    }
    DiskMapScreen #disk-log {
        height: 100%;
    }
    DiskMapScreen #conflict-area {
        height: auto;
        color: $warning;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="screen-inner"):
            yield Static("── Disk Map ─────────────────────────────────────────────", classes="title")
            yield Static("  Scanning disks…", id="disk-status", classes="info")
            with ScrollableContainer(id="disk-scroll"):
                yield RichLog(id="disk-log", auto_scroll=False, markup=True)
            yield Static("", id="conflict-area")
            yield Button("Resize / Free Space →", id="resize", classes="primary")
            yield Button("← Back",               id="back",   classes="back")
        yield Footer()

    def on_mount(self) -> None:
        self._scan()

    @work(thread=True)
    def _scan(self) -> None:
        from dualboot import scan_disks, scan_all_bootloaders, check_conflicts, build_disk_tree
        disks       = scan_disks()
        bootloaders = scan_all_bootloaders(disks)
        tree        = build_disk_tree(disks, bootloaders)
        conflicts   = check_conflicts(disks, bootloaders)

        def _update():
            self.query_one("#disk-status", Static).update("  Disks found:")
            log = self.query_one("#disk-log", RichLog)
            log.write(tree)
            if conflicts:
                warn_text = "\n".join(f"  ⚠  {c}" for c in conflicts)
                self.query_one("#conflict-area", Static).update(warn_text)
        self.app.call_from_thread(_update)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "resize":
            self.app.push_screen(PartitionWizardScreen())
        elif event.button.id == "back":
            self.app.pop_screen()


class PartitionWizardScreen(Screen):
    """Pick a disk and partition to shrink."""

    DEFAULT_CSS = """
    PartitionWizardScreen #part-list { height: 1fr; border: solid $panel; }
    PartitionWizardScreen #disk-select { height: auto; margin-bottom: 1; }
    """

    def __init__(self):
        super().__init__()
        self._parts: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="screen-inner"):
            yield Static("── Resize Partition ─────────────────────────────────────", classes="title")
            yield Static("  Select a disk:", classes="info")
            yield Select([], id="disk-select")
            yield Static("  Select a partition to shrink:", classes="info")
            yield ListView(id="part-list")
            yield Static("", id="part-info", classes="info")
            yield Button("Next →", id="next", classes="primary")
            yield Button("← Back", id="back", classes="back")
        yield Footer()

    def on_mount(self) -> None:
        self._load_disks()

    @work(thread=True)
    def _load_disks(self) -> None:
        from dualboot import scan_disks
        disks = scan_disks()
        options = [(f"{d.device}  {d.model}  {d.size}", d.device) for d in disks if d.is_gpt]

        def _set():
            sel = self.query_one("#disk-select", Select)
            sel.set_options(options)
            if options:
                sel.value = options[0][1]
                self._load_partitions(options[0][1])
        self.app.call_from_thread(_set)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value and str(event.value) != Select.BLANK:
            self._load_partitions(str(event.value))

    @work(thread=True)
    def _load_partitions(self, disk: str) -> None:
        from partutil import list_partitions
        parts = [
            p for p in list_partitions(disk)
            if p.fs_type not in ("", "fat32", "fat16", "vfat")
            and p.size_bytes > 500 * 1024 * 1024
        ]
        self._parts = parts

        def _set():
            lv = self.query_one("#part-list", ListView)
            lv.clear()
            for p in parts:
                label = p.label or "?"
                lv.append(ListItem(Label(
                    f"  {p.device}  {p.size_gb:.1f} GB  {p.fs_type.upper()}  {label}"
                )))
        self.app.call_from_thread(_set)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self.query_one("#part-list", ListView).index
        if idx is not None and idx < len(self._parts):
            p = self._parts[idx]
            self.query_one("#part-info", Static).update(
                f"  {p.device}  {p.size_gb:.1f} GB  {p.fs_type.upper()}"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next":
            idx = self.query_one("#part-list", ListView).index
            if idx is None or idx >= len(self._parts):
                self.notify("Select a partition first", severity="warning")
                return
            self.app.push_screen(PartSizeScreen(self._parts[idx]))
        elif event.button.id == "back":
            self.app.pop_screen()


class PartSizeScreen(Screen):
    """Enter how much space to free."""

    def __init__(self, part):
        super().__init__()
        self._part = part

    def compose(self) -> ComposeResult:
        p = self._part
        yield Header()
        with Vertical(classes="screen-inner"):
            yield Static("── How Much Space to Free ───────────────────────────────", classes="title")
            yield Static("")
            yield Static(f"  Partition:    {p.device}", classes="info")
            yield Static(f"  Filesystem:   {p.fs_type.upper()}", classes="info")
            yield Static(f"  Current size: {p.size_gb:.1f} GB", classes="info")
            yield Static("")
            yield Static("  How much space do you want to FREE for macOS?", classes="info")
            yield Static("  macOS needs at least 40 GB. Example: 60 GB", classes="info")
            yield Static("")
            yield Input(placeholder="e.g. 60 GB", id="free-input")
            yield Static("", id="size-preview", classes="info")
            yield Static("")
            yield Button("Next →", id="next", classes="primary")
            yield Button("← Back", id="back", classes="back")
        yield Footer()

    def on_input_changed(self, event: Input.Changed) -> None:
        from partutil import parse_size_input
        val = parse_size_input(event.value)
        p = self._part
        if val is None:
            self.query_one("#size-preview", Static).update("")
            return
        new_size = p.size_bytes - val
        new_gb   = new_size / (1024 ** 3)
        freed_gb = val / (1024 ** 3)
        if new_size < 5 * 1024 ** 3:
            self.query_one("#size-preview", Static).update(
                f"  ⚠  Remaining size would be {new_gb:.1f} GB — dangerously small"
            )
        else:
            self.query_one("#size-preview", Static).update(
                f"  {p.device} → {new_gb:.1f} GB   ({freed_gb:.1f} GB freed for macOS)"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next":
            from partutil import parse_size_input
            free_bytes = parse_size_input(self.query_one("#free-input", Input).value)
            if not free_bytes:
                self.notify("Enter a valid size (e.g. 60 GB)", severity="warning")
                return
            new_size = self._part.size_bytes - free_bytes
            if new_size < 5 * 1024 ** 3:
                self.notify("Remaining size too small — need at least 5 GB", severity="error")
                return
            if free_bytes >= self._part.size_bytes:
                self.notify("Cannot free more than the full partition size", severity="error")
                return
            self.app.push_screen(PartResizeConfirmScreen(self._part, new_size))
        elif event.button.id == "back":
            self.app.pop_screen()


class PartResizeConfirmScreen(Screen):
    """Stern warning + typed confirmation before resizing."""

    def __init__(self, part, new_size_bytes: int):
        super().__init__()
        self._part           = part
        self._new_size       = new_size_bytes
        self._confirm_phrase = f"SHRINK {part.device}"

    def compose(self) -> ComposeResult:
        p        = self._part
        old_gb   = p.size_gb
        new_gb   = self._new_size / (1024 ** 3)
        freed_gb = old_gb - new_gb
        yield Header()
        with Vertical(classes="screen-inner"):
            yield Static("── Confirm Resize ───────────────────────────────────────", classes="title")
            yield Static("")
            yield Static(f"  Partition:    {p.device}  ({p.fs_type.upper()})", classes="info")
            yield Static(f"  Current size: {old_gb:.1f} GB", classes="info")
            yield Static(f"  New size:     {new_gb:.1f} GB", classes="info")
            yield Static(f"  Space freed:  {freed_gb:.1f} GB  (unallocated — macOS installer will use it)", classes="info")
            yield Static("")
            yield Static("  ⚠  BACK UP YOUR DATA BEFORE CONTINUING.", classes="warn")
            yield Static("  ⚠  Power loss during resize may corrupt the partition.", classes="warn")
            yield Static("  ⚠  This cannot be undone automatically.", classes="warn")
            yield Static("")
            yield Static(f"  To continue, type:  {self._confirm_phrase}", classes="info")
            yield Static("")
            yield Input(placeholder=self._confirm_phrase, id="confirm-input")
            yield Static("")
            yield Button("Resize", id="confirm", classes="danger")
            yield Button("← Cancel", id="cancel", classes="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            typed = self.query_one("#confirm-input", Input).value.strip()
            if typed != self._confirm_phrase:
                self.query_one("#confirm-input", Input).placeholder = f"Type exactly: {self._confirm_phrase}"
                return
            self.app.push_screen(PartResizeRunScreen(self._part, self._new_size))
        elif event.button.id == "cancel":
            self.app.pop_screen()


class PartResizeRunScreen(Screen):
    """Execute the partition resize and stream progress."""

    DEFAULT_CSS = """
    PartResizeRunScreen #resize-log { height: 1fr; border: solid $panel; }
    """

    def __init__(self, part, new_size_bytes: int):
        super().__init__()
        self._part     = part
        self._new_size = new_size_bytes
        self._done     = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="screen-inner"):
            yield Static(f"── Resizing {self._part.device} ──────────────────────────────", classes="title")
            yield Static("", id="resize-status", classes="info")
            with ScrollableContainer():
                yield RichLog(id="resize-log", auto_scroll=True, markup=True)
            yield Button("← Back", id="back", classes="back")
        yield Footer()

    def on_mount(self) -> None:
        self._run()

    @work(thread=True)
    def _run(self) -> None:
        from partutil import resize_partition

        def log(msg: str):
            self.app.call_from_thread(
                lambda m=msg: self.query_one("#resize-log", RichLog).write(m)
            )

        self.app.call_from_thread(
            lambda: self.query_one("#resize-status", Static).update("  Resizing — do not interrupt…")
        )

        result = resize_partition(self._part, self._new_size, log_cb=log)
        self._done = True
        freed_gb = self._part.size_gb - self._new_size / (1024 ** 3)

        if result == "OK":
            self.app.call_from_thread(lambda: self.query_one("#resize-status", Static).update(
                f"  ✓  Done — {freed_gb:.1f} GB freed. Unallocated space is ready for macOS."
            ))
            self.app.call_from_thread(lambda: self.app.notify("Resize complete", severity="information"))
        else:
            self.app.call_from_thread(lambda: self.query_one("#resize-status", Static).update(
                f"  ✗  {result}"
            ))
            self.app.call_from_thread(lambda: self.app.notify("Resize failed", severity="error"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            if not self._done:
                self.notify("Resize in progress — please wait", severity="warning")
                return
            self.app.pop_screen()


class ConfirmScreen(Screen):
    def __init__(self, device: str, repair: bool = False, skip_format: bool = False):
        super().__init__()
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def compose(self) -> ComposeResult:
        import subprocess, re
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
            warn = "This will update OpenCore, kexts, and config on the existing USB."
        elif self.skip_format:
            action = "WRITE TO (no format)"
            warn = "USB must already be FAT32 formatted. No data will be erased."
        else:
            action = "FORMAT AND WRITE TO"
            warn = "ALL DATA ON THIS DRIVE WILL BE PERMANENTLY ERASED."

        yield Header()
        yield Container(
            Vertical(
                Static("── Confirm ───────────────────────────────────────────────", classes="title"),
                Static(""),
                Static(f"  Target device:  {self.device}", classes="info"),
                Static(f"  Disk model:     {model}", classes="info"),
                Static(f"  Disk size:      {size}", classes="info"),
                Static(""),
                Static(f"  Action: {action} {self.device}", classes="info"),
                Static(f"  ⚠  {warn}", classes="warn"),
                *(
                    [Static(f"  Dual boot: {self.app.dual_boot}", classes="info")]
                    if getattr(self.app, "dual_boot", "")
                    else []
                ),
                Static(""),
                Static(f"  To continue, type:  {self.confirm_phrase}", classes="info"),
                Static(""),
                Input(placeholder=self.confirm_phrase, id="confirm-input"),
                Static(""),
                Button("Proceed",   id="confirm", classes="primary"),
                Button("← Cancel",  id="cancel",  classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            typed = self.query_one("#confirm-input", Input).value.strip()
            if typed != self.confirm_phrase:
                self.query_one("#confirm-input", Input).placeholder = f"Type exactly: {self.confirm_phrase}"
                return
            self.app.push_screen(InstallScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        elif event.button.id == "cancel":
            self.app.pop_screen()

class InstallScreen(Screen):
    def __init__(self, device: str, repair: bool = False, skip_format: bool = False):
        super().__init__()
        self.device = device
        self.repair = repair
        self.skip_format = skip_format

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(classes="screen-inner"):
            with Vertical():
                yield Static(f"── {'Repairing' if self.repair else 'Building'} EFI → {self.device} ──────────────────────", classes="title")
                yield Static("", id="status")
                yield ProgressBar(id="progress", total=100)
                yield LoadingIndicator(id="spinner")
                with Vertical(id="log-area"):
                    with Horizontal(id="log-row"):
                        yield RichLog(id="log",     auto_scroll=True, markup=True)
                        yield RichLog(id="cmd-log", auto_scroll=True, markup=True)
                    with Horizontal(id="log-bar"):
                        yield Static("", id="log-bar-space")
                        yield Button("Advanced ▶", id="advanced", classes="advanced-btn")
                yield Button("← Back", id="back", classes="back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#spinner", LoadingIndicator).display = False
        self.run_install()

    def _log(self, msg: str, level: str = "info") -> None:
        try:
            colors = {"ok": "green", "warn": "yellow", "error": "red", "info": "#888888", "header": "cyan"}
            color = colors.get(level, "#888888")
            self.query_one("#log", RichLog).write(f"[{color}]{msg}[/{color}]")
        except Exception:
            pass

    def _cmd_log(self, cmd: list) -> None:
        try:
            cmd_str = " ".join(shlex.quote(str(c)) for c in cmd)
            prompt = "hackmate@admin" if IS_WINDOWS else "hackmate@root"
            sym = ">" if IS_WINDOWS else "$"
            self.query_one("#cmd-log", RichLog).write(
                f"[dim]{prompt}[/dim][#00ff88]{sym}[/#00ff88] [white]{cmd_str}[/white]"
            )
        except Exception:
            pass

    def _cmd_out(self, line: str, is_err: bool = False) -> None:
        try:
            color = "#ff6666" if is_err else "#444466"
            self.query_one("#cmd-log", RichLog).write(f"[{color}]  {line}[/{color}]")
        except Exception:
            pass

    def _toggle_advanced(self) -> None:
        try:
            panel = self.query_one("#cmd-log", RichLog)
            btn   = self.query_one("#advanced", Button)
            panel.display = not panel.display
            btn.label = "Advanced ✕" if panel.display else "Advanced ▶"
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "advanced":
            self._toggle_advanced()
        elif event.button.id == "back":
            self.app.pop_screen()

    def _show_spinner(self, visible: bool) -> None:
        try:
            self.query_one("#spinner", LoadingIndicator).display = visible
        except Exception:
            pass

    def _status(self, pct: int, msg: str) -> None:
        try:
            self.query_one("#status", Static).update(f"  {msg}")
            self.query_one("#progress", ProgressBar).progress = pct
            self._show_spinner(0 < pct < 100)
        except Exception:
            pass

    @work(thread=True)
    def run_install(self) -> None:
        from recovery import _ensure_cert_bundle_env
        _ensure_cert_bundle_env()

        profile: HardwareProfile    = self.app.profile
        version: MacOSVersion       = self.app.macos_version
        device: str                 = self.device
        repair: bool                = self.repair
        skip_format: bool           = self.skip_format
        tmp = Path(get_tmp_dir())
        tmp.mkdir(parents=True, exist_ok=True)
        # Repair mode doesn't reformat the drive, so it needs the drive's
        # actual current letter just like Already Formatted does — only a
        # fresh Full Build can assume the fixed "Z:" HackMate itself assigns
        # during formatting. Without this, repair always assumed Z: even
        # when Windows had mounted the drive somewhere else, and failed with
        # a raw WinError pointing at a drive letter nothing was ever on.
        mount = get_mount_path(device, skip_format=(skip_format or repair))

        def ui(pct, msg):
            self.app.call_from_thread(self._status, pct, msg)

        def log(msg, level="info"):
            self.app.call_from_thread(self._log, msg, level)

        def cmd(args, **kw):
            self.app.call_from_thread(self._cmd_log, args)
            result = subprocess.run(args, **kw)
            if hasattr(result, "returncode") and result.returncode != 0:
                out = (getattr(result, "stderr", b"") or b"").decode(errors="replace").strip()
                if out:
                    for line in out.splitlines():
                        self.app.call_from_thread(self._cmd_out, line, True)
            return result

        self.app.call_from_thread(self._show_spinner, True)

        import urllib.request
        import urllib.error
        import zipfile

        local_mode = (device == "local")
        if local_mode:
            mount = self.app.efi_output_path

        try:
            # Resolve every kext download before the USB is formatted. A dead
            # source found later would be silently dropped from config.plist,
            # and the user would only notice when that hardware doesn't work.
            ui(1, "Checking kext sources...")
            log("── Checking kext download sources...", "header")
            from kexts import select_kexts, check_kext_sources, download_kexts
            kexts = select_kexts(profile, wifi_kext_mode=self.app.wifi_kext_mode)
            src_results, release_cache = check_kext_sources(
                kexts,
                progress_cb=lambda i, n, m: self.app.call_from_thread(
                    self._status, 1 + int((i / max(n, 1)) * 4), m),
            )
            dead = [n for n, r in src_results.items() if r.startswith("ERROR")]
            checked = [n for n, r in src_results.items() if not r.startswith("SKIP")]
            if dead and len(dead) == len(checked):
                # Every kext failing at once usually isn't a connectivity
                # problem (recovery already downloaded fine over a totally
                # separate connection to Apple's CDN) — it's almost always
                # GitHub's 60 req/hr unauthenticated API limit, which was
                # previously masked by this exact generic message. Surface
                # the real reason from the first result instead of guessing.
                sample = src_results[dead[0]]
                if "rate limit" in sample.lower():
                    log(f"  {sample.split('ERROR: ', 1)[-1]}", "warn")
                else:
                    log("  Could not reach any kext source — check your internet connection.", "warn")
                    log(f"  ({sample})", "warn")
            elif dead:
                for name in dead:
                    log(f"  {name}: {src_results[name]}", "warn")
                log(f"  {len(dead)} kext(s) cannot be downloaded and will be skipped.", "warn")
            else:
                log(f"  All {len(checked)} kext sources reachable", "ok")

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

                # Backup existing EFI before any changes (repair only)
                existing_efi = Path(f"{mount}") / "EFI" if not IS_WINDOWS else Path(f"{mount}\\EFI")
                if repair and existing_efi.exists():
                    import datetime, zipfile as zf
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_dir = Path.home() / "HackMate" / "backups"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_zip = backup_dir / f"EFI_backup_{ts}.zip"
                    file_count = 0
                    # Python 3.12 tightened relative_to()'s matching: the bare
                    # drive string "Z:" isn't treated as the same anchor as
                    # the rooted "Z:\EFI\..." paths rglob() returns, and
                    # raises "is not in the subpath of" even though it's
                    # obviously the same drive. Root it the same way.
                    mount_root = Path(f"{mount}\\") if IS_WINDOWS else Path(f"{mount}")
                    with zf.ZipFile(backup_zip, "w", zf.ZIP_DEFLATED) as z:
                        for f in existing_efi.rglob("*"):
                            if f.is_file():
                                z.write(f, f.relative_to(mount_root))
                                file_count += 1
                    size_mb = backup_zip.stat().st_size / 1024 / 1024
                    log(f"── EFI backed up: {file_count} files, {size_mb:.1f} MB → {backup_zip}", "ok")
            else:
                ui(2, f"Formatting {device} as FAT32...")
                log(f"── Formatting {device}...", "header")
                self.app.call_from_thread(self._cmd_log, ["format_usb"] if IS_WINDOWS else ["parted", "mkfs.fat"])
                fmt_ok = format_usb(device, mount)
                if not fmt_ok:
                    raise RuntimeError(f"Failed to format {device}")
                log(f"Formatted {device} as FAT32 (GPT+ESP)", "ok")

            ui(8, "Creating EFI structure...")
            efi       = Path(f"{mount}") / "EFI" if not IS_WINDOWS else Path(f"{mount}\\EFI")
            oc_dir    = efi / "OC"
            boot_dir  = efi / "BOOT"
            kext_dir  = oc_dir / "Kexts"
            acpi_dir  = oc_dir / "ACPI"
            driver_dir= oc_dir / "Drivers"
            for d in [efi, oc_dir, boot_dir, kext_dir, acpi_dir, driver_dir]:
                d.mkdir(parents=True, exist_ok=True)
            log("EFI folder structure ready.", "ok")

            if not repair and not local_mode:
                ui(10, f"Downloading {version.name} recovery from Apple...")
                log(f"── Fetching {version.name} from Apple CDN...", "header")
                recovery_dest = tmp / "recovery"
                self.app.call_from_thread(self._cmd_log, [
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
            from smbios import generate as gen_smbios, SMBIOSData
            smbios = None

            # In repair mode, reuse existing SMBIOS so serial/MLB/UUID stay the same
            if repair:
                existing_config = oc_dir / "config.plist"
                if existing_config.exists():
                    try:
                        import plistlib
                        with open(str(existing_config), "rb") as f:
                            old_cfg = plistlib.load(f)
                        pi = old_cfg.get("PlatformInfo", {}).get("Generic", {})
                        if pi.get("SystemSerialNumber") and pi.get("MLB"):
                            smbios = SMBIOSData(
                                model=pi.get("SystemProductName", profile.smbios_model),
                                serial=pi["SystemSerialNumber"],
                                board_serial=pi["MLB"],
                                system_uuid=pi.get("SystemUUID", ""),
                                rom=pi.get("ROM", b"").hex() if isinstance(pi.get("ROM"), bytes) else pi.get("ROM", ""),
                            )
                            log(f"  Reusing existing SMBIOS (serial preserved)", "ok")
                    except Exception as e:
                        log(f"  Could not read existing SMBIOS ({e}), generating fresh", "info")

            if smbios is None:
                smbios = gen_smbios(profile)

            log(f"  Model:   {smbios.model}", "ok")
            log(f"  Serial:  {smbios.serial}", "ok")
            log(f"  MLB:     {smbios.board_serial}", "ok")
            log(f"  UUID:    {smbios.system_uuid}", "ok")

            ui(40, "Generating config.plist...")
            log("── Generating config.plist...", "header")
            from config_gen import generate as gen_config, write_plist, _required_ssdts
            macos_major = version.major if version else 0
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
            log(f"  {len(kexts)} kexts selected for this hardware", "ok")

            ui(50, f"{'Verifying' if repair else 'Downloading'} {len(kexts)} kexts...")
            log(f"── {'Verifying and updating' if repair else 'Downloading'} kexts from GitHub...", "header")

            def kext_progress(i, n, msg):
                pct = 50 + int((i / n) * 30)
                self.app.call_from_thread(self._status, pct, msg)
                self.app.call_from_thread(self._log, f"  [{i+1}/{n}] {msg}", "info")

            results = download_kexts(kexts, kext_dir, progress_cb=kext_progress, verify=repair,
                                    release_cache=release_cache)
            ok_count  = sum(1 for v in results.values() if v.startswith("OK"))
            err_count = sum(1 for v in results.values() if v.startswith("ERROR"))
            log(f"  {ok_count} kexts downloaded successfully", "ok")
            failed_kexts = {name for name, res in results.items() if res.startswith("ERROR")}
            for name, result in results.items():
                if result.startswith("ERROR"):
                    log(f"  WARN: {name} — {result}", "warn")

            # Remove failed kexts from config.plist so missing .kext files don't prevent booting,
            # then point every surviving entry at the binary its bundle actually contains.
            import plistlib
            from config_gen import sync_executable_paths
            cfg = plistlib.loads(config_path.read_bytes())

            if failed_kexts:
                before = len(cfg["Kernel"]["Add"])
                cfg["Kernel"]["Add"] = [
                    k for k in cfg["Kernel"]["Add"]
                    if not any(name in k.get("BundlePath", "") for name in failed_kexts)
                ]
                removed = before - len(cfg["Kernel"]["Add"])
                if removed:
                    log(f"  Removed {removed} failed kext(s) from config.plist to keep EFI bootable", "warn")

            corrected = sync_executable_paths(cfg, kext_dir)
            if corrected:
                log(f"  Corrected ExecutablePath for {len(corrected)} kext(s): {', '.join(corrected)}", "ok")

            config_path.write_bytes(plistlib.dumps(cfg, fmt=plistlib.FMT_XML))

            # Extras — HeliPort (itlwm users) and USBToolBox app (everyone)
            from kexts import download_heliport, download_usbtoolbox_app
            extras_dir = Path(mount) / "EFI" / "HackMate-Extras"
            if self.app.wifi_kext_mode == "itlwm":
                ok = download_heliport(
                    extras_dir,
                    progress_cb=lambda m: log(f"  {m}", "info")
                )
                if ok:
                    log("  HeliPort saved to EFI/HackMate-Extras/", "ok")
                else:
                    log("  HeliPort download failed — get it from github.com/OpenIntelWireless/HeliPort", "warn")
            ok = download_usbtoolbox_app(
                extras_dir,
                progress_cb=lambda m: log(f"  {m}", "info")
            )
            if ok:
                log("  USBToolBox app saved to EFI/HackMate-Extras/", "ok")
            else:
                log("  USBToolBox download failed — get it from github.com/USBToolBox/Tool", "warn")

            MIN_EFI = 50 * 1024  # sane minimum — corrupt/truncated files are smaller
            oc_required = [
                boot_dir / "BOOTx64.efi",
                oc_dir   / "OpenCore.efi",
                driver_dir / "OpenRuntime.efi",
                driver_dir / "HfsPlus.efi",
            ]
            oc_valid = repair and all(
                f.exists() and f.stat().st_size > MIN_EFI for f in oc_required
            )

            if oc_valid:
                ui(88, "OpenCore files valid — skipping download")
                log("── OpenCore already valid, skipping download", "ok")
            else:
                ui(82, "Downloading OpenCore...")
                log("── Downloading OpenCore...", "header")
                oc_url = "https://api.github.com/repos/acidanthera/OpenCorePkg/releases/latest"
                req = urllib.request.Request(oc_url, headers={"User-Agent": "HackMate/1.0"})
                try:
                    with urllib.request.urlopen(req, timeout=15) as r:
                        oc_data = json.loads(r.read())
                except urllib.error.HTTPError as e:
                    if e.code in (403, 429):
                        raise RuntimeError(
                            "GitHub API rate limit exceeded (60 req/hr unauthenticated) while "
                            "downloading OpenCore. Wait ~1 hour and rerun, or set a GITHUB_TOKEN "
                            "environment variable."
                        ) from e
                    raise

                oc_asset = None
                for asset in oc_data.get("assets", []):
                    name = asset["name"].lower()
                    if "opencore-" in name and "release" in name and name.endswith(".zip"):
                        oc_asset = asset
                        break

                if oc_asset:
                    oc_zip = tmp / oc_asset["name"]
                    expected_size = oc_asset.get("size", 0)
                    last_err = None
                    for attempt in range(3):
                        try:
                            oc_req = urllib.request.Request(
                                oc_asset["browser_download_url"], headers={"User-Agent": "HackMate/1.0"}
                            )
                            with urllib.request.urlopen(oc_req, timeout=60) as r:
                                oc_zip.write_bytes(r.read())
                            actual_size = oc_zip.stat().st_size
                            if expected_size and abs(actual_size - expected_size) > 1024:
                                raise IOError(f"size mismatch (got {actual_size}, expected {expected_size})")
                            last_err = None
                            break
                        except Exception as e:
                            last_err = e
                            log(f"  OpenCore download attempt {attempt + 1}/3 failed: {e}", "warn")
                    if last_err:
                        raise RuntimeError(f"OpenCore download failed after 3 attempts: {last_err}") from last_err
                    log(f"  Downloaded {oc_asset['name']}", "ok")

                    oc_extract = tmp / "oc_extracted"
                    with zipfile.ZipFile(str(oc_zip)) as z:
                        z.extractall(str(oc_extract))

                    # Always use X64 binaries — rglob finds both X64 and IA32; IA32 causes "Unsupported"
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

                    # HfsPlus.efi is not in the OC zip — download from OcBinaryData
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

            # In repair mode, back up existing SSDTs first so we can restore
            # them if generation fails — never leave the system with zero SSDTs.
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

            ok_ssdts   = [n for n, s in ssdt_results.items() if s == "OK"]
            skip_ssdts = [n for n, s in ssdt_results.items() if s.startswith("SKIP")]
            err_ssdts  = [n for n, s in ssdt_results.items() if s.startswith("ERROR")]

            # If all SSDTs failed in repair mode, restore the backup so the
            # system isn't left with an empty ACPI folder
            if repair and ssdt_backup_dir and not ok_ssdts:
                log("  All SSDTs failed — restoring previous SSDTs", "warn")
                shutil.rmtree(str(acpi_dir))
                shutil.copytree(str(ssdt_backup_dir), str(acpi_dir))

            # ssdt.py handles 3-tier fallback internally (SSDTTime → template → bundled .aml).
            # If any SSDT still shows SKIP/ERROR here, it genuinely couldn't be generated —
            # remove it from config.plist, along with any ACPI rename that pointed at it,
            # so OpenCore neither loads a missing file nor applies an orphaned rename.
            if skip_ssdts or err_ssdts:
                import plistlib
                from config_gen import strip_missing_ssdts
                with open(str(config_path), "rb") as f:
                    cfg = plistlib.load(f)
                # Only remove SSDTs that are truly absent from acpi_dir
                missing = [n for n in skip_ssdts + err_ssdts
                           if not (acpi_dir / f"{n}.aml").exists()]
                tables_gone, patches_gone = strip_missing_ssdts(cfg, missing)
                with open(str(config_path), "wb") as f:
                    plistlib.dump(cfg, f)
                if patches_gone:
                    log(f"  Removed {patches_gone} ACPI rename(s) left without their SSDT", "info")

            for n in ok_ssdts:
                log(f"  {n}.aml", "ok")
            for n in skip_ssdts:
                reason = ssdt_results.get(n, "")
                not_required = "not required" in reason or "not present" in reason
                log(f"  {n} — {reason}", "info" if not_required else "warn")
            for n in err_ssdts:
                log(f"  {n} — {ssdt_results[n]}", "error")

            # Write README only for SSDTs that genuinely need manual intervention
            # (not for hardware-appropriate skips like SSDT-AWAC on non-AWAC systems)
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
            issues   = efi_check(efi, profile)
            errors   = [m for lvl, m in issues if lvl == "error"]
            warnings = [m for lvl, m in issues if lvl == "warn"]
            infos    = [m for lvl, m in issues if lvl == "info"]
            oks      = [m for lvl, m in issues if lvl == "ok"]
            # Print non-ok issues with full explanations, suppress ok spam
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
                        self.app.push_screen,
                        BIOSChecklistScreen(version.name, device)
                    )

            try:
                import hwdb_submit
                feature = "no_usb" if local_mode else ("repair" if repair else ("skip_format" if skip_format else "full"))
                log_text = hwdb_submit.build_log(
                    profile, feature, version.name if version else "unknown",
                    worked="build completed", issues="none", dual_boot=dual_boot,
                )
                hwdb_submit.submit_log(profile, feature, log_text, dual_boot=dual_boot)
            except Exception:
                pass

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

            try:
                import hwdb_submit
                feature = "no_usb" if locals().get("local_mode") else (
                    "repair" if locals().get("repair") else (
                        "skip_format" if locals().get("skip_format") else "full"))
                v = locals().get("version")
                log_text = hwdb_submit.build_log(
                    profile, feature, v.name if v else "unknown",
                    worked="build failed", issues=str(e), dual_boot=locals().get("dual_boot", ""),
                )
                hwdb_submit.submit_log(profile, feature, log_text, dual_boot=locals().get("dual_boot", ""))
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

class ConfigEditorUSBScreen(Screen):
    """Pick which USB / config.plist to edit."""

    def compose(self) -> ComposeResult:
        from config_editor import find_configs
        self._configs = find_configs()
        yield Header()
        yield Container(
            Vertical(
                Static("── Edit Config.plist ────────────────────────────────────", classes="title"),
                Static(""),
                Static("  Select a config.plist to edit:", classes="info"),
                Static(""),
                ListView(
                    *[ListItem(Static(f"  {p}")) for p in self._configs] if self._configs
                    else [ListItem(Static("  No config.plist found on any mounted USB"))],
                    id="cfg-list"
                ),
                Static(""),
                Static("  Mount your USB first if it doesn't appear above.", classes="info"),
                Static(""),
                Button("← Back", id="back", classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self.query_one("#cfg-list", ListView).index
        if self._configs:
            self.app.push_screen(ConfigEditorScreen(self._configs[idx]))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

class ConfigEditorScreen(Screen):
    """Simple / Advanced config.plist editor."""

    def __init__(self, config_path):
        super().__init__()
        self._path = config_path
        self._mode = "simple"   # "simple" or "advanced"
        self._cfg  = None
        self._changes: list[str] = []

    def _load(self):
        from config_editor import load_config
        self._cfg = load_config(self._path)

    def compose(self) -> ComposeResult:
        self._load()
        from config_editor import (
            get_boot_args, get_sip_enabled, get_hide_auxiliary,
            get_timeout, get_oc_logging, get_secure_boot_model, get_smbios,
            get_igpu_platform_id, suggest_framebuffers, BOOT_ARG_PRESETS,
            suggest_audio_layouts, get_dgpu_disabled,
        )
        cfg     = self._cfg
        args    = get_boot_args(cfg)
        profile = self.app.profile

        alcid_val   = str(args.get("alcid", ""))
        timeout_val = str(get_timeout(cfg))
        smbios_val  = get_smbios(cfg)
        sbm_val     = get_secure_boot_model(cfg)

        # iGPU suggestions
        gpu_id    = getattr(profile, "gpu_device_id", "").lower() if profile else ""
        fb_opts   = suggest_framebuffers(gpu_id)
        cur_fb    = get_igpu_platform_id(cfg)
        gpu_label = getattr(profile, "gpu_name", "") if profile else ""

        # audio suggestions
        codec      = getattr(profile, "audio_codec", "") if profile else ""
        alc_opts   = suggest_audio_layouts(codec)

        # dGPU
        dgpu_name   = getattr(profile, "dgpu_name",   "") if profile else ""
        dgpu_vendor = getattr(profile, "dgpu_vendor",  "") if profile else ""
        has_dgpu    = bool(dgpu_vendor and getattr(profile, "gpu_vendor", "") == "intel")

        yield Header()
        yield Container(
            Vertical(
                Static("── Config Editor ──────────────── [tab: Advanced ▶]", classes="title"),
                Button("Switch to Advanced mode", id="mode-toggle", classes="back"),
                Static(f"  {self._path}", classes="info"),
                Static(""),
                ScrollableContainer(
                    Vertical(
                        Static("  ── Boot Arg Presets ──────────────────────", classes="cfg-section"),
                        Horizontal(
                            *[Button(name, id=f"preset-{name.lower().replace(' ','-')}", classes="advanced-btn")
                              for name in BOOT_ARG_PRESETS],
                            classes="cfg-row",
                        ),
                        Static("  ── Boot Args ─────────────────────────────", classes="cfg-section"),
                        Horizontal(Static("  Verbose (-v)",         classes="cfg-label"), Switch(value="-v" in args,              id="sw-verbose"),  classes="cfg-row"),
                        Horizontal(Static("  No compat check",      classes="cfg-label"), Switch(value="-no_compat_check" in args,id="sw-nocompat"), classes="cfg-row"),
                        Horizontal(Static("  Debug logging",        classes="cfg-label"), Switch(value="debug" in args,           id="sw-debug"),    classes="cfg-row"),
                        Horizontal(Static("  alcid (audio layout)", classes="cfg-label"), Input(value=alcid_val, placeholder="11", id="in-alcid", classes="short-input"), classes="cfg-row"),
                        *(
                            [Static(f"  Suggestions for {codec}: " + "  ".join(f"[{lid}] {desc}" for lid, desc in alc_opts), classes="info")]
                            if alc_opts else []
                        ),
                        *([Static(f"  Quick set:", classes="info"), Horizontal(*[Button(str(lid), id=f"alcid-{lid}", classes="advanced-btn") for lid, _ in alc_opts[:4]], classes="cfg-row")] if alc_opts else []),
                        Static("  ── OpenCore ──────────────────────────────", classes="cfg-section"),
                        Horizontal(Static("  Picker timeout (sec)", classes="cfg-label"), Input(value=timeout_val, placeholder="5", id="in-timeout", classes="short-input"), classes="cfg-row"),
                        Horizontal(Static("  Show recovery",        classes="cfg-label"), Switch(value=not get_hide_auxiliary(cfg), id="sw-recovery"),classes="cfg-row"),
                        Horizontal(Static("  OC file logging",      classes="cfg-label"), Switch(value=get_oc_logging(cfg),        id="sw-oclog"),   classes="cfg-row"),
                        Static("  ── Security ──────────────────────────────", classes="cfg-section"),
                        Horizontal(Static("  SIP enabled",          classes="cfg-label"), Switch(value=get_sip_enabled(cfg),       id="sw-sip"),     classes="cfg-row"),
                        Horizontal(Static("  SecureBootModel",      classes="cfg-label"), Input(value=sbm_val, placeholder="Disabled", id="in-sbm", classes="short-input"), classes="cfg-row"),
                        Static("  ── System ────────────────────────────────", classes="cfg-section"),
                        Horizontal(Static("  SMBIOS model",         classes="cfg-label"), Input(value=smbios_val, placeholder="MacBookPro15,2", id="in-smbios"), classes="cfg-row"),
                        *(
                            [
                                Static("  ── Discrete GPU ──────────────────────────", classes="cfg-section"),
                                Static(f"  {dgpu_name}", classes="info"),
                                Horizontal(Static("  Disable dGPU (Optimus fix)", classes="cfg-label"), Switch(value=get_dgpu_disabled(cfg), id="sw-dgpu"), classes="cfg-row"),
                            ] if has_dgpu else []
                        ),
                        *(
                            [
                                Static("  ── iGPU Framebuffer ──────────────────────", classes="cfg-section"),
                                Static(f"  Detected: {gpu_label} ({gpu_id})", classes="info"),
                                Static(f"  Current:  {cur_fb or '(not set)'}", id="fb-current", classes="info"),
                                Static("  Suggestions:", classes="info"),
                                *[Horizontal(
                                    Static(f"  {label}", classes="cfg-label"),
                                    Button("Apply", id=f"fb-{hex_id}", classes="advanced-btn"),
                                    classes="cfg-row",
                                ) for hex_id, label in fb_opts],
                                Horizontal(Static("  Custom platform-id", classes="cfg-label"), Input(value=cur_fb, placeholder="e.g. 0000c087", id="in-fb", classes="short-input"), classes="cfg-row"),
                            ] if fb_opts or gpu_id else []
                        ),
                        id="simple-panel"
                    ),
                    Vertical(
                        Static("  ── Advanced: raw plist key editor ────────────────────", classes="cfg-section"),
                        Static(""),
                        Static("  Key path (dot-separated):", classes="info"),
                        Input(placeholder="e.g. Misc.Debug.Target", id="adv-key"),
                        Static(""),
                        Static("  Value:", classes="info"),
                        Input(placeholder="value", id="adv-val"),
                        Static(""),
                        Static("  Type:", classes="info"),
                        Input(value="string", placeholder="string / bool / int / data", id="adv-type"),
                        Static(""),
                        Horizontal(
                            Button("Get", id="adv-get", classes="primary"),
                            Button("Set", id="adv-set", classes="primary"),
                        ),
                        Static(""),
                        Static("  Recent changes:", classes="cfg-section"),
                        Static("  (none yet)", id="adv-log", classes="info"),
                        id="advanced-panel"
                    ),
                    id="editor-scroll"
                ),
                Static(""),
                Horizontal(
                    Button("Save",    id="save",   classes="primary"),
                    Button("← Back",  id="back",   classes="back"),
                ),
                Static("", id="save-status"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#advanced-panel").display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        if bid == "mode-toggle":
            self._mode = "advanced" if self._mode == "simple" else "simple"
            self.query_one("#simple-panel").display   = (self._mode == "simple")
            self.query_one("#advanced-panel").display = (self._mode == "advanced")
            self.query_one("#mode-toggle", Button).label = (
                "Switch to Simple mode" if self._mode == "advanced" else "Switch to Advanced mode"
            )

        elif bid.startswith("alcid-"):
            layout_id = bid.split("-")[1]
            self.query_one("#in-alcid", Input).value = layout_id
            self.query_one("#save-status", Static).update(f"  alcid set to {layout_id} — save to write.")

        elif bid.startswith("preset-"):
            from config_editor import get_boot_args, set_boot_args, BOOT_ARG_PRESETS
            # map button id back to preset name
            preset_key = next(
                (k for k in BOOT_ARG_PRESETS if f"preset-{k.lower().replace(' ','-')}" == bid),
                None
            )
            if preset_key:
                self._apply_simple()
                args = get_boot_args(self._cfg)
                args.update(BOOT_ARG_PRESETS[preset_key])
                set_boot_args(self._cfg, args)
                self.query_one("#save-status", Static).update(f"  Preset '{preset_key}' applied — save to write.")

        elif bid.startswith("fb-"):
            hex_id = bid[3:]
            from config_editor import set_igpu_platform_id
            set_igpu_platform_id(self._cfg, hex_id)
            try:
                self.query_one("#fb-current", Static).update(f"  Current:  {hex_id}")
                self.query_one("#in-fb", Input).value = hex_id
            except Exception:
                pass
            self.query_one("#save-status", Static).update(f"  Framebuffer set to {hex_id} — save to write.")

        elif bid == "adv-get":
            from config_editor import get_value
            key = self.query_one("#adv-key", Input).value.strip()
            try:
                val = get_value(self._cfg, key)
                self.query_one("#adv-val", Input).value = str(val)
            except Exception as e:
                self.query_one("#adv-val", Input).value = f"ERROR: {e}"

        elif bid == "adv-set":
            from config_editor import set_value, coerce_value
            key  = self.query_one("#adv-key",  Input).value.strip()
            raw  = self.query_one("#adv-val",  Input).value.strip()
            typ  = self.query_one("#adv-type", Input).value.strip() or "string"
            try:
                val = coerce_value(raw, typ)
                set_value(self._cfg, key, val)
                entry = f"  • {key} → {raw}"
                self._changes.append(entry)
                self.query_one("#adv-log", Static).update("\n".join(self._changes[-8:]))
            except Exception as e:
                self.query_one("#adv-log", Static).update(f"  ERROR: {e}")

        elif bid == "save":
            self._apply_simple()
            from config_editor import save_config
            try:
                save_config(self._path, self._cfg)
                self.query_one("#save-status", Static).update("  ✓ Saved.")
            except Exception as e:
                self.query_one("#save-status", Static).update(f"  ✗ Save failed: {e}")

        elif bid == "back":
            self.app.pop_screen()

    def _apply_simple(self) -> None:
        """Read all simple-mode widgets and apply to cfg."""
        from config_editor import (
            get_boot_args, set_boot_args, set_sip, set_hide_auxiliary,
            set_timeout, set_oc_logging, set_secure_boot_model, set_smbios,
            set_igpu_platform_id, set_dgpu_disabled,
        )
        cfg  = self._cfg
        args = get_boot_args(cfg)

        def sw(id_) -> bool:
            try:
                return self.query_one(id_, Switch).value
            except Exception:
                return False

        def inp(id_) -> str:
            try:
                return self.query_one(id_, Input).value.strip()
            except Exception:
                return ""

        # boot-args flags
        for flag, widget_id in [
            ("-v",                "sw-verbose"),
            ("-no_compat_check",  "sw-nocompat"),
        ]:
            if sw(f"#{widget_id}"):
                args[flag] = True
            else:
                args.pop(flag, None)

        # debug=0x100 + keepsyms=1 together
        if sw("#sw-debug"):
            args["debug"]    = "0x100"
            args["keepsyms"] = "1"
        else:
            args.pop("debug",    None)
            args.pop("keepsyms", None)

        # alcid
        alcid = inp("#in-alcid")
        if alcid.isdigit():
            args["alcid"] = alcid
        else:
            args.pop("alcid", None)

        set_boot_args(cfg, args)

        # timeout
        t = inp("#in-timeout")
        if t.isdigit():
            set_timeout(cfg, int(t))

        set_hide_auxiliary(cfg, not sw("#sw-recovery"))
        set_oc_logging(cfg, sw("#sw-oclog"))
        set_sip(cfg, sw("#sw-sip"))

        sbm = inp("#in-sbm")
        if sbm:
            set_secure_boot_model(cfg, sbm)

        smbios = inp("#in-smbios")
        if smbios:
            set_smbios(cfg, smbios)

        fb = inp("#in-fb")
        if fb and len(fb) == 8:
            try:
                set_igpu_platform_id(cfg, fb)
            except Exception:
                pass

        try:
            set_dgpu_disabled(cfg, sw("#sw-dgpu"))
        except Exception:
            pass

class BIOSChecklistScreen(Screen):
    """Show what BIOS settings to configure before booting the USB."""
    def __init__(self, version_name: str, device: str):
        super().__init__()
        self.version_name = version_name
        self.device = device

    def compose(self) -> ComposeResult:
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

        rows = []
        for title, detail in items:
            rows.append(Static(f"  ◻  {title}", classes="info"))
            rows.append(Static(f"       {detail}", classes="info"))
            rows.append(Static(""))

        yield Header()
        yield Container(
            Vertical(
                Static("── Before You Boot ──────────────────────────────────────", classes="title"),
                Static(""),
                Static(f"  USB ready: {self.version_name} on {self.device}", classes="ok"),
                Static(""),
                Static("  Configure these BIOS settings first:", classes="warn"),
                Static("  (Location varies by motherboard — check your manual)", classes="info"),
                Static(""),
                *rows,
                Static("  Then boot from USB. At OpenCore picker, select the macOS installer.", classes="info"),
                Static(""),
                Button("Got it — I'm done", id="done", classes="primary"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done":
            self.app.pop_screen()

class DemoScreen(Screen):
    """Auto-playing walkthrough for screenshots/GIFs — launched with --demo."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(classes="screen-inner"):
            with Vertical():
                yield Static("── HackMate Demo ────────────────────────────────────────", classes="title")
                yield Static("", id="stage")
                yield ProgressBar(id="progress", total=100)
                yield RichLog(id="log", auto_scroll=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_demo()

    def _log(self, msg: str, level: str = "info") -> None:
        colors = {"ok": "green", "warn": "yellow", "error": "red", "info": "#888888", "header": "cyan"}
        color  = colors.get(level, "#888888")
        self.query_one("#log", RichLog).write(f"[{color}]{msg}[/{color}]")

    def _stage(self, pct: int, msg: str) -> None:
        self.query_one("#stage",    Static).update(f"  {msg}")
        self.query_one("#progress", ProgressBar).progress = pct

    @work(thread=True)
    def run_demo(self) -> None:
        import time

        def ui(pct, msg): self.app.call_from_thread(self._stage, pct, msg)
        def log(msg, lv="info"): self.app.call_from_thread(self._log, msg, lv)

        time.sleep(0.5)

        ui(5, "Scanning hardware...")
        time.sleep(0.8)
        log("── Hardware Detection ─────────────────────────────────", "header")
        for line in [
            ("  CPU       Intel Core i5-8350U", "ok"),
            ("  Codename  Kaby Lake-R  (Gen 8)", "ok"),
            ("  Platform  laptop  —  Laptop", "ok"),
            ("  GPU       Intel UHD Graphics 620 [intel]", "ok"),
            ("  Audio     Realtek ALC257  →  layout-id 11", "ok"),
            ("  Ethernet  Intel I219-V", "ok"),
            ("  WiFi      Intel Wireless-AC 8265", "ok"),
            ("  SMBIOS    MacBookPro15,2", "ok"),
            ("  Kexts     22 selected", "ok"),
            ("  NVMe      Yes   Thunderbolt: Yes", "ok"),
        ]:
            log(*line)
            time.sleep(0.07)

        time.sleep(1.0)

        ui(20, "Downloading kexts from GitHub...")
        log("", "info")
        log("── Downloading Kexts ──────────────────────────────────", "header")
        kexts = [
            "Lilu", "VirtualSMC", "WhateverGreen", "AppleALC",
            "IntelMausiEthernet", "itlwm", "IntelBluetoothFirmware",
            "VoodooPS2Controller", "VoodooI2C", "VoodooI2CELAN",
            "USBToolBox", "UTBMap", "NVMeFix", "CPUFriend",
        ]
        for k in kexts:
            log(f"  {k}.kext  — OK", "ok")
            time.sleep(0.08)
        log("  HeliPort saved to EFI/HackMate-Extras/", "ok")
        log("  USBToolBox app saved to EFI/HackMate-Extras/", "ok")

        time.sleep(0.5)

        ui(45, "Generating SSDTs from DSDT...")
        log("", "info")
        log("── Generating SSDTs ───────────────────────────────────", "header")
        ssdts = [
            ("SSDT-PLUG",    "SSDTTime"),
            ("SSDT-EC-USBX", "SSDTTime"),
            ("SSDT-PNLF",    "SSDTTime"),
            ("SSDT-GPI0",    "SSDTTime"),
            ("SSDT-XOSI",    "bundled"),
        ]
        for name, method in ssdts:
            log(f"  {name:<16} [{method}]  OK", "ok")
            time.sleep(0.15)

        time.sleep(0.5)

        ui(62, "Downloading OpenCore...")
        log("", "info")
        log("── OpenCore + Config ──────────────────────────────────", "header")
        time.sleep(0.4)
        log("  OpenCore 1.0.4 extracted", "ok")
        time.sleep(0.2)
        log("  SMBIOS generated  (MacBookPro15,2)", "ok")
        time.sleep(0.2)
        log("  config.plist generated  (42 quirks configured)", "ok")

        time.sleep(0.5)

        ui(88, "Running EFI sanity checks...")
        log("", "info")
        log("── EFI Sanity Check ───────────────────────────────────", "header")
        time.sleep(0.3)
        log("  42 checks passed", "ok")

        ui(100, "USB is ready!")
        log("", "info")
        log("══════════════════════════════════════════════════════", "header")
        log("  USB is ready!  Boot from it to install macOS Tahoe.", "ok")
        log("  Configure BIOS settings, then select the installer.", "info")
        log("══════════════════════════════════════════════════════", "header")
        time.sleep(2)
        self.app.call_from_thread(self.app.exit)

def _get_version() -> str:
    try:
        sha = (Path(__file__).parent / ".version").read_text().strip()[:7]
        return f"v2.0.0 ({sha})"
    except Exception:
        return "v2.0.0"

VERSION = _get_version()

class HackMate(App):
    CSS = CSS
    TITLE = "HackMate"
    SUB_TITLE = VERSION

    profile:         HardwareProfile | None = None
    macos_version:   MacOSVersion   | None = None
    wifi_kext_mode:  str                   = "itlwm"
    disable_dgpu:    bool                  = False
    dual_boot:       str                   = ""
    efi_output_path: str                   = ""

    def on_mount(self) -> None:
        if DEMO_MODE:
            self.push_screen(DemoScreen())
        else:
            import hwdb_submit
            if hwdb_submit.consent_already_asked():
                self.push_screen(WelcomeScreen())
            else:
                self.push_screen(HwdbConsentScreen())
        self.set_interval(3600, self._check_for_update)

    @work(thread=True)
    def _check_for_update(self) -> None:
        from updater import check_update_silent, _download_file, FILES, VERSION_FILE
        has_update, remote_sha, changelog = check_update_silent()
        if not has_update:
            return

        short = remote_sha[:7]
        summary = changelog[0] if changelog else "improvements and fixes"
        self.call_from_thread(
            self.notify,
            f"Downloading update {short}...",
            title="HackMate Update",
            severity="information",
            timeout=5,
        )

        failed = [f for f in FILES if not _download_file(f, remote_sha)]
        if not failed:
            VERSION_FILE.write_text(remote_sha)
            self.call_from_thread(
                self.notify,
                f"{short}: {summary} — restart to apply",
                title="Update ready",
                severity="information",
                timeout=30,
            )
        else:
            self.call_from_thread(
                self.notify,
                f"Update {short} failed ({len(failed)} file(s)) — will retry next hour",
                severity="warning",
                timeout=10,
            )

if __name__ == "__main__":
    HackMate().run()
