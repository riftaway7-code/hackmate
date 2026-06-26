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
IS_LINUX = not IS_WINDOWS


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def require_admin():
    if not is_admin():
        if IS_WINDOWS:
            print("HackMate requires administrator privileges.")
            print("Right-click and select 'Run as administrator'.")
            input("Press Enter to exit...")
        else:
            print("HackMate requires root. Run with: sudo python3 hackmate.py")
        sys.exit(1)


def dmi_vendor() -> str:
    if IS_WINDOWS:
        try:
            return subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-WmiObject Win32_ComputerSystem).Manufacturer"],
                capture_output=True, text=True, timeout=8
            ).stdout.strip().lower()
        except Exception:
            return ""
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
        if not cmd:
            return ""
        try:
            return subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=8
            ).stdout.strip().lower()
        except Exception:
            return ""
    try:
        return Path(f"/sys/class/dmi/id/{field}").read_text().strip().lower()
    except Exception:
        return ""


def cpu_core_count() -> int:
    if IS_WINDOWS:
        try:
            raw = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-WmiObject Win32_Processor).NumberOfCores"],
                capture_output=True, text=True, timeout=8
            ).stdout.strip()
            return int(raw) if raw.isdigit() else 8
        except Exception:
            return 8
    try:
        raw = subprocess.run(
            ["nproc", "--all"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return int(raw) if raw.isdigit() else 8
    except Exception:
        return 8


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
            if not size:
                return None
            buf = ctypes.create_string_buffer(size)
            read = k32.GetSystemFirmwareTable(provider, table_id, buf, size)
            if not read:
                return None
            dst = tmp / "DSDT.aml"
            dst.write_bytes(bytes(buf[:read]))
            return dst
        except Exception:
            return None
    src = Path("/sys/firmware/acpi/tables/DSDT")
    if not src.exists():
        return None
    import shutil
    dst = tmp / "DSDT.aml"
    shutil.copy2(str(src), str(dst))
    return dst


def find_iasl(ssdttime_dir: Path) -> Optional[Path]:
    """Find the iasl compiler in SSDTTime Scripts dir"""
    if IS_WINDOWS:
        iasl = ssdttime_dir / "Scripts" / "iasl.exe"
        if iasl.exists():
            return iasl
    iasl = ssdttime_dir / "Scripts" / "iasl"
    if iasl.exists():
        return iasl
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
            raw = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PnpDevice | Where-Object {$_.Class -eq 'HIDClass' -or $_.Class -eq 'Mouse'} | Select-Object -ExpandProperty FriendlyName"],
                capture_output=True, text=True, timeout=8
            ).stdout.lower()
            if "i2c" in raw:
                return "i2c"
            if "ps/2" in raw or "synaptics" in raw or "alps" in raw or "elantech" in raw:
                return "ps2"
            return "none"
        except Exception:
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
        for p in parts:
            disk_num = str(p.get("DiskNumber", ""))
            letter = str(p.get("DriveLetter") or "").strip()
            if disk_num in usb_disk_numbers and letter and letter not in seen:
                seen.add(letter)
                label, size_bytes = vol_map.get(letter, ("", usb_disk_numbers[disk_num]))
                size_gb = f"{int(size_bytes) // 1024 // 1024 // 1024}GB" if size_bytes else "?"
                drives.append((f"{letter}:", size_gb, label or ""))
    except Exception:
        pass
    return drives


def format_usb(device: str, mount_point: str) -> bool:
    """Format USB as FAT32 with GPT+ESP. Returns True on success."""
    if IS_WINDOWS:
        return _format_usb_windows(device, mount_point)
    return _format_usb_linux(device, mount_point)


def _format_usb_linux(device: str, mount_point: str) -> bool:
    import re
    import time
    disk = re.sub(r'p?\d+$', '', device) if re.search(r'\d$', device) else device
    part_device = (disk + "p1") if disk[-1].isdigit() else (disk + "1")

    # Unmount everything on the disk
    import glob
    for part in sorted(glob.glob(f"{disk}*")):
        subprocess.run(["umount", part], capture_output=True)

    subprocess.run(["parted", "-s", disk, "mklabel", "gpt"], check=True, capture_output=True)
    subprocess.run(["parted", "-s", disk, "mkpart", "primary", "fat32", "1MiB", "100%"],
                   check=True, capture_output=True)
    subprocess.run(["parted", "-s", disk, "set", "1", "esp", "on"], capture_output=True)
    subprocess.run(["partprobe", disk], capture_output=True)
    time.sleep(1)

    subprocess.run(["mkfs.fat", "-F32", "-n", "HACKINTOSH", part_device],
                   check=True, capture_output=True)

    # Mount
    Path(mount_point).mkdir(parents=True, exist_ok=True)
    subprocess.run(["mount", part_device, mount_point], check=True, capture_output=True)
    return True


def _format_usb_windows(drive_letter: str, mount_letter: str = "Z") -> bool:
    import tempfile
    src = drive_letter.rstrip(':\\')
    script = (
        f"select volume {src}\n"
        "clean\n"
        "create partition primary\n"
        "format fs=fat32 quick label=HACKINTOSH\n"
        f"assign letter={mount_letter}\n"
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


def mount_usb(device: str, mount_point: str) -> bool:
    """Mount USB partition. On Windows, the drive is already mounted after format."""
    if IS_WINDOWS:
        return True  # Windows auto-mounts after format
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
        return True  # Windows handles this automatically
    result = subprocess.run(["umount", mount_point], capture_output=True)
    return result.returncode == 0


def get_mount_path(device: str = "") -> str:
    """Get the mount path/letter for the USB drive."""
    if IS_WINDOWS:
        return "Z:"  # We always mount as Z: during format
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
            raw = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PnpDevice | Where-Object {$_.Class -eq 'SDHost'} | Select-Object -ExpandProperty FriendlyName"],
                capture_output=True, text=True, timeout=8
            ).stdout.strip()
            return bool(raw)
        except Exception:
            return False
    try:
        lspci = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5
        ).stdout.lower()
        return "sd host" in lspci or "card reader" in lspci or "rtsx" in lspci
    except Exception:
        return False
