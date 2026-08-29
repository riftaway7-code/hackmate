from dataclasses import dataclass

from compat import dmi_vendor
from hardware import HardwareProfile, has_macos_supported_gpu
from kexts import select_kexts, DB as KEXT_DB, get_alc_layout
from config_gen import (
    _required_ssdts,
    _cpu_needs_spoof,
    _igpu_config,
    _booter_section,
    _uefi_section,
)
import recovery


def _is_pentium_or_celeron(profile: HardwareProfile) -> bool:
    name = (profile.cpu_name or profile.cpu_brand or "").lower()
    return "pentium" in name or "celeron" in name


GUIDE = "https://dortania.github.io/OpenCore-Install-Guide/"
CONFIG = "https://dortania.github.io/OpenCore-Install-Guide/config.plist/"
ACPI_GUIDE = "https://dortania.github.io/Getting-Started-With-ACPI/"
SSDT_PREBUILT = (
    "https://dortania.github.io/Getting-Started-With-ACPI/ssdt-methods/ssdt-prebuilt.html"
)
AMD_GUIDE = "https://dortania.github.io/OpenCore-Install-Guide/AMD/"
AMD_VANILLA = "https://github.com/AMD-OSX/AMD_Vanilla"

_SECTION_DOC = {
    "macOS": GUIDE,
    "SMBIOS": CONFIG + "#platforminfo",
    "boot-args": CONFIG + "#nvram",
    "Booter": CONFIG + "#booter",
    "Kernel": CONFIG + "#kernel",
    "DeviceProperties": CONFIG + "#deviceproperties",
    "ACPI": ACPI_GUIDE,
    "Kexts": GUIDE,
}

_AMD_SECTIONS = {"SMBIOS", "boot-args", "Booter", "Kernel", "DeviceProperties"}

_SSDT_REASON = {
    "SSDT-PLUG": "CPU power management (X86PlatformPlugin) on Haswell through Comet Lake",
    "SSDT-GPRW": "neutralises the _GPE instant-wake so the machine stays asleep",
    "SSDT-EC": "adds a stub EC device macOS expects on desktop boards",
    "SSDT-EC-USBX": "stub EC plus USB power properties (USBX) for laptops and Skylake+",
    "SSDT-USBX": "USB power properties (USBX) for Skylake and newer desktops",
    "SSDT-PNLF": "backlight control device for the internal laptop panel",
    "SSDT-AWAC": "forces the legacy RTC clock on 300-series and newer boards that default to AWAC",
    "SSDT-PMC": "restores the PMC device so NVRAM works on 300-series desktops",
    "SSDT-IMEI": "adds the IMEI device on Sandy/Ivy Bridge boards that omit it",
    "SSDT-GPI0": "wakes the I2C GPIO controller the trackpad hangs off",
    "SSDT-XOSI": "spoofs _OSI so Windows-gated ACPI paths run under macOS",
}

_BOOTER_QUIRK_REASON = {
    "AvoidRuntimeDefrag": "keeps firmware runtime services working under macOS",
    "DevirtualiseMmio": "frees MMIO regions so the kernel slide can be allocated",
    "EnableSafeModeSlide": "lets safe mode use KASLR like a normal boot",
    "EnableWriteUnprotector": "removes the write protection on the page table for older firmware",
    "RebuildAppleMemoryMap": "rewrites the memory map into a shape macOS accepts",
    "SetupVirtualMap": "maps SetVirtualAddresses calls into safe memory",
    "SyncRuntimePermissions": "fixes memory attributes for firmware that lands runtime code in BS regions",
    "ProvideCustomSlide": "picks a safe kernel slide when the firmware leaves gaps",
    "ResizeAppleGpuBars": "clamps the GPU BAR size to something macOS tolerates",
}

_KERNEL_QUIRK_REASON = {
    "AppleXcpmCfgLock": "skips the MSR 0xE2 write when the BIOS locks CFG-Lock",
    "AppleCpuPmCfgLock": "same CFG-Lock workaround for AppleIntelCPUPowerManagement",
    "DisableIoMapper": "turns off VT-d from macOS since the DMAR table is not stripped",
    "ProvideCurrentCpuInfo": "feeds the kernel real CPU data, required by the AMD patches and on newer Intel",
    "PanicNoKextDump": "keeps panic logs readable by dropping the kext dump",
    "PowerTimeoutKernelPanic": "stops Big Sur+ panicking when a driver misses a power change deadline",
    "DisableLinkeditJettison": "lets Lilu and friends stay resident without lilubetaall",
    "LapicKernelPanic": "disables the LAPIC interrupt check that some OEM laptops trip",
    "XhciPortLimit": "lifts the 15-port limit before a proper USB map exists",
}


@dataclass(frozen=True)
class Decision:
    section: str
    setting: str
    value: str
    reason: str
    doc: str = ""


def _doc_for(section: str, amd: bool) -> str:
    if amd and section in _AMD_SECTIONS:
        return AMD_GUIDE
    return _SECTION_DOC.get(section, GUIDE)


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (bytes, bytearray)):
        return value.hex() or "(empty)"
    return str(value)


def _macos_decisions(profile: HardwareProfile, macos_major: int, amd: bool) -> list[Decision]:
    out: list[Decision] = []
    compatible = recovery.compatible_versions(
        profile.cpu_generation,
        profile.gpu_vendor,
        profile.cpu_vendor or "intel",
        profile.cpu_codename,
        profile.gpu_name,
    )
    if compatible:
        newest = compatible[0]
        oldest = compatible[-1]
        span = newest.name if newest is oldest else f"{oldest.name} .. {newest.name}"
        gpu_desc = f"{profile.gpu_vendor} GPU" if profile.gpu_vendor else "no supported GPU"
        if amd:
            basis = (
                f"{profile.cpu_codename or 'Ryzen'}, {gpu_desc}: bootable on AMD with the "
                f"community kernel patches"
            )
        else:
            basis = (
                f"gen {profile.cpu_generation} Intel CPU, {gpu_desc}: "
                f"{newest.notes or 'per the Dortania support matrix'}"
            )
        out.append(Decision("macOS", "supported range", span, basis, _doc_for("macOS", amd)))
    if macos_major:
        chosen = next((v for v in compatible if v.major == macos_major), None)
        label = chosen.name if chosen else f"macOS major {macos_major}"
        out.append(Decision("macOS", "target", label, "selected for this build", _doc_for("macOS", amd)))
    if _is_pentium_or_celeron(profile):
        out.append(Decision(
            "macOS", "ceiling", "Monterey",
            "Pentium/Celeron parts have AVX2 fused off and Ventura and newer require it",
            _doc_for("macOS", amd),
        ))
    return out


def _smbios_decisions(profile: HardwareProfile, amd: bool) -> list[Decision]:
    if not profile.smbios_model:
        return []
    return [Decision(
        "SMBIOS", "SMBIOS model", profile.smbios_model,
        f"closest Mac to a gen {profile.cpu_generation} {profile.platform or 'desktop'} "
        f"with this GPU for power management and board-id",
        _doc_for("SMBIOS", amd),
    )]


def _kext_decisions(profile: HardwareProfile, wifi_kext_mode: str, amd: bool) -> list[Decision]:
    reasons = {name: entry.note for name, entry in KEXT_DB.items()}
    out: list[Decision] = []
    for kext in select_kexts(profile, wifi_kext_mode=wifi_kext_mode):
        out.append(Decision(
            "Kexts", kext.name, "included",
            reasons.get(kext.name, "required for this hardware"),
            _doc_for("Kexts", amd),
        ))
    return out


def _ssdt_decisions(profile: HardwareProfile, wifi_kext_mode: str, amd: bool) -> list[Decision]:
    kexts = select_kexts(profile, wifi_kext_mode=wifi_kext_mode)
    out: list[Decision] = []
    for name in _required_ssdts(profile, kexts):
        out.append(Decision(
            "ACPI", name, "added",
            _SSDT_REASON.get(name, "from the Dortania prebuilt-SSDT matrix"),
            SSDT_PREBUILT,
        ))
    return out


def _kernel_decisions(profile: HardwareProfile, amd: bool) -> list[Decision]:
    out: list[Decision] = []
    spoof = _cpu_needs_spoof(profile)
    if spoof:
        out.append(Decision(
            "Kernel", "Emulate/Cpuid1Data", _fmt_value(spoof[0]),
            "spoofs the CPUID to a whitelisted CPU so XCPM and X86PlatformPlugin initialise",
            _doc_for("Kernel", amd),
        ))
    if profile.cpu_generation and profile.cpu_generation <= 3:
        out.append(Decision(
            "Kernel", "Emulate/DummyPowerManagement", "on",
            "Sandy/Ivy Bridge have no XCPM so AppleIntelCPUPowerManagement is stubbed out",
            _doc_for("Kernel", amd),
        ))
    if amd:
        out.append(Decision(
            "Kernel", "Patch", "AMD Vanilla set",
            "the community kernel patches Ryzen needs, with the core-count byte set to this CPU",
            AMD_VANILLA,
        ))
        for setting in ("AppleXcpmCfgLock", "AppleCpuPmCfgLock"):
            out.append(Decision(
                "Kernel", f"Quirks/{setting}", "off",
                "not an Intel CPU, so the CFG-Lock MSR workaround does not apply",
                _doc_for("Kernel", amd),
            ))
    if "hp" in dmi_vendor().lower():
        out.append(Decision(
            "Kernel", "Quirks/LapicKernelPanic", "on",
            "HP firmware raises a spurious LAPIC interrupt that panics the kernel otherwise",
            _doc_for("Kernel", amd),
        ))
    return out


def _bootarg_decisions(profile: HardwareProfile, macos_major: int, amd: bool) -> list[Decision]:
    out: list[Decision] = []
    doc = _doc_for("boot-args", amd)
    if profile.audio_codec:
        codec_layout = get_alc_layout(profile.audio_codec)
        out.append(Decision("boot-args", "alcid", str(codec_layout),
                            f"AppleALC layout for the {profile.audio_codec} codec", doc))
    if macos_major >= 15 and not has_macos_supported_gpu(profile):
        out.append(Decision("boot-args", "revpatch=sbvmm", "set",
                            "Sequoia+ with no natively supported GPU: spoof VMM so macOS boots", doc))
        out.append(Decision("boot-args", "-lilubetaall", "set",
                            "lets Lilu plugins load on the newer, unrecognised kernel", doc))
    if profile.cpu_vendor == "amd":
        out.append(Decision("boot-args", "npci=0x2000", "set",
                            "skips PCI configuration that hangs early boot on AMD", doc))
    if profile.gpu_vendor == "nvidia" or profile.dgpu_vendor == "nvidia":
        out.append(Decision("boot-args", "nv_disable=1", "set",
                            "no modern macOS driver for this NVIDIA GPU, so disable it at boot", doc))
    if profile.platform == "laptop" and profile.gpu_vendor == "intel":
        out.append(Decision("boot-args", "agdpmod=vit9696", "set",
                            "stops the black screen from the board-id display check on laptop iGPUs", doc))
        out.append(Decision("boot-args", "darkwake=0", "set",
                            "avoids the laptop waking itself from sleep", doc))
    return out


def _deviceprops_decisions(profile: HardwareProfile, macos_major: int, amd: bool) -> list[Decision]:
    if profile.gpu_vendor != "intel" or profile.cpu_generation > 10:
        return []
    if "arc" in (profile.gpu_name or "").lower():
        return []
    headless = profile.platform == "desktop" and profile.dgpu_vendor == "amd"
    try:
        platform_id, device_id = _igpu_config(profile, headless=headless, macos_major=macos_major)
    except Exception:
        return []
    out = [Decision(
        "DeviceProperties", "AAPL,ig-platform-id", _fmt_value(platform_id),
        ("connectorless framebuffer because a supported AMD dGPU drives the display"
         if headless else
         f"framebuffer for {profile.oc_platform or 'this iGPU'} on "
         f"{'a laptop panel' if profile.platform == 'laptop' else 'desktop outputs'}"),
        _doc_for("DeviceProperties", amd),
    )]
    if device_id:
        out.append(Decision(
            "DeviceProperties", "device-id", _fmt_value(device_id),
            "fakes a supported iGPU device-id so WhateverGreen picks the right framebuffer",
            _doc_for("DeviceProperties", amd),
        ))
    return out


def _booter_decisions(profile: HardwareProfile, amd: bool) -> list[Decision]:
    section = _booter_section(profile, resizable_bar=profile.resizable_bar)
    quirks = section.get("Quirks", {})
    out: list[Decision] = []
    for name, enabled in quirks.items():
        if enabled and name in _BOOTER_QUIRK_REASON:
            out.append(Decision("Booter", f"Quirks/{name}", "on", _BOOTER_QUIRK_REASON[name],
                                _doc_for("Booter", amd)))
    return out


def _uefi_decisions(profile: HardwareProfile, amd: bool) -> list[Decision]:
    section = _uefi_section(profile)
    drivers = section.get("Drivers", [])
    names = [d["Path"] if isinstance(d, dict) else d for d in drivers]
    out: list[Decision] = []
    if any("HfsPlus" in n for n in names):
        out.append(Decision("UEFI", "Drivers/HfsPlus", "loaded",
                            "lets OpenCore read the HFS+ recovery and installer volumes", GUIDE))
    if any("OpenRuntime" in n for n in names):
        out.append(Decision("UEFI", "Drivers/OpenRuntime", "loaded",
                            "required companion to the Booter quirks", GUIDE))
    if any("OpenCanopy" in n for n in names):
        out.append(Decision("UEFI", "Drivers/OpenCanopy", "loaded",
                            "graphical boot picker", GUIDE))
    if any("audio" in n.lower() for n in names):
        out.append(Decision("UEFI", "Drivers/AudioDxe", "loaded",
                            "boot chime and picker voiceover", GUIDE))
    return out


def explain(
    profile: HardwareProfile,
    macos_major: int = 0,
    wifi_kext_mode: str = "itlwm",
    dual_boot: str = "",
) -> list[Decision]:
    amd = profile.cpu_vendor == "amd"
    decisions: list[Decision] = []
    decisions += _macos_decisions(profile, macos_major, amd)
    decisions += _smbios_decisions(profile, amd)
    decisions += _ssdt_decisions(profile, wifi_kext_mode, amd)
    decisions += _kext_decisions(profile, wifi_kext_mode, amd)
    decisions += _kernel_decisions(profile, amd)
    decisions += _bootarg_decisions(profile, macos_major, amd)
    decisions += _deviceprops_decisions(profile, macos_major, amd)
    decisions += _booter_decisions(profile, amd)
    decisions += _uefi_decisions(profile, amd)
    return decisions


_SECTION_ORDER = ["macOS", "SMBIOS", "ACPI", "Kexts", "Kernel", "boot-args",
                  "DeviceProperties", "Booter", "UEFI"]


def to_rows(decisions: list[Decision]) -> list[dict]:
    return [
        {"section": d.section, "setting": d.setting, "value": d.value,
         "reason": d.reason, "doc": d.doc}
        for d in decisions
    ]


def render(decisions: list[Decision]) -> str:
    by_section: dict[str, list[Decision]] = {}
    for d in decisions:
        by_section.setdefault(d.section, []).append(d)

    ordered = [s for s in _SECTION_ORDER if s in by_section]
    ordered += [s for s in by_section if s not in _SECTION_ORDER]

    lines: list[str] = []
    for section in ordered:
        lines.append(f"== {section} ==")
        for d in by_section[section]:
            head = f"  {d.setting}"
            if d.value:
                head += f" = {d.value}"
            lines.append(head)
            lines.append(f"      {d.reason}")
            if d.doc:
                lines.append(f"      {d.doc}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
