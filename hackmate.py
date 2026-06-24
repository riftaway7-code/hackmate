import subprocess
import os
import sys
import shutil
import shlex
import json
from pathlib import Path

if os.geteuid() != 0:
    print("HackMate requires root. Run with: sudo python3 hackmate.py")
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


# ─── Welcome ──────────────────────────────────────────────────────────────────

class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Static(BANNER,     classes="title",    id="banner"),
                Static("Automated OpenCore EFI builder — any hardware", classes="info", id="subtitle"),
                Static(""),
                Button("Build EFI", id="start",  classes="primary"),
                Button("Quit",      id="quit",   classes="danger"),
                id="welcome-inner"
            ),
            id="welcome"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.app.push_screen(ScanScreen())
        elif event.button.id == "quit":
            self.app.exit()


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
        kexts = select_kexts(profile)
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
        versions = compatible_versions(profile.cpu_generation, profile.gpu_vendor)
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

def get_usb_drives() -> list[tuple[str, str, str]]:
    result = subprocess.run(
        ["lsblk", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL,TRAN", "-J", "-p"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    drives = []
    for dev in data.get("blockdevices", []):
        if dev.get("tran") != "usb":
            continue
        children = dev.get("children", [])
        if children:
            for child in children:
                size = dev.get("size", "?")
                label = child.get("label") or child.get("fstype") or "No Label"
                drives.append((child["name"], size, label))
        else:
            drives.append((dev["name"], dev.get("size", "?"), "No partition"))
    return drives


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
                self.app.push_screen(InstallScreen(selected))
        elif event.button.id == "back":
            self.app.pop_screen()


# ─── Install ──────────────────────────────────────────────────────────────────

class InstallScreen(Screen):
    def __init__(self, device: str):
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(classes="screen-inner"):
            with Vertical():
                yield Static(f"── Building EFI → {self.device} ───────────────────────", classes="title")
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
            self.query_one("#cmd-log", RichLog).write(
                f"[dim]hackmate@root[/dim][#00ff88]$[/#00ff88] [white]{cmd_str}[/white]"
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
        tmp = Path("/tmp/hackmate_build")
        mount = Path("/tmp/hackmate_usb")

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

        try:
            # ── 1. Format USB ────────────────────────────────────────────────
            ui(2, "Formatting USB as FAT32...")
            log(f"Unmounting {device}...", "info")
            cmd(["umount", device], capture_output=True)
            cmd(["mkfs.fat", "-F32", "-n", "HACKINTOSH", device],
                check=True, capture_output=True)
            log("Formatted as FAT32.", "ok")

            # ── 2. Mount USB ─────────────────────────────────────────────────
            ui(5, "Mounting USB...")
            mount.mkdir(parents=True, exist_ok=True)
            cmd(["mount", device, str(mount)], check=True, capture_output=True)
            log(f"Mounted at {mount}", "ok")

            # ── 3. Create EFI structure ───────────────────────────────────────
            ui(8, "Creating EFI structure...")
            efi       = mount / "EFI"
            oc_dir    = efi / "OC"
            boot_dir  = efi / "BOOT"
            kext_dir  = oc_dir / "Kexts"
            acpi_dir  = oc_dir / "ACPI"
            driver_dir= oc_dir / "Drivers"
            for d in [efi, oc_dir, boot_dir, kext_dir, acpi_dir, driver_dir]:
                d.mkdir(parents=True, exist_ok=True)
            log("EFI folder structure created.", "ok")

            # ── 4. Download macOS recovery ────────────────────────────────────
            ui(10, f"Downloading {version.name} recovery from Apple...")
            log(f"── Fetching {version.name} from Apple CDN...", "header")
            recovery_dest = tmp / "recovery"
            self.app.call_from_thread(self._cmd_log, [
                "python3", "macrecovery.py",
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
            com_apple = mount / "com.apple.recovery.boot"
            if com_apple.exists():
                shutil.rmtree(str(com_apple))
            com_apple.mkdir(parents=True)
            for i, src in enumerate(files, 1):
                mb = src.stat().st_size // 1024 // 1024
                log(f"  Writing {src.name} ({mb} MB)...", "info")
                shutil.copy2(str(src), str(com_apple / src.name))
                log(f"  {src.name} written", "ok")
            log("Recovery copied to USB.", "ok")

            # ── 5. Generate SMBIOS ────────────────────────────────────────────
            ui(35, "Generating SMBIOS...")
            log("── Generating SMBIOS...", "header")
            from smbios import generate as gen_smbios
            smbios = gen_smbios(profile)
            log(f"  Model:   {smbios.model}", "ok")
            log(f"  Serial:  {smbios.serial}", "ok")
            log(f"  MLB:     {smbios.board_serial}", "ok")
            log(f"  UUID:    {smbios.system_uuid}", "ok")

            # ── 6. Generate config.plist ──────────────────────────────────────
            ui(40, "Generating config.plist...")
            log("── Generating config.plist...", "header")
            from config_gen import generate as gen_config, write_plist, _required_ssdts
            config = gen_config(profile, smbios)
            config_path = oc_dir / "config.plist"
            write_plist(config, config_path)
            log(f"  config.plist written ({config_path.stat().st_size} bytes)", "ok")

            # ── 7. Download kexts ─────────────────────────────────────────────
            ui(45, "Selecting kexts...")
            log("── Selecting kexts...", "header")
            from kexts import select_kexts, download_kexts
            kexts = select_kexts(profile)
            log(f"  {len(kexts)} kexts selected for this hardware", "ok")

            ui(50, f"Downloading {len(kexts)} kexts from GitHub...")
            log("── Downloading kexts from GitHub...", "header")

            def kext_progress(i, n, msg):
                pct = 50 + int((i / n) * 30)
                self.app.call_from_thread(self._status, pct, msg)
                self.app.call_from_thread(self._log, f"  [{i+1}/{n}] {msg}", "info")

            results = download_kexts(kexts, kext_dir, progress_cb=kext_progress)
            ok_count  = sum(1 for v in results.values() if v.startswith("OK"))
            err_count = sum(1 for v in results.values() if v.startswith("ERROR"))
            log(f"  {ok_count} kexts downloaded successfully", "ok")
            for name, result in results.items():
                if result.startswith("ERROR"):
                    log(f"  WARN: {name} — {result}", "warn")

            # ── 8. Download OpenCore ──────────────────────────────────────────
            ui(82, "Downloading OpenCore...")
            log("── Downloading OpenCore...", "header")
            oc_url = "https://api.github.com/repos/acidanthera/OpenCorePkg/releases/latest"
            import urllib.request
            req = urllib.request.Request(oc_url, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                oc_data = __import__("json").loads(r.read())

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

                import zipfile
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

                # HfsPlus.efi is not in the OC zip — download from OcBinaryData
                hfsplus_dest = driver_dir / "HfsPlus.efi"
                if not hfsplus_dest.exists():
                    log("  HfsPlus.efi not in OC zip — fetching from OcBinaryData...", "info")
                    self.app.call_from_thread(self._cmd_log, ["wget", "OcBinaryData/Drivers/HfsPlus.efi"])
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

            # ── 9. SSDTs via SSDTTime ─────────────────────────────────────────
            ui(90, "Generating SSDTs with SSDTTime...")
            log("── Generating SSDTs with SSDTTime...", "header")
            ssdts = _required_ssdts(profile, kexts)
            log(f"  Need: {', '.join(ssdts)}", "info")

            from ssdt import generate as gen_ssdts
            ssdt_results = gen_ssdts(
                needed=ssdts,
                acpi_dir=acpi_dir,
                tmp=tmp,
                progress_cb=lambda m: self.app.call_from_thread(self._log, f"  {m}", "info"),
            )

            ok_ssdts   = [n for n, s in ssdt_results.items() if s == "OK"]
            skip_ssdts = [n for n, s in ssdt_results.items() if s.startswith("SKIP")]
            err_ssdts  = [n for n, s in ssdt_results.items() if s.startswith("ERROR")]

            for n in ok_ssdts:
                log(f"  {n}.aml", "ok")
            for n in skip_ssdts:
                log(f"  {n} — manual install needed", "warn")
            for n in err_ssdts:
                log(f"  {n} — {ssdt_results[n]}", "error")

            # Write README for anything that couldn't be auto-generated
            manual = skip_ssdts + err_ssdts
            if manual:
                note = acpi_dir / "README_MANUAL_SSDTS.txt"
                note.write_text(
                    "These SSDTs need manual installation:\n\n" +
                    "\n".join(f"  - {n}.aml" for n in manual) +
                    "\n\nDownload prebuilt SSDTs from:\n"
                    "  https://dortania.github.io/Getting-Started-With-ACPI/\n"
                )
                log(f"  {len(manual)} SSDTs need manual install — see README_MANUAL_SSDTS.txt", "warn")

            # ── 10. Unmount ───────────────────────────────────────────────────
            ui(97, "Unmounting USB...")
            cmd(["umount", str(mount)], capture_output=True)
            shutil.rmtree(str(tmp), ignore_errors=True)

            ui(100, f"Done! {version.name} EFI ready on {device}")
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
            try:
                cmd(["umount", str(mount)], capture_output=True)
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()


# ─── App ──────────────────────────────────────────────────────────────────────

class HackMate(App):
    CSS = CSS
    TITLE = "HackMate"
    SUB_TITLE = "OpenCore EFI Builder"

    profile:      HardwareProfile | None = None
    macos_version: MacOSVersion   | None = None

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())


if __name__ == "__main__":
    HackMate().run()
