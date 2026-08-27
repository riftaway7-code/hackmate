import subprocess
import re
import json
from dataclasses import dataclass, field
from compat import IS_WINDOWS, IS_LINUX, IS_MACOS
import pci_ids

@dataclass
class HardwareProfile:
    cpu_name: str = ""
    cpu_vendor: str = ""
    cpu_codename: str = ""
    cpu_generation: int = 0
    cpu_family: str = ""      # desktop / laptop / hedt
    core_count: int = 0
    thread_count: int = 0

    gpu_name: str = ""
    gpu_vendor: str = ""      # intel / amd / nvidia
    gpu_device_id: str = ""
    gpu_subsystem: str = ""

    dgpu_name: str = ""
    dgpu_vendor: str = ""     # nvidia / amd — only set when discrete GPU alongside Intel iGPU
    dgpu_device_id: str = ""

    audio_name: str = ""
    audio_codec: str = ""     # e.g. ALC295
    audio_pci_device: int = -1
    audio_pci_function: int = -1

    ethernet_name: str = ""
    ethernet_chipset: str = ""  # e.g. Intel I219
    ethernet_pci_device: int = -1
    ethernet_pci_function: int = -1

    wifi_name: str = ""
    wifi_chipset: str = ""
    wifi_pci_device: int = -1
    wifi_pci_function: int = -1

    platform: str = ""        # laptop / desktop
    has_touchpad: bool = False
    touchpad_type: str = "ps2"
    has_thunderbolt: bool = False
    nvme_present: bool = False
    nvme_pci_device: int = -1
    nvme_pci_function: int = -1

    smbios_model: str = ""    # e.g. MacBookPro15,2
    oc_platform: str = ""     # e.g. Kaby Lake-R

    resizable_bar: bool = False
    cpu_brand: str = ""

    raw_pci: list = field(default_factory=list)

def needs_dgpu_disable_prompt(profile: HardwareProfile) -> bool:
    return bool(
        profile.dgpu_vendor
        and (profile.platform == "laptop" or profile.dgpu_vendor == "nvidia")
    )

def has_macos_supported_gpu(profile: HardwareProfile) -> bool:
    """Whether at least one detected GPU has native macOS acceleration."""
    has_supported_intel_igpu = (
        profile.gpu_vendor == "intel" and profile.cpu_generation < 11
    )
    has_amd_gpu = "amd" in (profile.gpu_vendor, profile.dgpu_vendor)
    return has_supported_intel_igpu or has_amd_gpu

def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""

def _ps(command: str) -> str:
    try:
        wrapped = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + command
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", wrapped],
            capture_output=True, timeout=10
        )
        return result.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""

def _lspci() -> list[str]:
    import platform
    if platform.system() == "Darwin":
        raw = _run(["system_profiler", "SPPCIDataType"])
        return raw.splitlines()
    out = _run(["lspci", "-nn"])
    if not out and platform.system() == "Linux":
        out = _run(["lspci"])
    return out.splitlines()

INTEL_GENERATIONS = {
    "0106": (2, "Sandy Bridge", "Sandy Bridge"),
    "0166": (3, "Ivy Bridge", "Ivy Bridge"),
    "0416": (4, "Haswell", "Haswell"),
    "0a16": (4, "Haswell", "Haswell"),
    "0d26": (4, "Haswell", "Haswell"),
    "1616": (5, "Broadwell", "Broadwell"),
    "1626": (5, "Broadwell", "Broadwell"),
    "1916": (6, "Skylake", "Skylake"),
    "191b": (6, "Skylake", "Skylake"),
    "1926": (6, "Skylake", "Skylake"),
    "5916": (7, "Kaby Lake", "Kaby Lake"),
    "591b": (7, "Kaby Lake", "Kaby Lake"),
    "5926": (7, "Kaby Lake", "Kaby Lake"),
    "591c": (7, "Kaby Lake", "Kaby Lake"),
    "591e": (7, "Kaby Lake", "Kaby Lake"),
    "5917": (8, "Kaby Lake-R", "Kaby Lake-R"),  # Intel UHD 620 (T480s/MateBook/XPS)
    "3e9b": (8, "Coffee Lake", "Coffee Lake"),
    "3e92": (8, "Coffee Lake", "Coffee Lake"),
    "3e91": (8, "Coffee Lake", "Coffee Lake"),
    "87c0": (8, "Kaby Lake-R", "Kaby Lake-R"),
    "3ea0": (8, "Whiskey Lake", "Whiskey Lake"),  # UHD 620 Whiskey Lake
    "3ea5": (8, "Whiskey Lake", "Whiskey Lake"),
    "3ea6": (8, "Whiskey Lake", "Whiskey Lake"),
    "3ea9": (8, "Whiskey Lake", "Whiskey Lake"),
    "3e98": (9, "Coffee Lake Refresh", "Coffee Lake"),
    "9b41": (10, "Comet Lake", "Comet Lake"),
    "9bc8": (10, "Comet Lake", "Comet Lake"),
    "9bc4": (10, "Comet Lake", "Comet Lake"),
    "9bca": (10, "Comet Lake", "Comet Lake"),
    "8a52": (10, "Ice Lake", "Ice Lake"),
    "8a5a": (10, "Ice Lake", "Ice Lake"),
    "9a49": (11, "Tiger Lake", "Tiger Lake"),
    "9a40": (11, "Tiger Lake", "Tiger Lake"),
    "46a6": (12, "Alder Lake", "Alder Lake"),
    "4626": (12, "Alder Lake", "Alder Lake"),
    "a7a0": (13, "Raptor Lake", "Raptor Lake"),
    "a7a1": (14, "Raptor Lake Refresh", "Raptor Lake"),
    "a7a8": (14, "Raptor Lake Refresh", "Raptor Lake"),
    "7d55": (15, "Arrow Lake", "Arrow Lake"),
    "7d51": (15, "Arrow Lake", "Arrow Lake"),
}

CPU_OPTIONS = [
    ("intel-2",    "Intel Core i3/i5/i7-2xxx  —  Sandy Bridge (2nd gen desktop)"),
    ("intel-3",    "Intel Core i3/i5/i7-3xxx  —  Ivy Bridge (3rd gen desktop)"),
    ("intel-4",    "Intel Core i3/i5/i7-4xxx  —  Haswell (4th gen desktop)"),
    ("intel-5d",   "Intel Core i5/i7-5xxx  —  Broadwell (5th gen desktop)"),
    ("intel-6d",   "Intel Core i3/i5/i7-6xxx  —  Skylake (6th gen desktop)"),
    ("intel-7d",   "Intel Core i3/i5/i7-7xxx  —  Kaby Lake (7th gen desktop)"),
    ("intel-8d",   "Intel Core i3/i5/i7/i9-8xxx  —  Coffee Lake (8th gen desktop)"),
    ("intel-9d",   "Intel Core i5/i7/i9-9xxx  —  Coffee Lake Refresh (9th gen desktop)"),
    ("intel-10d",  "Intel Core i3/i5/i7/i9-10xxx  —  Comet Lake (10th gen desktop)"),
    ("intel-2m",   "Intel Core i5/i7-2xxx  —  Sandy Bridge (2nd gen laptop)"),
    ("intel-3m",   "Intel Core i5/i7-3xxx  —  Ivy Bridge (3rd gen laptop)"),
    ("intel-4m",   "Intel Core i5/i7-4xxx  —  Haswell (4th gen laptop)"),
    ("intel-5m",   "Intel Core i5/i7-5xxx  —  Broadwell (5th gen laptop)"),
    ("intel-6m",   "Intel Core i3/i5/i7-6xxx  —  Skylake (6th gen laptop)"),
    ("intel-7m",   "Intel Core i3/i5/i7-7xxx  —  Kaby Lake (7th gen laptop)"),
    ("intel-8kr",  "Intel Core i5/i7-8xxx U  —  Kaby Lake-R (8th gen, 4-core laptop)"),
    ("intel-8wl",  "Intel Core i5/i7-8xxx U  —  Whiskey Lake (8th gen, 4-core laptop)"),
    ("intel-8cl",  "Intel Core i7/i9-8xxx H  —  Coffee Lake-H (8th gen, 6-core laptop)"),
    ("intel-9m",   "Intel Core i5/i7/i9-9xxx H  —  Coffee Lake Refresh (9th gen laptop)"),
    ("intel-10cm", "Intel Core i3/i5/i7-10xxx H  —  Comet Lake-H (10th gen laptop)"),
    ("intel-10il", "Intel Core i3/i5/i7-10xxx U/Y  —  Ice Lake (10th gen laptop, Iris Plus)"),
    ("intel-11tl", "Intel Core i5/i7-11xxx  —  Tiger Lake (11th gen laptop, iGPU unsupported)"),
    ("amd-zen1d",  "AMD Ryzen 3/5/7 1xxx  —  Zen (desktop)"),
    ("amd-zenpd",  "AMD Ryzen 3/5/7 2xxx  —  Zen+ (desktop)"),
    ("amd-zen2d",  "AMD Ryzen 5/7/9 3xxx  —  Zen 2 (desktop)"),
    ("amd-tr3",    "AMD Threadripper 3xxx  —  Zen 2 (HEDT)"),
    ("amd-zen3d",  "AMD Ryzen 5/7/9 5xxx  —  Zen 3 (desktop)"),
    ("amd-tr5",    "AMD Threadripper 5xxx  —  Zen 3 (HEDT)"),
    ("amd-zen4d",  "AMD Ryzen 5/7/9 7xxx  —  Zen 4 (desktop, AM5)"),
    ("amd-zen5d",  "AMD Ryzen 5/7/9 9xxx  —  Zen 5 (desktop, AM5)"),
    ("amd-zen1m",  "AMD Ryzen 3/5/7 2xxx U  —  Zen (laptop APU)"),
    ("amd-zenpm",  "AMD Ryzen 3/5/7 3xxx U  —  Zen+ (laptop APU)"),
    ("amd-zen2m",  "AMD Ryzen 4xxx / 5xxx U  —  Zen 2 (laptop APU)"),
    ("amd-zen3m",  "AMD Ryzen 5xxx / PRO 5xxx  —  Zen 3 (laptop APU)"),
    ("amd-zen3pm", "AMD Ryzen 6xxx  —  Zen 3+ (laptop APU)"),
    ("amd-zen4m",  "AMD Ryzen 7xxx / AI 3xx  —  Zen 4 (laptop APU)"),
    ("amd-zen5m",  "AMD Ryzen AI 3xx / 9xxx  —  Zen 5 (laptop APU)"),
]

GPU_OPTIONS = [
    ("",         "Auto / same as CPU iGPU"),
    ("5916",     "Intel HD 620 (Kaby Lake)"),
    ("591b",     "Intel HD 630 (Kaby Lake)"),
    ("5917",     "Intel UHD 620 (Kaby Lake-R)"),
    ("3ea0",     "Intel UHD 620 (Whiskey Lake)"),
    ("3e98",     "Intel UHD 630 (Coffee Lake)"),
    ("9bca",     "Intel UHD 620 (Comet Lake)"),
    ("9bc4",     "Intel UHD 630 (Comet Lake)"),
    ("0166",     "Intel HD 4000 (Ivy Bridge)"),
    ("0416",     "Intel HD 4600 (Haswell)"),
    ("1916",     "Intel HD 520 (Skylake)"),
    ("amd",      "AMD Radeon (iGPU / dGPU)"),
    ("nvidia",   "Nvidia (must disable in BIOS for macOS)"),
]

ETHERNET_OPTIONS = [
    ("",        "None / Unknown"),
    ("rtl8111", "Realtek RTL8111 / RTL8168"),
    ("rtl8125", "Realtek RTL8125 (2.5G)"),
    ("i219",    "Intel I219-V / I219-LM"),
    ("i225",    "Intel I225-V (2.5G)"),
    ("i226",    "Intel I226-V (2.5G)"),
    ("i211",    "Intel I211-AT"),
]

WIFI_OPTIONS = [
    ("",         "None"),
    ("intel",    "Intel (AX200 / AX210 / AC-9260 / AC-8265)"),
    ("broadcom", "Broadcom (BCM94360 / BCM943602)"),
    ("atheros",  "Atheros / Qualcomm"),
    ("realtek",  "Realtek (limited support)"),
]

CPU_META = {
    "intel-2":    (2,  "Sandy Bridge",        "intel", "Sandy Bridge"),
    "intel-3":    (3,  "Ivy Bridge",          "intel", "Ivy Bridge"),
    "intel-4":    (4,  "Haswell",             "intel", "Haswell"),
    "intel-5d":   (5,  "Broadwell",           "intel", "Broadwell"),
    "intel-6d":   (6,  "Skylake",             "intel", "Skylake"),
    "intel-7d":   (7,  "Kaby Lake",           "intel", "Kaby Lake"),
    "intel-8d":   (8,  "Coffee Lake",         "intel", "Coffee Lake"),
    "intel-9d":   (9,  "Coffee Lake Refresh", "intel", "Coffee Lake Refresh"),
    "intel-10d":  (10, "Comet Lake",          "intel", "Comet Lake"),
    "intel-2m":   (2,  "Sandy Bridge",        "intel", "Sandy Bridge"),
    "intel-3m":   (3,  "Ivy Bridge",          "intel", "Ivy Bridge"),
    "intel-4m":   (4,  "Haswell",             "intel", "Haswell"),
    "intel-5m":   (5,  "Broadwell",           "intel", "Broadwell"),
    "intel-6m":   (6,  "Skylake",             "intel", "Skylake"),
    "intel-7m":   (7,  "Kaby Lake",           "intel", "Kaby Lake"),
    "intel-8kr":  (8,  "Kaby Lake-R",         "intel", "Kaby Lake"),
    "intel-8wl":  (8,  "Whiskey Lake",        "intel", "Coffee Lake"),
    "intel-8cl":  (8,  "Coffee Lake-H",       "intel", "Coffee Lake"),
    "intel-9m":   (9,  "Coffee Lake Refresh", "intel", "Coffee Lake Refresh"),
    "intel-10cm": (10, "Comet Lake-H",        "intel", "Comet Lake"),
    "intel-10il": (10, "Ice Lake",            "intel", "Ice Lake"),
    "intel-11tl": (11, "Tiger Lake",          "intel", "Tiger Lake"),
    "amd-zen1d":  (8,  "Zen",                "amd",   "Ryzen"),
    "amd-zenpd":  (8,  "Zen+",               "amd",   "Ryzen"),
    "amd-zen2d":  (10, "Zen 2",              "amd",   "Ryzen"),
    "amd-tr3":    (10, "Zen 2 Threadripper", "amd",   "Threadripper"),
    "amd-zen3d":  (11, "Zen 3",              "amd",   "Ryzen"),
    "amd-tr5":    (11, "Zen 3 Threadripper", "amd",   "Threadripper"),
    "amd-zen4d":  (12, "Zen 4",              "amd",   "Ryzen"),
    "amd-zen5d":  (12, "Zen 5",              "amd",   "Ryzen"),
    "amd-zen1m":  (8,  "Zen APU",            "amd",   "Ryzen"),
    "amd-zenpm":  (8,  "Zen+ APU",           "amd",   "Ryzen"),
    "amd-zen2m":  (10, "Zen 2 APU",          "amd",   "Ryzen"),
    "amd-zen3m":  (11, "Zen 3 APU",          "amd",   "Ryzen"),
    "amd-zen3pm": (11, "Zen 3+ APU",         "amd",   "Ryzen"),
    "amd-zen4m":  (12, "Zen 4 APU",          "amd",   "Ryzen"),
    "amd-zen5m":  (12, "Zen 5 APU",          "amd",   "Ryzen"),
}

SMBIOS_MAP = {
    (1, "laptop"):  "MacBookPro8,1",
    (1, "desktop"): "MacPro5,1",
    (2, "laptop"):  "MacBookPro8,1",
    (3, "laptop"):  "MacBookPro9,2",
    (4, "laptop"):  "MacBookPro11,1",
    (5, "laptop"):  "MacBookPro12,1",
    (6, "laptop"):  "MacBookPro13,1",
    (7, "laptop"):  "MacBookPro14,1",
    (8, "laptop"):  "MacBookPro15,2",
    (9, "laptop"):  "MacBookPro16,1",
    (10, "laptop"): "MacBookPro16,2",
    (11, "laptop"): "MacBookPro16,1",
    (12, "laptop"): "MacBookPro16,1",
    (13, "laptop"): "MacBookPro16,1",
    (14, "laptop"):  "MacBookPro16,1",
    (15, "laptop"):  "MacBookPro16,1",
    (6, "desktop"):  "iMac17,1",
    (7, "desktop"):  "iMac18,3",
    (8, "desktop"):  "iMac19,1",
    (9, "desktop"):  "iMac19,1",
    (10, "desktop"): "iMac20,1",
    (11, "desktop"): "MacPro7,1",
    (12, "desktop"): "MacPro7,1",
    (13, "desktop"): "MacPro7,1",
    (14, "desktop"): "MacPro7,1",
    (15, "desktop"): "MacPro7,1",
}

ETHERNET_MAP = {
    "i219": "IntelMausiEthernet",
    "i218": "IntelMausiEthernet",
    "i211": "SmallTreeIntel82576",
    "i210": "SmallTreeIntel82576",
    "rtl8111": "RealtekRTL8111",
    "rtl8168": "RealtekRTL8111",
    "rtl8125": "LucyRTL8125Ethernet",
    "ax88": "AtherosE2200Ethernet",
    "bcm57": "BCM57XXEthernet",
}

WIFI_MAP = {
    "intel": "itlwm",
    "broadcom": "AirportBrcmFixup",
    "atheros": "IO80211FamilyLegacy",
    "realtek": None,
}

AUDIO_CODEC_IDS = {
    "10ec:0295": "ALC295",
    "10ec:0256": "ALC256",
    "10ec:0255": "ALC255",
    "10ec:0289": "ALC289",
    "10ec:0294": "ALC294",
    "10ec:0298": "ALC298",
    "10ec:0269": "ALC269",
    "10ec:0282": "ALC282",
    "10ec:0283": "ALC283",
    "10ec:1220": "ALC1220",
    "10ec:0887": "ALC887",
    "10ec:0892": "ALC892",
    "10ec:0897": "ALC897",
    "8086:2284": "Intel Smart Sound",
}

_INTEL_CODENAMES = {
    1: "Nehalem/Westmere",
    2: "Sandy Bridge", 3: "Ivy Bridge", 4: "Haswell", 5: "Broadwell",
    6: "Skylake", 7: "Kaby Lake", 8: "Coffee Lake", 9: "Coffee Lake Refresh",
    10: "Ice Lake / Comet Lake", 11: "Tiger Lake", 12: "Alder Lake",
    13: "Raptor Lake", 14: "Raptor Lake Refresh", 15: "Arrow Lake",
}


def _parse_intel_model(name: str) -> tuple[int, str]:
    """Generation + codename from an Intel CPU model string; (0, "") if unknown.

    Replaces three diverging copies of a digit heuristic whose 4-digit rule
    ("starts with 1 → gen 10") predates Tiger/Alder/Raptor mobile chips:
    i3-1115G4 (11th), i5-1235U (12th) and i5-1334U (13th) were all being
    filed as gen 10 "Ice Lake / Comet Lake" — dozens of hwdb reports carry
    exactly that wrong tag. First two digits ARE the generation for every
    1xxx mobile model (1065G7→10, 1135G7→11, 1235U→12, 1334U→13)."""
    low = name.lower()

    if "xeon" in low:
        m = re.search(r"\bv(\d)\b", low)
        if m:
            gen = {2: 3, 3: 4, 4: 5, 5: 6, 6: 7}.get(int(m.group(1)), 0)
        elif re.search(r"\be[357]-\d{4}\b", low):
            gen = 2  # v1 Xeons (no suffix) are Sandy Bridge era
        else:
            gen = 0
        return gen, _INTEL_CODENAMES.get(gen, "")

    m1 = re.search(r"i[357]-(\d{3})\b", name, re.IGNORECASE)
    if m1:
        return 1, _INTEL_CODENAMES[1]

    m = re.search(r"i[3579]-(\d{4,5})", name, re.IGNORECASE)
    if not m:
        return 0, ""
    num = m.group(1)
    gen = int(num[:2]) if (len(num) == 5 or num[0] == "1") else int(num[0])
    if not (2 <= gen <= 15):
        return 0, ""
    codename = _INTEL_CODENAMES.get(gen, "Unknown")
    if gen == 10:
        # 4-digit 10xxGx = Ice Lake, 5-digit 10xxx = Comet Lake
        codename = "Ice Lake" if len(num) == 4 else "Comet Lake"
    elif gen == 11:
        codename = "Tiger Lake" if len(num) == 4 else "Rocket Lake"
    return gen, codename


_OC_PLATFORM_MAP = {
    15: "Arrow Lake",  14: "Raptor Lake", 13: "Raptor Lake", 12: "Alder Lake",
    11: "Tiger Lake",  10: "Ice Lake",    9:  "Coffee Lake",
    8:  "Coffee Lake", 7:  "Kaby Lake",   6:  "Skylake",
    5:  "Broadwell",   4:  "Haswell",     3:  "Ivy Bridge",
    2:  "Sandy Bridge", 1: "Nehalem/Westmere",
}


def _oc_platform_for(gen: int, platform: str, codename: str = "") -> str:
    """Gen 11 splits by form factor: Tiger Lake is laptop-only, Rocket Lake is
    desktop-only, and they need different OpenCore platform handling (Rocket
    Lake's Xe iGPU has no macOS driver at all — see hardware_warnings())."""
    if gen == 11:
        return "Rocket Lake" if platform == "desktop" else "Tiger Lake"
    return _OC_PLATFORM_MAP.get(gen, codename or "Unknown")


def _detect_oc_platform(profile: HardwareProfile):
    """Fill the OpenCore platform after the system form factor is known."""
    if "intel" in profile.cpu_vendor and not profile.oc_platform:
        profile.oc_platform = _oc_platform_for(
            profile.cpu_generation, profile.platform, profile.cpu_codename
        )


def _detect_cpu_linux(profile: HardwareProfile):
    cpuinfo = _run(["cat", "/proc/cpuinfo"])
    for line in cpuinfo.splitlines():
        if "model name" in line and not profile.cpu_name:
            profile.cpu_name = line.split(":")[1].strip()
        if "vendor_id" in line and not profile.cpu_vendor:
            profile.cpu_vendor = line.split(":")[1].strip().lower()

    for line in cpuinfo.splitlines():
        if "siblings" in line and not profile.thread_count:
            try: profile.thread_count = int(line.split(":")[1])
            except ValueError: pass
        elif "cpu cores" in line and not profile.core_count:
            try: profile.core_count = int(line.split(":")[1])
            except ValueError: pass

    if "intel" in profile.cpu_vendor:
        for line in profile.raw_pci:
            if "VGA" in line or "Display" in line:
                m = re.search(r'\[8086:([0-9a-f]{4})\]', line.lower())
                if m:
                    dev_id = m.group(1)
                    if dev_id in INTEL_GENERATIONS:
                        gen, codename, oc_platform = INTEL_GENERATIONS[dev_id]
                        profile.cpu_generation = gen
                        profile.cpu_codename = codename
                        profile.oc_platform = oc_platform
                        break

        if not profile.cpu_generation:
            gen, codename = _parse_intel_model(profile.cpu_name)
            if gen:
                profile.cpu_generation = gen
                profile.cpu_codename = codename

        if not profile.cpu_generation:
            _infer_intel_gen_from_name(profile)
    elif "amd" in profile.cpu_vendor or "amd" in profile.cpu_name.lower():
        profile.cpu_vendor = "amd"
        _detect_amd_gen(profile)

def _detect_cpu_windows(profile: HardwareProfile):
    name = _ps("(Get-WmiObject Win32_Processor | Select-Object -First 1).Name")
    profile.cpu_name = name.strip()
    vendor = "intel" if "intel" in name.lower() else "amd" if "amd" in name.lower() else "unknown"
    profile.cpu_vendor = vendor

    if vendor == "intel":
        gen, codename = _parse_intel_model(name)
        profile.cpu_generation = gen
        profile.cpu_codename = codename or "Unknown"

        if profile.gpu_device_id:
            dev_id = profile.gpu_device_id.lower()
            if dev_id in INTEL_GENERATIONS:
                gen, codename, oc_platform = INTEL_GENERATIONS[dev_id]
                profile.cpu_generation = gen
                profile.cpu_codename = codename
                profile.oc_platform = oc_platform

        if not profile.cpu_generation:
            _infer_intel_gen_from_name(profile)
    elif vendor == "amd":
        _detect_amd_gen(profile)

    # Core/thread count
    try:
        cores_raw = _ps("(Get-WmiObject Win32_Processor).NumberOfCores")
        if cores_raw.isdigit():
            profile.core_count = int(cores_raw)
        threads_raw = _ps("(Get-WmiObject Win32_Processor).NumberOfLogicalProcessors")
        if threads_raw.isdigit():
            profile.thread_count = int(threads_raw)
    except Exception:
        pass

def _infer_intel_gen_from_name(profile: HardwareProfile):
    name = profile.cpu_name.lower()
    if (
        "15th" in name
        or "arrow" in name
        or "core ultra 200" in name
        or re.search(r"core ultra\s+\d\s+2\d{2}", name)
    ):
        profile.cpu_generation = 15
        profile.cpu_codename = "Arrow Lake"
        profile.oc_platform = "Arrow Lake"
    elif "core ultra" in name:
        profile.cpu_generation = 14
        profile.cpu_codename = "Meteor Lake"
        profile.oc_platform = "Meteor Lake"
    elif "14th" in name or "raptor lake refresh" in name:
        profile.cpu_generation = 14
        profile.cpu_codename = "Raptor Lake Refresh"
        profile.oc_platform = "Raptor Lake"
    elif "13th" in name or "raptor" in name:
        profile.cpu_generation = 13
        profile.cpu_codename = "Raptor Lake"
        profile.oc_platform = "Raptor Lake"
    elif "12th" in name or "alder" in name:
        profile.cpu_generation = 12
        profile.cpu_codename = "Alder Lake"
        profile.oc_platform = "Alder Lake"
    elif "11th" in name or "tiger" in name or "rocket" in name:
        profile.cpu_generation = 11
        profile.cpu_codename = "Rocket Lake" if "rocket" in name else "Tiger Lake"
    elif "10th" in name or "comet" in name or "ice" in name:
        profile.cpu_generation = 10
        profile.cpu_codename = "Comet Lake"
        profile.oc_platform = "Comet Lake"
    elif "9th" in name or "coffee lake refresh" in name or "coffee lake-r" in name:
        profile.cpu_generation = 9
        profile.cpu_codename = "Coffee Lake Refresh"
        profile.oc_platform = "Coffee Lake"
    elif "8th" in name or "coffee" in name or "kaby lake-r" in name or "whiskey" in name:
        profile.cpu_generation = 8
        profile.cpu_codename = "Whiskey Lake" if "whiskey" in name else "Coffee Lake / Kaby Lake-R"
        profile.oc_platform = "Kaby Lake-R"
    elif "7th" in name or "kaby" in name:
        profile.cpu_generation = 7
        profile.cpu_codename = "Kaby Lake"
        profile.oc_platform = "Kaby Lake"
    elif "6th" in name or "skylake" in name:
        profile.cpu_generation = 6
        profile.cpu_codename = "Skylake"
        profile.oc_platform = "Skylake"
    elif "5th" in name or "broadwell" in name:
        profile.cpu_generation = 5
        profile.cpu_codename = "Broadwell"
        profile.oc_platform = "Broadwell"
    elif "4th" in name or "haswell" in name:
        profile.cpu_generation = 4
        profile.cpu_codename = "Haswell"
        profile.oc_platform = "Haswell"

def _set_cpu_brand(profile: HardwareProfile):
    name = profile.cpu_name.lower()
    if "xeon" in name:
        profile.cpu_brand = "Xeon"
    elif "pentium" in name:
        profile.cpu_brand = "Pentium"
    elif "celeron" in name:
        profile.cpu_brand = "Celeron"
    elif "atom" in name:
        profile.cpu_brand = "Atom"
    elif "core ultra" in name:
        profile.cpu_brand = "Core Ultra"
    elif "ryzen" in name:
        profile.cpu_brand = "Ryzen"
    elif "threadripper" in name:
        profile.cpu_brand = "Threadripper"
    else:
        profile.cpu_brand = "Core"

def _detect_amd_gen(profile: HardwareProfile):
    name = profile.cpu_name.lower()
    if "ryzen ai" in name:
        profile.cpu_generation = 12
        profile.cpu_codename = "Zen 5"
    elif "ryzen" in name or "threadripper" in name:
        # Match model number after "ryzen [pro] N NNNN" — avoids grabbing frequencies or years
        m = re.search(r'ryzen\s+(?:threadripper\s+)?\d*\s*(?:pro\s+)?(\d{4})', name) \
            or re.search(r'(\d{4})', name)
        if m:
            model = int(m.group(1))
            sfx = re.search(rf'{model}([a-z]+)', name.replace(" ", ""))
            u_series = bool(sfx) and sfx.group(1).startswith("u")  # 5700U vs 5700/5700X
            g_series = bool(sfx) and sfx.group(1).startswith("g")  # 2400G vs 2400/2400X
            hundreds = (model // 100) % 10
            if model >= 9000:
                profile.cpu_generation = 12
                profile.cpu_codename = "Zen 5"
            elif model >= 8000:
                profile.cpu_generation = 12
                profile.cpu_codename = "Zen 4"
            elif model >= 7000:
                third = (model // 10) % 10
                if third == 2:
                    profile.cpu_generation = 10
                    profile.cpu_codename = "Zen 2"
                elif third == 3:
                    profile.cpu_generation = 11
                    profile.cpu_codename = "Zen 3"
                else:
                    profile.cpu_generation = 12
                    profile.cpu_codename = "Zen 4"
            elif model >= 6000:
                profile.cpu_generation = 11
                profile.cpu_codename = "Zen 3+"
            elif model >= 5000:
                if u_series and hundreds in (3, 5, 7):
                    profile.cpu_generation = 10
                    profile.cpu_codename = "Zen 2"
                else:
                    profile.cpu_generation = 11
                    profile.cpu_codename = "Zen 3"
            elif model >= 3000:
                if g_series or u_series:
                    profile.cpu_generation = 8
                    profile.cpu_codename = "Zen+"
                else:
                    profile.cpu_generation = 10
                    profile.cpu_codename = "Zen 2"
            elif model >= 2000:
                profile.cpu_generation = 8
                profile.cpu_codename = "Zen" if g_series else "Zen+"
            else:
                profile.cpu_generation = 8
                profile.cpu_codename = "Zen"
        else:
            profile.cpu_generation = 8
            profile.cpu_codename = "Zen (Ryzen)"
    elif "athlon" in name and ("200" in name or "300" in name):
        profile.cpu_generation = 8
        profile.cpu_codename = "Zen (Athlon)"
    elif any(k in name for k in ("fx-", "fx(tm)", "phenom", " a4-", " a6-", " a8-", " a10-", " a12-")):
        profile.cpu_generation = 0
        profile.cpu_codename = "Pre-Zen (unsupported vanilla)"
    else:
        profile.cpu_generation = 8
        profile.cpu_codename = "AMD (unknown)"
    profile.oc_platform = "Ryzen"

def _detect_platform_linux(profile: HardwareProfile):
    battery = _run(["ls", "/sys/class/power_supply/"])
    profile.platform = "laptop" if "BAT" in battery else "desktop"

    dmesg = _run(["dmesg"])
    touchpad_files = _run(["find", "/sys/bus/i2c/devices", "-name", "*trackpad*", "-o", "-name", "*touchpad*"])

    for line in profile.raw_pci:
        if "thunderbolt" in line.lower() or "alpine ridge" in line.lower() or "titan ridge" in line.lower():
            profile.has_thunderbolt = True

    profile.nvme_present = "nvme" in _run(["lsblk", "-d", "-o", "NAME,TRAN"]).lower()

    if profile.platform == "desktop":
        profile.has_touchpad = False
        profile.touchpad_type = "n/a"
        return

    profile.has_touchpad = (
        "synaptics" in dmesg.lower()
        or "i2c-hid" in dmesg.lower()
        or bool(touchpad_files)
        or any("i2c" in l.lower() and ("hid" in l.lower() or "touch" in l.lower()) for l in profile.raw_pci)
    )

    from compat import detect_touchpad_type
    profile.touchpad_type = detect_touchpad_type()

def _detect_platform_windows(profile: HardwareProfile):
    chassis = _ps(
        "(Get-WmiObject Win32_SystemEnclosure).ChassisTypes | ForEach-Object { $_ }"
    )
    laptop_types = {"8", "9", "10", "11", "12", "14"}
    desktop_types = {"3", "4", "5", "6", "7", "13", "15", "16", "17", "23"}
    chassis_ids = re.findall(r"\d+", chassis)
    if any(t in laptop_types for t in chassis_ids):
        profile.platform = "laptop"
    elif any(t in desktop_types for t in chassis_ids):
        # Trust an explicit desktop chassis type over the battery fallback below —
        # UPS software (APC, CyberPower) registers its own Win32_Battery entry,
        # which used to misclassify UPS-equipped desktops as laptops.
        profile.platform = "desktop"
    else:
        battery_names = _ps(
            "(Get-WmiObject Win32_Battery | Select-Object -ExpandProperty Name) -join '|'"
        )
        real_battery = bool(battery_names.strip()) and not re.search(
            r"\bups\b", battery_names, re.IGNORECASE
        )
        profile.platform = "laptop" if real_battery else "desktop"

    # NVMe
    out = _ps("Get-PhysicalDisk | Where-Object {$_.BusType -eq 'NVMe'} | Measure-Object | Select-Object -ExpandProperty Count")
    try:
        profile.nvme_present = int(out.strip()) > 0
    except Exception:
        profile.nvme_present = False

    # Thunderbolt — check for Thunderbolt controllers
    tb = _ps("Get-PnpDevice | Where-Object {$_.Class -eq 'System' -and $_.FriendlyName -match 'Thunderbolt'} | Measure-Object | Select-Object -ExpandProperty Count")
    try:
        profile.has_thunderbolt = int(tb.strip()) > 0
    except Exception:
        profile.has_thunderbolt = False

    if profile.platform == "desktop":
        profile.has_touchpad = False
        profile.touchpad_type = "n/a"
    else:
        from compat import detect_touchpad_type
        profile.touchpad_type = detect_touchpad_type()
        profile.has_touchpad = profile.touchpad_type != "none"

def _extract_device_name(line: str) -> str:
    m = re.search(r'\]: (.+?) \[', line)
    if m:
        return m.group(1).strip()
    parts = line.split("]: ")
    if len(parts) > 1:
        return parts[1].split("[")[0].strip()
    return line.split(":")[-1].strip()

_UNHELPFUL_NAME_RE = re.compile(
    r"^(unknown device|device( \S+)?|vga compatible controller|3d controller|display controller)$",
    re.IGNORECASE,
)


def _is_unhelpful_device_name(name: str) -> bool:
    return not name or bool(_UNHELPFUL_NAME_RE.match(name.strip()))


def _detect_gpu_linux(profile: HardwareProfile):
    names = []
    ids_by_name = {}
    for line in profile.raw_pci:
        if "VGA" in line or "Display" in line or "3D" in line:
            lower = line.lower()
            m = re.search(r'\[([0-9a-f]{4}:[0-9a-f]{4})\]', line)
            ids = m.group(1).lower() if m else ""
            name = _extract_device_name(line)
            if _is_unhelpful_device_name(name) and ids:
                fallback = pci_ids.pci_device_name(ids[:4], ids[5:])
                if fallback:
                    name = fallback
            if "8086" in ids and "intel" not in lower:
                name = f"Intel {name}"
            elif "10de" in ids and "nvidia" not in lower:
                name = f"NVIDIA {name}"
            elif "1002" in ids and "amd" not in lower and "radeon" not in lower:
                name = f"AMD {name}"
            names.append(name)
            ids_by_name[name] = ids

    igpu_name, igpu_vendor, dgpu_name, dgpu_vendor = _classify_gpus(names)
    if igpu_name:
        profile.gpu_name, profile.gpu_vendor = igpu_name, igpu_vendor
        profile.gpu_device_id = ids_by_name.get(igpu_name, "")
        profile.dgpu_name, profile.dgpu_vendor = dgpu_name, dgpu_vendor
        profile.dgpu_device_id = ids_by_name.get(dgpu_name, "")
    elif dgpu_name:
        profile.gpu_name, profile.gpu_vendor = dgpu_name, dgpu_vendor
        profile.gpu_device_id = ids_by_name.get(dgpu_name, "")
    elif names:
        profile.gpu_name = names[0]
        profile.gpu_device_id = ids_by_name.get(names[0], "")

_VIRTUAL_GPU_KEYWORDS = (
    "microsoft", "virtual", "remote", "parsec", "displaylink", "spacedesk",
    "vmware", "virtualbox", "citrix", "teamviewer", "idd", "meta",
)


def _classify_gpus(gpus: list[str]) -> tuple[str, str, str, str]:
    """(igpu_name, igpu_vendor, dgpu_name, dgpu_vendor) from GPU name list.

    The old logic assigned whatever came first as "the" GPU and only ever
    demoted to dGPU when an Intel iGPU had already been seen — so on AMD
    systems, F/KF-series Intel, and any machine where WMI listed the discrete
    card first, RTX 3050s and RX 6600 XTs were filed as "igpu" with "dgpu:
    none" all over hwdb. Classify by what the card actually is instead."""
    igpu_name = igpu_vendor = ""
    nvidia_name = amd_discrete_name = ""
    for name in gpus:
        lower = name.lower()
        if any(k in lower for k in _VIRTUAL_GPU_KEYWORDS):
            continue
        if "intel" in lower or re.search(r"\b(uhd|iris|hd graphics)\b", lower):
            if not igpu_name:
                igpu_name, igpu_vendor = name, "intel"
        elif "nvidia" in lower or "geforce" in lower or "quadro" in lower or "rtx" in lower or "gtx" in lower:
            if not nvidia_name:
                nvidia_name = name
        elif "amd" in lower or "radeon" in lower or "ati " in lower:
            if "vega" in lower:
                discrete = bool(re.search(r"\bvega (?:56|64|vii)\b", lower))
            else:
                discrete = bool(re.search(r"\brx[\s\d]|\br[579] \d{3}\b|firepro|radeon pro|\bxt\b", lower))
            if discrete:
                if not amd_discrete_name:
                    amd_discrete_name = name
            elif not igpu_name:
                igpu_name, igpu_vendor = name, "amd"

    if not igpu_name and amd_discrete_name and nvidia_name:
        return amd_discrete_name, "amd", nvidia_name, "nvidia"

    if nvidia_name:
        dgpu_name, dgpu_vendor = nvidia_name, "nvidia"
    elif amd_discrete_name:
        dgpu_name, dgpu_vendor = amd_discrete_name, "amd"
    else:
        dgpu_name = dgpu_vendor = ""
    return igpu_name, igpu_vendor, dgpu_name, dgpu_vendor


def _detect_gpu_windows(profile: HardwareProfile):
    raw = _ps(
        "Get-WmiObject Win32_VideoController | "
        "Select-Object Name,PNPDeviceID | ConvertTo-Json -Compress"
    ).strip()
    controllers = []
    try:
        controllers = json.loads(raw) if raw else []
        if isinstance(controllers, dict):
            controllers = [controllers]
        if not isinstance(controllers, list):
            controllers = []
    except (TypeError, ValueError):
        controllers = []

    for item in controllers:
        if not isinstance(item, dict):
            continue
        if str(item.get("Name", "")).strip():
            continue
        pnp = str(item.get("PNPDeviceID", ""))
        ven = re.search(r"VEN_([0-9A-Fa-f]{4})", pnp)
        dev = re.search(r"DEV_([0-9A-Fa-f]{4})", pnp)
        if ven and dev:
            fallback = pci_ids.pci_device_name(ven.group(1), dev.group(1))
            if fallback:
                item["Name"] = fallback

    gpus = [
        str(item.get("Name", "")).strip()
        for item in controllers
        if isinstance(item, dict) and str(item.get("Name", "")).strip()
    ]
    if not gpus:
        names_raw = _ps(
            "(Get-WmiObject Win32_VideoController | "
            "ForEach-Object { $_.Name }) -join '||'"
        ).strip()
        gpus = [name.strip() for name in names_raw.split("||") if name.strip()]

    ids_by_name = {}
    for item in controllers:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name", "")).strip()
        pnp = str(item.get("PNPDeviceID", ""))
        match = re.search(r"DEV_([0-9A-Fa-f]{4})", pnp)
        if name and match:
            ids_by_name[name] = match.group(1).upper()

    igpu_name, igpu_vendor, dgpu_name, dgpu_vendor = _classify_gpus(gpus)
    if igpu_name:
        profile.gpu_name, profile.gpu_vendor = igpu_name, igpu_vendor
        profile.gpu_device_id = ids_by_name.get(igpu_name, "")
        profile.dgpu_name, profile.dgpu_vendor = dgpu_name, dgpu_vendor
        profile.dgpu_device_id = ids_by_name.get(dgpu_name, "")
    elif dgpu_name:
        profile.gpu_name, profile.gpu_vendor = dgpu_name, dgpu_vendor
        profile.gpu_device_id = ids_by_name.get(dgpu_name, "")
    elif gpus:
        profile.gpu_name = gpus[0]
        profile.gpu_device_id = ids_by_name.get(gpus[0], "")

def _get_hda_codec_linux() -> str:
    try:
        codecs = subprocess.run(["cat", "/proc/asound/card0/codec#0"], capture_output=True, text=True).stdout
        for line in codecs.splitlines():
            if "Codec:" in line:
                return line.split("Codec:")[-1].strip()
    except Exception:
        pass
    return ""

_NOT_ONBOARD_AUDIO_LINUX = (
    "nvidia", "hdmi", "displayport", "display audio", "dp audio", "radeon",
)

def _detect_audio_linux(profile: HardwareProfile):
    fallback = ""
    selected = ""
    for line in profile.raw_pci:
        lower = line.lower()
        if "audio" not in lower and "multimedia" not in lower:
            continue
        if not fallback:
            fallback = line
        if not any(k in lower for k in _NOT_ONBOARD_AUDIO_LINUX):
            selected = line
            break

    selected = selected or fallback
    if not selected:
        return

    addr = _LSPCI_ADDRESS_RE.match(selected)
    if addr:
        profile.audio_pci_device = int(addr.group(1), 16)
        profile.audio_pci_function = int(addr.group(2), 16)
    m = re.search(r'\[([0-9a-f]{4}:[0-9a-f]{4})\]', selected)
    if m:
        ids = m.group(1).lower()
        profile.audio_name = _extract_device_name(selected)
        if ids in AUDIO_CODEC_IDS:
            profile.audio_codec = AUDIO_CODEC_IDS[ids]
        else:
            codec = _get_hda_codec_linux()
            profile.audio_codec = codec if codec else ids

def _get_hda_codec_windows() -> str:
    try:
        raw = _ps(
            "(Get-PnpDevice | Where-Object { $_.InstanceId -match 'HDAUDIO.*VEN_10EC' } | "
            "Select-Object -ExpandProperty InstanceId) -join '||'"
        ).strip()
    except Exception:
        return ""
    for instance_id in raw.split("||"):
        m = re.search(r"VEN_10EC&DEV_([0-9A-Fa-f]{4})", instance_id)
        if m:
            model = m.group(1).lstrip("0") or "0"
            return f"ALC{model}"
    return ""

def _detect_audio_windows(profile: HardwareProfile):
    raw = _ps("(Get-WmiObject Win32_SoundDevice | ForEach-Object { $_.Name }) -join '||'").strip()
    devices = [d.strip() for d in raw.split("||") if d.strip()]

    _NOT_ONBOARD = (
        "nvidia", "steam", "virtual", "usb", "bluetooth", "hdmi", "displayport",
        "display audio", "streaming", "focusrite", "webcam", "camera", "monitor",
        "wave extensible", "dp audio", "smart sound",
    )

    best = ""
    for dev in devices:
        if re.search(r'ALC\d{3,4}', dev, re.IGNORECASE):
            best = dev
            break
    if not best:
        best = next((d for d in devices if "realtek" in d.lower()), "")
    if not best:
        best = next((d for d in devices
                     if not any(k in d.lower() for k in _NOT_ONBOARD)), "")
    if not best and devices:
        best = devices[0]

    profile.audio_name = best
    m = re.search(r'ALC(\d{3,4})', best.upper())
    if m:
        profile.audio_codec = f"ALC{m.group(1)}"
    elif "realtek" in best.lower():
        profile.audio_codec = _get_hda_codec_windows() or "Realtek"
    else:
        profile.audio_codec = best

_LSPCI_ADDRESS_RE = re.compile(r'^[0-9a-f]{2,4}:([0-9a-f]{2})\.([0-9a-f])')


def _detect_nvme_linux(profile: HardwareProfile):
    for line in profile.raw_pci:
        if "non-volatile memory controller" in line.lower():
            addr = _LSPCI_ADDRESS_RE.match(line)
            if addr:
                profile.nvme_pci_device = int(addr.group(1), 16)
                profile.nvme_pci_function = int(addr.group(2), 16)
            break


def _detect_network_linux(profile: HardwareProfile):
    for line in profile.raw_pci:
        lower = line.lower()
        if "ethernet" in lower or "network" in lower or "wireless" in lower or "wi-fi" in lower or "wlan" in lower:
            name = _extract_device_name(line)
            if "wireless" in lower or "wi-fi" in lower or "wlan" in lower or "802.11" in lower:
                profile.wifi_name = name
                if "intel" in lower:
                    profile.wifi_chipset = "intel"
                elif "broadcom" in lower or "bcm" in lower:
                    profile.wifi_chipset = "broadcom"
                elif "atheros" in lower or "qualcomm" in lower:
                    profile.wifi_chipset = "atheros"
                elif "realtek" in lower:
                    profile.wifi_chipset = "realtek"
                addr = _LSPCI_ADDRESS_RE.match(line)
                if addr:
                    profile.wifi_pci_device = int(addr.group(1), 16)
                    profile.wifi_pci_function = int(addr.group(2), 16)
            else:
                profile.ethernet_name = name
                if "i225" in lower:
                    profile.ethernet_chipset = "i225"
                elif "i226" in lower:
                    profile.ethernet_chipset = "i226"
                elif "i219" in lower or "i218" in lower:
                    profile.ethernet_chipset = "i219"
                elif "i211" in lower or "i210" in lower:
                    profile.ethernet_chipset = "i211"
                elif "rtl8125" in lower:
                    profile.ethernet_chipset = "rtl8125"
                elif "rtl" in lower or "realtek" in lower:
                    profile.ethernet_chipset = "rtl8111"
                elif "ax88" in lower or "asix" in lower:
                    profile.ethernet_chipset = "ax88"
                addr = _LSPCI_ADDRESS_RE.match(line)
                if addr:
                    profile.ethernet_pci_device = int(addr.group(1), 16)
                    profile.ethernet_pci_function = int(addr.group(2), 16)

def _detect_network_windows(profile: HardwareProfile):
    raw = _ps("""
        $nic = Get-NetAdapter -Physical -ErrorAction Stop | Where-Object {
            $_.InterfaceDescription -notmatch 'Wi-Fi|Wireless|WiFi|802.11|Bluetooth'
        } | Select-Object -First 1
        $nic.InterfaceDescription
    """)
    profile.ethernet_name = raw.strip()
    name_lower = raw.lower()
    if "i219" in name_lower: profile.ethernet_chipset = "i219"
    elif "i218" in name_lower: profile.ethernet_chipset = "i218"
    elif "i217" in name_lower: profile.ethernet_chipset = "i217"
    elif "i225" in name_lower: profile.ethernet_chipset = "i225"
    elif "i226" in name_lower: profile.ethernet_chipset = "i226"
    elif "rtl8111" in name_lower or "rtl8168" in name_lower: profile.ethernet_chipset = "rtl8111"
    elif "rtl8125" in name_lower: profile.ethernet_chipset = "rtl8125"
    elif "rtl8100" in name_lower: profile.ethernet_chipset = "rtl8100"
    elif "realtek" in name_lower: profile.ethernet_chipset = "rtl8111"

    # WiFi
    raw = _ps("""
        $nic = Get-CimInstance Win32_NetworkAdapter | Where-Object {
            $_.Name -match 'Wi-Fi|Wireless|WiFi|802.11'
        } | Select-Object -First 1
        $nic.Name
    """)
    profile.wifi_name = raw.strip()
    name_lower = raw.lower()
    if "intel" in name_lower: profile.wifi_chipset = "intel"
    elif "broadcom" in name_lower: profile.wifi_chipset = "broadcom"
    elif "atheros" in name_lower or "qualcomm" in name_lower: profile.wifi_chipset = "atheros"
    elif "realtek" in name_lower: profile.wifi_chipset = "realtek"
    elif "mediatek" in name_lower: profile.wifi_chipset = "mediatek"

    if not profile.wifi_chipset:
        intel_wifi_ids = "0070|0074|4070|2723|2725|0094"
        raw_pnp = _ps(f"""
            (Get-PnpDevice -PresentOnly | Where-Object {{
                $_.InstanceId -match 'PCI\\\\VEN_8086&DEV_({intel_wifi_ids})'
            }} | Select-Object -First 1).InstanceId
        """)
        if raw_pnp.strip():
            profile.wifi_chipset = "intel"
            if not profile.wifi_name:
                profile.wifi_name = "Intel WiFi (no driver installed)"

def hardware_warnings(profile: HardwareProfile) -> list[str]:
    """Known-bad configurations per the Dortania guide's Hardware Limitations
    page (macos-limits.html) that HackMate can detect from fields already on
    the profile, without adding new hardware probing. These are dead ends or
    near-dead-ends today, independent of anything HackMate's pipeline can fix —
    surfacing them here means a user finds out before building, not after a
    failed boot."""
    warnings: list[str] = []
    name = profile.cpu_name.lower()

    if profile.cpu_vendor == "amd" and profile.platform == "laptop":
        warnings.append(
            "AMD laptop CPUs (Ryzen mobile APUs) are not supported by the AMD "
            "Vanilla patch set — this build will not boot."
        )

    if profile.platform == "laptop" and any(k in name for k in ("atom", "celeron", "pentium")):
        warnings.append(
            "Mobile Atom/Celeron/Pentium CPUs are not supported on laptops — "
            "this build will not boot."
        )

    if (
        profile.cpu_vendor == "intel"
        and profile.cpu_generation >= 11
        and profile.gpu_vendor == "intel"
    ):
        if profile.platform == "laptop":
            warnings.append(
                "Tiger Lake and newer Intel Xe integrated graphics have no "
                "macOS driver — laptop internal displays normally depend on "
                "that iGPU, so this machine will not have usable accelerated "
                "graphics."
            )
        elif profile.dgpu_vendor != "amd":
            warnings.append(
                "Rocket Lake and newer Intel integrated graphics have no "
                "macOS driver — a supported AMD discrete GPU is required for "
                "usable video output."
            )
        else:
            warnings.append(
                "This Intel integrated GPU has no macOS driver and will be "
                "left unconfigured — disable it in BIOS and use the supported "
                "AMD discrete GPU for every display."
            )

    if not has_macos_supported_gpu(profile):
        warnings.append(
            "This system has no macOS-supported GPU for accelerated display. "
            "HackMate enables GOP passthrough for basic, unaccelerated firmware-"
            "framebuffer output during installation; use it to finish Setup "
            "Assistant, then enable Screen Sharing in System Settings > General "
            "> Sharing > Screen Sharing (or Remote Login for SSH) for headless "
            "operation, which does not require display acceleration once enabled."
        )

    if profile.wifi_chipset == "atheros":
        warnings.append(
            "Atheros WiFi support tops out at macOS High Sierra (10.13) — it "
            "will not work on any newer macOS version."
        )

    if profile.wifi_chipset == "intel":
        warnings.append(
            "AirportItlwm (menu-bar-integrated Intel WiFi) has no upstream "
            "build past macOS Sonoma — Sequoia and Tahoe are stuck with "
            "itlwm + HeliPort, which works but isn't Apple's native AirPort "
            "stack. Switching to a Broadcom card is not a guaranteed fix "
            "either: Apple also dropped native driver support for most "
            "Broadcom WiFi chips starting in Sonoma, so those need OpenCore "
            "Legacy Patcher's WiFi/Bluetooth root patch after install too — "
            "or, for some chipsets, "
            "github.com/0xFireWolf/AppleBCMWLANCompanion instead."
        )

    if profile.wifi_chipset == "realtek":
        warnings.append(
            "Realtek PCI WiFi cards have no macOS driver on any version — "
            "swap in an Intel, Broadcom, or Atheros/Qualcomm card, or use a "
            "USB WiFi adapter instead."
        )

    return warnings


def detect_smbios(profile: HardwareProfile):
    key = (profile.cpu_generation, profile.platform)
    if profile.cpu_vendor == "amd":
        profile.smbios_model = "MacPro7,1" if profile.platform == "desktop" else "MacBookPro15,2"
    elif key in SMBIOS_MAP:
        profile.smbios_model = SMBIOS_MAP[key]
    else:
        profile.smbios_model = "MacBookPro15,2"

def _sp(data_type: str) -> str:
    try:
        return subprocess.run(
            ["system_profiler", data_type], capture_output=True, text=True, timeout=15
        ).stdout
    except Exception:
        return ""

def _detect_cpu_macos(profile: HardwareProfile):
    profile.cpu_name = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    vendor_raw = _run(["sysctl", "-n", "machdep.cpu.vendor"]).lower()
    if "intel" in vendor_raw:
        profile.cpu_vendor = "intel"
    elif "amd" in vendor_raw or "amd" in profile.cpu_name.lower():
        profile.cpu_vendor = "amd"

    try:
        profile.core_count = int(_run(["sysctl", "-n", "hw.physicalcpu"]) or "0")
        profile.thread_count = int(_run(["sysctl", "-n", "hw.logicalcpu"]) or "0")
    except Exception:
        pass

    # Detect generation from CPU name same as Linux
    if profile.cpu_vendor == "intel":
        name = profile.cpu_name.lower()
        for keyword, gen, codename in [
            ("14th", 14, "Raptor Lake Refresh"), ("13th", 13, "Raptor Lake"),
            ("12th", 12, "Alder Lake"), ("11th", 11, "Tiger Lake"),
            ("10th", 10, "Ice Lake / Comet Lake"), ("8th", 8, "Coffee Lake"),
            ("7th", 7, "Kaby Lake"), ("6th", 6, "Skylake"),
            ("5th", 5, "Broadwell"), ("4th", 4, "Haswell"),
        ]:
            if keyword in name:
                profile.cpu_generation = gen
                profile.cpu_codename = codename
                break

        if not profile.cpu_generation:
            gen, codename = _parse_intel_model(profile.cpu_name)
            if gen:
                profile.cpu_generation = gen
                profile.cpu_codename = codename

        if not profile.cpu_generation:
            _infer_intel_gen_from_name(profile)

    elif profile.cpu_vendor == "amd":
        _detect_amd_gen(profile)

def _detect_gpu_macos(profile: HardwareProfile):
    sp = _sp("SPDisplaysDataType")
    intel_name = ""
    discrete_name = discrete_vendor = ""
    for line in sp.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        name = line.split(":")[-1].strip() if ":" in line else line
        if "intel" in lower and ("uhd" in lower or "iris" in lower or "hd graphics" in lower):
            if not intel_name:
                intel_name = name
        elif "amd" in lower or "radeon" in lower:
            if not discrete_name:
                discrete_name, discrete_vendor = name, "amd"
        elif "nvidia" in lower or "geforce" in lower:
            if not discrete_name:
                discrete_name, discrete_vendor = name, "nvidia"

    if intel_name:
        profile.gpu_name, profile.gpu_vendor = intel_name, "intel"
        profile.dgpu_name, profile.dgpu_vendor = discrete_name, discrete_vendor
    elif discrete_name:
        profile.gpu_name, profile.gpu_vendor = discrete_name, discrete_vendor

_NOT_ONBOARD_AUDIO = (
    "blackhole", "existential audio", "soundflower", "loopback",
    "background music", "obs", "virtual", "steam", "displayport", "hdmi",
)
_GENERIC_AUDIO_HEADERS = ("audio", "devices", "inputs", "outputs")

def _detect_audio_macos(profile: HardwareProfile):
    sp = _sp("SPAudioDataType")
    fallback = ""
    for line in sp.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if "alc" in lower or "realtek" in lower:
            m = re.search(r'alc\d+', lower)
            if m:
                profile.audio_codec = m.group(0).upper()
                profile.audio_name = stripped
                return
        elif stripped.endswith(":"):
            name_lower = stripped[:-1].strip().lower()
            if name_lower in _GENERIC_AUDIO_HEADERS:
                continue
            if any(k in name_lower for k in _NOT_ONBOARD_AUDIO):
                continue
            if "audio" in name_lower and not fallback:
                fallback = stripped.rstrip(":")
    if fallback:
        profile.audio_name = fallback

def _detect_network_macos(profile: HardwareProfile):
    eth = _sp("SPEthernetDataType")
    for line in eth.splitlines():
        stripped = line.strip()
        if not stripped.endswith(":") or ("Ethernet" not in stripped and "Connection" not in stripped):
            continue
        lower = stripped.lower()
        if "i219" in lower or "i218" in lower:
            profile.ethernet_chipset = "i219"
        elif "i225" in lower or "i226" in lower:
            profile.ethernet_chipset = "i225"
        elif "i211" in lower or "i210" in lower:
            profile.ethernet_chipset = "i211"
        elif "rtl8125" in lower:
            profile.ethernet_chipset = "rtl8125"
        elif "rtl" in lower or "realtek" in lower:
            profile.ethernet_chipset = "rtl8111"
        elif "e1000e" in lower or "82574" in lower or "82577" in lower or "82578" in lower:
            profile.ethernet_chipset = "e1000e"
        elif "atheros" in lower or "ar81" in lower:
            profile.ethernet_chipset = "ar81xx"
        elif "broadcom" in lower and "bcm5722" in lower:
            profile.ethernet_chipset = "bcm5722"
        else:
            continue
        profile.ethernet_name = stripped.rstrip(":")
        break

    wifi = _sp("SPAirPortDataType")
    for line in wifi.splitlines():
        lower = line.lower()
        if "card type" in lower or "driver" in lower:
            if "intel" in lower or "itlwm" in lower:
                profile.wifi_chipset = "intel"
                profile.wifi_name = "Intel WiFi"
            elif "broadcom" in lower or "0x14e4" in lower or "brcm" in lower:
                profile.wifi_chipset = "broadcom"
                profile.wifi_name = "Broadcom WiFi"
            elif "atheros" in lower or "0x168c" in lower:
                profile.wifi_chipset = "atheros"
                profile.wifi_name = "Atheros WiFi"
            if profile.wifi_chipset:
                break

_THUNDERBOLT_DEVICE_IDS = {
    "0x15b8", "0x15b9", "0x15ba", "0x15bb", "0x15bc", "0x15bd", "0x15be", "0x15bf",
    "0x15c0", "0x15c1",
    "0x15d2", "0x15d3", "0x15d9", "0x15da", "0x15db", "0x15dc", "0x15dd", "0x15de", "0x15df",
    "0x15e7", "0x15e8", "0x15e9", "0x15ea", "0x15eb", "0x15ec",
}

def _detect_platform_macos(profile: HardwareProfile):
    model = _run(["sysctl", "-n", "hw.model"]).lower()
    profile.platform = "laptop" if "macbook" in model else "desktop"
    profile.has_touchpad = "macbook" in model
    if profile.has_touchpad:
        profile.touchpad_type = "i2c"
    sp = _sp("SPStorageDataType").lower()
    profile.nvme_present = "nvme" in sp or "apple ssd" in sp

    pci = _sp("SPPCIDataType")
    vendor = ""
    for line in pci.splitlines():
        stripped = line.strip()
        if stripped.startswith("Vendor ID:"):
            vendor = stripped.split(":", 1)[1].strip().lower()
        elif stripped.startswith("Device ID:"):
            device = stripped.split(":", 1)[1].strip().lower()
            if vendor == "0x8086" and device in _THUNDERBOLT_DEVICE_IDS:
                profile.has_thunderbolt = True

def scan() -> HardwareProfile:
    profile = HardwareProfile()

    if IS_WINDOWS:
        _detect_gpu_windows(profile)
        _detect_cpu_windows(profile)
        _detect_audio_windows(profile)
        _detect_network_windows(profile)
        _detect_platform_windows(profile)
        _detect_oc_platform(profile)
    elif IS_MACOS:
        _detect_cpu_macos(profile)
        _detect_gpu_macos(profile)
        _detect_audio_macos(profile)
        _detect_network_macos(profile)
        _detect_platform_macos(profile)
        _detect_oc_platform(profile)
    else:
        profile.raw_pci = _lspci()
        _detect_cpu_linux(profile)
        _detect_platform_linux(profile)
        _detect_oc_platform(profile)
        _detect_gpu_linux(profile)
        _detect_audio_linux(profile)
        _detect_network_linux(profile)
        _detect_nvme_linux(profile)

    detect_smbios(profile)
    _set_cpu_brand(profile)
    return profile

if __name__ == "__main__":
    p = scan()
    print(f"CPU:        {p.cpu_name}")
    print(f"Codename:   {p.cpu_codename} (Gen {p.cpu_generation})")
    print(f"Platform:   {p.platform}")
    print(f"OC Target:  {p.oc_platform}")
    print(f"GPU:        {p.gpu_name} [{p.gpu_vendor}]")
    print(f"Audio:      {p.audio_name} / codec: {p.audio_codec}")
    print(f"Ethernet:   {p.ethernet_name} [{p.ethernet_chipset}]")
    print(f"WiFi:       {p.wifi_name} [{p.wifi_chipset}]")
    print(f"Thunderbolt:{p.has_thunderbolt}")
    print(f"NVMe:       {p.nvme_present}")
    print(f"Touchpad:   {p.has_touchpad} ({p.touchpad_type})")
    print(f"SMBIOS:     {p.smbios_model}")
