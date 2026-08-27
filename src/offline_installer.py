"""
Offline (network-free) macOS install support, built around corpnewt/UnPlugged
(https://github.com/corpnewt/UnPlugged).

HackMate's normal USB carries Apple's ~700 MB recovery image; the actual macOS
payload is still pulled from Apple after you boot it. This module stages a FULL
offline installer on a *second* USB so the install can run with no network:

  1. resolve + download the full `InstallAssistant.pkg` (~13 GB) for the chosen
     macOS version from Apple's software-update catalog (the same source
     gibMacOS uses), and
  2. drop `UnPlugged.command` (corpnewt's recovery-side installer script) and a
     short README next to it.

You then boot the OpenCore USB HackMate already built, pick the recovery entry,
open Terminal, `cd` to the second USB and run `./UnPlugged.command`.

Nothing here touches the target machine — it only prepares media.

Not integration-tested end to end (Apple can restructure the catalog; ExFAT
tooling differs per host). Treat as beta and sanity-check the staged files.
"""

import plistlib
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from compat import IS_WINDOWS, IS_MACOS

# publicrelease "others" merged catalog — covers Big Sur .. Tahoe. gibMacOS uses
# the same file; the leading version list only has to be a superset.
SUCATALOG_URL = (
    "https://swscan.apple.com/content/catalogs/others/"
    "index-26-15-14-13-12-10.16-10.15-10.14-10.13-10.12-10.11-10.10-10.9"
    "-mountainlion-lion-snowleopard-leopard.merged-1.sucatalog"
)

UNPLUGGED_URL = "https://raw.githubusercontent.com/corpnewt/UnPlugged/master/UnPlugged.command"

# InstallAssistant.pkg only exists for Big Sur (11) and newer. HackMate's
# supported install targets are Ventura+; keep the offline path to those.
SUPPORTED_MAJORS = {"13", "14", "15", "26"}

MIN_USB_BYTES = 16 * 1024 ** 3  # UnPlugged asks for 16 GB+


@dataclass
class FullInstaller:
    major: str          # "15"
    version: str        # "15.1.1"
    build: str          # "24B2091"
    title: str          # "Install macOS Sequoia"
    url: str            # …/InstallAssistant.pkg
    size: int           # bytes
    post_date: str      # ISO-ish, for picking the newest


# ---------------------------------------------------------------- SSL / download

def _contexts() -> list:
    out = [ssl.create_default_context()]
    try:
        import certifi
        out.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    unv = ssl.create_default_context()
    unv.check_hostname = False
    unv.verify_mode = ssl.CERT_NONE
    out.append(unv)
    return out


def _urlopen(url: str, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "HackMate/1.0"})
    last = None
    for ctx in _contexts():
        try:
            return urllib.request.urlopen(req, context=ctx, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (ssl.SSLError, urllib.error.URLError) as e:
            last = e
    raise last


def _http_bytes(url: str, timeout: int = 60) -> bytes:
    with _urlopen(url, timeout=timeout) as r:
        return r.read()


def download_stream(url: str, dest: Path, expected_size: int = 0, progress_cb=None) -> None:
    """Stream `url` to `dest`, resuming a partial file via a Range request.
    progress_cb(done_bytes, total_bytes) is called as it goes. Raises on failure
    or on a final size mismatch when expected_size is known."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = dest.stat().st_size if dest.exists() else 0
    if expected_size and have == expected_size:
        if progress_cb:
            progress_cb(have, expected_size)
        return
    if expected_size and have > expected_size:
        have = 0  # partial is bogus, start over
        dest.unlink(missing_ok=True)

    headers = {"User-Agent": "HackMate/1.0"}
    mode = "wb"
    if have:
        headers["Range"] = f"bytes={have}-"
        mode = "ab"

    with _urlopen(url, headers=headers, timeout=120) as r:
        if have and r.status != 206:      # server ignored the Range — restart
            have = 0
            mode = "wb"
        total = expected_size
        if not total:
            clen = r.headers.get("Content-Length")
            rng = r.headers.get("Content-Range", "")
            if "/" in rng:
                total = int(rng.rsplit("/", 1)[-1])
            elif clen:
                total = have + int(clen)
        done = have
        with open(dest, mode) as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)

    if expected_size and dest.stat().st_size != expected_size:
        raise RuntimeError(
            f"{dest.name}: got {dest.stat().st_size} bytes, expected {expected_size}"
        )


# ---------------------------------------------------------------- catalog

def _dist_field(dist: str, key: str) -> str:
    m = re.search(rf"<key>{key}</key>\s*<string>([^<]+)</string>", dist)
    return m.group(1).strip() if m else ""


def resolve_full_installer(major: str, catalog_url: str = SUCATALOG_URL) -> FullInstaller:
    """Find the newest full `InstallAssistant.pkg` for a macOS major version
    (e.g. "15") in Apple's catalog. Raises if none is found."""
    if major not in SUPPORTED_MAJORS:
        raise ValueError(
            f"offline installer supports macOS {sorted(SUPPORTED_MAJORS)} only "
            f"(InstallAssistant.pkg doesn't exist for {major})"
        )
    catalog = plistlib.loads(_http_bytes(catalog_url, timeout=90))
    candidates: list[FullInstaller] = []

    for pid, product in catalog.get("Products", {}).items():
        pkgs = product.get("Packages", [])
        ia = next(
            (p for p in pkgs if str(p.get("URL", "")).endswith("InstallAssistant.pkg")),
            None,
        )
        if not ia:
            continue
        dist_url = (product.get("Distributions", {}) or {}).get("English", "")
        if not dist_url:
            continue
        try:
            dist = _http_bytes(dist_url, timeout=30).decode("utf-8", "replace")
        except Exception:
            continue
        version = _dist_field(dist, "VERSION")
        if not version or version.split(".", 1)[0] != major:
            continue
        title = ""
        mt = re.search(r"<title>([^<]+)</title>", dist)
        if mt:
            title = mt.group(1).strip()
        candidates.append(FullInstaller(
            major=major,
            version=version,
            build=_dist_field(dist, "BUILD"),
            title=title or f"Install macOS {major}",
            url=ia["URL"],
            size=int(ia.get("Size", 0)),
            post_date=str(product.get("PostDate", "")),
        ))

    if not candidates:
        raise RuntimeError(
            f"no InstallAssistant.pkg for macOS {major} in Apple's catalog "
            f"(the catalog layout may have changed)"
        )
    candidates.sort(key=lambda c: (c.post_date, c.version), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------- UnPlugged

def fetch_unplugged(dest_dir: Path) -> Path:
    """Download UnPlugged.command into dest_dir. Returns its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "UnPlugged.command"
    out.write_bytes(_http_bytes(UNPLUGGED_URL, timeout=30))
    if not IS_WINDOWS:
        try:
            out.chmod(0o755)
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- ExFAT format

def exfat_format_commands(device: str, label: str = "INSTALLER") -> list[list[str]]:
    """The shell commands that erase `device` and lay down a single ExFAT
    volume. Split out so it can be unit-tested without touching a disk."""
    if IS_MACOS:
        return [["diskutil", "eraseDisk", "ExFAT", label, "MBR", device]]
    if IS_WINDOWS:
        # caller feeds a diskpart script to `diskpart /s`; represent it as one
        # "command" whose args are the script lines.
        return [[
            "diskpart-script",
            f"select disk {device}",
            "clean",
            "convert mbr",
            "create partition primary",
            "format fs=exfat quick label=" + label,
            "assign",
        ]]
    # Linux
    part = device + ("p1" if re.search(r"\d$", device) else "1")
    return [
        ["wipefs", "-a", device],
        ["parted", "-s", device, "mklabel", "msdos"],
        ["parted", "-s", device, "mkpart", "primary", "1MiB", "100%"],
        ["mkfs.exfat", "-n", label, part],
    ]


def format_exfat(device: str, label: str = "INSTALLER", log=None) -> None:
    """Erase `device` and create one ExFAT volume. `device` is a diskutil id
    (/dev/diskN), a Linux block device (/dev/sdX) or, on Windows, the diskpart
    disk NUMBER. Raises on failure."""
    _log = log or (lambda *_: None)
    cmds = exfat_format_commands(device, label)

    if IS_WINDOWS:
        script = "\n".join(cmds[0][1:]) + "\n"
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(script)
            spath = f.name
        try:
            r = subprocess.run(["diskpart", "/s", spath], capture_output=True,
                               text=True, timeout=180)
            if r.returncode != 0:
                raise RuntimeError(f"diskpart failed:\n{(r.stdout + r.stderr).strip()[-600:]}")
        finally:
            Path(spath).unlink(missing_ok=True)
        return

    if IS_MACOS is False and not _which("mkfs.exfat"):
        raise RuntimeError(
            "mkfs.exfat not found — install exfatprogs (Debian/Ubuntu: "
            "`sudo apt install exfatprogs`, Arch: `sudo pacman -S exfatprogs`)"
        )

    for cmd in cmds:
        _log(" ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise RuntimeError(f"{cmd[0]} failed:\n{(r.stdout + r.stderr).strip()[-600:]}")


def _which(name: str) -> str:
    from shutil import which
    return which(name) or ""


# ---------------------------------------------------------------- orchestrator

README_TEXT = """\
HackMate — offline macOS installer (UnPlugged)
=============================================

This USB holds a full macOS installer so the install can run with no network.

On the target machine:

  1. Boot the OpenCore USB HackMate built (the other one).
  2. In the OpenCore picker choose the macOS recovery / "Install macOS" entry.
  3. When the macOS Utilities window appears: Utilities -> Terminal.
  4. Run:

       cd "/Volumes/{volume}"
       ./UnPlugged.command

  5. Follow UnPlugged's prompts (pick this installer as the source, pick the
     target disk). It does NOT need internet.

Files here:
  - InstallAssistant.pkg   full macOS {version} ({build}) installer payload
  - UnPlugged.command      corpnewt's recovery-side installer script
    (https://github.com/corpnewt/UnPlugged)

Sonoma and newer: if UnPlugged can't mount the payload from recovery, boot an
older BaseSystem (Ventura) recovery entry and run it from there instead.
"""


def whole_disk(device: str) -> str:
    """Strip a partition suffix so formatting targets the disk, not a slice.
    /dev/sdb1 -> /dev/sdb ; /dev/nvme0n1p1 -> /dev/nvme0n1 ; others unchanged."""
    m = re.match(r"(/dev/(?:nvme\d+n\d+|mmcblk\d+|loop\d+))p\d+$", device)
    if m:
        return m.group(1)
    m = re.match(r"(/dev/[vsh]d[a-z]+)\d+$", device)
    if m:
        return m.group(1)
    return device


def _windows_disk_number(device: str) -> str:
    if device.upper().startswith("RAWDISK"):
        return device[7:]
    letter = device.rstrip(":\\").upper()[:1]
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Partition -DriveLetter {letter}).DiskNumber"],
        capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    if not out.isdigit():
        raise RuntimeError(f"could not resolve a disk number for {device}")
    return out


def _mount_after_format(device: str, label: str) -> Path:
    """Return a writable directory for the freshly-made ExFAT volume."""
    if IS_MACOS:
        return Path(f"/Volumes/{label}")
    if IS_WINDOWS:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Volume -FileSystemLabel {label}).DriveLetter"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        if not out:
            raise RuntimeError("ExFAT volume has no drive letter after format")
        return Path(f"{out}:\\")
    # Linux — mount the first partition ourselves
    part = whole_disk(device)
    part += "p1" if re.search(r"\d$", part) else "1"
    mp = Path("/tmp/hackmate-offline-usb")
    mp.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["mount", part, str(mp)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"mount {part} failed: {(r.stdout + r.stderr).strip()[-300:]}")
    return mp


def prepare_offline_usb(device: str, major: str, progress_cb=None, log=None) -> dict:
    """Full flow: resolve the installer, erase `device` to a single ExFAT
    volume, then stage InstallAssistant.pkg + UnPlugged.command + README onto
    it. `device` is whatever compat.get_usb_drives() returned for that USB."""
    _log = log or (lambda *_: None)
    _log(f"Resolving the newest full installer for macOS {major}…")
    installer = resolve_full_installer(major)
    _log(f"  {installer.title} {installer.version} ({installer.build}), "
         f"{installer.size / 1024**3:.1f} GB")

    fmt_target = (
        _windows_disk_number(device) if IS_WINDOWS
        else device if IS_MACOS
        else whole_disk(device)
    )
    _log(f"Erasing {device} → one ExFAT volume (INSTALLER)…")
    format_exfat(fmt_target, "INSTALLER", log=_log)

    volume = _mount_after_format(device, "INSTALLER")
    result = stage_offline_usb(volume, installer, progress_cb=progress_cb, log=_log)
    result["volume"] = str(volume)
    return result


def stage_offline_usb(volume_path: Path, installer: FullInstaller, progress_cb=None,
                      log=None) -> dict:
    """Download InstallAssistant.pkg + UnPlugged.command onto an already-mounted
    ExFAT volume and write the README. Returns a summary dict."""
    _log = log or (lambda *_: None)
    volume_path = Path(volume_path)
    if not volume_path.is_dir():
        raise RuntimeError(f"{volume_path} is not a mounted, writable volume")

    _log(f"Downloading {installer.title} {installer.version} "
         f"({installer.size / 1024**3:.1f} GB) — this is the long part")
    pkg = volume_path / "InstallAssistant.pkg"
    download_stream(installer.url, pkg, installer.size, progress_cb=progress_cb)

    _log("Fetching UnPlugged.command")
    fetch_unplugged(volume_path)

    (volume_path / "OFFLINE-INSTALL-README.txt").write_text(
        README_TEXT.format(volume=volume_path.name or "INSTALLER",
                           version=installer.version, build=installer.build)
    )
    _log("Offline installer USB is ready")
    return {
        "pkg": str(pkg),
        "size": pkg.stat().st_size,
        "version": installer.version,
        "build": installer.build,
    }
