import subprocess
import re
from dataclasses import dataclass, field
from typing import Optional


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

    audio_name: str = ""
    audio_codec: str = ""     # e.g. ALC295

    ethernet_name: str = ""
    ethernet_chipset: str = ""  # e.g. Intel I219

    wifi_name: str = ""
    wifi_chipset: str = ""

    platform: str = ""        # laptop / desktop
    has_touchpad: bool = False
    has_thunderbolt: bool = False
    nvme_present: bool = False

    smbios_model: str = ""    # e.g. MacBookPro15,2
    oc_platform: str = ""     # e.g. Kaby Lake-R

    raw_pci: list = field(default_factory=list)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _lspci() -> list[str]:
    return _run(["lspci", "-nn"]).splitlines()


INTEL_GENERATIONS = {
    # Sandy Bridge
    "206a": (2, "Sandy Bridge", "Kaby Lake"),
    "0106": (2, "Sandy Bridge", "Sandy Bridge"),
    # Ivy Bridge
    "0166": (3, "Ivy Bridge", "Ivy Bridge"),
    # Haswell
    "0416": (4, "Haswell", "Haswell"),
    "0a16": (4, "Haswell", "Haswell"),
    "0d26": (4, "Haswell", "Haswell"),
    # Broadwell
    "1616": (5, "Broadwell", "Broadwell"),
    "1626": (5, "Broadwell", "Broadwell"),
    # Skylake
    "1916": (6, "Skylake", "Skylake"),
    "191b": (6, "Skylake", "Skylake"),
    "1926": (6, "Skylake", "Skylake"),
    # Kaby Lake
    "5916": (7, "Kaby Lake", "Kaby Lake"),
    "591b": (7, "Kaby Lake", "Kaby Lake"),
    "5926": (7, "Kaby Lake", "Kaby Lake"),
    # Kaby Lake-R / Coffee Lake
    "3e9b": (8, "Coffee Lake", "Coffee Lake"),
    "87c0": (8, "Kaby Lake-R", "Kaby Lake-R"),
    # Whiskey Lake / Amber Lake
    "3ea5": (8, "Whiskey Lake", "Whiskey Lake"),
    # Comet Lake
    "9b41": (10, "Comet Lake", "Comet Lake"),
    "9bc8": (10, "Comet Lake", "Comet Lake"),
    # Ice Lake
    "8a52": (10, "Ice Lake", "Ice Lake"),
    "8a5a": (10, "Ice Lake", "Ice Lake"),
    # Tiger Lake
    "9a49": (11, "Tiger Lake", "Tiger Lake"),
    "9a40": (11, "Tiger Lake", "Tiger Lake"),
    # Alder Lake
    "46a6": (12, "Alder Lake", "Alder Lake"),
    "4626": (12, "Alder Lake", "Alder Lake"),
    # Raptor Lake
    "a7a0": (13, "Raptor Lake", "Raptor Lake"),
}

SMBIOS_MAP = {
    # Intel laptop
    (2, "laptop"):  "MacBookPro8,1",
    (3, "laptop"):  "MacBookPro9,2",
    (4, "laptop"):  "MacBookPro11,1",
    (5, "laptop"):  "MacBookPro12,1",
    (6, "laptop"):  "MacBookPro13,1",
    (7, "laptop"):  "MacBookPro14,1",
    (8, "laptop"):  "MacBookPro15,2",
    (10, "laptop"): "MacBookPro16,2",
    (11, "laptop"): "MacBookPro18,1",
    (12, "laptop"): "MacBookPro18,3",
    (13, "laptop"): "MacBookPro18,3",
    # Intel desktop
    (6, "desktop"):  "iMac17,1",
    (7, "desktop"):  "iMac18,3",
    (8, "desktop"):  "iMac19,1",
    (9, "desktop"):  "iMac19,1",
    (10, "desktop"): "iMac20,1",
    (11, "desktop"): "iMac21,1",
    (12, "desktop"): "iMacPro1,1",
    (13, "desktop"): "iMacPro1,1",
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
    "intel": "itlwm",       # needs HeliPort
    "broadcom": "AirportBrcmFixup",
    "atheros": "IO80211FamilyLegacy",
    "realtek": None,        # not supported
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


def detect_cpu(profile: HardwareProfile):
    cpuinfo = _run(["cat", "/proc/cpuinfo"])
    for line in cpuinfo.splitlines():
        if "model name" in line and not profile.cpu_name:
            profile.cpu_name = line.split(":")[1].strip()
        if "vendor_id" in line and not profile.cpu_vendor:
            profile.cpu_vendor = line.split(":")[1].strip().lower()

    siblings = [l for l in cpuinfo.splitlines() if "siblings" in l]
    cores = [l for l in cpuinfo.splitlines() if "cpu cores" in l]
    if siblings:
        profile.thread_count = int(siblings[0].split(":")[1].strip())
    if cores:
        profile.core_count = int(cores[0].split(":")[1].strip())

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
            name = profile.cpu_name.lower()
            if "12th" in name or "alder" in name or "-12" in name:
                profile.cpu_generation = 12
                profile.cpu_codename = "Alder Lake"
                profile.oc_platform = "Alder Lake"
            elif "11th" in name or "tiger" in name or "-11" in name:
                profile.cpu_generation = 11
                profile.cpu_codename = "Tiger Lake"
                profile.oc_platform = "Tiger Lake"
            elif "10th" in name or "comet" in name or "ice" in name or "-10" in name:
                profile.cpu_generation = 10
                profile.cpu_codename = "Comet Lake"
                profile.oc_platform = "Comet Lake"
            elif "8th" in name or "coffee" in name or "kaby lake-r" in name or "-8" in name:
                profile.cpu_generation = 8
                profile.cpu_codename = "Coffee Lake / Kaby Lake-R"
                profile.oc_platform = "Kaby Lake-R"
            elif "7th" in name or "kaby" in name or "-7" in name:
                profile.cpu_generation = 7
                profile.cpu_codename = "Kaby Lake"
                profile.oc_platform = "Kaby Lake"
            elif "6th" in name or "skylake" in name or "-6" in name:
                profile.cpu_generation = 6
                profile.cpu_codename = "Skylake"
                profile.oc_platform = "Skylake"
            elif "5th" in name or "broadwell" in name or "-5" in name:
                profile.cpu_generation = 5
                profile.cpu_codename = "Broadwell"
                profile.oc_platform = "Broadwell"
            elif "4th" in name or "haswell" in name or "-4" in name:
                profile.cpu_generation = 4
                profile.cpu_codename = "Haswell"
                profile.oc_platform = "Haswell"

    elif "amd" in profile.cpu_vendor or "amd" in profile.cpu_name.lower():
        profile.cpu_vendor = "amd"
        name = profile.cpu_name.lower()

        if "ryzen" in name or "threadripper" in name:
            # Detect Zen architecture from model number.
            # Ryzen: 1xxx=Zen, 2xxx=Zen+, 3xxx=Zen2, 4xxx=Zen2 APU,
            #        5xxx=Zen3, 6xxx=Zen3+ APU, 7xxx=Zen4, 8xxx=Zen4 APU, 9xxx=Zen5
            # Threadripper: 1xxx=Zen, 2xxx=Zen+, 3xxx=Zen2, 5xxx=Zen3, 7xxx=Zen4
            #
            # cpu_generation is mapped to an equivalent Intel generation for use
            # in config_gen.py and kexts.py (SSDT selection, kext selection, quirks).
            # Per the Dortania guide, AMD has no Intel-style generation restrictions
            # for macOS compatibility — all Ryzen CPUs support macOS Sierra through
            # current with appropriate kernel patches.
            m = re.search(r'(\d{4})', name)
            if m:
                model = int(m.group(1))
                if model >= 9000:
                    profile.cpu_generation = 12
                    profile.cpu_codename = "Zen 5"
                elif model >= 7000:
                    profile.cpu_generation = 12
                    profile.cpu_codename = "Zen 4"
                elif model >= 6000:
                    profile.cpu_generation = 11
                    profile.cpu_codename = "Zen 3+"
                elif model >= 5000:
                    profile.cpu_generation = 11
                    profile.cpu_codename = "Zen 3"
                elif model >= 4000:
                    profile.cpu_generation = 10
                    profile.cpu_codename = "Zen 2"
                elif model >= 3000:
                    profile.cpu_generation = 10
                    profile.cpu_codename = "Zen 2"
                elif model >= 2000:
                    profile.cpu_generation = 8
                    profile.cpu_codename = "Zen+"
                else:
                    profile.cpu_generation = 8
                    profile.cpu_codename = "Zen"
            else:
                profile.cpu_generation = 8
                profile.cpu_codename = "Zen (Ryzen)"
        elif "athlon" in name and ("200" in name or "300" in name):
            # Athlon 200GE/300GE series are Zen/Zen+ based
            profile.cpu_generation = 8
            profile.cpu_codename = "Zen (Athlon)"
        else:
            # Unknown AMD CPU — assume Zen or newer
            profile.cpu_generation = 8
            profile.cpu_codename = "AMD (unknown)"

        profile.oc_platform = "Ryzen"


def detect_platform(profile: HardwareProfile):
    battery = _run(["ls", "/sys/class/power_supply/"])
    profile.platform = "laptop" if "BAT" in battery else "desktop"

    touchpad = _run(["find", "/sys/bus/i2c/devices", "-name", "*trackpad*", "-o", "-name", "*touchpad*"])
    i2c_hid = _run(["dmesg"])
    profile.has_touchpad = bool(touchpad) or "i2c-hid" in i2c_hid.lower() or "synaptics" in i2c_hid.lower()

    for line in profile.raw_pci:
        if "thunderbolt" in line.lower() or "alpine ridge" in line.lower() or "titan ridge" in line.lower():
            profile.has_thunderbolt = True

    nvme_check = _run(["lsblk", "-d", "-o", "NAME,TRAN"])
    profile.nvme_present = "nvme" in nvme_check.lower()

    i2c_check = _run(["dmesg"])
    touchpad_files = _run(["find", "/sys/bus/i2c/devices", "-name", "*trackpad*"])
    profile.has_touchpad = (
        "synaptics" in i2c_check.lower()
        or "i2c-hid" in i2c_check.lower()
        or bool(touchpad_files)
        or any("i2c" in l.lower() and ("hid" in l.lower() or "touch" in l.lower()) for l in profile.raw_pci)
    )


def _extract_device_name(line: str) -> str:
    m = re.search(r'\]: (.+?) \[', line)
    if m:
        return m.group(1).strip()
    parts = line.split("]: ")
    if len(parts) > 1:
        return parts[1].split("[")[0].strip()
    return line.split(":")[-1].strip()


def detect_gpu(profile: HardwareProfile):
    for line in profile.raw_pci:
        if "VGA" in line or "Display" in line or "3D" in line:
            lower = line.lower()
            m = re.search(r'\[([0-9a-f]{4}:[0-9a-f]{4})\]', line)
            ids = m.group(1).lower() if m else ""

            if "8086" in ids or "intel" in lower:
                profile.gpu_vendor = "intel"
                profile.gpu_name = _extract_device_name(line)
                profile.gpu_device_id = ids
            elif "1002" in ids or "amd" in lower or "radeon" in lower:
                profile.gpu_vendor = "amd"
                profile.gpu_name = _extract_device_name(line)
                profile.gpu_device_id = ids
            elif "10de" in ids or "nvidia" in lower or "geforce" in lower:
                profile.gpu_vendor = "nvidia"
                profile.gpu_name = _extract_device_name(line)
                profile.gpu_device_id = ids


def _get_hda_codec(profile: HardwareProfile) -> str:
    try:
        codecs = subprocess.run(["cat", "/proc/asound/card0/codec#0"], capture_output=True, text=True).stdout
        for line in codecs.splitlines():
            if "Codec:" in line:
                return line.split("Codec:")[-1].strip()
    except Exception:
        pass
    return ""


def detect_audio(profile: HardwareProfile):
    for line in profile.raw_pci:
        if "audio" in line.lower() or "multimedia" in line.lower():
            m = re.search(r'\[([0-9a-f]{4}:[0-9a-f]{4})\]', line)
            if m:
                ids = m.group(1).lower()
                profile.audio_name = _extract_device_name(line)
                if ids in AUDIO_CODEC_IDS:
                    profile.audio_codec = AUDIO_CODEC_IDS[ids]
                else:
                    codec = _get_hda_codec(profile)
                    profile.audio_codec = codec if codec else ids


def detect_network(profile: HardwareProfile):
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
            else:
                profile.ethernet_name = name
                if "i219" in lower or "i218" in lower:
                    profile.ethernet_chipset = "i219"
                elif "i211" in lower or "i210" in lower:
                    profile.ethernet_chipset = "i211"
                elif "rtl8125" in lower:
                    profile.ethernet_chipset = "rtl8125"
                elif "rtl" in lower or "realtek" in lower:
                    profile.ethernet_chipset = "rtl8111"
                elif "ax88" in lower or "asix" in lower:
                    profile.ethernet_chipset = "ax88"


def detect_smbios(profile: HardwareProfile):
    key = (profile.cpu_generation, profile.platform)
    if key in SMBIOS_MAP:
        profile.smbios_model = SMBIOS_MAP[key]
    elif profile.cpu_vendor == "amd":
        profile.smbios_model = "MacPro7,1" if profile.platform == "desktop" else "MacBookPro15,2"
    else:
        profile.smbios_model = "MacBookPro15,2"


def scan() -> HardwareProfile:
    profile = HardwareProfile()
    profile.raw_pci = _lspci()
    detect_cpu(profile)
    detect_platform(profile)
    detect_gpu(profile)
    detect_audio(profile)
    detect_network(profile)
    detect_smbios(profile)
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
    print(f"Touchpad:   {p.has_touchpad}")
    print(f"SMBIOS:     {p.smbios_model}")
