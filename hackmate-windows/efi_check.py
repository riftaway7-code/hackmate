"""
EFI sanity checker — validates the generated EFI against common issues.
Returns a list of (level, message) tuples: level is "ok", "warn", or "error".
"""

import plistlib
from pathlib import Path


def check(efi_root: Path, profile) -> list[tuple[str, str]]:
    results = []

    def ok(msg):   results.append(("ok",    msg))
    def warn(msg): results.append(("warn",  msg))
    def err(msg):  results.append(("error", msg))

    oc_dir     = efi_root / "OC"
    boot_dir   = efi_root / "BOOT"
    kext_dir   = oc_dir / "Kexts"
    acpi_dir   = oc_dir / "ACPI"
    driver_dir = oc_dir / "Drivers"
    config     = oc_dir / "config.plist"

    # ── Structure ────────────────────────────────────────────────────────────
    for path, label in [
        (boot_dir / "BOOTx64.efi", "BOOTx64.efi"),
        (oc_dir / "OpenCore.efi",  "OpenCore.efi"),
        (config,                    "config.plist"),
    ]:
        if path.exists(): ok(f"{label} present")
        else:             err(f"{label} MISSING — EFI won't boot")

    # ── Drivers ──────────────────────────────────────────────────────────────
    required_drivers = {
        "OpenRuntime.efi":    "required for memory patches",
        "HfsPlus.efi":        "required to read HFS+ macOS partitions",
        "ResetNvramEntry.efi":"required for NVRAM reset on boot",
    }
    for drv, reason in required_drivers.items():
        if (driver_dir / drv).exists(): ok(f"Driver: {drv}")
        else:                           err(f"Driver missing: {drv} ({reason})")

    # ── config.plist cross-checks ─────────────────────────────────────────────
    if not config.exists():
        return results

    try:
        cfg = plistlib.loads(config.read_bytes())
    except Exception as e:
        err(f"config.plist parse error: {e}")
        return results

    # ACPI files listed vs present
    acpi_add = cfg.get("ACPI", {}).get("Add", [])
    for entry in acpi_add:
        fname = entry.get("Path", "")
        if not fname:
            continue
        if (acpi_dir / fname).exists():
            ok(f"ACPI: {fname}")
        else:
            warn(f"ACPI listed in config but file missing: {fname}")

    # Kexts listed vs present on disk
    kernel_add = cfg.get("Kernel", {}).get("Add", [])
    kext_names = [e.get("BundlePath", "").split("/")[0] for e in kernel_add]

    for entry in kernel_add:
        bundle = entry.get("BundlePath", "").split("/")[0]
        if not bundle:
            continue
        if (kext_dir / bundle).exists():
            ok(f"Kext: {bundle}")
        else:
            warn(f"Kext listed in config but missing: {bundle}")

    # Drivers listed in config vs present
    driver_add = cfg.get("UEFI", {}).get("Drivers", [])
    for entry in driver_add:
        path = entry.get("Path", "") if isinstance(entry, dict) else entry
        if path and not (driver_dir / path).exists():
            warn(f"Driver listed in config but missing: {path}")

    # ── Kext load order ───────────────────────────────────────────────────────
    lilu_dependents = {
        "VirtualSMC.kext", "AppleALC.kext", "WhateverGreen.kext",
        "NVMeFix.kext", "CPUFriend.kext", "BrightnessKeys.kext",
    }
    kext_order = [e.get("BundlePath", "").split("/")[0] for e in kernel_add]
    lilu_idx = next((i for i, k in enumerate(kext_order) if k == "Lilu.kext"), None)

    if lilu_idx is None and any(k in lilu_dependents for k in kext_order):
        err("Lilu.kext missing but its dependents are present — kexts won't load")
    elif lilu_idx is not None:
        for dep in lilu_dependents:
            dep_idx = next((i for i, k in enumerate(kext_order) if k == dep), None)
            if dep_idx is not None and dep_idx < lilu_idx:
                err(f"{dep} loads before Lilu — must come after")
        ok("Kext load order: Lilu before dependents")

    # ── Conflicting kexts ─────────────────────────────────────────────────────
    kext_set = set(kext_order)
    if "itlwm.kext" in kext_set and "AirportItlwm.kext" in kext_set:
        err("itlwm and AirportItlwm both present — use one or the other")

    smc_kexts = {"VirtualSMC.kext", "FakeSMC.kext"}
    if len(smc_kexts & kext_set) > 1:
        err("VirtualSMC and FakeSMC both present — remove one")

    audio_kexts = {"AppleALC.kext", "VoodooHDA.kext"}
    if len(audio_kexts & kext_set) > 1:
        warn("AppleALC and VoodooHDA both present — use one or the other")

    # ── Hardware-specific checks ───────────────────────────────────────────────
    if profile.nvme_present and "NVMeFix.kext" not in kext_set:
        warn("NVMe detected but NVMeFix.kext missing — NVMe power management may be broken")

    if profile.platform == "laptop":
        if "VoodooPS2Controller.kext" not in kext_set and "VoodooI2C.kext" not in kext_set:
            warn("Laptop detected but no keyboard/trackpad kext found")
        if "BrightnessKeys.kext" not in kext_set:
            warn("Laptop detected but BrightnessKeys.kext missing — Fn brightness keys won't work")

    if profile.gpu_vendor == "nvidia":
        err("NVIDIA GPU detected — NVIDIA is not supported on macOS Monterey and later")

    if profile.cpu_vendor == "amd" and profile.gpu_vendor == "intel":
        err("AMD CPU with Intel iGPU only — no macOS iGPU support for AMD APUs")

    # ── SMBIOS sanity ────────────────────────────────────────────────────────
    pi = cfg.get("PlatformInfo", {}).get("Generic", {})
    sn = pi.get("SystemProductName", "")
    if sn:
        if profile.platform == "laptop" and sn.startswith("iMac"):
            warn(f"SMBIOS is {sn} but laptop detected — should be MacBookPro or MacBookAir")
        elif profile.platform == "desktop" and "MacBook" in sn:
            warn(f"SMBIOS is {sn} but desktop detected — should be iMac or MacPro")
        else:
            ok(f"SMBIOS: {sn}")

    return results
