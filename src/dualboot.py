from __future__ import annotations
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from compat import IS_WINDOWS

_EFI_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


@dataclass
class PartitionInfo:
    device: str
    size: str
    fs_type: str
    label: str
    mount: str
    is_efi: bool
    part_type_guid: str = ""


@dataclass
class DiskInfo:
    device: str
    model: str
    size: str
    transport: str
    is_gpt: bool
    partitions: list[PartitionInfo] = field(default_factory=list)


@dataclass
class BootloaderInfo:
    partition: str
    windows: bool = False
    linux_grub: bool = False
    linux_efi: bool = False
    opencore: bool = False
    refind: bool = False
    other: list[str] = field(default_factory=list)


def scan_disks() -> list[DiskInfo]:
    if IS_WINDOWS:
        return _scan_windows()
    return _scan_linux()


def _scan_linux() -> list[DiskInfo]:
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o",
             "NAME,SIZE,MODEL,TRAN,PTTYPE,FSTYPE,LABEL,MOUNTPOINT,TYPE,PARTTYPE"],
            capture_output=True, text=True, timeout=10
        ).stdout
        data = json.loads(out)
    except Exception:
        return []

    disks = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        name = dev.get("name", "")
        # skip virtual/ram devices
        if name.startswith(("zram", "ram", "loop")):
            continue
        size_bytes = int(dev.get("size") or 0)
        if size_bytes == 0:
            continue
        disk = DiskInfo(
            device=f"/dev/{name}",
            model=(dev.get("model") or "Unknown").strip(),
            size=_bytes_to_human(size_bytes),
            transport=(dev.get("tran") or "?").upper(),
            is_gpt=(dev.get("pttype") or "").lower() == "gpt",
        )
        for part in (dev.get("children") or []):
            if part.get("type") not in ("part",):
                continue
            fs     = (part.get("fstype") or "").lower()
            label  = (part.get("label") or "").strip()
            mount  = (part.get("mountpoint") or "").strip()
            pguid  = (part.get("parttype") or "").lower()
            is_efi = pguid == _EFI_GUID or (
                fs == "vfat" and label.upper() in ("EFI", "ESP", "SYSTEM")
            )
            disk.partitions.append(PartitionInfo(
                device=f"/dev/{part['name']}",
                size=_bytes_to_human(int(part.get("size") or 0)),
                fs_type=fs,
                label=label,
                mount=mount,
                is_efi=is_efi,
                part_type_guid=pguid,
            ))
        disks.append(disk)
    return disks


def _scan_windows() -> list[DiskInfo]:
    script = r"""
$disks = Get-Disk | Sort-Object Number | ForEach-Object {
    $d = $_
    $parts = Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue |
             Sort-Object PartitionNumber | ForEach-Object {
        $p   = $_
        $vol = Get-Volume -Partition $p -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            name  = "Disk$($d.Number)p$($p.PartitionNumber)"
            size  = $p.Size
            fs    = if ($vol) { $vol.FileSystemType } else { "" }
            label = if ($vol) { $vol.FileSystemLabel } else { "" }
            mount = if ($vol -and $vol.DriveLetter) { "$($vol.DriveLetter):" } else { "" }
            is_esp = ($p.GptType -eq "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}")
        }
    }
    [PSCustomObject]@{
        device     = "Disk$($d.Number)"
        model      = $d.FriendlyName
        size       = $d.Size
        transport  = $d.BusType
        is_gpt     = ($d.PartitionStyle -eq "GPT")
        partitions = @($parts)
    }
}
$disks | ConvertTo-Json -Depth 5
"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=20
        ).stdout
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []

    disks = []
    for d in data:
        disk = DiskInfo(
            device=d.get("device", "?"),
            model=d.get("model") or "Unknown",
            size=_bytes_to_human(int(d.get("size") or 0)),
            transport=str(d.get("transport") or "?"),
            is_gpt=bool(d.get("is_gpt", True)),
        )
        for p in (d.get("partitions") or []):
            if not isinstance(p, dict):
                continue
            disk.partitions.append(PartitionInfo(
                device=p.get("name", "?"),
                size=_bytes_to_human(int(p.get("size") or 0)),
                fs_type=(p.get("fs") or "").lower(),
                label=p.get("label") or "",
                mount=p.get("mount") or "",
                is_efi=bool(p.get("is_esp")),
            ))
        disks.append(disk)
    return disks


def _bytes_to_human(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or unit == "TB":
            return f"{b:.0f} {unit}"
        b //= 1024
    return f"{b} TB"


def detect_bootloaders(part: PartitionInfo) -> BootloaderInfo | None:
    """Try to detect bootloaders on an EFI partition. Returns None if mount fails."""
    if not part.is_efi:
        return None
    info = BootloaderInfo(partition=part.device)

    if part.mount:
        _scan_efi_dir(Path(part.mount), info)
        return info

    if IS_WINDOWS:
        return None  # would need diskpart assign — skip

    tmp = tempfile.mkdtemp(prefix="hm_efi_")
    mounted = False
    try:
        r = subprocess.run(
            ["mount", "-o", "ro", part.device, tmp],
            capture_output=True, timeout=8
        )
        if r.returncode == 0:
            mounted = True
            _scan_efi_dir(Path(tmp), info)
    finally:
        if mounted:
            subprocess.run(["umount", tmp], capture_output=True, timeout=5)
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    return info if mounted else None


def _scan_efi_dir(root: Path, info: BootloaderInfo):
    efi = root / "EFI"
    if not efi.exists():
        return
    known = {
        "BOOT", "Microsoft",
        "ubuntu", "fedora", "debian", "arch", "manjaro", "gentoo",
        "opensuse", "centos", "rhel", "bazzite", "nobara", "pop",
        "mint", "zorin", "elementary",
        "OC", "refind", "systemd", "Linux",
        "HackMate-Extras", "HackMate", "tools", "Tools",
    }
    for sub in efi.iterdir():
        if not sub.is_dir():
            continue
        n = sub.name
        if n == "Microsoft" and (sub / "Boot" / "bootmgfw.efi").exists():
            info.windows = True
        elif n in ("ubuntu", "fedora", "debian", "arch", "manjaro",
                   "gentoo", "opensuse", "centos", "rhel",
                   "bazzite", "nobara", "pop", "mint", "zorin", "elementary"):
            if (sub / "grubx64.efi").exists():
                info.linux_grub = True
        elif n == "systemd" and (sub / "systemd-bootx64.efi").exists():
            info.linux_efi = True
        elif n == "Linux":
            info.linux_efi = True
        elif n == "OC" and (sub / "OpenCore.efi").exists():
            info.opencore = True
        elif n == "refind" and (sub / "refind_x64.efi").exists():
            info.refind = True
        elif n not in known:
            info.other.append(n)


def scan_all_bootloaders(disks: list[DiskInfo]) -> dict[str, BootloaderInfo]:
    """Scan all EFI partitions across all disks. Returns {device: BootloaderInfo}."""
    result: dict[str, BootloaderInfo] = {}
    for disk in disks:
        for part in disk.partitions:
            if part.is_efi:
                bl = detect_bootloaders(part)
                if bl is not None:
                    result[part.device] = bl
    return result


def check_conflicts(disks: list[DiskInfo],
                    bootloaders: dict[str, BootloaderInfo]) -> list[str]:
    warnings: list[str] = []

    # Build a map of partition device → parent disk transport
    part_transport: dict[str, str] = {}
    for disk in disks:
        for part in disk.partitions:
            part_transport[part.device] = disk.transport.upper()

    # Only count OC installs on non-USB drives; USB is the hackintosh installer
    oc_on_internal = [
        dev for dev, b in bootloaders.items()
        if b.opencore and part_transport.get(dev, "") != "USB"
    ]
    if len(oc_on_internal) > 1:
        warnings.append(
            f"{len(oc_on_internal)} internal EFI partitions contain OpenCore — "
            "remove duplicates to avoid boot confusion"
        )

    for d in disks:
        if not d.is_gpt and d.transport.upper() not in ("USB",):
            warnings.append(
                f"{d.device} ({d.model}) uses MBR/Legacy — macOS requires GPT"
            )
    return warnings


def build_disk_tree(disks: list[DiskInfo],
                    bootloaders: dict[str, BootloaderInfo]) -> str:
    """Return a Rich-markup string of the disk layout as a tree."""
    lines: list[str] = []
    for disk in disks:
        scheme = "[yellow]MBR[/]" if not disk.is_gpt else "GPT"
        lines.append(
            f"[bold cyan]{disk.device}[/]  {disk.model}  "
            f"{disk.size}  {scheme}  {disk.transport}"
        )
        for i, part in enumerate(disk.partitions):
            connector = "  └─" if i == len(disk.partitions) - 1 else "  ├─"
            tags: list[str] = []
            if part.is_efi:
                tags.append("[yellow]EFI[/]")
            bl = bootloaders.get(part.device)
            if bl:
                if bl.windows:                    tags.append("[blue]Windows[/]")
                if bl.linux_grub or bl.linux_efi: tags.append("[green]Linux[/]")
                if bl.opencore:                   tags.append("[magenta]OpenCore[/]")
                if bl.refind:                     tags.append("[cyan]rEFInd[/]")
                for unk in bl.other:              tags.append(f"[dim]{unk}[/]")
            label = part.label or part.fs_type.upper() or "?"
            tag_str = "  " + " ".join(tags) if tags else ""
            lines.append(f"{connector} {part.device}  {part.size}  {label}{tag_str}")
    return "\n".join(lines) if lines else "  No disks found."


def fix_macos_boot(oc_efi_dir: Path, efi_mount: str) -> str:
    """Reinstall OpenCore from oc_efi_dir into an already-mounted EFI partition.
    Returns 'OK' or 'ERROR: ...'."""
    import shutil
    target_efi = Path(efi_mount) / "EFI"
    try:
        oc_src  = oc_efi_dir / "OC"
        oc_dst  = target_efi / "OC"
        boot_src = oc_efi_dir / "BOOT" / "BOOTx64.efi"
        boot_dst = target_efi / "BOOT" / "BOOTx64.efi"

        if oc_dst.exists():
            shutil.rmtree(oc_dst)
        shutil.copytree(oc_src, oc_dst)

        boot_dst.parent.mkdir(parents=True, exist_ok=True)
        if boot_src.exists():
            shutil.copy2(boot_src, boot_dst)

        return "OK"
    except Exception as e:
        return f"ERROR: {e}"
