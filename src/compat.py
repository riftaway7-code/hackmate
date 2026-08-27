"""
Platform abstraction layer for HackMate.
Handles OS detection and provides platform-specific implementations
for things like DMI queries, DSDT dumping, admin checks, etc.
"""

import sys
import os
import subprocess
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"
IS_MACOS  = sys.platform == "darwin"
IS_LINUX  = not IS_WINDOWS and not IS_MACOS


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _get_sudo_hint() -> str:
    """Generate the correct sudo command based on how Python is invoked."""
    python = sys.executable
    # Check if running from a venv
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    if in_venv:
        return f"sudo {python} {' '.join(sys.argv)}"
    return f"sudo python3 {' '.join(sys.argv)}"


def require_admin():
    if not is_admin():
        if IS_WINDOWS:
            print("HackMate requires administrator privileges.")
            print("Right-click and select 'Run as administrator'.")
            input("Press Enter to exit...")
        else:
            hint = _get_sudo_hint()
            print("HackMate requires root privileges.")
            print(f"Run with: {hint}")
        sys.exit(1)


def _run(cmd: list) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        if IS_WINDOWS:
            return r.stdout.decode("oem", errors="replace").strip()
        return r.stdout.decode(errors="replace").strip()
    except Exception:
        return ""


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    """Fetch a URL with the SSL fallback chain every download in HackMate
    needs on Windows: the default context first, then certifi's CA bundle
    (frozen EXEs often can't reach the system root store — the single
    biggest cause of failed builds in hwdb reports, as
    CERTIFICATE_VERIFY_FAILED), and only then unverified as a last resort
    (downloads are integrity-checked against GitHub's reported asset size
    by the callers that matter). Raises on final failure."""
    import ssl
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers=headers or {"User-Agent": "HackMate/1.0"})

    contexts = [ssl.create_default_context()]
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    contexts.append(unverified)

    last_err = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (ssl.SSLError, urllib.error.URLError) as e:
            last_err = e
    raise last_err


def is_valid_pe_binary(data: bytes, min_size: int = 50 * 1024) -> bool:
    return len(data) >= min_size and data[:2] == b"MZ"


def real_home() -> Path:
    """The invoking user's home, not root's — HackMate runs under sudo on
    Linux, where Path.home() points at /root and caches/consent written
    there are invisible to the actual user next run."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and not IS_WINDOWS:
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except Exception:
            pass
    return Path.home()


def dmi_vendor() -> str:
    if IS_WINDOWS:
        return _run(["powershell", "-NoProfile", "-Command",
                     "(Get-WmiObject Win32_ComputerSystem).Manufacturer"]).lower()
    if IS_MACOS:
        return _run(["sysctl", "-n", "hw.model"]).lower()
    try:
        return Path("/sys/class/dmi/id/sys_vendor").read_text().strip().lower()
    except Exception:
        return ""


def dmi_field(field: str) -> str:
    if IS_WINDOWS:
        wmi_map = {
            "sys_vendor":   "(Get-WmiObject Win32_ComputerSystem).Manufacturer",
            "product_name": "(Get-WmiObject Win32_ComputerSystem).Model",
            "board_vendor": "(Get-WmiObject Win32_BaseBoard).Manufacturer",
            "board_name":   "(Get-WmiObject Win32_BaseBoard).Product",
        }
        cmd = wmi_map.get(field)
        return _run(["powershell", "-NoProfile", "-Command", cmd]).lower() if cmd else ""
    if IS_MACOS:
        macos_map = {
            "sys_vendor":   ["sysctl", "-n", "hw.model"],
            "product_name": ["sysctl", "-n", "hw.model"],
        }
        cmd = macos_map.get(field)
        return _run(cmd).lower() if cmd else ""
    try:
        return Path(f"/sys/class/dmi/id/{field}").read_text().strip().lower()
    except Exception:
        return ""


def cpu_core_count() -> int:
    if IS_WINDOWS:
        try:
            raw = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-WmiObject Win32_Processor | Select-Object -First 1).NumberOfCores"])
            raw = raw.strip().splitlines()[0].strip()
            return int(raw) if raw.isdigit() else 8
        except Exception:
            return 8
    if IS_MACOS:
        try:
            raw = _run(["sysctl", "-n", "hw.physicalcpu"])
            return int(raw) if raw.isdigit() else 8
        except Exception:
            return 8
    try:
        raw = _run(["nproc", "--all"])
        return int(raw) if raw.isdigit() else 8
    except Exception:
        return 8


def _get_dsdt_windows_registry(tmp: Path) -> Optional[Path]:
    """Fallback DSDT source: Windows caches the raw ACPI table Windows booted
    with under HKLM\\HARDWARE\\ACPI\\DSDT\\<vendor>\\<oem>\\<revision>\\00000000
    as a REG_BINARY value. This works on machines where GetSystemFirmwareTable
    returns nothing (seen in the field across a wide, hardware-independent
    spread of Windows builds — cause unconfirmed, but this registry path is
    populated independently by the OS at boot, not by that API)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\DSDT") as dsdt_key:
            vendor = winreg.EnumKey(dsdt_key, 0)
            with winreg.OpenKey(dsdt_key, vendor) as vendor_key:
                oem = winreg.EnumKey(vendor_key, 0)
                with winreg.OpenKey(vendor_key, oem) as oem_key:
                    revision = winreg.EnumKey(oem_key, 0)
                    with winreg.OpenKey(oem_key, revision) as rev_key:
                        data, _ = winreg.QueryValueEx(rev_key, "00000000")
                        dst = tmp / "DSDT.aml"
                        dst.write_bytes(bytes(data))
                        return dst
    except Exception:
        return None


def get_dsdt(tmp: Path) -> Optional[Path]:
    """Dump the system DSDT to tmp/DSDT.aml"""
    if IS_WINDOWS:
        try:
            import ctypes
            provider = int.from_bytes(b'ACPI', 'big')
            table_id = int.from_bytes(b'DSDT', 'big')
            k32 = ctypes.windll.kernel32
            k32.GetSystemFirmwareTable.restype = ctypes.c_uint32
            k32.GetSystemFirmwareTable.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32
            ]
            size = k32.GetSystemFirmwareTable(provider, table_id, None, 0)
            if size:
                buf = ctypes.create_string_buffer(size)
                read = k32.GetSystemFirmwareTable(provider, table_id, buf, size)
                if read:
                    dst = tmp / "DSDT.aml"
                    dst.write_bytes(bytes(buf[:read]))
                    return dst
        except Exception:
            pass
        return _get_dsdt_windows_registry(tmp)
    if IS_MACOS:
        try:
            dst = tmp / "DSDT.aml"
            # ioreg dumps ACPI tables on macOS
            raw = subprocess.run(
                ["ioreg", "-l", "-p", "IOACPIPlane", "-k", "DSDT"],
                capture_output=True, timeout=10
            ).stdout
            # Find DSDT bytes in ioreg output
            import re
            m = re.search(rb'"DSDT"\s*=\s*<([0-9a-f\s]+)>', raw, re.IGNORECASE)
            if m:
                hex_data = m.group(1).replace(b' ', b'')
                dst.write_bytes(bytes.fromhex(hex_data.decode()))
                return dst
        except Exception:
            pass
        return None
    src = Path("/sys/firmware/acpi/tables/DSDT")
    if not src.exists():
        return None
    import shutil
    dst = tmp / "DSDT.aml"
    shutil.copy2(str(src), str(dst))
    return dst


def find_iasl(ssdttime_dir: Path) -> Optional[Path]:
    """
    Find the iasl compiler in SSDTTime's Scripts dir.

    SSDTTime downloads the compiler as `iasl-stable` (plus an `iasl-legacy`
    fallback for older ACPI), not as a bare `iasl`, so look for every name it
    can land under. Preference order is newest-first.
    """
    scripts = ssdttime_dir / "Scripts"
    if IS_WINDOWS:
        names = ("iasl.exe", "iasl-stable.exe", "iasl-legacy.exe")
    else:
        names = ("iasl-stable", "iasl", "iasl-legacy")
    for name in names:
        candidate = scripts / name
        if candidate.exists():
            return candidate
    return None


def chmod_iasl(ssdttime_dir: Path):
    """Make iasl executable (no-op on Windows)"""
    if IS_WINDOWS:
        return
    for iasl in (ssdttime_dir / "Scripts").rglob("iasl*"):
        iasl.chmod(iasl.stat().st_mode | 0o111)


def detect_touchpad_type() -> str:
    """Returns 'ps2', 'i2c', or 'none'"""
    if IS_WINDOWS:
        try:
            # PNP0C50 / ACPI0C50 is the ACPI hardware ID every I2C-HID touchpad
            # exposes, whatever its FriendlyName ("I2C HID Device", "HID-compliant
            # touch pad", an OEM string, …). Matching the HID beats matching the
            # name — generic-named precision touchpads were slipping through and
            # getting PS/2 kexts + no SSDT-GPI0.
            i2c_hit = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "if (Get-PnpDevice -PresentOnly | Where-Object { "
                 "($_.HardwareID -join ' ') -match 'PNP0C50|ACPI0C50' -or "
                 "$_.InstanceId -match 'PNP0C50|ACPI0C50' }) { 'i2c' }"],
                capture_output=True, text=True, timeout=8
            ).stdout.strip().lower()
            if "i2c" in i2c_hit:
                return "i2c"

            raw = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PnpDevice | Where-Object {$_.Class -eq 'HIDClass' -or $_.Class -eq 'Mouse'} | Select-Object -ExpandProperty FriendlyName"],
                capture_output=True, text=True, timeout=8
            ).stdout.lower()
            if "i2c hid" in raw or "i2c-hid" in raw:
                return "i2c"
            if "ps/2" in raw or "synaptics" in raw or "alps" in raw or "elantech" in raw:
                return "ps2"
            return "none"
        except Exception:
            return "ps2"
    if IS_MACOS:
        # Best effort — only meaningful when the build host is the target Mac.
        try:
            io = subprocess.run(
                ["ioreg", "-l"], capture_output=True, text=True, timeout=10
            ).stdout.lower()
        except Exception:
            io = ""
        if any(k in io for k in ("voodooi2c", "applehsspihiddriver", "pnp0c50", "acpi0c50", "i2c-hid")):
            return "i2c"
        if any(k in io for k in ("applespi", "voodoops2", "ps2", "atkbd")):
            return "ps2"
        return "ps2"
    # Linux: check dmesg for I2C HID devices
    try:
        dmesg = subprocess.run(
            ["dmesg"], capture_output=True, text=True, timeout=5
        ).stdout.lower()
        if "i2c-hid" in dmesg or "i2c_hid" in dmesg or "i2c hid" in dmesg:
            return "i2c"
    except Exception:
        pass
    # Check /proc/bus/input/devices for I2C
    try:
        inputs = Path("/proc/bus/input/devices").read_text().lower()
        if "i2c" in inputs:
            return "i2c"
    except Exception:
        pass
    return "ps2"


def get_usb_drives() -> list[tuple[str, str, str]]:
    """Return list of (device, size, label) for USB drives."""
    if IS_WINDOWS:
        return _get_usb_drives_windows()
    if IS_MACOS:
        return _get_usb_drives_macos()
    return _get_usb_drives_linux()


def _get_usb_drives_linux() -> list[tuple[str, str, str]]:
    import json
    try:
        result = subprocess.run(
            ["lsblk", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL,TRAN", "-J", "-p"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
    except Exception:
        return []
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


def _get_usb_drives_macos() -> list[tuple[str, str, str]]:
    import plistlib
    try:
        raw = subprocess.run(
            ["diskutil", "list", "-plist", "external"],
            capture_output=True, timeout=10
        ).stdout
        data = plistlib.loads(raw)
        drives = []
        for disk in data.get("WholeDisks", []):
            info_raw = subprocess.run(
                ["diskutil", "info", "-plist", disk],
                capture_output=True, timeout=5
            ).stdout
            info = plistlib.loads(info_raw)
            size_bytes = info.get("TotalSize", 0)
            size_gb = f"{size_bytes // 1024 // 1024 // 1024}GB" if size_bytes else "?"
            label = info.get("VolumeName") or info.get("MediaName") or ""
            drives.append((f"/dev/{disk}", size_gb, label))
        return drives
    except Exception:
        return []


def _get_usb_drives_windows() -> list[tuple[str, str, str]]:
    import json
    import string
    drives = []
    try:
        out_disk = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Disk | Where-Object {$_.BusType -eq 'USB'} | Select-Object Number, Size | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if not out_disk:
            return drives
        disks = json.loads(out_disk)
        if isinstance(disks, dict):
            disks = [disks]
        usb_disk_numbers = {str(d.get("Number", "")): d.get("Size", 0) for d in disks}

        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Partition | Where-Object { -not $_.DriveLetter -and $_.DiskNumber -in @(" +
             ",".join(usb_disk_numbers.keys()) + ") } | Add-PartitionAccessPath -AssignDriveLetter -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=10
        )

        out_part = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Partition | Where-Object {$_.DriveLetter} | Select-Object DiskNumber, DriveLetter | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if not out_part:
            return drives
        parts = json.loads(out_part)
        if isinstance(parts, dict):
            parts = [parts]

        out_vol = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Volume | Where-Object {$_.DriveLetter} | Select-Object DriveLetter, FileSystemLabel, Size | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        vol_map = {}
        if out_vol:
            vols = json.loads(out_vol)
            if isinstance(vols, dict):
                vols = [vols]
            for v in vols:
                letter = str(v.get("DriveLetter") or "").strip()
                if letter:
                    vol_map[letter] = (v.get("FileSystemLabel") or "", v.get("Size") or 0)

        seen = set()
        disks_with_letter = set()
        for p in parts:
            disk_num = str(p.get("DiskNumber", ""))
            letter = str(p.get("DriveLetter") or "").strip()
            if disk_num in usb_disk_numbers and letter and letter not in seen:
                seen.add(letter)
                disks_with_letter.add(disk_num)
                label, size_bytes = vol_map.get(letter, ("", usb_disk_numbers[disk_num]))
                size_gb = f"{int(size_bytes) // 1024 // 1024 // 1024}GB" if size_bytes else "?"
                drives.append((f"{letter}:", size_gb, label or ""))

        # USB disks with no partition at all (blank/unpartitioned) or where
        # Windows refused to auto-assign a letter never show up above —
        # they'd otherwise silently vanish even though Get-Disk found them.
        for disk_num, size_bytes in usb_disk_numbers.items():
            if disk_num and disk_num not in disks_with_letter:
                size_gb = f"{int(size_bytes) // 1024 // 1024 // 1024}GB" if size_bytes else "?"
                drives.append((f"RAWDISK{disk_num}", size_gb, "(raw / not yet formatted)"))
    except Exception:
        pass
    return drives


def format_usb(device: str, mount_point: str) -> bool:
    """Format USB as FAT32 with GPT+ESP. Returns True on success."""
    if IS_WINDOWS:
        return _format_usb_windows(device, mount_point)
    if IS_MACOS:
        return _format_usb_macos(device)
    return _format_usb_linux(device, mount_point)


def _run_checked(cmd: list[str]) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"'{cmd[0]}' isn't installed. Install it with your distro's package "
            f"manager (e.g. `sudo apt install parted dosfstools` on Debian/Ubuntu) "
            f"and try again."
        )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise RuntimeError(f"{' '.join(cmd)} failed: {stderr}")


def _format_usb_linux(device: str, mount_point: str) -> bool:
    import re
    import time
    disk = re.sub(r'p?\d+$', '', device) if re.search(r'\d$', device) else device
    part_device = (disk + "p1") if disk[-1].isdigit() else (disk + "1")

    if not Path(disk).exists():
        raise RuntimeError(
            f"{disk} is no longer present — the USB drive may have been unplugged or "
            f"reassigned to a different device path. Reconnect it and try again."
        )

    import glob

    def _unmount_all(pattern: str) -> None:
        for part in sorted(glob.glob(pattern)):
            result = subprocess.run(["umount", part], capture_output=True)
            if result.returncode != 0:
                subprocess.run(["umount", "-l", part], capture_output=True)

    last_err = None
    for attempt in range(3):
        try:
            _unmount_all(f"{disk}*")
            _run_checked(["parted", "-s", disk, "mklabel", "gpt"])
            _run_checked(["parted", "-s", disk, "mkpart", "primary", "fat32", "1MiB", "100%"])
            subprocess.run(["parted", "-s", disk, "set", "1", "esp", "on"], capture_output=True)
            subprocess.run(["partprobe", disk], capture_output=True)
            time.sleep(1)

            _unmount_all(part_device)
            _run_checked(["mkfs.fat", "-F32", "-n", "HACKINTOSH", part_device])
            last_err = None
            break
        except RuntimeError as e:
            last_err = e
            if "isn't installed" in str(e):
                break
            time.sleep(2)
    if last_err:
        is_mount_race = any(s in str(last_err).lower() for s in
                             ("mounted", "busy", "being used", "no volume"))
        if is_mount_race:
            raise RuntimeError(
                f"{last_err}\n\nThe USB kept getting remounted automatically after 3 attempts — "
                f"your desktop environment's automounter may be racing HackMate. Try unmounting "
                f"the drive in your file manager first, then retry."
            )
        raise RuntimeError(str(last_err))

    subprocess.run(["sync"], capture_output=True)
    time.sleep(1)

    Path(mount_point).mkdir(parents=True, exist_ok=True)
    try:
        _run_checked(["mount", part_device, mount_point])
    except RuntimeError:
        time.sleep(2)
        _run_checked(["mount", part_device, mount_point])
    return True


def _format_usb_macos(device: str) -> bool:
    # diskutil handles GPT+ESP automatically with FAT32
    disk = device.replace("/dev/", "")
    result = subprocess.run(
        ["diskutil", "eraseDisk", "FAT32", "HACKINTOSH", "GPT", disk],
        capture_output=True, timeout=60
    )
    return result.returncode == 0


def _format_usb_windows(drive_letter: str, mount_letter: str = "Z") -> bool:
    import tempfile
    letter = drive_letter.rstrip(':\\')
    target_letter = mount_letter.rstrip(':\\')

    if letter.upper().startswith("RAWDISK"):
        # Picked from the USB list as a blank/unpartitioned disk — we already
        # know its disk number, no drive letter to resolve it from at all.
        disk_num_raw = letter[7:]
    else:
        # diskpart needs disk number, not drive letter — resolve it via PowerShell
        disk_num_raw = _run([
            "powershell", "-NoProfile", "-Command",
            f"(Get-Partition -DriveLetter {letter} | Get-Disk).Number"
        ]).strip()

        # Fallback: USB may be RAW (no partition table) — try via Get-Volume
        if not disk_num_raw.isdigit():
            disk_num_raw = _run([
                "powershell", "-NoProfile", "-Command",
                f"(Get-Volume -DriveLetter {letter} -ErrorAction SilentlyContinue | Get-Partition -ErrorAction SilentlyContinue | Get-Disk).Number"
            ]).strip()

        if not disk_num_raw.isdigit():
            usb_disks = _run([
                "powershell", "-NoProfile", "-Command",
                "(Get-Disk | Where-Object {$_.BusType -eq 'USB'}).Number"
            ]).split()
            if len(usb_disks) == 1 and usb_disks[0].isdigit():
                disk_num_raw = usb_disks[0]

    if not disk_num_raw.isdigit():
        raise RuntimeError(
            f"Could not resolve disk number for drive {letter}: — the USB may be RAW with no drive letter. "
            f"Open Disk Management, format the USB as FAT32, then use the 'Already Formatted' button."
        )

    already_used = _run([
        "powershell", "-NoProfile", "-Command",
        f"Test-Path {target_letter}:\\"
    ]).strip().lower()
    if already_used == "true":
        raise RuntimeError(
            f"Drive letter {target_letter}: is already in use by another drive on this "
            f"system (network share, another disk, etc). Free it up — disconnect or "
            f"unmap whatever's using {target_letter}: — then try again."
        )

    # Drives sold as "4GB"+ often report under 4096 MiB to Windows (decimal
    # vs binary GB, plus reserved sectors), so a fixed size=4096 request
    # fails outright on them with diskpart's generic "specified size and
    # offset" error — cap to whatever the disk actually has.
    disk_size_mb_raw = _run([
        "powershell", "-NoProfile", "-Command",
        f"[math]::Floor((Get-Disk -Number {disk_num_raw}).Size / 1MB)"
    ]).strip()
    partition_size_mb = 4096
    if disk_size_mb_raw.isdigit():
        partition_size_mb = min(4096, max(1, int(disk_size_mb_raw) - 8))

    create_script = (
        f"select disk {disk_num_raw}\n"
        "clean\n"
        f"create partition primary size={partition_size_mb}\n"
        "exit\n"
    )
    format_script = (
        f"select disk {disk_num_raw}\n"
        "select partition 1\n"
        "format fs=fat32 quick label=HACKINTOSH\n"
        f"assign letter={target_letter}\n"
        "exit\n"
    )

    def _run_diskpart(script_text: str) -> tuple[int, str]:
        p = Path(tempfile.mktemp(suffix=".txt"))
        p.write_text(script_text)
        try:
            r = subprocess.run(["diskpart", "/s", str(p)], capture_output=True, timeout=120)
            out = (r.stdout.decode("oem", errors="replace") +
                   r.stderr.decode("oem", errors="replace"))
            return r.returncode, out.strip()[-400:]
        finally:
            p.unlink(missing_ok=True)

    import time as _time
    last_detail = ""
    for attempt in range(3):
        code, detail = _run_diskpart(create_script)
        if code != 0:
            last_detail = detail
            if attempt < 2:
                _time.sleep(3)
            continue
        _time.sleep(2)  # let Windows map the new partition to a volume before formatting it
        code, detail = _run_diskpart(format_script)
        if code == 0:
            last_detail = ""
            break
        last_detail = detail
        if attempt < 2:
            _time.sleep(3)
    else:
        raise RuntimeError(f"diskpart failed after 3 attempts:\n{last_detail}")

    mounted = _run([
        "powershell", "-NoProfile", "-Command",
        f"Test-Path {target_letter}:\\"
    ]).strip().lower()
    if mounted != "true":
        raise RuntimeError(
            f"USB formatted but {target_letter}: never became accessible afterward. "
            f"Try unplugging and reconnecting the USB, then use 'Already Formatted'."
        )
    return True


def mount_usb(device: str, mount_point: str) -> bool:
    """Mount USB partition."""
    if IS_WINDOWS:
        return True  # Windows auto-mounts after format
    if IS_MACOS:
        # macOS auto-mounts to /Volumes/HACKINTOSH after format
        return True
    import re
    import glob
    disk = re.sub(r'p?\d+$', '', device) if re.search(r'\d$', device) else device
    part_device = (disk + "p1") if disk[-1].isdigit() else (disk + "1")
    for part in sorted(glob.glob(f"{disk}*")):
        subprocess.run(["umount", part], capture_output=True)
    Path(mount_point).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["mount", part_device, mount_point], capture_output=True)
    return result.returncode == 0


def unmount_usb(mount_point: str) -> bool:
    """Unmount the USB drive."""
    if IS_WINDOWS:
        return True
    if IS_MACOS:
        try:
            subprocess.run(["diskutil", "unmount", mount_point], capture_output=True, timeout=10)
        except Exception:
            pass
        return True
    # Linux — flush write buffers first so umount doesn't stall
    try:
        subprocess.run(["sync"], capture_output=True, timeout=30)
    except Exception:
        pass
    try:
        result = subprocess.run(["umount", mount_point], capture_output=True, timeout=15)
        if result.returncode != 0:
            subprocess.run(["umount", "-l", mount_point], capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        try:
            subprocess.run(["umount", "-l", mount_point], capture_output=True, timeout=5)
        except Exception:
            pass
    return True


def _find_free_drive_letter() -> str:
    """Which drive letters are already taken varies per machine — Z: is
    frequently claimed by a VPN network share, a mapped drive, or a second
    disk. Hardcoding Z: as the target meant anyone with something already
    on it had to manually go free it up before HackMate could even start
    (seen repeatedly in the wild: 'Drive letter Z: is already in use').
    Scan for a letter that's actually free instead."""
    used_raw = _run([
        "powershell", "-NoProfile", "-Command",
        "[System.IO.DriveInfo]::GetDrives() | ForEach-Object { $_.Name.Substring(0,1).ToUpper() }"
    ])
    used = set(used_raw.split())
    for letter in "ZYXWVUTSRQPONMLKJIHGFED":
        if letter not in used:
            return f"{letter}:"
    raise RuntimeError("No free drive letters available — free one up and try again.")


def get_mount_path(device: str = "", skip_format: bool = False) -> str:
    """Get the mount path for the USB drive."""
    if IS_WINDOWS:
        if skip_format and device:
            if device.upper().startswith("RAWDISK"):
                raise RuntimeError(
                    "This USB has no filesystem yet (it showed up blank/unpartitioned) — "
                    "'Already Formatted' doesn't apply to it. Use 'Full Build' instead so "
                    "HackMate partitions and formats it for you."
                )
            letter = device.strip(":\\/").upper()
            if letter and letter.isalpha():
                if not os.path.exists(f"{letter}:\\"):
                    raise RuntimeError(
                        f"{letter}: isn't accessible — the drive may be RAW (no filesystem) "
                        f"rather than already formatted. Open Disk Management and format it as "
                        f"FAT32 first, or use 'Full Build' instead so HackMate formats it for you."
                    )
                return f"{letter}:"
        return _find_free_drive_letter()
    if IS_MACOS:
        return "/Volumes/HACKINTOSH"
    return "/tmp/hackmate_usb"


def get_tmp_dir() -> str:
    """Get temp directory for building."""
    if IS_WINDOWS:
        import tempfile
        return tempfile.mkdtemp(prefix="hackmate_")
    return "/tmp/hackmate_build"


def has_card_reader() -> bool:
    if IS_WINDOWS:
        try:
            raw = _run(["powershell", "-NoProfile", "-Command",
                        "Get-PnpDevice | Where-Object {$_.Class -eq 'SDHost'} | Select-Object -ExpandProperty FriendlyName"])
            return bool(raw)
        except Exception:
            return False
    if IS_MACOS:
        sp = _run(["system_profiler", "SPUSBDataType"]).lower()
        return "card reader" in sp or "rtsx" in sp or "rts5" in sp
    try:
        lspci = _run(["lspci"]).lower()
        return "sd host" in lspci or "card reader" in lspci or "rtsx" in lspci
    except Exception:
        return False
