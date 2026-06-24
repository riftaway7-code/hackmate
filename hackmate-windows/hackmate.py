import subprocess
import os
import sys
import shutil
import ctypes
import json
import string
import tempfile
from pathlib import Path

def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

if not _is_admin():
    print("HackMate requires administrator privileges.")
    print("Right-click the script and select 'Run as administrator'.")
    input("Press Enter to exit...")
    sys.exit(1)

from updater import check_and_update
if check_and_update():
    os.execv(sys.executable, [sys.executable] + sys.argv)

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Button, ListView, ListItem, ProgressBar, Static, RichLog, LoadingIndicator
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual import work

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
"""

BANNER = (
    "██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗\n"
    "██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝\n"
    "███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗  \n"
    "██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝  \n"
    "██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗\n"
    "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝"
)


# ─── USB detection (Windows) ──────────────────────────────────────────────────

def get_usb_drives() -> list[tuple[str, str, str]]:
    """Return list of (drive_letter, size, label) for removable USB drives."""
    drives = []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject Win32_LogicalDisk | Where-Object {$_.DriveType -eq 2} | "
             "Select-Object DeviceID, Size, VolumeName | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if not out:
            return drives
        items = json.loads(out)
        if isinstance(items, dict):
            items = [items]
        for item in items:
            letter = item.get("DeviceID", "")
            size_bytes = item.get("Size") or 0
            label = item.get("VolumeName") or ""
            size_gb = f"{int(size_bytes) // 1024 // 1024 // 1024}GB" if size_bytes else "?"
            drives.append((letter, size_gb, label))
    except Exception:
        pass
    return drives


def _format_usb_diskpart(drive_letter: str) -> bool:
    """Format a drive using diskpart, preserving the original drive letter."""
    letter = drive_letter.rstrip(':\\')
    script = (
        f"select volume {letter}\n"
        "clean\n"
        "create partition primary\n"
        "format fs=fat32 quick label=HACKINTOSH\n"
        f"assign letter={letter}\n"
        "exit\n"
    )
    script_path = Path(tempfile.mktemp(suffix=".txt"))
    script_path.write_text(script)
    try:
        result = subprocess.run(
            ["diskpart", "/s", str(script_path)],
            capture_output=True, text=True, timeout=120
        )
        return result.returncode == 0
    finally:
        script_path.unlink(missing_ok=True)


def _get_drive_letter_for_disk(disk_number: int) -> str | None:
    """Get the drive letter assigned to a disk after formatting."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-Partition -DiskNumber {disk_number} | Get-Volume | Select-Object -ExpandProperty DriveLetter"],
        capture_output=True, text=True, timeout=10
    ).stdout.strip()
    if out and out[0] in string.ascii_letters:
        return out[0] + ":"
    return None


# ─── Welcome ──────────────────────────────────────────────────────────────────

class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static(BANNER, classes="title"),
                Static("  OpenCore EFI Builder for Windows  —  fully automated", classes="dim"),
                Static(""),
                Button("Start →", id="start", classes="primary"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.app.push_screen(ScanScreen())


# ─── Scan ─────────────────────────────────────────────────────────────────────

class ScanScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static("── Scanning Hardware ────────────────────────────────", classes="title"),
                Static("Detecting your system...", id="scan-status"),
                Static("", id="hw-info"),
                Button("Continue →", id="continue", classes="primary"),
                Button("← Back",     id="back",     classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#continue", Button).display = False
        self.scan_hardware()

    @work(thread=True)
    def scan_hardware(self) -> None:
        profile = scan()
        self.app.profile = profile

        lines = [
            f"  CPU:       {profile.cpu_name}",
            f"  Gen:       {profile.cpu_generation} ({profile.cpu_codename})",
            f"  GPU:       {profile.gpu_name} [{profile.gpu_vendor}]",
            f"  Audio:     {profile.audio_codec}",
            f"  Ethernet:  {profile.ethernet_name}",
            f"  WiFi:      {profile.wifi_name}",
            f"  Platform:  {profile.platform}",
            f"  NVMe:      {'Yes' if profile.nvme_present else 'No'}",
            f"  SMBIOS:    {profile.smbios_model}",
        ]

        def update():
            self.query_one("#scan-status", Static).update("  Hardware detected:")
            self.query_one("#hw-info", Static).update("\n".join(lines))
            self.query_one("#continue", Button).display = True

        self.app.call_from_thread(update)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            versions = compatible_versions(self.app.profile.cpu_generation, self.app.profile.gpu_vendor)
            self.app.push_screen(VersionScreen(versions))
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── Version ──────────────────────────────────────────────────────────────────

class VersionScreen(Screen):
    def __init__(self, versions):
        super().__init__()
        self.versions = versions

    def compose(self) -> ComposeResult:
        items = [ListItem(Label(f"  {v.name}  {('— ' + v.notes) if v.notes else ''}")) for v in self.versions]
        if not items:
            items = [ListItem(Label("  No compatible macOS versions for your hardware"))]
        yield Header()
        yield Container(
            Vertical(
                Static("── Select macOS Version ─────────────────────────────", classes="title"),
                ListView(*items, id="ver-list"),
                Static(""),
                Button("Continue →", id="continue", classes="primary"),
                Button("← Back",     id="back",     classes="back"),
                classes="screen-inner"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue" and self.versions:
            lv = self.query_one("#ver-list", ListView)
            idx = lv.index or 0
            self.app.macos_version = self.versions[idx]
            self.app.push_screen(USBScreen())
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── USB ──────────────────────────────────────────────────────────────────────

class USBScreen(Screen):
    def __init__(self):
        super().__init__()
        self.drives = get_usb_drives()

    def compose(self) -> ComposeResult:
        version = self.app.macos_version
        items = [ListItem(Label(f"  {letter}   {size}   {label}")) for letter, size, label in self.drives]
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
                self.app.push_screen(InstallScreen(selected))
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── Install ──────────────────────────────────────────────────────────────────

class InstallScreen(Screen):
    def __init__(self, drive_letter: str):
        super().__init__()
        self.drive_letter = drive_letter

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(classes="screen-inner"):
            with Vertical():
                yield Static(f"── Building EFI → {self.drive_letter} ───────────────────────", classes="title")
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
            cmd_str = " ".join(str(c) for c in cmd)
            self.query_one("#cmd-log", RichLog).write(
                f"[dim]hackmate@admin[/dim][#00ff88]>[/#00ff88] [white]{cmd_str}[/white]"
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
        import urllib.request
        import zipfile

        profile: HardwareProfile = self.app.profile
        version: MacOSVersion    = self.app.macos_version
        drive = self.drive_letter  # e.g. "E:"
        tmp = Path(tempfile.mkdtemp(prefix="hackmate_"))

        def ui(pct, msg):
            self.app.call_from_thread(self._status, pct, msg)

        def log(msg, level="info"):
            self.app.call_from_thread(self._log, msg, level)

        def cmd(args):
            self.app.call_from_thread(self._cmd_log, args)
            result = subprocess.run(args, capture_output=True, text=True)
            if result.returncode != 0 and result.stderr:
                for line in result.stderr.splitlines():
                    self.app.call_from_thread(self._cmd_out, line, True)
            return result

        self.app.call_from_thread(self._show_spinner, True)

        try:
            # ── 1. Format USB ────────────────────────────────────────────────
            ui(2, f"Formatting {drive} as FAT32...")
            log(f"── Formatting {drive}...", "header")
            self.app.call_from_thread(self._cmd_log, ["diskpart", "/s", "format_usb.txt"])
            ok = _format_usb_diskpart(drive)
            if not ok:
                raise RuntimeError(f"Failed to format {drive}")
            log(f"  {drive} formatted as FAT32", "ok")

            # ── 2. Create EFI structure ───────────────────────────────────────
            ui(8, "Creating EFI structure...")
            efi_root  = Path(f"{drive}\\EFI")
            oc_dir    = efi_root / "OC"
            boot_dir  = efi_root / "BOOT"
            kext_dir  = oc_dir / "Kexts"
            acpi_dir  = oc_dir / "ACPI"
            driver_dir= oc_dir / "Drivers"
            for d in [efi_root, oc_dir, boot_dir, kext_dir, acpi_dir, driver_dir]:
                d.mkdir(parents=True, exist_ok=True)
            log("  EFI structure created", "ok")

            # ── 3. Download macOS recovery ────────────────────────────────────
            ui(10, f"Downloading {version.name} from Apple...")
            log(f"── Fetching {version.name} from Apple CDN...", "header")
            recovery_dest = tmp / "recovery"
            self.app.call_from_thread(self._cmd_log, [
                "python", "macrecovery.py",
                "-b", version.board_id, "-m", version.mlb,
                *(version.os_flag.split() if version.os_flag else []),
                "download", "--outdir", str(recovery_dest),
            ])

            def recovery_progress(msg):
                self.app.call_from_thread(self._log, f"  {msg}", "info")
                self.app.call_from_thread(self._cmd_out, msg)

            ok_dl, msg_dl = download_recovery(version, recovery_dest, progress_cb=recovery_progress)
            if not ok_dl:
                raise RuntimeError(f"Recovery download failed: {msg_dl}")
            log(msg_dl, "ok")

            ui(28, "Copying recovery to USB...")
            log("── Copying recovery to USB...", "header")
            com_apple = Path(f"{drive}\\com.apple.recovery.boot")
            if com_apple.exists():
                shutil.rmtree(str(com_apple))
            com_apple.mkdir(parents=True)
            for src in recovery_dest.iterdir():
                mb = src.stat().st_size // 1024 // 1024
                log(f"  Writing {src.name} ({mb} MB)...", "info")
                shutil.copy2(str(src), str(com_apple / src.name))
                log(f"  {src.name} written", "ok")

            # ── 4. Generate SMBIOS ────────────────────────────────────────────
            ui(35, "Generating SMBIOS...")
            log("── Generating SMBIOS...", "header")
            smbios = gen_smbios(profile)
            log(f"  Model:  {smbios.model}", "ok")
            log(f"  Serial: {smbios.serial}", "ok")
            log(f"  MLB:    {smbios.board_serial}", "ok")
            log(f"  UUID:   {smbios.system_uuid}", "ok")

            # ── 5. Generate config.plist ──────────────────────────────────────
            ui(40, "Generating config.plist...")
            log("── Generating config.plist...", "header")
            config = gen_config(profile, smbios)
            config_path = oc_dir / "config.plist"
            write_plist(config, config_path)
            log(f"  config.plist written ({config_path.stat().st_size} bytes)", "ok")

            # ── 6. Download kexts ─────────────────────────────────────────────
            ui(45, "Selecting kexts...")
            log("── Selecting kexts...", "header")
            from kexts import select_kexts, download_kexts
            kexts = select_kexts(profile)
            log(f"  {len(kexts)} kexts selected", "ok")

            ui(50, f"Downloading {len(kexts)} kexts...")
            log("── Downloading kexts from GitHub...", "header")

            def kext_progress(i, n, msg):
                pct = 50 + int((i / n) * 30)
                self.app.call_from_thread(self._status, pct, msg)
                self.app.call_from_thread(self._log, f"  [{i+1}/{n}] {msg}", "info")

            results = download_kexts(kexts, kext_dir, progress_cb=kext_progress)
            ok_count = sum(1 for v in results.values() if v.startswith("OK"))
            log(f"  {ok_count} kexts downloaded successfully", "ok")
            for name, result in results.items():
                if result.startswith("ERROR"):
                    log(f"  WARN: {name} — {result}", "warn")

            # ── 7. Download OpenCore ──────────────────────────────────────────
            ui(82, "Downloading OpenCore...")
            log("── Downloading OpenCore...", "header")
            oc_url = "https://api.github.com/repos/acidanthera/OpenCorePkg/releases/latest"
            req = urllib.request.Request(oc_url, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                oc_data = json.loads(r.read())

            oc_asset = None
            for asset in oc_data.get("assets", []):
                n = asset["name"].lower()
                if "opencore-" in n and "release" in n and n.endswith(".zip"):
                    oc_asset = asset
                    break

            if oc_asset:
                oc_zip = tmp / oc_asset["name"]
                urllib.request.urlretrieve(oc_asset["browser_download_url"], str(oc_zip))
                log(f"  Downloaded {oc_asset['name']}", "ok")
                oc_extract = tmp / "oc_extracted"
                with zipfile.ZipFile(str(oc_zip)) as z:
                    z.extractall(str(oc_extract))

                for fname, dest in [
                    ("BOOTx64.efi", boot_dir / "BOOTx64.efi"),
                    ("OpenCore.efi", oc_dir / "OpenCore.efi"),
                ]:
                    found = list(oc_extract.rglob(fname))
                    if found:
                        shutil.copy(str(found[0]), str(dest))
                        log(f"  {fname} copied", "ok")

                for driver in ["OpenRuntime.efi", "HfsPlus.efi", "ResetNvramEntry.efi"]:
                    found = list(oc_extract.rglob(driver))
                    if found:
                        shutil.copy(str(found[0]), str(driver_dir / driver))
                        log(f"  Driver: {driver}", "ok")

                hfsplus_dest = driver_dir / "HfsPlus.efi"
                if not hfsplus_dest.exists():
                    log("  Fetching HfsPlus.efi from OcBinaryData...", "info")
                    hfsplus_url = "https://raw.githubusercontent.com/acidanthera/OcBinaryData/master/Drivers/HfsPlus.efi"
                    req2 = urllib.request.Request(hfsplus_url, headers={"User-Agent": "HackMate/1.0"})
                    with urllib.request.urlopen(req2, timeout=15) as r:
                        hfsplus_dest.write_bytes(r.read())
                    log("  HfsPlus.efi downloaded", "ok")

            # ── 8. SSDTs ─────────────────────────────────────────────────────
            ui(90, "Generating SSDTs...")
            log("── Generating SSDTs...", "header")
            kexts_list = select_kexts(profile)
            ssdts = _required_ssdts(profile, kexts_list)
            log(f"  Need: {', '.join(ssdts)}", "info")

            from ssdt import generate as gen_ssdts
            ssdt_results = gen_ssdts(
                needed=ssdts,
                acpi_dir=acpi_dir,
                tmp=tmp,
                progress_cb=lambda m: self.app.call_from_thread(self._log, f"  {m}", "info"),
            )
            for n, s in ssdt_results.items():
                if s == "OK":
                    log(f"  {n}.aml", "ok")
                elif s.startswith("SKIP"):
                    log(f"  {n} — manual install needed", "warn")
                else:
                    log(f"  {n} — {s}", "error")

            manual = [n for n, s in ssdt_results.items() if not s.startswith("OK")]
            if manual:
                note = acpi_dir / "README_MANUAL_SSDTS.txt"
                note.write_text(
                    "These SSDTs need manual installation:\n\n" +
                    "\n".join(f"  - {n}.aml" for n in manual) +
                    "\n\nDownload from: https://dortania.github.io/Getting-Started-With-ACPI/\n"
                )

            # ── Cleanup ───────────────────────────────────────────────────────
            shutil.rmtree(str(tmp), ignore_errors=True)

            ui(100, f"Done! {version.name} EFI ready on {drive}")
            log("", "info")
            log("══════════════════════════════════════════════════", "header")
            log("  USB is ready!", "ok")
            if manual:
                log("  ! Some SSDTs need manual install (see README_MANUAL_SSDTS.txt)", "warn")
            log("  1. Boot from the USB to install macOS", "info")
            log("  2. After install: run USBToolBox to map USB ports", "info")
            log("══════════════════════════════════════════════════", "header")

        except Exception as e:
            ui(0, f"Error: {e}")
            log(f"FATAL: {e}", "error")
            import traceback
            log(traceback.format_exc(), "error")
            shutil.rmtree(str(tmp), ignore_errors=True)


# ─── App ──────────────────────────────────────────────────────────────────────

class HackMate(App):
    CSS = CSS
    TITLE = "HackMate — OpenCore EFI Builder"
    BINDINGS = [("q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.profile = None
        self.macos_version = None
        self.push_screen(WelcomeScreen())


if __name__ == "__main__":
    HackMate().run()
