"""
Hardware detection for Windows using PowerShell/WMIC.
"""

import subprocess
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HardwareProfile:
    cpu_name: str = ""
    cpu_vendor: str = ""
    cpu_generation: int = 0
    cpu_codename: str = ""
    gpu_name: str = ""
    gpu_vendor: str = ""
    gpu_device_id: str = ""
    audio_codec: str = ""
    ethernet_name: str = ""
    ethernet_chipset: str = ""
    wifi_name: str = ""
    wifi_chipset: str = ""
    platform: str = "desktop"
    touchpad_type: str = "ps2"
    has_thunderbolt: bool = False
    nvme_present: bool = False
    smbios_model: str = ""
    oc_platform: str = ""


def _ps(command: str) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _wmic(query: str) -> str:
    try:
        result = subprocess.run(
            ["wmic"] + query.split(),
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _detect_cpu() -> tuple[str, str, int, str]:
    name = _ps("(Get-WmiObject Win32_Processor).Name")
    name = name.strip()
    vendor = "intel" if "intel" in name.lower() else "amd" if "amd" in name.lower() else "unknown"

    gen = 0
    codename = "Unknown"

    if vendor == "intel":
        m = re.search(r"i[3579]-(\d{4,5})", name, re.IGNORECASE)
        if m:
            num = m.group(1)
            if len(num) == 5:
                d = int(num[:2])
            else:
                first = int(num[0])
                d = 10 if first == 1 else first  # Ice Lake 1xxxGx = 10th gen
            gen_map = {2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9,10:10,11:11,12:12,13:13,14:14}
            gen = gen_map.get(d, 0)
        codename_map = {
            2:"Sandy Bridge", 3:"Ivy Bridge", 4:"Haswell", 5:"Broadwell",
            6:"Skylake", 7:"Kaby Lake", 8:"Coffee Lake", 9:"Coffee Lake Refresh",
            10:"Ice Lake / Comet Lake", 11:"Tiger Lake", 12:"Alder Lake", 13:"Raptor Lake", 14:"Raptor Lake Refresh"
        }
        codename = codename_map.get(gen, "Unknown")
    elif vendor == "amd":
        if "ryzen 3" in name.lower(): gen = 17
        elif "ryzen 5" in name.lower(): gen = 17
        elif "ryzen 7" in name.lower(): gen = 17
        elif "ryzen 9" in name.lower(): gen = 17
        codename = "Zen"

    return name, vendor, gen, codename


def _detect_gpu() -> tuple[str, str, str]:
    raw = _ps("(Get-WmiObject Win32_VideoController | Select-Object -First 1).Name")
    name = raw.strip()
    vendor = "unknown"
    device_id = ""

    if "intel" in name.lower():
        vendor = "intel"
    elif "amd" in name.lower() or "radeon" in name.lower():
        vendor = "amd"
    elif "nvidia" in name.lower():
        vendor = "nvidia"

    pnp = _ps("(Get-WmiObject Win32_VideoController | Select-Object -First 1).PNPDeviceID")
    m = re.search(r"DEV_([0-9A-Fa-f]{4})", pnp)
    if m:
        device_id = m.group(1).upper()

    return name, vendor, device_id


def _detect_audio() -> str:
    raw = _ps("(Get-WmiObject Win32_SoundDevice | Select-Object -First 1).Name")
    return raw.strip()


def _detect_ethernet() -> tuple[str, str]:
    raw = _ps("""
        $nic = Get-WmiObject Win32_NetworkAdapter | Where-Object {
            $_.AdapterType -eq 'Ethernet 802.3' -and $_.PNPDeviceID -notlike 'ROOT*'
        } | Select-Object -First 1
        $nic.Name
    """)
    name = raw.strip()
    chipset = "unknown"
    name_lower = name.lower()
    if "i219" in name_lower: chipset = "i219"
    elif "i218" in name_lower: chipset = "i218"
    elif "i217" in name_lower: chipset = "i217"
    elif "i225" in name_lower: chipset = "i225"
    elif "i226" in name_lower: chipset = "i226"
    elif "rtl8111" in name_lower or "rtl8168" in name_lower: chipset = "rtl8111"
    elif "rtl8125" in name_lower: chipset = "rtl8125"
    elif "rtl8100" in name_lower: chipset = "rtl8100"
    return name, chipset


def _detect_wifi() -> tuple[str, str]:
    raw = _ps("""
        $nic = Get-WmiObject Win32_NetworkAdapter | Where-Object {
            $_.Name -match 'Wi-Fi|Wireless|WiFi|802.11'
        } | Select-Object -First 1
        $nic.Name
    """)
    name = raw.strip()
    chipset = "unknown"
    name_lower = name.lower()
    if "intel" in name_lower: chipset = "intel"
    elif "broadcom" in name_lower: chipset = "broadcom"
    elif "atheros" in name_lower or "qualcomm" in name_lower: chipset = "atheros"
    elif "realtek" in name_lower: chipset = "realtek"
    elif "mediatek" in name_lower: chipset = "mediatek"
    return name, chipset


def _detect_platform() -> str:
    chassis = _ps(
        "(Get-WmiObject Win32_SystemEnclosure).ChassisTypes | ForEach-Object { $_ }"
    )
    laptop_types = {"8", "9", "10", "11", "12", "14", "18", "21"}
    for t in re.findall(r"\d+", chassis):
        if t in laptop_types:
            return "laptop"
    # Fallback: check if battery exists
    battery = _ps("(Get-WmiObject Win32_Battery | Measure-Object).Count")
    if battery.strip() not in ("", "0"):
        return "laptop"
    return "desktop"


def _detect_nvme() -> bool:
    out = _ps("Get-PhysicalDisk | Where-Object {$_.BusType -eq 'NVMe'} | Measure-Object | Select-Object -ExpandProperty Count")
    try:
        return int(out.strip()) > 0
    except Exception:
        return False


def _smbios_model(cpu_gen: int, gpu_vendor: str, platform: str, cpu_vendor: str) -> str:
    if cpu_vendor == "amd":
        return "iMacPro1,1"
    if platform == "laptop":
        m = {
            14: "MacBookPro15,4", 13: "MacBookPro15,4", 12: "MacBookPro14,1",
            11: "MacBookPro18,1", 10: "MacBookPro16,2", 9: "MacBookPro15,2",
            8:  "MacBookPro15,2", 7: "MacBookPro14,1",  6: "MacBookPro13,1",
            5:  "MacBookPro12,1", 4: "MacBookPro11,1",  3: "MacBookPro9,2",
        }
        return m.get(cpu_gen, "MacBookPro16,2")
    else:
        m = {
            14: "iMac20,1", 13: "iMac20,1", 12: "iMac20,1",
            11: "iMac20,1", 10: "iMac19,1", 9:  "iMac19,1",
            8:  "iMac18,3", 7:  "iMac18,3", 6:  "iMac17,1",
        }
        return m.get(cpu_gen, "iMac19,1")


_OC_PLATFORM_MAP = {
    14: "Raptor Lake", 13: "Raptor Lake", 12: "Alder Lake",
    11: "Tiger Lake",  10: "Ice Lake",    9:  "Coffee Lake",
    8:  "Coffee Lake", 7:  "Kaby Lake",   6:  "Skylake",
    5:  "Broadwell",   4:  "Haswell",     3:  "Ivy Bridge",
    2:  "Sandy Bridge",
}

def scan() -> HardwareProfile:
    p = HardwareProfile()
    p.cpu_name, p.cpu_vendor, p.cpu_generation, p.cpu_codename = _detect_cpu()
    p.gpu_name, p.gpu_vendor, p.gpu_device_id = _detect_gpu()
    p.audio_codec = _detect_audio()
    p.ethernet_name, p.ethernet_chipset = _detect_ethernet()
    p.wifi_name, p.wifi_chipset = _detect_wifi()
    p.platform = _detect_platform()
    p.nvme_present = _detect_nvme()
    p.smbios_model = _smbios_model(p.cpu_generation, p.gpu_vendor, p.platform, p.cpu_vendor)
    p.oc_platform = _OC_PLATFORM_MAP.get(p.cpu_generation, p.cpu_codename or "Unknown")
    return p
