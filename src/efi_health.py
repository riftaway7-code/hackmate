"""
Standalone OpenCore EFI auditor.

efi_check validates an EFI that HackMate just built, against the machine it was
built for. This module inspects *any* OpenCore EFI — including hand-built ones —
using only what is on the disk, so it can be pointed at a USB or an internal
EFI partition with no hardware profile in hand.

Every check here corresponds to a failure that ships silently: a config.plist
that looks fine, boots, and then leaves you with no WiFi, dead USB ports, a
broken ACPI table, or SIP quietly switched off.

audit() returns a list of (level, title, detail) where level is one of
"critical" / "warn" / "info" / "ok".
"""

import plistlib
import struct
from pathlib import Path

Finding = tuple  # (level, title, detail)

APPLE_BOOT_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"

# XNU csr.h — bits set in csr-active-config are protections that are TURNED OFF.
CSR_FLAGS = [
    (1 << 0,  "untrusted kexts allowed"),
    (1 << 1,  "filesystem protection off"),
    (1 << 2,  "task_for_pid allowed"),
    (1 << 3,  "kernel debugger allowed"),
    (1 << 4,  "Apple-internal allowed"),
    (1 << 5,  "dtrace unrestricted"),
    (1 << 6,  "NVRAM unrestricted"),
    (1 << 7,  "device configuration allowed"),
    (1 << 8,  "any recovery OS allowed"),
    (1 << 9,  "unapproved kexts allowed"),
    (1 << 10, "executable policy override"),
    (1 << 11, "unauthenticated root allowed"),
]

# Renames only make sense when some table supplies the symbol they redirect to.
RENAME_PROVIDERS = {
    "XOSI": "a table defining the XOSI method (SSDT-XOSI)",
    "XSID": "a table defining XSID",
    "XGPR": "a table defining GPRW (SSDT-GPRW)",
    "XPRW": "a table defining XPRW",
}

# Unmaintained or superseded — present in old guides, no upstream releases.
DEPRECATED_KEXTS = {
    "IOElectrify":            "unmaintained; modern OpenCore handles Thunderbolt natively",
    "ThunderboltReset":       "unmaintained; superseded by native Thunderbolt support",
    "NullCPUPowerManagement": "superseded by proper SSDT-PLUG CPU power management",
    "ACPIBatteryManager":     "superseded by ECEnabler",
    "USBInjectAll":           "only for port discovery; should not ship in a final EFI",
    "FakePCIID":              "superseded by DeviceProperties device-id injection",
}

# Kexts that only do something on one chassis type.
DESKTOP_ONLY_KEXTS = {
    "SMCSuperIO": "reads desktop Super I/O fan controllers; laptops have none",
}
LAPTOP_RECOMMENDED_KEXTS = {
    "SMCBatteryManager": "battery percentage and charging state",
    "HibernationFixup":  "sleep/wake stability, especially with NVMe",
    "ECEnabler":         "reading battery fields wider than 8 bits",
}


def _find_dir(parent: Path, name: str):
    """FAT32 is case-insensitive; some EFIs ship `oc`, others `OC`."""
    if not parent.is_dir():
        return None
    for child in parent.iterdir():
        if child.is_dir() and child.name.lower() == name.lower():
            return child
    return None


def _u32(raw) -> int:
    if isinstance(raw, (bytes, bytearray)) and len(raw) >= 4:
        return struct.unpack("<I", bytes(raw[:4]))[0]
    if isinstance(raw, int):
        return raw
    return 0


def _decode_csr(value: int) -> list[str]:
    return [label for bit, label in CSR_FLAGS if value & bit]


def _acpi_names_defined(aml: bytes) -> set:
    """Which of the device/method names we care about a table declares."""
    found = set()
    for name in (b"USBX", b"XOSI", b"GPRW", b"XPRW", b"XSID", b"XGPR"):
        if name in aml:
            found.add(name.decode())
    return found


def _kext_executable(kext_dir: Path):
    """(declared_executable, exists) read from the bundle's own Info.plist."""
    info = kext_dir / "Contents" / "Info.plist"
    if not info.exists():
        return None, False
    try:
        plist = plistlib.loads(info.read_bytes())
    except Exception:
        return None, False
    exe = plist.get("CFBundleExecutable", "")
    if not exe:
        return "", True
    return exe, (kext_dir / "Contents" / "MacOS" / exe).exists()


def _check_sip(cfg: dict, out: list):
    nvram = cfg.get("NVRAM", {}).get("Add", {}).get(APPLE_BOOT_GUID, {})
    if "csr-active-config" not in nvram:
        out.append(("info", "SIP setting not present",
                    "csr-active-config is not in NVRAM/Add, so macOS keeps whatever "
                    "value is already stored in firmware."))
        return

    value = _u32(nvram["csr-active-config"])
    disabled = _decode_csr(value)

    if value == 0:
        out.append(("ok", "SIP fully enabled", "csr-active-config is 0x0."))
    else:
        out.append((
            "warn",
            f"SIP partially disabled (csr-active-config = 0x{value:X})",
            "Protections currently off: " + ", ".join(disabled) + ". "
            "Lilu-based kexts inject without disabling SIP, so unless you are "
            "root-patching, 0x0 is the safer value.",
        ))


def _check_acpi(cfg: dict, acpi_dir: Path, out: list):
    acpi = cfg.get("ACPI", {})
    tables = [e for e in acpi.get("Add", []) if e.get("Enabled", True)]

    # Which symbols do the loaded tables actually define?
    provided = set()
    usbx_providers = []
    for entry in tables:
        path = entry.get("Path", "")
        aml = acpi_dir / path if acpi_dir else None
        if not path:
            continue
        if aml is None or not aml.exists():
            out.append(("critical", f"ACPI table missing: {path}",
                        "config.plist loads this table but the file is not in ACPI/. "
                        "OpenCore will refuse to boot."))
            continue
        try:
            data = aml.read_bytes()
        except Exception:
            continue
        names = _acpi_names_defined(data)
        provided |= names
        if "USBX" in names:
            usbx_providers.append(path)

    if len(usbx_providers) > 1:
        out.append(("critical", "_SB.USBX defined by more than one table",
                    f"{', '.join(usbx_providers)} each declare a USBX device. "
                    "Duplicate ACPI device definitions make table loading fail."))

    # A rename points a firmware symbol at a replacement. If nothing supplies
    # the replacement, every call to the original symbol now goes nowhere.
    for patch in acpi.get("Patch", []):
        if not patch.get("Enabled", True):
            continue
        replace = patch.get("Replace", b"")
        if not isinstance(replace, (bytes, bytearray)):
            continue
        try:
            target = bytes(replace).decode("ascii").strip("_\x00")
        except UnicodeDecodeError:
            continue
        if target in RENAME_PROVIDERS and target not in provided:
            comment = patch.get("Comment") or f"rename to {target}"
            out.append((
                "critical",
                f"Orphaned ACPI rename: {comment}",
                f"This renames a firmware symbol to {target}, but no loaded table "
                f"defines it. Expected {RENAME_PROVIDERS[target]}. Every call to the "
                "original symbol now resolves to nothing.",
            ))

    if tables and not any(l == "critical" for l, _, _ in out):
        out.append(("ok", f"{len(tables)} ACPI table(s) present and consistent", ""))


def _check_kexts(cfg: dict, kext_dir: Path, out: list):
    entries = cfg.get("Kernel", {}).get("Add", [])
    enabled = [e for e in entries if e.get("Enabled", True)]
    names = {e.get("BundlePath", "").split("/")[0].removesuffix(".kext") for e in enabled}

    for entry in enabled:
        bundle = entry.get("BundlePath", "")
        if not bundle:
            continue
        kext = kext_dir / bundle if kext_dir else None
        if kext is None or not kext.exists():
            out.append(("critical", f"Kext missing: {bundle}",
                        "config.plist injects this kext but the bundle is not in Kexts/."))
            continue

        declared = entry.get("ExecutablePath", "")
        actual, exists = _kext_executable(kext)

        if actual is None:
            out.append(("critical", f"{bundle} has no readable Info.plist",
                        "The bundle is incomplete or corrupt."))
            continue

        if actual == "":
            if declared:
                out.append(("critical", f"{bundle} declares an executable it does not have",
                            f"config.plist sets ExecutablePath to '{declared}', but this is a "
                            "plist-only bundle. OpenCore will fail to inject it."))
            continue

        want = f"Contents/MacOS/{actual}"
        if not exists:
            out.append(("critical", f"{bundle} is missing its binary",
                        f"Info.plist names '{actual}' but Contents/MacOS/{actual} is absent."))
        elif declared != want:
            out.append(("critical", f"{bundle} has the wrong ExecutablePath",
                        f"config.plist says '{declared or '(empty)'}' but the bundle ships "
                        f"'{want}'. OpenCore will not inject this kext."))

    # Lilu has to be injected before anything that plugs into it.
    order = [e.get("BundlePath", "").split("/")[0] for e in enabled]
    if "Lilu.kext" in order:
        lilu = order.index("Lilu.kext")
        late = [k for k in order[:lilu] if k.endswith(".kext") and k != "Lilu.kext"]
        plugins = {"VirtualSMC.kext", "AppleALC.kext", "WhateverGreen.kext", "NVMeFix.kext",
                   "CPUFriend.kext", "RestrictEvents.kext", "BrightnessKeys.kext"}
        broken = [k for k in late if k in plugins]
        if broken:
            out.append(("critical", "Lilu loads after its plugins",
                        f"{', '.join(broken)} are injected before Lilu.kext and will "
                        "silently fail to initialise."))

    for dep in sorted(names & set(DEPRECATED_KEXTS)):
        out.append(("warn", f"Deprecated kext: {dep}.kext", DEPRECATED_KEXTS[dep]))

    smbios = cfg.get("PlatformInfo", {}).get("Generic", {}).get("SystemProductName", "")
    is_laptop = smbios.startswith(("MacBook", "MacBookPro", "MacBookAir"))

    if is_laptop:
        for kext, why in DESKTOP_ONLY_KEXTS.items():
            if kext in names:
                out.append(("info", f"{kext}.kext does nothing on a laptop", why))
        for kext, why in LAPTOP_RECOMMENDED_KEXTS.items():
            if kext not in names:
                out.append(("info", f"{kext}.kext is not present", f"Needed for {why}."))


def _usb_bundle_info(kext_dir: Path, bundle: str):
    """
    (kind, ports) for a USBToolBox bundle.

    A map and the default injector look alike from the outside: both are
    plist-only and both declare IOKitPersonalities. The difference is that a real
    map lists ports, while the injector declares a controller and nothing else —
    so counting ports is the only way to tell a generated map from a placeholder.
    """
    kext = (kext_dir / bundle) if kext_dir else None
    if not kext or not kext.exists():
        return "missing", 0
    try:
        plist = plistlib.loads((kext / "Contents" / "Info.plist").read_bytes())
    except Exception:
        return "missing", 0

    identifier = plist.get("CFBundleIdentifier", "")
    ports = 0
    for personality in plist.get("IOKitPersonalities", {}).values():
        ports += len(personality.get("IOProviderMergeProperties", {}).get("ports", {}))

    if identifier.endswith(".map"):
        return "map", ports
    if identifier.endswith(".injector"):
        return "injector", ports
    return "other", ports


def _check_usb_map(cfg: dict, kext_dir: Path, out: list):
    driver_on = False
    enabled_maps, disabled_maps, injector_on = [], [], False

    for entry in cfg.get("Kernel", {}).get("Add", []):
        bundle = entry.get("BundlePath", "").split("/")[0]
        if not bundle.endswith(".kext"):
            continue
        stem = bundle[: -len(".kext")]
        enabled = entry.get("Enabled", True)

        if stem == "USBToolBox":
            driver_on = enabled
            continue

        kind, ports = _usb_bundle_info(kext_dir, bundle)
        if kind == "injector":
            injector_on = injector_on or enabled
        elif kind == "map":
            (enabled_maps if enabled else disabled_maps).append((stem, ports))

    if not driver_on and not enabled_maps and not injector_on:
        out.append(("warn", "No USB port map",
                    "macOS allows only 15 ports per controller. Without a map, ports drop "
                    "out at random and sleep can break."))
        return

    mapped_ports = sum(p for _, p in enabled_maps)

    if enabled_maps and not driver_on:
        out.append(("critical", f"{enabled_maps[0][0]}.kext is enabled but USBToolBox.kext is not",
                    "The map is inert without its driver — both must be enabled."))
    elif mapped_ports:
        names = ", ".join(f"{n} ({p} ports)" for n, p in enabled_maps)
        out.append(("ok", f"USB map active: {names}", ""))
    else:
        shelved = ", ".join(f"{n}.kext ({p} ports)" for n, p in disabled_maps if p)
        detail = ("The only enabled USBToolBox bundle declares no ports, so nothing is "
                  "actually mapped and macOS falls back to the first 15 ports it finds.")
        if shelved:
            detail += (f" A generated map is sitting on this EFI but is switched off: {shelved}. "
                       "Enable it in config.plist, or re-run USB Mapping.")
        else:
            detail += " Run USB Mapping to generate one."
        out.append(("warn", "USB ports are not mapped", detail))

    if len(enabled_maps) > 1:
        out.append(("warn",
                    f"More than one USB map enabled: {', '.join(n for n, _ in enabled_maps)}",
                    "Exactly one map should be active."))


def _check_platform_info(cfg: dict, out: list):
    generic = cfg.get("PlatformInfo", {}).get("Generic", {})
    serial = generic.get("SystemSerialNumber", "")
    mlb = generic.get("MLB", "")
    uuid = generic.get("SystemUUID", "")

    if not serial or serial.startswith("0000000"):
        out.append(("warn", "SystemSerialNumber is a placeholder",
                    "iMessage, FaceTime and iCloud will not activate."))
    if not mlb or mlb.startswith("0000000"):
        out.append(("warn", "MLB is a placeholder", "iMessage and FaceTime will not activate."))
    elif len(mlb) != 17:
        out.append(("warn", f"MLB is {len(mlb)} characters, not 17",
                    "Apple's activation servers reject board serials of the wrong length."))
    if not uuid or uuid == "00000000-0000-0000-0000-000000000000":
        out.append(("warn", "SystemUUID is unset", "iCloud services may not activate."))

    if serial and mlb and uuid and len(mlb) == 17 and not serial.startswith("0000000"):
        out.append(("ok", f"SMBIOS identity complete ({generic.get('SystemProductName','?')})", ""))


def _check_boot_args(cfg: dict, out: list):
    nvram = cfg.get("NVRAM", {}).get("Add", {}).get(APPLE_BOOT_GUID, {})
    raw = nvram.get("boot-args", "")
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    args = raw.split()

    if "-no_compat_check" not in args:
        out.append(("info", "-no_compat_check is not set",
                    "Without it, boot.efi can reject a future macOS update because the "
                    "spoofed board ID is not on its supported list."))
    if "-v" in args:
        out.append(("info", "Verbose boot is on",
                    "Useful while debugging; remove -v for a normal boot screen."))


def audit(efi_root: Path) -> list:
    """Inspect an OpenCore EFI folder. `efi_root` is the folder containing OC/."""
    out: list = []

    oc_dir = _find_dir(efi_root, "OC")
    if oc_dir is None:
        return [("critical", "No OC folder found",
                 f"{efi_root} does not look like an OpenCore EFI.")]

    boot_dir = _find_dir(efi_root, "BOOT")
    kext_dir = _find_dir(oc_dir, "Kexts")
    acpi_dir = _find_dir(oc_dir, "ACPI")

    config = next((p for p in oc_dir.iterdir()
                   if p.is_file() and p.name.lower() == "config.plist"), None)
    if config is None:
        return [("critical", "config.plist is missing", f"Expected it in {oc_dir}.")]

    try:
        cfg = plistlib.loads(config.read_bytes())
    except Exception as exc:
        return [("critical", "config.plist cannot be parsed", str(exc))]

    if boot_dir is None or not (boot_dir / "BOOTx64.efi").exists():
        out.append(("critical", "BOOTx64.efi is missing", "Firmware has nothing to load."))
    if not (oc_dir / "OpenCore.efi").exists():
        out.append(("critical", "OpenCore.efi is missing", "BOOTx64.efi will fail to chainload."))

    _check_acpi(cfg, acpi_dir, out)
    _check_kexts(cfg, kext_dir, out)
    _check_usb_map(cfg, kext_dir, out)
    _check_sip(cfg, out)
    _check_platform_info(cfg, out)
    _check_boot_args(cfg, out)

    return out


def summarise(findings: list) -> dict:
    counts = {"critical": 0, "warn": 0, "info": 0, "ok": 0}
    for level, _, _ in findings:
        counts[level] = counts.get(level, 0) + 1
    return counts


def format_report(findings: list, efi_root: Path) -> str:
    """Plain-text report for the --doctor CLI."""
    green, yellow, red, grey, blue, bold, reset = (
        "\x1b[38;5;48m", "\x1b[38;5;220m", "\x1b[38;5;203m",
        "\x1b[38;5;244m", "\x1b[38;5;74m", "\x1b[1m", "\x1b[0m",
    )
    mark = {"critical": (red, "✗"), "warn": (yellow, "⚠"),
            "info": (blue, "ℹ"), "ok": (green, "✓")}

    lines = [f"\n{bold}HackMate EFI Health Check{reset}  {grey}{efi_root}{reset}", ""]
    for level in ("critical", "warn", "info", "ok"):
        for lvl, title, detail in findings:
            if lvl != level:
                continue
            color, symbol = mark[lvl]
            lines.append(f"  {color}{symbol}{reset} {title}")
            if detail:
                for chunk in _wrap(detail, 76):
                    lines.append(f"    {grey}{chunk}{reset}")

    counts = summarise(findings)
    lines.append("")
    if counts["critical"]:
        lines.append(f"  {red}{counts['critical']} critical{reset} · "
                     f"{yellow}{counts['warn']} warning(s){reset} · "
                     f"{grey}{counts['info']} note(s){reset}")
        lines.append(f"  {red}This EFI has problems that will stop it booting correctly.{reset}")
    elif counts["warn"]:
        lines.append(f"  {yellow}{counts['warn']} warning(s){reset} · "
                     f"{grey}{counts['info']} note(s){reset} · "
                     f"{green}{counts['ok']} passed{reset}")
    else:
        lines.append(f"  {green}No problems found{reset} · {counts['ok']} checks passed")
    lines.append("")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list:
    words, line, lines = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines
