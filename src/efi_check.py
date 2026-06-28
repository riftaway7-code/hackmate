"""
EFI diagnostic engine — validates the generated EFI against common issues.
Returns a list of (level, message) tuples.
  "error" — definitely broken, will prevent boot
  "warn"  — might be a problem, worth investigating
  "info"  — recommendation, not critical
  "ok"    — confirmed working
"""

import plistlib
import struct
from pathlib import Path


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_valid_efi(path: Path) -> bool:
    """Check EFI binary has a valid PE/COFF header (MZ magic)."""
    try:
        magic = path.read_bytes()[:2]
        return magic == b'MZ'
    except Exception:
        return False


def _kext_has_valid_structure(kext_path: Path, exec_path: str) -> tuple[bool, str]:
    """
    Returns (ok, reason).
    Checks Info.plist exists and the executable (if expected) is present.
    """
    info_plist = kext_path / "Contents" / "Info.plist"
    if not info_plist.exists():
        return False, "Contents/Info.plist missing — kext bundle is incomplete"
    try:
        plistlib.loads(info_plist.read_bytes())
    except Exception:
        return False, "Contents/Info.plist is corrupt or unreadable"
    if exec_path:
        binary = kext_path / exec_path
        if not binary.exists():
            return False, f"Executable {exec_path} missing from bundle"
        if binary.stat().st_size == 0:
            return False, f"Executable {exec_path} is empty (0 bytes) — likely a bad download"
    return True, ""


def _smbios_is_placeholder(value: str) -> bool:
    return not value or value in ("", "00000000", "000000000000") or value.startswith("0000000")


# ─── Hardware mismatch checks ────────────────────────────────────────────────

def _check_hardware_mismatch(cfg: dict, profile, results):
    def warn(msg): results.append(("warn",  msg))
    def info(msg): results.append(("info",  msg))
    def ok(msg):   results.append(("ok",    msg))

    kernel_add  = cfg.get("Kernel",   {}).get("Add",     [])
    kext_set    = {e.get("BundlePath", "").split("/")[0] for e in kernel_add}
    dev_props   = cfg.get("DeviceProperties", {}).get("Add", {})

    # ── iGPU platform-id ─────────────────────────────────────────────────────
    igpu_key = next((k for k in dev_props if "IGPU" in k.upper() or "GFX0" in k.upper() or "B0D2" in k.upper()), None)
    if igpu_key and profile.gpu_vendor == "intel":
        stored_id = dev_props[igpu_key].get("AAPL,ig-platform-id")
        if stored_id:
            stored_hex = stored_id.hex() if isinstance(stored_id, bytes) else ""
            # Import the expected value from config_gen
            try:
                from config_gen import _igpu_config
                expected_id, _ = _igpu_config(profile)
                if stored_hex and expected_id and stored_hex != expected_id.hex():
                    warn(
                        f"ig-platform-id in EFI ({stored_hex}) does not match what HackMate "
                        f"would generate for your GPU ({expected_id.hex()}). "
                        f"This EFI may have been made for different hardware."
                    )
                else:
                    ok(f"ig-platform-id matches your GPU")
            except Exception:
                pass

    # ── Audio layout-id ───────────────────────────────────────────────────────
    audio_key = next((k for k in dev_props if "HDEF" in k.upper() or "HDAS" in k.upper() or "B0D3" in k.upper()), None)
    if audio_key:
        layout_raw = dev_props[audio_key].get("layout-id")
        if layout_raw:
            layout_id = struct.unpack("<I", layout_raw)[0] if isinstance(layout_raw, bytes) else int(layout_raw)
            try:
                from config_gen import get_alc_layout
                expected_layout = get_alc_layout(profile.audio_codec)
                if expected_layout and layout_id != expected_layout:
                    warn(
                        f"Audio layout-id in EFI ({layout_id}) does not match your codec "
                        f"{profile.audio_codec} (expected {expected_layout}). "
                        f"Audio may not work — use Repair EFI to regenerate."
                    )
                else:
                    ok(f"Audio layout-id {layout_id} matches your codec")
            except Exception:
                pass

    # ── WiFi kext vs detected hardware ───────────────────────────────────────
    wifi = profile.wifi_name.lower() if profile.wifi_name else ""
    if "intel" in wifi:
        if "itlwm.kext" not in kext_set and "AirportItlwm.kext" not in kext_set:
            warn(
                "Intel WiFi detected but no Intel WiFi kext (itlwm/AirportItlwm) in EFI. "
                "WiFi will not work."
            )
        else:
            ok("Intel WiFi kext present for detected Intel WiFi")
    elif "broadcom" in wifi or "bcm" in wifi:
        if "AirportBrcmFixup.kext" not in kext_set:
            warn(
                "Broadcom WiFi detected but AirportBrcmFixup.kext missing. "
                "WiFi will not work."
            )

    # ── Ethernet kext vs detected hardware ───────────────────────────────────
    eth = profile.ethernet_name.lower() if profile.ethernet_name else ""
    if "intel" in eth:
        if not any("Intel" in k or "Mausi" in k for k in kext_set):
            warn(
                "Intel Ethernet detected but no Intel Ethernet kext found. "
                "Wired network will not work."
            )
    elif "realtek" in eth:
        if "RealtekRTL8111.kext" not in kext_set:
            warn(
                "Realtek Ethernet detected but RealtekRTL8111.kext missing. "
                "Wired network will not work."
            )

    # ── Platform vs SMBIOS ───────────────────────────────────────────────────
    pi = cfg.get("PlatformInfo", {}).get("Generic", {})
    sn = pi.get("SystemProductName", "")
    if sn:
        if profile.platform == "laptop" and sn.startswith("iMac"):
            warn(
                f"SMBIOS is {sn} but a laptop was detected. "
                f"Should be MacBookPro or MacBookAir. "
                f"Power management and battery may not work correctly."
            )
        elif profile.platform == "desktop" and "MacBook" in sn:
            warn(
                f"SMBIOS is {sn} but a desktop was detected. "
                f"Should be iMac or MacPro."
            )
        else:
            ok(f"SMBIOS {sn} matches platform ({profile.platform})")


# ─── Config completeness ─────────────────────────────────────────────────────

def _check_config_completeness(cfg: dict, results):
    def err(msg):  results.append(("error", msg))
    def warn(msg): results.append(("warn",  msg))
    def info(msg): results.append(("info",  msg))
    def ok(msg):   results.append(("ok",    msg))

    pi = cfg.get("PlatformInfo", {}).get("Generic", {})

    sn  = pi.get("SystemSerialNumber", "")
    mlb = pi.get("MLB", "")
    uid = pi.get("SystemUUID", "")

    if _smbios_is_placeholder(sn):
        err("SystemSerialNumber is missing or placeholder — iMessage/iCloud will not work")
    else:
        ok("SystemSerialNumber is set")

    if _smbios_is_placeholder(mlb):
        err("MLB is missing or placeholder — iMessage/iCloud will not work")
    else:
        ok("MLB is set")

    if not uid or uid == "00000000-0000-0000-0000-000000000000":
        err("SystemUUID is missing or all-zeros — iMessage/iCloud will not work")
    else:
        ok("SystemUUID is set")

    # boot-args sanity
    nvram_add = cfg.get("NVRAM", {}).get("Add", {})
    apple_ns  = nvram_add.get("7C436110-AB2A-4BBB-A880-FE41995C9F82", {})
    boot_args = apple_ns.get("boot-args", "")

    if "-v" not in boot_args:
        info("Verbose mode (-v) is off — add it to boot-args to see errors during boot")
    if "keepsyms=1" not in boot_args:
        info("keepsyms=1 not in boot-args — kernel panic backtraces will be less readable")

    # SecureBootModel
    misc = cfg.get("Misc", {}).get("Security", {})
    sbm = misc.get("SecureBootModel", "")
    if sbm not in ("Disabled", "Default") and sbm:
        info(
            f"SecureBootModel is '{sbm}' — if you see boot errors about root hash or "
            f"security violations, set it to Disabled."
        )


# ─── Kext conflict detection ─────────────────────────────────────────────────

KNOWN_CONFLICTS = [
    ({"itlwm.kext", "AirportItlwm.kext"},
     "itlwm and AirportItlwm both present — they do the same job, keep only one. "
     "AirportItlwm shows as native WiFi, itlwm needs HeliPort."),

    ({"VirtualSMC.kext", "FakeSMC.kext"},
     "VirtualSMC and FakeSMC both present — they conflict. Remove FakeSMC."),

    ({"AppleALC.kext", "VoodooHDA.kext"},
     "AppleALC and VoodooHDA both present — use AppleALC for supported codecs, "
     "VoodooHDA only as a fallback."),

    ({"NootedRed.kext", "WhateverGreen.kext"},
     "NootedRed and WhateverGreen both present — NootedRed handles AMD APU graphics, "
     "WhateverGreen is for dedicated GPUs. Remove WhateverGreen on AMD APU systems."),
]

def _check_conflicts(kext_set: set, results):
    def err(msg):  results.append(("error", msg))
    def warn(msg): results.append(("warn",  msg))

    for conflict_set, explanation in KNOWN_CONFLICTS:
        if conflict_set.issubset(kext_set):
            err(f"Conflict: {explanation}")


# ─── Main check ───────────────────────────────────────────────────────────────

def check(efi_root: Path, profile) -> list[tuple[str, str]]:
    results = []

    def err(msg):  results.append(("error", msg))
    def warn(msg): results.append(("warn",  msg))
    def info(msg): results.append(("info",  msg))
    def ok(msg):   results.append(("ok",    msg))

    oc_dir     = efi_root / "OC"
    boot_dir   = efi_root / "BOOT"
    kext_dir   = oc_dir / "Kexts"
    acpi_dir   = oc_dir / "ACPI"
    driver_dir = oc_dir / "Drivers"
    config     = oc_dir / "config.plist"

    # ── Core structure ────────────────────────────────────────────────────────
    for path, label in [
        (boot_dir / "BOOTx64.efi", "BOOTx64.efi"),
        (oc_dir   / "OpenCore.efi", "OpenCore.efi"),
        (config,                    "config.plist"),
    ]:
        if not path.exists():
            err(f"{label} is missing — EFI will not boot without it")
        elif path.suffix == ".efi" and not _is_valid_efi(path):
            err(f"{label} exists but is not a valid EFI binary (bad header) — likely a corrupt download")
        else:
            ok(f"{label} present and valid")

    # ── Drivers ───────────────────────────────────────────────────────────────
    required_drivers = {
        "OpenRuntime.efi": "required for memory map patches — without it macOS will not boot",
        "HfsPlus.efi":     "required to read HFS+ macOS partitions",
    }
    for drv, reason in required_drivers.items():
        path = driver_dir / drv
        if not path.exists():
            err(f"Driver missing: {drv} — {reason}")
        elif not _is_valid_efi(path):
            err(f"Driver {drv} is corrupt (bad EFI header) — re-run HackMate to redownload")
        else:
            ok(f"Driver {drv} present and valid")

    # Optional drivers
    optional_drivers = {
        "AudioDxe.efi":       "needed for boot chime",
        "OpenCanopy.efi":     "needed for graphical OpenCore picker",
        "OpenLinuxBoot.efi":  "needed to boot Linux from OpenCore",
    }
    for drv, reason in optional_drivers.items():
        path = driver_dir / drv
        if path.exists() and not _is_valid_efi(path):
            warn(f"Optional driver {drv} exists but has a corrupt header — remove or redownload it")

    # ── config.plist ─────────────────────────────────────────────────────────
    if not config.exists():
        return results

    try:
        cfg = plistlib.loads(config.read_bytes())
    except Exception as e:
        err(f"config.plist cannot be parsed: {e} — the file is corrupt, run Repair EFI to regenerate it")
        return results

    ok("config.plist parses successfully")

    # ── ACPI files ────────────────────────────────────────────────────────────
    for entry in cfg.get("ACPI", {}).get("Add", []):
        fname = entry.get("Path", "")
        if not fname:
            continue
        path = acpi_dir / fname
        if not path.exists():
            warn(
                f"config.plist lists ACPI table {fname} but the file is not on the USB. "
                f"This SSDT won't load — functionality it provides (e.g. brightness, power) may be missing."
            )
        elif path.stat().st_size < 36:
            warn(f"ACPI table {fname} is too small ({path.stat().st_size} bytes) — likely corrupt")
        else:
            ok(f"ACPI: {fname}")

    # ── Kext integrity ────────────────────────────────────────────────────────
    kernel_add = cfg.get("Kernel", {}).get("Add", [])
    kext_set   = set()

    for entry in kernel_add:
        bundle    = entry.get("BundlePath", "").split("/")[0]
        exec_path = entry.get("ExecutablePath", "")
        enabled   = entry.get("Enabled", True)
        if not bundle:
            continue
        kext_set.add(bundle)
        if not enabled:
            continue
        kext_path = kext_dir / bundle
        if not kext_path.exists():
            err(
                f"config.plist references kext {bundle} but it is not on the USB. "
                f"OpenCore will fail to inject it — run Repair EFI to redownload."
            )
            continue
        valid, reason = _kext_has_valid_structure(kext_path, exec_path)
        if not valid:
            err(f"Kext {bundle} is incomplete: {reason}. Run Repair EFI to redownload.")
        else:
            ok(f"Kext {bundle} structure valid")

    # ── Drivers in config vs on disk ─────────────────────────────────────────
    for entry in cfg.get("UEFI", {}).get("Drivers", []):
        path_str = entry.get("Path", "") if isinstance(entry, dict) else entry
        if path_str and not (driver_dir / path_str).exists():
            warn(
                f"config.plist lists driver {path_str} but it is not on the USB. "
                f"Remove the entry from config.plist or redownload the driver."
            )

    # ── Kext load order ───────────────────────────────────────────────────────
    lilu_dependents = {
        "VirtualSMC.kext", "AppleALC.kext", "WhateverGreen.kext",
        "NVMeFix.kext", "CPUFriend.kext", "BrightnessKeys.kext",
        "NootedRed.kext", "NootedBlue.kext", "RestrictEvents.kext",
        "FeatureUnlock.kext", "CryptexFixup.kext",
    }
    kext_order = [e.get("BundlePath", "").split("/")[0] for e in kernel_add]
    lilu_idx   = next((i for i, k in enumerate(kext_order) if k == "Lilu.kext"), None)

    if lilu_idx is None and any(k in lilu_dependents for k in kext_order):
        err(
            "Lilu.kext is missing but kexts that depend on it are present "
            f"({', '.join(k for k in kext_order if k in lilu_dependents)}). "
            "These kexts will not load without Lilu."
        )
    elif lilu_idx is not None:
        for dep in lilu_dependents:
            dep_idx = next((i for i, k in enumerate(kext_order) if k == dep), None)
            if dep_idx is not None and dep_idx < lilu_idx:
                err(
                    f"{dep} is loaded before Lilu.kext (position {dep_idx} vs {lilu_idx}). "
                    f"It must come after Lilu or it will silently fail to initialize."
                )
        ok("Kext load order: Lilu loads before its dependents")

    # ── Conflict detection ────────────────────────────────────────────────────
    _check_conflicts(kext_set, results)

    # ── Hardware-specific checks ──────────────────────────────────────────────
    if profile.nvme_present and "NVMeFix.kext" not in kext_set:
        info(
            "NVMe drive detected but NVMeFix.kext is missing. "
            "NVMe power management won't be optimized — drive may run hot or have higher idle power."
        )

    if profile.platform == "laptop":
        if "VoodooPS2Controller.kext" not in kext_set and "VoodooI2C.kext" not in kext_set:
            err(
                "Laptop detected but no keyboard/trackpad kext found "
                "(VoodooPS2Controller or VoodooI2C). Keyboard and trackpad will not work."
            )
        if "BrightnessKeys.kext" not in kext_set:
            info(
                "BrightnessKeys.kext is missing. "
                "Fn brightness keys (F5/F6) will not work."
            )
        if "SMCBatteryManager.kext" not in kext_set:
            warn(
                "SMCBatteryManager.kext is missing. "
                "Battery percentage and charging status will not show in macOS."
            )

    if profile.gpu_vendor == "nvidia":
        err(
            "NVIDIA GPU detected. NVIDIA is not supported on macOS Monterey and later — "
            "the GPU will not accelerate graphics. Only Intel iGPU will work if available."
        )

    if profile.cpu_vendor == "amd" and profile.gpu_vendor == "intel":
        err(
            "AMD CPU with Intel iGPU only — macOS does not support Intel iGPU on AMD systems. "
            "You need a supported AMD or NVIDIA (pre-Monterey) dGPU for graphics acceleration."
        )

    # ── Config completeness ───────────────────────────────────────────────────
    _check_config_completeness(cfg, results)

    # ── Hardware mismatch ─────────────────────────────────────────────────────
    _check_hardware_mismatch(cfg, profile, results)

    return results
