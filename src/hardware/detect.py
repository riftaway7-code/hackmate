import subprocess
import re
from dataclasses import dataclass, field
from compat import IS_WINDOWS, IS_LINUX, IS_MACOS


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
    touchpad_type: str = "ps2"
    has_thunderbolt: bool = False
    nvme_present: bool = False

    smbios_model: str = ""    # e.g. MacBookPro15,2
    oc_platform: str = ""     # e.g. Kaby Lake-R

    raw_pci: list = field(default_factory=list)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def _ps(command: str) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _lspci() -> list[str]:
    return _run(["lspci", "-nn"]).splitlines()


INTEL_GENERATIONS = {
    "206a": (2, "Sandy Bridge", "Kaby Lake"),
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
    "3e9b": (8, "Coffee Lake", "Coffee Lake"),
    "87c0": (8, "Kaby Lake-R", "Kaby Lake-R"),
    "3ea5": (8, "Whiskey Lake", "Whiskey Lake"),
    "9b41": (10, "Comet Lake", "Comet Lake"),
    "9bc8": (10, "Comet Lake", "Comet Lake"),
    "8a52": (10, "Ice Lake", "Ice Lake"),
    "8a5a": (10, "Ice Lake", "Ice Lake"),
    "9a49": (11, "Tiger Lake", "Tiger Lake"),
    "9a40": (11, "Tiger Lake", "Tiger Lake"),
    "46a6": (12, "Alder Lake", "Alder Lake"),
    "4626": (12, "Alder Lake", "Alder Lake"),
    "a7a0": (13, "Raptor Lake", "Raptor Lake"),
}

SMBIOS_MAP = {
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

_OC_PLATFORM_MAP = {
    14: "Raptor Lake", 13: "Raptor Lake", 12: "Alder Lake",
    11: "Tiger Lake",  10: "Ice Lake",    9:  "Coffee Lake",
    8:  "Coffee Lake", 7:  "Kaby Lake",   6:  "Skylake",
    5:  "Broadwell",   4:  "Haswell",     3:  "Ivy Bridge",
    2:  "Sandy Bridge",
}


# ─── CPU detection ─────────────────────────────────────────────────────────────

def _detect_cpu_linux(profile: HardwareProfile):
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
            _infer_intel_gen_from_name(profile)
    elif "amd" in profile.cpu_vendor or "amd" in profile.cpu_name.lower():
        profile.cpu_vendor = "amd"
        _detect_amd_gen(profile)

    if not profile.oc_platform:
        profile.oc_platform = _OC_PLATFORM_MAP.get(profile.cpu_generation, profile.cpu_codename or "Unknown")


def _detect_cpu_windows(profile: HardwareProfile):
    name = _ps("(Get-WmiObject Win32_Processor).Name")
    profile.cpu_name = name.strip()
    vendor = "intel" if "intel" in name.lower() else "amd" if "amd" in name.lower() else "unknown"
    profile.cpu_vendor = vendor

    if vendor == "intel":
        m = re.search(r"i[3579]-(\d{4,5})", name, re.IGNORECASE)
        if m:
            num = m.group(1)
            if len(num) == 5:
                d = int(num[:2])
            else:
                first = int(num[0])
                d = 10 if first == 1 else first
            gen_map = {2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9,10:10,11:11,12:12,13:13,14:14}
            profile.cpu_generation = gen_map.get(d, 0)
        codename_map = {
            2:"Sandy Bridge", 3:"Ivy Bridge", 4:"Haswell", 5:"Broadwell",
            6:"Skylake", 7:"Kaby Lake", 8:"Coffee Lake", 9:"Coffee Lake Refresh",
            10:"Ice Lake / Comet Lake", 11:"Tiger Lake", 12:"Alder Lake", 13:"Raptor Lake", 14:"Raptor Lake Refresh"
        }
        profile.cpu_codename = codename_map.get(profile.cpu_generation, "Unknown")

        # Try to get device ID from PCI for more accurate gen detection
        pnp = _ps("(Get-WmiObject Win32_VideoController | Select-Object -First 1).PNPDeviceID")
        m2 = re.search(r"DEV_([0-9A-Fa-f]{4})", pnp)
        if m2:
            dev_id = m2.group(1).lower()
            if dev_id in INTEL_GENERATIONS:
                gen, codename, oc_platform = INTEL_GENERATIONS[dev_id]
                profile.cpu_generation = gen
                profile.cpu_codename = codename
                profile.oc_platform = oc_platform

        if not profile.cpu_generation:
            _infer_intel_gen_from_name(profile)
    elif vendor == "amd":
        _detect_amd_gen(profile)

    profile.oc_platform = _OC_PLATFORM_MAP.get(profile.cpu_generation, profile.cpu_codename or "Unknown")

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


def _detect_amd_gen(profile: HardwareProfile):
    name = profile.cpu_name.lower()
    if "ryzen" in name or "threadripper" in name:
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
        profile.cpu_generation = 8
        profile.cpu_codename = "Zen (Athlon)"
    else:
        profile.cpu_generation = 8
        profile.cpu_codename = "AMD (unknown)"
    profile.oc_platform = "Ryzen"


# ─── Platform detection ────────────────────────────────────────────────────────

def _detect_platform_linux(profile: HardwareProfile):
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

    from compat import detect_touchpad_type
    profile.touchpad_type = detect_touchpad_type()


def _detect_platform_windows(profile: HardwareProfile):
    chassis = _ps(
        "(Get-WmiObject Win32_SystemEnclosure).ChassisTypes | ForEach-Object { $_ }"
    )
    laptop_types = {"8", "9", "10", "11", "12", "14", "18", "21"}
    for t in re.findall(r"\d+", chassis):
        if t in laptop_types:
            profile.platform = "laptop"
            break
    else:
        battery = _ps("(Get-WmiObject Win32_Battery | Measure-Object).Count")
        if battery.strip() not in ("", "0"):
            profile.platform = "laptop"
        else:
            profile.platform = "desktop"

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

    from compat import detect_touchpad_type
    profile.touchpad_type = detect_touchpad_type()
    profile.has_touchpad = profile.touchpad_type != "none"


# ─── GPU detection ─────────────────────────────────────────────────────────────

def _extract_device_name(line: str) -> str:
    m = re.search(r'\]: (.+?) \[', line)
    if m:
        return m.group(1).strip()
    parts = line.split("]: ")
    if len(parts) > 1:
        return parts[1].split("[")[0].strip()
    return line.split(":")[-1].strip()


def _detect_gpu_linux(profile: HardwareProfile):
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


def _detect_gpu_windows(profile: HardwareProfile):
    raw = _ps("(Get-WmiObject Win32_VideoController | Select-Object -First 1).Name")
    profile.gpu_name = raw.strip()

    if "intel" in raw.lower():
        profile.gpu_vendor = "intel"
    elif "amd" in raw.lower() or "radeon" in raw.lower():
        profile.gpu_vendor = "amd"
    elif "nvidia" in raw.lower():
        profile.gpu_vendor = "nvidia"

    pnp = _ps("(Get-WmiObject Win32_VideoController | Select-Object -First 1).PNPDeviceID")
    m = re.search(r"DEV_([0-9A-Fa-f]{4})", pnp)
    if m:
        profile.gpu_device_id = m.group(1).upper()


# ─── Audio detection ───────────────────────────────────────────────────────────

def _get_hda_codec_linux() -> str:
    try:
        codecs = subprocess.run(["cat", "/proc/asound/card0/codec#0"], capture_output=True, text=True).stdout
        for line in codecs.splitlines():
            if "Codec:" in line:
                return line.split("Codec:")[-1].strip()
    except Exception:
        pass
    return ""


def _detect_audio_linux(profile: HardwareProfile):
    for line in profile.raw_pci:
        if "audio" in line.lower() or "multimedia" in line.lower():
            m = re.search(r'\[([0-9a-f]{4}:[0-9a-f]{4})\]', line)
            if m:
                ids = m.group(1).lower()
                profile.audio_name = _extract_device_name(line)
                if ids in AUDIO_CODEC_IDS:
                    profile.audio_codec = AUDIO_CODEC_IDS[ids]
                else:
                    codec = _get_hda_codec_linux()
                    profile.audio_codec = codec if codec else ids


def _detect_audio_windows(profile: HardwareProfile):
    raw = _ps("(Get-WmiObject Win32_SoundDevice | Select-Object -First 1).Name")
    profile.audio_name = raw.strip()
    # Try to extract codec from name
    name = raw.upper()
    m = re.search(r'ALC(\d{3,4})', name)
    if m:
        profile.audio_codec = f"ALC{m.group(1)}"
    elif "realtek" in name.lower():
        profile.audio_codec = "Realtek"
    else:
        profile.audio_codec = raw.strip()


# ─── Network detection ─────────────────────────────────────────────────────────

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


def _detect_network_windows(profile: HardwareProfile):
    # Ethernet
    raw = _ps("""
        $nic = Get-WmiObject Win32_NetworkAdapter | Where-Object {
            $_.AdapterType -eq 'Ethernet 802.3' -and $_.PNPDeviceID -notlike 'ROOT*'
        } | Select-Object -First 1
        $nic.Name
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

    # WiFi
    raw = _ps("""
        $nic = Get-WmiObject Win32_NetworkAdapter | Where-Object {
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


# ─── SMBIOS ────────────────────────────────────────────────────────────────────

def detect_smbios(profile: HardwareProfile):
    key = (profile.cpu_generation, profile.platform)
    if key in SMBIOS_MAP:
        profile.smbios_model = SMBIOS_MAP[key]
    elif profile.cpu_vendor == "amd":
        profile.smbios_model = "MacPro7,1" if profile.platform == "desktop" else "MacBookPro15,2"
    else:
        profile.smbios_model = "MacBookPro15,2"


# ─── macOS detection ───────────────────────────────────────────────────────────

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
                profile.oc_platform = codename
                break
    elif profile.cpu_vendor == "amd":
        _detect_amd_gen(profile)


def _detect_gpu_macos(profile: HardwareProfile):
    sp = _sp("SPDisplaysDataType")
    for line in sp.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if "intel" in lower and ("uhd" in lower or "iris" in lower or "hd graphics" in lower):
            profile.gpu_vendor = "intel"
            profile.gpu_name = line.split(":")[-1].strip() if ":" in line else line
        elif "amd" in lower or "radeon" in lower:
            profile.gpu_vendor = "amd"
            profile.gpu_name = line.split(":")[-1].strip() if ":" in line else line
        elif "nvidia" in lower or "geforce" in lower:
            profile.gpu_vendor = "nvidia"
            profile.gpu_name = line.split(":")[-1].strip() if ":" in line else line


def _detect_audio_macos(profile: HardwareProfile):
    sp = _sp("SPAudioDataType")
    for line in sp.splitlines():
        lower = line.lower()
        if "alc" in lower or "realtek" in lower:
            m = re.search(r'alc\d+', lower)
            if m:
                profile.audio_codec = m.group(0).upper()
                profile.audio_name = line.strip()
                break
        elif "audio" in lower and ":" in line:
            profile.audio_name = line.split(":")[-1].strip()


def _detect_network_macos(profile: HardwareProfile):
    sp = _sp("SPNetworkDataType")
    lower = sp.lower()
    if "i219" in lower or "i218" in lower:
        profile.ethernet_chipset = "i219"
        profile.ethernet_name = "Intel Ethernet"
    elif "realtek" in lower:
        profile.ethernet_chipset = "rtl8111"
        profile.ethernet_name = "Realtek Ethernet"
    if "intel" in lower and ("wi-fi" in lower or "wireless" in lower or "ax" in lower):
        profile.wifi_chipset = "intel"
        profile.wifi_name = "Intel WiFi"
    elif "broadcom" in lower and ("wi-fi" in lower or "wireless" in lower):
        profile.wifi_chipset = "broadcom"
        profile.wifi_name = "Broadcom WiFi"


def _detect_platform_macos(profile: HardwareProfile):
    model = _run(["sysctl", "-n", "hw.model"]).lower()
    profile.platform = "laptop" if "macbook" in model else "desktop"
    profile.has_touchpad = "macbook" in model
    if profile.has_touchpad:
        profile.touchpad_type = "i2c"
    sp = _sp("SPStorageDataType").lower()
    profile.nvme_present = "nvme" in sp or "apple ssd" in sp


# ─── Main scan ─────────────────────────────────────────────────────────────────

def scan() -> HardwareProfile:
    profile = HardwareProfile()

    if IS_WINDOWS:
        _detect_cpu_windows(profile)
        _detect_gpu_windows(profile)
        _detect_audio_windows(profile)
        _detect_network_windows(profile)
        _detect_platform_windows(profile)
    elif IS_MACOS:
        _detect_cpu_macos(profile)
        _detect_gpu_macos(profile)
        _detect_audio_macos(profile)
        _detect_network_macos(profile)
        _detect_platform_macos(profile)
    else:
        profile.raw_pci = _lspci()
        _detect_cpu_linux(profile)
        _detect_platform_linux(profile)
        _detect_gpu_linux(profile)
        _detect_audio_linux(profile)
        _detect_network_linux(profile)

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
    print(f"Touchpad:   {p.has_touchpad} ({p.touchpad_type})")
    print(f"SMBIOS:     {p.smbios_model}")
