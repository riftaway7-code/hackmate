import subprocess
import os
import sys
import shutil
import shlex
import json
from pathlib import Path

from compat import require_admin, IS_WINDOWS, get_usb_drives, format_usb, mount_usb, unmount_usb, get_mount_path, get_tmp_dir
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
"""

BANNER = (
    "██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗\n"
    "██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝\n"
    "███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗  \n"
    "██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝  \n"
    "██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗\n"
    "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝"
)


# ─── Enable OC Logging ────────────────────────────────────────────────────────

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


# ─── Log Checker ──────────────────────────────────────────────────────────────

class LogCheckerScreen(Screen):
    """Analyze OpenCore logs and kernel panic files to identify issues and suggest fixes."""

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


# ─── Welcome ──────────────────────────────────────────────────────────────────

class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static(BANNER,     classes="title",    id="banner"),
                Static("Automated OpenCore EFI builder — any hardware", classes="info", id="subtitle"),
                Static(""),
                Button("Build EFI",              id="start",      classes="primary"),
                Button("Build EFI (Manual)",     id="manual",     classes="primary"),
                Button("Restore EFI",            id="restore",    classes="primary"),
                Button("Edit Config",            id="edit_cfg",   classes="primary"),
                Button("Check Logs",             id="check_logs", classes="primary"),
                Button("Quit",                   id="quit",       classes="danger"),
                id="welcome-inner"
            ),
            id="welcome"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.app.push_screen(ScanScreen())
        elif event.button.id == "manual":
            self.app.push_screen(ManualHardwareScreen())
        elif event.button.id == "restore":
            self.app.push_screen(RestoreScreen())
        elif event.button.id == "edit_cfg":
            self.app.push_screen(ConfigEditorUSBScreen())
        elif event.button.id == "check_logs":
            self.app.push_screen(LogCheckerScreen())
        elif event.button.id == "quit":
            self.app.exit()


# ─── Restore Screen ───────────────────────────────────────────────────────────

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


# ─── Manual Hardware Screen ───────────────────────────────────────────────────

class ManualHardwareScreen(Screen):
    """Let user specify hardware manually — for building a USB for a different machine."""

    CPU_OPTIONS = [
        # ── Intel Desktop ──────────────────────────────────────────────────────
        ("intel-2",    "Intel Core i3/i5/i7-2xxx  —  Sandy Bridge (2nd gen desktop)"),
        ("intel-3",    "Intel Core i3/i5/i7-3xxx  —  Ivy Bridge (3rd gen desktop)"),
        ("intel-4",    "Intel Core i3/i5/i7-4xxx  —  Haswell (4th gen desktop)"),
        ("intel-5d",   "Intel Core i5/i7-5xxx  —  Broadwell (5th gen desktop)"),
        ("intel-6d",   "Intel Core i3/i5/i7-6xxx  —  Skylake (6th gen desktop)"),
        ("intel-7d",   "Intel Core i3/i5/i7-7xxx  —  Kaby Lake (7th gen desktop)"),
        ("intel-8d",   "Intel Core i3/i5/i7/i9-8xxx  —  Coffee Lake (8th gen desktop)"),
        ("intel-9d",   "Intel Core i5/i7/i9-9xxx  —  Coffee Lake Refresh (9th gen desktop)"),
        ("intel-10d",  "Intel Core i3/i5/i7/i9-10xxx  —  Comet Lake (10th gen desktop)"),
        # ── Intel Laptop ───────────────────────────────────────────────────────
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
        # ── AMD Desktop ────────────────────────────────────────────────────────
        ("amd-zen1d",  "AMD Ryzen 3/5/7 1xxx  —  Zen (desktop)"),
        ("amd-zenpd",  "AMD Ryzen 3/5/7 2xxx  —  Zen+ (desktop)"),
        ("amd-zen2d",  "AMD Ryzen 5/7/9 3xxx  —  Zen 2 (desktop)"),
        ("amd-tr3",    "AMD Threadripper 3xxx  —  Zen 2 (HEDT)"),
        ("amd-zen3d",  "AMD Ryzen 5/7/9 5xxx  —  Zen 3 (desktop)"),
        ("amd-tr5",    "AMD Threadripper 5xxx  —  Zen 3 (HEDT)"),
        ("amd-zen4d",  "AMD Ryzen 5/7/9 7xxx  —  Zen 4 (desktop, AM5)"),
        ("amd-zen5d",  "AMD Ryzen 5/7/9 9xxx  —  Zen 5 (desktop, AM5)"),
        # ── AMD Laptop / APU ───────────────────────────────────────────────────
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


# ─── Scanning ─────────────────────────────────────────────────────────────────

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


# ─── macOS Version ────────────────────────────────────────────────────────────

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


# ─── USB Selection ────────────────────────────────────────────────────────────

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
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── Build Mode ───────────────────────────────────────────────────────────────

class WiFiKextScreen(Screen):
    """WiFi kext selection + optional credential pre-load for itlwm."""
    def __init__(self, device: str, repair: bool, skip_format: bool):
        super().__init__()
        self.device = device
        self.repair = repair
        self.skip_format = skip_format
        self._itlwm_chosen = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Intel WiFi Mode ──────────────────────────────────────", classes="title"),
                Static(""),
                Static("  Intel WiFi detected. Choose your WiFi kext:", classes="info"),
                Static(""),
                Static("  Standard (itlwm + HeliPort)", classes="info"),
                Static("    Works with ALL macOS versions including Tahoe.", classes="info"),
                Static("    Pre-load WiFi credentials to auto-connect during install.", classes="info"),
                Static(""),
                Static("  Native AirportBSD (AirportItlwm)", classes="info"),
                Static("    Shows as built-in WiFi — no HeliPort needed.", classes="info"),
                Static("    ⚠  Tied to macOS version — no Tahoe build yet.", classes="info"),
                Static(""),
                Button("Standard (itlwm + HeliPort)", id="itlwm",        classes="primary"),
                Button("Native (AirportItlwm)",        id="airportitlwm", classes="primary"),
                Button("← Back",                       id="back",         classes="back"),
                # Credential fields — hidden until Standard is chosen
                Static("", id="creds-sep", classes="info"),
                Static("── WiFi Auto-Connect (optional) ────────────────────────", id="creds-title", classes="title"),
                Static("  Network name (SSID):", id="creds-ssid-label", classes="info"),
                Input(placeholder="MyWiFiNetwork", id="ssid"),
                Static("  Password:", id="creds-pw-label", classes="info"),
                Input(placeholder="(leave blank for open networks)", password=True, id="password"),
                Static(""),
                Button("Save & Continue", id="creds-save", classes="primary"),
                Button("Skip",            id="creds-skip", classes="primary"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self._set_creds_visible(False)

    def _set_creds_visible(self, visible: bool) -> None:
        ids = ["creds-sep", "creds-title", "creds-ssid-label", "ssid",
               "creds-pw-label", "password", "creds-save", "creds-skip"]
        for wid in ids:
            try:
                self.query_one(f"#{wid}").display = visible
            except Exception:
                pass

    def _next(self) -> None:
        profile: HardwareProfile = self.app.profile
        if getattr(profile, "dgpu_vendor", "") and getattr(profile, "gpu_vendor", "") == "intel":
            self.app.push_screen(DGPUScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        else:
            self.app.push_screen(ConfirmScreen(self.device, repair=self.repair, skip_format=self.skip_format))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "itlwm":
            self.app.wifi_kext_mode = "itlwm"
            self._itlwm_chosen = True
            # Hide mode buttons, show credential fields
            self.query_one("#itlwm",       Button).display = False
            self.query_one("#airportitlwm",Button).display = False
            self._set_creds_visible(True)
        elif event.button.id == "airportitlwm":
            self.app.wifi_kext_mode = "AirportItlwm"
            self._next()
        elif event.button.id == "creds-save":
            self.app.wifi_ssid     = self.query_one("#ssid",     Input).value.strip()
            self.app.wifi_password = self.query_one("#password", Input).value
            self._next()
        elif event.button.id == "creds-skip":
            self.app.wifi_ssid = ""
            self.app.wifi_password = ""
            self._next()
        elif event.button.id == "back":
            if self._itlwm_chosen:
                # Go back to mode selection
                self._itlwm_chosen = False
                self.query_one("#itlwm",       Button).display = True
                self.query_one("#airportitlwm",Button).display = True
                self._set_creds_visible(False)
            else:
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
        if getattr(profile, "wifi_chipset", "") == "intel":
            self.app.push_screen(WiFiKextScreen(self.device, repair=repair, skip_format=skip_format))
        elif has_dgpu:
            self.app.push_screen(DGPUScreen(self.device, repair=repair, skip_format=skip_format))
        else:
            self.app.push_screen(ConfirmScreen(self.device, repair=repair, skip_format=skip_format))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "full":
            self._next_screen(repair=False, skip_format=False)
        elif event.button.id == "skip_format":
            self._next_screen(repair=False, skip_format=True)
        elif event.button.id == "repair":
            self._next_screen(repair=True, skip_format=False)
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── dGPU Screen ─────────────────────────────────────────────────────────────

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
            self.app.push_screen(ConfirmScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        elif event.button.id == "skip":
            self.app.disable_dgpu = False
            self.app.push_screen(ConfirmScreen(self.device, repair=self.repair, skip_format=self.skip_format))
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── Confirm Screen ───────────────────────────────────────────────────────────

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


# ─── Install ──────────────────────────────────────────────────────────────────

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
        profile: HardwareProfile    = self.app.profile
        version: MacOSVersion       = self.app.macos_version
        device: str                 = self.device
        repair: bool                = self.repair
        skip_format: bool           = self.skip_format
        tmp = Path(get_tmp_dir())
        tmp.mkdir(parents=True, exist_ok=True)
        mount = get_mount_path(device, skip_format=skip_format)

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
        import zipfile

        try:
            if repair or skip_format:
                # ── Repair / Already Formatted: mount existing USB ────────────
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
                    with zf.ZipFile(backup_zip, "w", zf.ZIP_DEFLATED) as z:
                        for f in existing_efi.rglob("*"):
                            if f.is_file():
                                z.write(f, f.relative_to(mount))
                                file_count += 1
                    size_mb = backup_zip.stat().st_size / 1024 / 1024
                    log(f"── EFI backed up: {file_count} files, {size_mb:.1f} MB → {backup_zip}", "ok")
            else:
                # ── 1. Format USB ─────────────────────────────────────────────
                ui(2, f"Formatting {device} as FAT32...")
                log(f"── Formatting {device}...", "header")
                self.app.call_from_thread(self._cmd_log, ["format_usb"] if IS_WINDOWS else ["parted", "mkfs.fat"])
                fmt_ok = format_usb(device, mount)
                if not fmt_ok:
                    raise RuntimeError(f"Failed to format {device}")
                log(f"Formatted {device} as FAT32 (GPT+ESP)", "ok")

            # ── 2. Create / ensure EFI structure ─────────────────────────────
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

            if not repair:
                # ── 3. Download macOS recovery ────────────────────────────────
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
                    if "%" in msg or "Chunk" in msg:
                        self.app.call_from_thread(self._log, f"  {msg}", "info")
                        self.app.call_from_thread(self._cmd_out, msg)
                    elif "complete" in msg.lower() or "verification" in msg.lower():
                        self.app.call_from_thread(self._log, f"  {msg}", "ok")
                        self.app.call_from_thread(self._cmd_out, msg)
                    else:
                        self.app.call_from_thread(self._log, f"  {msg}", "info")
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

            # ── 4. Generate SMBIOS ────────────────────────────────────────────
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

            # ── 5. Generate config.plist ──────────────────────────────────────
            ui(40, "Generating config.plist...")
            log("── Generating config.plist...", "header")
            from config_gen import generate as gen_config, write_plist, _required_ssdts
            macos_major = int(version.version) if version and version.version.isdigit() else 0
            config = gen_config(profile, smbios, macos_major, wifi_kext_mode=self.app.wifi_kext_mode)
            if self.app.disable_dgpu:
                from config_editor import set_dgpu_disabled
                set_dgpu_disabled(config, True)
                log("  dGPU disabled in DeviceProperties", "ok")
            config_path = oc_dir / "config.plist"
            write_plist(config, config_path)
            log(f"  config.plist written ({config_path.stat().st_size} bytes)", "ok")

            # ── 6. Download kexts ─────────────────────────────────────────────
            ui(45, "Selecting kexts...")
            log("── Selecting kexts...", "header")
            from kexts import select_kexts, download_kexts
            kexts = select_kexts(profile, wifi_kext_mode=self.app.wifi_kext_mode)
            log(f"  {len(kexts)} kexts selected for this hardware", "ok")

            ui(50, f"{'Verifying' if repair else 'Downloading'} {len(kexts)} kexts...")
            log(f"── {'Verifying and updating' if repair else 'Downloading'} kexts from GitHub...", "header")

            def kext_progress(i, n, msg):
                pct = 50 + int((i / n) * 30)
                self.app.call_from_thread(self._status, pct, msg)
                self.app.call_from_thread(self._log, f"  [{i+1}/{n}] {msg}", "info")

            results = download_kexts(kexts, kext_dir, progress_cb=kext_progress, verify=repair)
            ok_count  = sum(1 for v in results.values() if v.startswith("OK"))
            err_count = sum(1 for v in results.values() if v.startswith("ERROR"))
            log(f"  {ok_count} kexts downloaded successfully", "ok")
            for name, result in results.items():
                if result.startswith("ERROR"):
                    log(f"  WARN: {name} — {result}", "warn")

            # HeliPort — download alongside itlwm so user has it ready on the USB
            if self.app.wifi_kext_mode == "itlwm":
                from kexts import download_heliport
                extras_dir = Path(mount) / "EFI" / "HackMate-Extras"
                ok = download_heliport(
                    extras_dir,
                    progress_cb=lambda m: log(f"  {m}", "info")
                )
                if ok:
                    log("  HeliPort saved to EFI/HackMate-Extras/ on USB", "ok")
                else:
                    log("  HeliPort download failed — get it from github.com/OpenIntelWireless/HeliPort", "warn")

                # Inject WiFi credentials into itlwm.kext so it auto-connects during install
                if self.app.wifi_ssid:
                    itlwm_plist = kext_dir / "itlwm.kext" / "Contents" / "Info.plist"
                    if itlwm_plist.exists():
                        try:
                            import plistlib as _pl
                            with open(str(itlwm_plist), "rb") as f:
                                kinfo = _pl.load(f)
                            personalities = kinfo.get("IOKitPersonalities", {})
                            for key in personalities:
                                personalities[key]["WiFiCredentials"] = [
                                    {"ssid": self.app.wifi_ssid, "password": self.app.wifi_password}
                                ]
                            with open(str(itlwm_plist), "wb") as f:
                                _pl.dump(kinfo, f)
                            log(f"  WiFi credentials injected for '{self.app.wifi_ssid}' — itlwm will auto-connect", "ok")
                        except Exception as e:
                            log(f"  WiFi credential injection failed: {e}", "warn")

            # ── 7. Download OpenCore ──────────────────────────────────────────
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

                    for driver in ["OpenRuntime.efi", "HfsPlus.efi", "ResetNvramEntry.efi"]:
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

            # ── 8. SSDTs via SSDTTime ─────────────────────────────────────────
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
            # remove it from config.plist so OpenCore doesn't fail on a missing file.
            if skip_ssdts or err_ssdts:
                import plistlib
                with open(str(config_path), "rb") as f:
                    cfg = plistlib.load(f)
                # Only remove SSDTs that are truly absent from acpi_dir
                bad = {f"{n}.aml" for n in skip_ssdts + err_ssdts
                       if not (acpi_dir / f"{n}.aml").exists()}
                cfg["ACPI"]["Add"] = [e for e in cfg["ACPI"]["Add"] if e.get("Path","") not in bad]
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

            # ── 9. EFI sanity check ─────────────────────────────────────────
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

            # ── 10. Unmount ───────────────────────────────────────────────────
            ui(99, "Unmounting USB...")
            unmount_usb(mount)
            shutil.rmtree(str(tmp), ignore_errors=True)

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()


# ─── Config Editor ───────────────────────────────────────────────────────────

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
                    # ── Simple mode ──────────────────────────────────────
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
                    # ── Advanced mode ─────────────────────────────────────
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


# ─── BIOS Checklist ──────────────────────────────────────────────────────────

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


# ─── App ──────────────────────────────────────────────────────────────────────

def _get_version() -> str:
    try:
        sha = (Path(__file__).parent / ".version").read_text().strip()[:7]
        return f"v1.3.0 ({sha})"
    except Exception:
        return "v1.3.0"

VERSION = _get_version()

class HackMate(App):
    CSS = CSS
    TITLE = "HackMate"
    SUB_TITLE = VERSION

    profile:        HardwareProfile | None = None
    macos_version:  MacOSVersion   | None = None
    wifi_kext_mode: str                   = "itlwm"
    wifi_ssid:      str                   = ""
    wifi_password:  str                   = ""
    disable_dgpu:   bool                  = False

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())


if __name__ == "__main__":
    HackMate().run()
