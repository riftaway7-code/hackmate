import os
import re
import urllib.request
import json
import zipfile
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from hardware import HardwareProfile
from compat import IS_WINDOWS, IS_MACOS, http_get, real_home

_CACHE_ROOT = real_home() / ".hackmate" / "cache"


def _cached_or_download(asset: dict, dest_dir: Path, cache_name: str = "kexts") -> Path:
    """Download a GitHub release asset with an on-disk cache. A failed build
    retried minutes later re-downloads everything today, and each retry burns
    more of the 60/hr unauthenticated API budget — the retry storms in hwdb
    (same user, same error, 4 submissions in a row) all start here. Cached
    zips are validated against GitHub's reported size before reuse."""
    cache_dir = _CACHE_ROOT / cache_name
    cached = cache_dir / asset["name"]
    expected_size = asset.get("size", 0)
    if cached.exists() and (not expected_size or abs(cached.stat().st_size - expected_size) <= 1024):
        return cached

    data = http_get(asset["browser_download_url"], timeout=60)
    out = dest_dir / asset["name"]
    out.write_bytes(data)
    if expected_size and abs(out.stat().st_size - expected_size) > 1024:
        raise IOError(f"size mismatch (got {out.stat().st_size}, expected {expected_size})")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(out), str(cached))
    except Exception:
        pass  # cache is best-effort — a full disk must not fail the build
    return out


def _extract_zip(zip_path: Path, extract_dir: Path) -> None:
    """extractall() minus the members no build ever needs: __MACOSX
    AppleDouble junk and dSYM debug bundles. dSYM trees are deep and full of
    odd names — extracting them onto a flaky FAT32 USB is exactly where two
    hwdb reports died with WinError 433 mid-VirtualSMC — and they also waste
    most of the space the kext zip takes on disk."""
    with zipfile.ZipFile(str(zip_path)) as z:
        for member in z.namelist():
            low = member.lower()
            if "__macosx" in low or ".dsym" in low:
                continue
            z.extract(member, str(extract_dir))

@dataclass
class KextEntry:
    name: str
    repo: str
    asset_pattern: str
    note: str = ""
    bundle_name: str = ""  # actual .kext bundle name if different from name
    exe_name: str = ""    # binary name inside Contents/MacOS/ if different from name

# Every known OC-compatible kext. Selection logic below picks what's needed.

DB: dict[str, KextEntry] = {

    "Lilu":              KextEntry("Lilu",            "acidanthera/Lilu",             "Lilu-",              "base patcher, must load first"),
    "VirtualSMC":        KextEntry("VirtualSMC",      "acidanthera/VirtualSMC",       "VirtualSMC-",        "SMC emulator (modern, Sandy Bridge+)"),
    "FakeSMC":           KextEntry("FakeSMC",         "CloverHackyColor/FakeSMC3_with_plugins", "FakeSMC", "SMC emulator (legacy, pre-Sandy Bridge)"),
    "RestrictEvents":    KextEntry("RestrictEvents",  "acidanthera/RestrictEvents",   "RestrictEvents-",    "various system event patches"),
    "FeatureUnlock":     KextEntry("FeatureUnlock",   "acidanthera/FeatureUnlock",    "FeatureUnlock-",     "Sidecar, AirPlay, Universal Control on unsupported SMBIOS"),
    "CPUFriend":         KextEntry("CPUFriend",       "acidanthera/CPUFriend",        "CPUFriend-",         "CPU frequency/power management"),
    "NVMeFix":           KextEntry("NVMeFix",         "acidanthera/NVMeFix",          "NVMeFix-",           "NVMe power management + APST"),
    "DebugEnhancer":     KextEntry("DebugEnhancer",   "acidanthera/DebugEnhancer",    "DebugEnhancer-",     "kernel debug logging"),
    "CryptexFixup":      KextEntry("CryptexFixup",    "acidanthera/CryptexFixup",     "CryptexFixup-",      "Ventura+ cryptex on older/AMD hardware"),


    "SMCBatteryManager": KextEntry("SMCBatteryManager","acidanthera/VirtualSMC",      "VirtualSMC-",        "battery status (in VirtualSMC zip)"),
    "SMCProcessor":      KextEntry("SMCProcessor",     "acidanthera/VirtualSMC",      "VirtualSMC-",        "CPU temp sensors (in VirtualSMC zip)"),
    "SMCSuperIO":        KextEntry("SMCSuperIO",       "acidanthera/VirtualSMC",      "VirtualSMC-",        "desktop fan sensors (in VirtualSMC zip)"),
    "SMCLightSensor":    KextEntry("SMCLightSensor",   "acidanthera/VirtualSMC",      "VirtualSMC-",        "ambient light sensor (in VirtualSMC zip)"),
    "SMCDellSensors":    KextEntry("SMCDellSensors",   "acidanthera/VirtualSMC",      "VirtualSMC-",        "Dell fan/temp sensors (in VirtualSMC zip)"),
    "SMCAMDProcessor":   KextEntry("SMCAMDProcessor",  "trulyspinach/SMCAMDProcessor","SMCAMDProcessor",   "AMD CPU sensors"),
    "SMCRadeonGPU":      KextEntry("SMCRadeonGPU",     "aluveitie/RadeonSensor",      "RadeonSensor-",      "AMD GPU temp in HWMonitor (bundled in RadeonSensor zip)"),

    "AppleALC":          KextEntry("AppleALC",         "acidanthera/AppleALC",        "AppleALC-",          "audio codec patches via Lilu"),
    "VoodooHDA":         KextEntry("VoodooHDA",        "CloverHackyColor/VoodooHDA", "VoodooHDA",           "post-install fallback audio for unsupported codecs"),
    "WhateverGreen":     KextEntry("WhateverGreen",    "acidanthera/WhateverGreen",   "WhateverGreen-",     "GPU framebuffer + audio HDMI/DP patches"),

    "VoodooPS2Controller":KextEntry("VoodooPS2Controller","acidanthera/VoodooPS2",    "VoodooPS2Controller-","PS/2 keyboard + mouse + trackpad"),
    "VoodooPS2Keyboard": KextEntry("VoodooPS2Keyboard","acidanthera/VoodooPS2",       "VoodooPS2Controller-","PS/2 keyboard (in VoodooPS2 zip)"),
    "VoodooPS2Mouse":    KextEntry("VoodooPS2Mouse",   "acidanthera/VoodooPS2",       "VoodooPS2Controller-","PS/2 mouse (in VoodooPS2 zip)"),
    "VoodooPS2Trackpad": KextEntry("VoodooPS2Trackpad","acidanthera/VoodooPS2",       "VoodooPS2Controller-","PS/2 trackpad (in VoodooPS2 zip)"),

    "VoodooI2C":         KextEntry("VoodooI2C",        "VoodooI2C/VoodooI2C",         "VoodooI2C-",         "I2C trackpad/touchscreen base", exe_name="VoodooI2C"),
    "VoodooI2CHID":      KextEntry("VoodooI2CHID",     "VoodooI2C/VoodooI2C",         "VoodooI2C-",         "generic I2C-HID satellite (bundled in VoodooI2C zip)"),
    "VoodooI2CSynaptics":KextEntry("VoodooI2CSynaptics","VoodooI2C/VoodooI2C",        "VoodooI2C-",         "Synaptics I2C satellite (bundled in VoodooI2C zip)"),
    "VoodooI2CELAN":     KextEntry("VoodooI2CELAN",    "VoodooI2C/VoodooI2C",         "VoodooI2C-",         "ELAN I2C satellite (bundled in VoodooI2C zip)"),
    "VoodooI2CAtmel":    KextEntry("VoodooI2CAtmel",   "VoodooI2C/VoodooI2C",         "VoodooI2C-",         "Atmel I2C satellite (bundled in VoodooI2C zip)"),
    "VoodooI2CFTE":      KextEntry("VoodooI2CFTE",     "VoodooI2C/VoodooI2C",         "VoodooI2C-",         "FTE1001 I2C satellite (bundled in VoodooI2C zip)"),
    "VoodooI2CGoodix":   KextEntry("VoodooI2CGoodix",  "lazd/VoodooI2CGoodix",        "VoodooI2CGoodix-",   "Goodix touchscreen satellite"),
    "VoodooGPIO":        KextEntry("VoodooGPIO",       "VoodooI2C/VoodooI2C",         "VoodooI2C-",         "GPIO pinning (bundled in VoodooI2C zip)"),
    "VoodooInput":       KextEntry("VoodooInput",      "acidanthera/VoodooInput",     "VoodooInput-",       "multitouch input magic trackpad emulation"),
    "VoodooSMBus":       KextEntry("VoodooSMBus",      "VoodooSMBus/VoodooSMBus",     "VoodooSMBus-",       "SMBus trackpad (Synaptics PS2 over SMBus)"),
    "VoodooRMI":         KextEntry("VoodooRMI",        "VoodooSMBus/VoodooRMI",       "VoodooRMI-",         "Synaptics RMI4 trackpad (better than PS2 on some laptops)"),
    "AlpsHID":           KextEntry("AlpsHID",          "blankmac/AlpsHID",            "AlpsHID",            "ALPS I2C touchpad + trackpoint (satellite, needs VoodooI2C/VoodooI2CHID)"),

    "IntelMausiEthernet":KextEntry("IntelMausiEthernet","acidanthera/IntelMausi",        "IntelMausi-",        "Intel I219/I218/I217 Ethernet", bundle_name="IntelMausi", exe_name="IntelMausi"),
    "AppleIGC":          KextEntry("AppleIGC",         "SongXiaoXi/AppleIGC",         "AppleIGC",           "Intel I225-V / I226-V 2.5GbE"),
    "AppleIGB":          KextEntry("AppleIGB",         "donatengit/AppleIGB",         "AppleIGB",           "alternative Intel I210/I211/82576+ Ethernet (IntelMausi-style; upstream's newest tags ship DEBUG-only builds)"),
    "AppleIntelE1000e":  KextEntry("AppleIntelE1000e", "chris1111/AppleIntelE1000e",  "AppleIntelE1000e-",  "Intel 82578/82577/82574/82567 Ethernet"),
    "AppleIntelI210Ethernet":KextEntry("AppleIntelI210Ethernet","donatengit/AppleIntelI210Ethernet","AppleIntelI210-","Intel I211/I210 Ethernet"),
    "RealtekRTL8111":    KextEntry("RealtekRTL8111",   "Mieze/RTL8111_driver_for_OS_X","RealtekRTL8111-",   "Realtek RTL8111/RTL8168"),
    "RealtekRTL8100":    KextEntry("RealtekRTL8100",   "Mieze/RTL8100",               "RealtekRTL8100-",    "Realtek RTL8101/RTL8102E/RTL8103E"),
    "RealtekR1000":      KextEntry("RealtekR1000",     "Mieze/Realtek-R1000-Adapter", "RealtekR1000-",      "Realtek RTL8169 (very old)"),
    "LucyRTL8125Ethernet":KextEntry("LucyRTL8125Ethernet","Mieze/LucyRTL8125Ethernet","LucyRTL8125Ethernet-","Realtek RTL8125 2.5GbE"),
    "AtherosE2200Ethernet":KextEntry("AtherosE2200Ethernet","Mieze/AtherosE2200Ethernet","AtherosE2200Ethernet-","Atheros AR8151/AR8161/AR8162/AR8171/AR8172"),
    "AtherosL1Ethernet": KextEntry("AtherosL1Ethernet","RehabMan/OS-X-Atheros-L1-Ethernet","AtherosL1-",    "Atheros L1 Gigabit (very old)"),
    "AtherosL1eEthernet":KextEntry("AtherosL1eEthernet","RehabMan/OS-X-Atheros-L1e-Ethernet","AtherosL1e-", "Atheros L1e Fast Ethernet"),
    "BCM5722D":          KextEntry("BCM5722D",         "SavageAUS/BCM5722D",          "BCM5722D-",          "Broadcom BCM5722 Ethernet"),
    "NullEthernet":      KextEntry("NullEthernet",     "jcreed69/NullEthernet",       "NullEthernet",       "placeholder ethernet for iMessage/iCloud on WiFi-only"),

    "itlwm":             KextEntry("itlwm",            "OpenIntelWireless/itlwm",     "itlwm_",             "Intel WiFi (needs HeliPort app for menu bar)"),
    "AirportItlwm":      KextEntry("AirportItlwm",     "OpenIntelWireless/itlwm",     "AirportItlwm_",      "Intel WiFi as native AirportBSD (macOS version specific!)"),
    "AirportBrcmFixup":  KextEntry("AirportBrcmFixup", "acidanthera/AirportBrcmFixup","AirportBrcmFixup-",  "Broadcom BCM94352Z/BCM943602CS WiFi patches"),
    "ATH9KFixup":        KextEntry("ATH9KFixup",       "black-dragon74/ATH9KFixup",   "release",            "Atheros AR9xxx WiFi patches"),

    "BrcmPatchRAM":      KextEntry("BrcmPatchRAM",     "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "Broadcom BT (macOS 10.10 and below)"),
    "BrcmPatchRAM2":     KextEntry("BrcmPatchRAM2",    "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "Broadcom BT (macOS 10.11-11)"),
    "BrcmPatchRAM3":     KextEntry("BrcmPatchRAM3",    "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "Broadcom BT (macOS 12+)"),
    "BrcmFirmwareData":  KextEntry("BrcmFirmwareData", "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "Broadcom BT firmware data"),
    "BrcmFirmwareRepo":  KextEntry("BrcmFirmwareRepo", "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "Broadcom BT firmware repo (for in-memory loading)"),
    "BrcmBluetoothInjector":KextEntry("BrcmBluetoothInjector","acidanthera/BrcmPatchRAM","BrcmPatchRAM-",   "Broadcom BT injector (macOS 12 and below)"),
    "BlueToolFixup":     KextEntry("BlueToolFixup",    "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "BT stack fix for macOS 12+ (in BrcmPatchRAM zip)"),
    "IntelBluetoothFirmware":KextEntry("IntelBluetoothFirmware","OpenIntelWireless/IntelBluetoothFirmware","IntelBluetooth",      "Intel BT firmware loader"),
    "IntelBTPatcher":    KextEntry("IntelBTPatcher",   "OpenIntelWireless/IntelBluetoothFirmware","IntelBluetooth",      "Intel BT patches for macOS 12+"),
    "IntelBluetoothInjector":KextEntry("IntelBluetoothInjector","OpenIntelWireless/IntelBluetoothFirmware","IntelBluetooth",  "Intel BT injector (macOS 11 and below)"),

    "NootRX":            KextEntry("NootRX",           "ChefKissInc/NootRX",          "NootRX-",            "AMD RX 6600/6700/6800/6900 (Navi 2x) on Ventura+"),
    "NootedRed":         KextEntry("NootedRed",        "ChefKissInc/NootedRed",       "NootedRed-",         "AMD Renoir/Cezanne/Rembrandt/Phoenix iGPU"),
    "RadeonSensor":      KextEntry("RadeonSensor",     "aluveitie/RadeonSensor",      "RadeonSensor-",      "AMD GPU temperature monitoring"),

    "NullCPUPowerManagement":KextEntry("NullCPUPowerManagement","baservand/NullCPUPowerManagement","NullCPUPowerManagement-","disable AppleIntelCPUPowerManagement (Sandy Bridge and older)"),
    "VoodooTSCSync":     KextEntry("VoodooTSCSync",    "RehabMan/VoodooTSCSync",      "VoodooTSCSync-",     "TSC sync for multi-socket / HEDT"),
    "AmdTSCSync":        KextEntry("AmdTSCSync",       "naveenkrdy/AmdTSCSync",       "AmdTSCSync-",        "TSC sync for AMD"),
    "ForgedInvariant":   KextEntry("ForgedInvariant",  "ChefKissInc/ForgedInvariant", "ForgedInvariant-",   "TSC sync alternative for AMD/HEDT"),
    "AMDRyzenCPUPowerManagement":KextEntry("AMDRyzenCPUPowerManagement","trulyspinach/SMCAMDProcessor","AMDRyzenCPUPowerManagement","AMD Ryzen CPU power management"),
    "CpuTopologyRebuild":KextEntry("CpuTopologyRebuild","b00t0x/CpuTopologyRebuild",  "CpuTopologyRebuild-","Alder/Raptor Lake P+E core topology fix"),
    "HibernationFixup":  KextEntry("HibernationFixup", "acidanthera/HibernationFixup","HibernationFixup-",  "sleep/wake stability fix"),
    "RTCMemoryFixup":    KextEntry("RTCMemoryFixup",   "acidanthera/RTCMemoryFixup",  "RTCMemoryFixup-",    "emulates CMOS/RTC offsets (fixes NVRAM reset loops on some boards)"),
    "IntelMKLFixup":     KextEntry("IntelMKLFixup",    "Carnations-Botanica/IntelMKLFixup","IntelMKLFixup-", "patches Intel MKL for AMD CPU compatibility"),
    "Innie":             KextEntry("Innie",            "cdf/Innie",                   "Innie-",             "makes external NVMe/PCIe drives appear internal (Recovery/FileVault icon fix)"),

    "ECEnabler":         KextEntry("ECEnabler",        "1Revenger1/ECEnabler",        "ECEnabler-",         "battery EC fields >8-bit (replaces ACPIBatteryManager patches)"),
    "ACPIBatteryManager":KextEntry("ACPIBatteryManager","RehabMan/OS-X-ACPI-Battery-Driver","ACPIBatteryManager-","battery (legacy, use ECEnabler instead on modern OC)"),

    "USBToolBox":        KextEntry("USBToolBox",       "USBToolBox/kext",             "USBToolBox-",        "USB port mapping tool"),
    "UTBMap":            KextEntry("UTBMap",           "",                            "",                   "USB port map (user-generated via USB Mapping after first boot)"),
    "USBInjectAll":      KextEntry("USBInjectAll",     "Sniki/OS-X-USB-Inject-All",   "USBInjectAll-",      "inject all USB ports (use only during mapping, not final EFI)"),
    "XHCI-unsupported":  KextEntry("XHCI-unsupported", "RehabMan/OS-X-USB-Inject-All","XHCI-unsupported-",  "unsupported USB 3.0 controllers (Sandy/Ivy Bridge)"),
    "GenericUSBXHCI":    KextEntry("GenericUSBXHCI",   "al3xtjames/GenericUSBXHCI",   "GenericUSBXHCI-",    "alternative driver for 3rd-party (ASMedia/NEC/Renesas) USB3 controllers"),

    "AHCIPortInjector":  KextEntry("AHCIPortInjector", "RehabMan/OS-X-AHCI-Port-Injector","AHCIPortInjector-","inject AHCI ports (very old hardware)"),
    "JMicronATA":        KextEntry("JMicronATA",       "RehabMan/OS-X-JMicron-ATA",   "JMicronATA-",        "JMicron ATA (very old)"),

    "FakePCIID":         KextEntry("FakePCIID",        "RehabMan/OS-X-Fake-PCI-ID",   "FakePCIID-",         "spoof PCI device IDs (base, required by all FakePCIID plugins)"),
    "FakePCIID_XHCIMux":         KextEntry("FakePCIID_XHCIMux",        "RehabMan/OS-X-Fake-PCI-ID","FakePCIID-","XHCI mux spoof"),
    "FakePCIID_Broadcom_WiFi":   KextEntry("FakePCIID_Broadcom_WiFi",  "RehabMan/OS-X-Fake-PCI-ID","FakePCIID-","Broadcom WiFi PCI ID spoof"),
    "FakePCIID_Intel_HDMI_Audio":KextEntry("FakePCIID_Intel_HDMI_Audio","RehabMan/OS-X-Fake-PCI-ID","FakePCIID-","Intel HDMI audio PCI ID spoof"),
    "FakePCIID_Intel_HD_Graphics":KextEntry("FakePCIID_Intel_HD_Graphics","RehabMan/OS-X-Fake-PCI-ID","FakePCIID-","Intel HD Graphics PCI ID spoof"),
    "FakePCIID_BCM57XX_as_BCM57765":KextEntry("FakePCIID_BCM57XX_as_BCM57765","RehabMan/OS-X-Fake-PCI-ID","FakePCIID-","BCM57xx Ethernet spoof as BCM57765"),

    "YogaSMC":           KextEntry("YogaSMC",          "zhen-zen/YogaSMC",            "YogaSMC",            "ThinkPad/IdeaPad FN keys, fan, keyboard backlight"),
    "AsusSMC":           KextEntry("AsusSMC",          "hieplpvip/AsusSMC",           "AsusSMC-",           "ASUS FN keys, keyboard backlight, fan"),
    "BrightnessKeys":    KextEntry("BrightnessKeys",   "acidanthera/BrightnessKeys",  "BrightnessKeys-",    "brightness Fn keys (F1/F2)"),
    "NoTouchID":         KextEntry("NoTouchID",        "al3xtjames/NoTouchID",        "NoTouchID-",         "suppress Touch ID prompts on non-T2 SMBIOS"),

    "RealtekCardReader": KextEntry("RealtekCardReader","0xFireWolf/RealtekCardReader", "RealtekCardReader", "Realtek RTS5xxx SD card reader"),
    "RealtekCardReaderFriend":KextEntry("RealtekCardReaderFriend","0xFireWolf/RealtekCardReaderFriend","RealtekCardReaderFriend","Lilu plugin companion for RealtekCardReader"),
    "Sinetek-rtsx":      KextEntry("Sinetek-rtsx",     "cholonam/Sinetek-rtsx",       "Sinetek-rtsx-",      "alternative Realtek RTSX card reader driver"),

}

ALC_LAYOUTS: dict[str, list[int]] = {
    "ALC255":  [3, 17, 18, 21, 27, 29, 69, 71, 76, 82, 86, 100],
    "ALC256":  [5, 12, 14, 21, 23, 56, 57, 69, 76, 82, 97, 99, 100],
    "ALC257":  [11, 13, 17, 18, 21, 23, 28, 66, 86, 97, 100],
    "ALC269":  [1, 3, 5, 7, 10, 11, 12, 13, 15, 17, 18, 20, 21, 22, 27, 28, 29, 55, 69, 76, 77, 88, 89, 99],
    "ALC280":  [3, 4, 5, 6, 7, 28, 29],
    "ALC282":  [3, 5, 7, 25, 28, 29, 44, 86],
    "ALC283":  [1, 3, 4, 5, 7, 11, 44, 86, 99],
    "ALC285":  [11, 21, 22, 31, 35, 61, 76, 85, 86, 93],
    "ALC287":  [11, 21, 34, 35, 56, 57, 71, 77, 90, 99],
    "ALC289":  [11, 23, 87, 88, 93],
    "ALC292":  [12, 15, 18, 28, 29],
    "ALC293":  [3, 28, 29, 44],
    "ALC294":  [11, 13, 21, 28, 44, 55, 66, 77],
    "ALC295":  [11, 13, 15, 21, 22, 28, 29, 77, 88, 96],
    "ALC298":  [3, 13, 28, 29, 47, 72],
    "ALC700":  [33, 35, 66, 69],
    "ALC887":  [1, 2, 3, 5, 7, 11, 12, 13, 17, 18, 25, 28, 29, 40, 66, 72, 99],
    "ALC892":  [1, 2, 3, 4, 5, 7, 11, 12, 15, 18, 28, 29, 66, 69, 92, 98, 99],
    "ALC897":  [11, 12, 13, 23, 66, 69, 76, 97, 99, 100],
    "ALC1150": [1, 2, 3, 5, 6, 7, 11, 101],
    "ALC1220": [1, 2, 3, 5, 7, 11, 13, 15, 21, 28, 29, 34, 69, 76, 86, 99, 100, 107],
    "Realtek ALC257": [11, 13, 17, 18, 21, 23, 28, 66, 86, 97, 100],
}

def get_alc_layout(codec: str) -> int:
    for key, layouts in ALC_LAYOUTS.items():
        if key.lower() in codec.lower():
            return layouts[0]
    return 1

def alc_layout_is_known(codec: str) -> bool:
    return any(key.lower() in codec.lower() for key in ALC_LAYOUTS)

def _dmi(field: str) -> str:
    if IS_WINDOWS:
        wmi_map = {
            "sys_vendor":    "(Get-WmiObject Win32_ComputerSystem).Manufacturer",
            "product_name":  "(Get-WmiObject Win32_ComputerSystem).Model",
            "board_vendor":  "(Get-WmiObject Win32_BaseBoard).Manufacturer",
            "board_name":    "(Get-WmiObject Win32_BaseBoard).Product",
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

def _detect_touchpad_type(profile: "HardwareProfile | None" = None) -> str:
    """Fine-grained trackpad bus/vendor for kext selection: 'ps2', 'rmi',
    'i2c_hid', 'i2c_elan', 'i2c_synaptics', ...

    The live probes below can only see the trackpad when the build host *is*
    the target machine. When they come up empty but the scan already concluded
    the target has an I2C trackpad (profile.touchpad_type == 'i2c'), trust that
    and fall back to the generic 'i2c_hid' satellite rather than silently
    handing the laptop PS/2 kexts and dropping SSDT-GPI0.
    """
    fine = _probe_touchpad_type()
    if fine == "ps2" and profile is not None and getattr(profile, "touchpad_type", "") == "i2c":
        return "i2c_hid"
    return fine


def _probe_touchpad_type() -> str:
    if IS_MACOS:
        try:
            io = subprocess.run(["ioreg", "-l"], capture_output=True, text=True, timeout=10).stdout.lower()
        except Exception:
            io = ""
        if "elan" in io and ("i2c" in io or "hid" in io):     return "i2c_elan"
        if "synaptics" in io and ("i2c" in io or "hid" in io): return "i2c_synaptics"
        if any(k in io for k in ("voodooi2c", "applehsspihiddriver", "pnp0c50", "acpi0c50", "i2c-hid")):
            return "i2c_hid"
        return "ps2"
    if IS_WINDOWS:
        # Widened: also pull every device whose HardwareID/InstanceId carries the
        # I2C-HID ACPI id (PNP0C50 / ACPI0C50). Filtering only on a name match of
        # 'touchpad|trackpad|synaptics|elan|alps' missed generic-named precision
        # touchpads ("I2C HID Device"), which then got PS/2 kexts and no GPI0.
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_PnPEntity | Where-Object { $_.Name -match 'touchpad|trackpad|synaptics|elan|alps' -or "
                 "($_.PNPDeviceID -match 'PNP0C50|ACPI0C50') } | ForEach-Object { \"$($_.Name) $($_.PNPDeviceID)\" }"],
                capture_output=True, text=True, timeout=10
            ).stdout.lower()
        except Exception:
            out = ""
        combined = out
        if "pnp0c50" in combined or "acpi0c50" in combined:
            combined += " i2c-hid"
    else:
        dmesg = subprocess.run(["dmesg"], capture_output=True, text=True).stdout.lower()
        i2c = subprocess.run(["find", "/sys/bus/i2c/devices", "-name", "name"],
                             capture_output=True, text=True).stdout.lower()
        smbus = subprocess.run(["find", "/sys/bus/platform/devices", "-name", "name"],
                               capture_output=True, text=True).stdout.lower()
        combined = dmesg + i2c + smbus

    if "rmi4" in combined or "rmi " in combined:     return "rmi"
    if "elan" in combined and "i2c" in combined:     return "i2c_elan"
    if "synaptics" in combined and "i2c" in combined:return "i2c_synaptics"
    if "atmel" in combined and "i2c" in combined:    return "i2c_atmel"
    if "goodix" in combined:                         return "i2c_goodix"
    if "fte" in combined and "i2c" in combined:      return "i2c_fte"
    if "alps" in combined and "i2c" in combined:     return "i2c_alps"
    if "i2c-hid" in combined or ("i2c" in combined and IS_WINDOWS): return "i2c_hid"
    return "ps2"

def _is_legacy(profile: HardwareProfile) -> bool:
    return profile.cpu_generation > 0 and profile.cpu_generation < 2

def _is_amd_apu(profile: HardwareProfile) -> bool:
    return (profile.cpu_vendor == "amd"
            and profile.gpu_vendor in ("amd", "")
            and (any(x in profile.gpu_name.lower() for x in ["vega", "radeon graphics", "renoir", "cezanne", "rembrandt", "phoenix", "navi"])
                 or re.search(r"\b\d{3}m\b", profile.gpu_name.lower()) is not None))

_NAVI2X_DEVICE_IDS = {
    "73A1", "73A2", "73A3", "73A4", "73A5", "73AB", "73AE", "73AF", "73BF",
    "73C3", "73C4", "73CE", "73DF",
    "73E0", "73E1", "73E3", "73E4", "73EF", "73FF",
}

def _amd_gpu(profile: HardwareProfile) -> tuple[str, str] | None:
    if profile.gpu_vendor == "amd":
        return profile.gpu_name, profile.gpu_device_id
    if profile.dgpu_vendor == "amd":
        return profile.dgpu_name, profile.dgpu_device_id
    return None

def _is_navi2x(profile: HardwareProfile) -> bool:
    amd_gpu = _amd_gpu(profile)
    if amd_gpu is None:
        return False
    name, device_id = amd_gpu
    name = name.lower()
    if any(x in name for x in [
        "rx 6600", "rx 6700", "rx 6800", "rx 6900", "navi 21", "navi 22", "navi 23", "navi 24"]):
        return True
    return device_id.upper().rsplit(":", 1)[-1] in _NAVI2X_DEVICE_IDS

def _is_hedt(profile: HardwareProfile) -> bool:
    name = profile.cpu_name.lower()
    return any(x in name for x in ["threadripper", "xeon w-", "i9-79", "i9-78", "i7-79", "i7-78"])

_XHCI_UNSUPPORTED_CHIPSETS = (
    "h370", "b360", "h310", "x79", "x99",
    # b365, q370, c246 share the same 300-series PCH die and USB3 XHCI
    # controller silicon as h370/b360/h310 (fuse-differentiated only) —
    # same "unsupported controller" problem, just missing from this list.
    "b365", "q370", "c246",
)

_XHCI_UNSUPPORTED_OEM_VENDORS = ("dell", "hp", "hewlett-packard", "lenovo")

def _needs_xhci_unsupported(board_name: str, vendor: str = "", platform: str = "", cpu_generation: int = 0) -> bool:
    name = board_name.lower()
    if any(chipset in name for chipset in _XHCI_UNSUPPORTED_CHIPSETS):
        return True
    # OEM desktops (Dell/HP/Lenovo) report cryptic board names (e.g. Dell's
    # "0G8YWV") that never mention the chipset, so the string match above
    # can't catch them — field-confirmed on a Dell OptiPlex (i3-9100/B365).
    # OEM prebuilts in this CPU generation range only ever ship the 300-series
    # PCH family (B360/H370/B365/Q370), never enthusiast boards like Z390, so
    # generation + OEM vendor alone is a safe stand-in for chipset detection.
    vendor_l = vendor.lower()
    if platform == "desktop" and cpu_generation in (8, 9) and any(v in vendor_l for v in _XHCI_UNSUPPORTED_OEM_VENDORS):
        return True
    return False

def _has_card_reader() -> bool:
    import platform
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_PnPEntity | Where-Object { $_.Name -match 'card reader|rts5|rtsx' } | Measure-Object | Select-Object -ExpandProperty Count"],
                capture_output=True, text=True, timeout=8
            ).stdout.strip()
            return int(out) > 0
        except Exception:
            return False
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(
                ["system_profiler", "SPUSBDataType"],
                capture_output=True, text=True, timeout=8
            ).stdout.lower()
            return "rts5" in out or "card reader" in out or "rtsx" in out
        except Exception:
            return False
    try:
        out = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=5).stdout.lower()
        return "rts5" in out or "card reader" in out or "rtsx" in out
    except Exception:
        return False

def select_kexts(profile: HardwareProfile, wifi_kext_mode: str = "itlwm") -> list[KextEntry]:
    selected: list[KextEntry] = []
    seen: set[str] = set()

    def add(*names: str):
        for name in names:
            if name in DB and name not in seen:
                seen.add(name)
                selected.append(DB[name])

    vendor = _dmi("sys_vendor") or _dmi("board_vendor")
    board_name = _dmi("board_name")
    tp = _detect_touchpad_type(profile) if profile.platform == "laptop" else "none"
    legacy = _is_legacy(profile)

    add("Lilu")
    add("FakeSMC" if legacy else "VirtualSMC")
    add("RestrictEvents", "FeatureUnlock")

    if _is_amd_apu(profile):
        add("NootedRed")
    else:
        add("WhateverGreen")

    if legacy:
        pass  # sensor plugins removed from DB — no working release exists anywhere (see DB comment)
    else:
        add("SMCProcessor")
        if profile.platform == "laptop":
            add("SMCBatteryManager", "SMCLightSensor")
        else:
            add("SMCSuperIO")
        if "dell" in vendor:
            add("SMCDellSensors")
        if profile.dgpu_vendor == "amd" or (profile.gpu_vendor == "amd" and not _is_amd_apu(profile)):
            add("SMCRadeonGPU")
        if profile.cpu_vendor == "amd":
            add("SMCAMDProcessor")

    codec = profile.audio_codec.lower()
    alc_supported = any(k.lower() in codec for k in ALC_LAYOUTS)
    if alc_supported or not codec:
        add("AppleALC")
    # VoodooHDA is not safe to prelink from an installer EFI on modern macOS.
    # Upstream's Big Sur+ workflow installs it into /Library/Extensions after
    # macOS is running, so leave explicitly unsupported codecs unconfigured
    # here instead of turning a missing-audio issue into a boot failure.
    # CodecCommander (EAPD sleep fix) is handled by AppleALC on modern systems

    if profile.platform == "laptop":
        if tp == "rmi":
            add("VoodooRMI", "VoodooPS2Controller", "VoodooInput")
        elif tp.startswith("i2c"):
            add("VoodooPS2Controller", "VoodooI2C", "VoodooInput")
            sat = {
                "i2c_hid":      "VoodooI2CHID",
                "i2c_synaptics":"VoodooI2CSynaptics",
                "i2c_elan":     "VoodooI2CELAN",
                "i2c_atmel":    "VoodooI2CAtmel",
                "i2c_fte":      "VoodooI2CFTE",
                "i2c_goodix":   "VoodooI2CGoodix",
                "i2c_alps":     "AlpsHID",
            }.get(tp, "VoodooI2CHID")
            add(sat)
            # VoodooGPIO is bundled inside VoodooI2C — don't add standalone
        else:
            add("VoodooPS2Controller")

        add("BrightnessKeys", "ECEnabler", "HibernationFixup", "NoTouchID")

    chip = profile.ethernet_chipset
    eth_map = {
        "i219": "IntelMausiEthernet", "i218": "IntelMausiEthernet", "i217": "IntelMausiEthernet",
        "i225": "AppleIGC",           "i226": "AppleIGC",
        "i211": "AppleIntelI210Ethernet", "i210": "AppleIntelI210Ethernet",
        "e1000e": "AppleIntelE1000e",
        "rtl8111": "RealtekRTL8111",  "rtl8168": "RealtekRTL8111",
        "rtl8100": "RealtekRTL8100",  "rtl8102": "RealtekRTL8100",
        "rtl8125": "LucyRTL8125Ethernet",
        "rtl8169": "RealtekR1000",
        "ar81xx": "AtherosE2200Ethernet",
        "ar8151": "AtherosE2200Ethernet", "ar8161": "AtherosE2200Ethernet",
        "ar8031": "AtherosL1eEthernet",
        "bcm5722": "BCM5722D",
    }
    if chip in eth_map:
        add(eth_map[chip])
    elif not chip:
        add("NullEthernet")

    wchip = profile.wifi_chipset
    if wifi_kext_mode == "none":
        pass  # user opted to leave onboard WiFi/BT untouched — no kexts injected
    elif wchip == "intel":
        chosen = "AirportItlwm" if wifi_kext_mode == "AirportItlwm" else "itlwm"
        add(chosen, "IntelBluetoothFirmware", "IntelBTPatcher", "BlueToolFixup")
    elif wchip == "broadcom":
        add("AirportBrcmFixup", "BrcmPatchRAM3", "BrcmFirmwareData", "BrcmBluetoothInjector", "BlueToolFixup")
    elif wchip == "atheros":
        add("ATH9KFixup")

    if _is_navi2x(profile):
        add("NootRX")
    if profile.dgpu_vendor == "amd" or (profile.gpu_vendor == "amd" and not _is_amd_apu(profile)):
        add("RadeonSensor")

    if legacy:
        add("NullCPUPowerManagement")
    else:
        add("CPUFriend")
        if profile.cpu_vendor == "intel" and profile.cpu_generation >= 12:
            add("CpuTopologyRebuild")
    if profile.cpu_vendor == "amd":
        add("AMDRyzenCPUPowerManagement", "AmdTSCSync", "CryptexFixup")
    if _is_hedt(profile):
        add("ForgedInvariant")

    if profile.nvme_present:
        add("NVMeFix")

    add("USBToolBox", "UTBMap")
    if profile.cpu_vendor == "intel" and (
        profile.cpu_generation <= 3
        or _needs_xhci_unsupported(board_name, vendor, profile.platform, profile.cpu_generation)
    ):
        add("XHCI-unsupported")

    # IOElectrify/ThunderboltReset are unmaintained; modern OC handles TB natively

    if "lenovo" in vendor:
        add("YogaSMC")
    if "asus" in vendor or "asustek" in vendor:
        add("AsusSMC")

    if _has_card_reader():
        add("RealtekCardReader", "RealtekCardReaderFriend")

    return selected

def _github_headers() -> dict:
    """Unauthenticated GitHub API calls are capped at 60 req/hr, which every
    kext download eats into individually — a handful of reruns in the same
    hour is enough to trip it. GITHUB_TOKEN raises that to 5000 req/hr, but
    nothing ever actually sent it despite the rate-limit error telling users
    to set it. Wire it up if present."""
    headers = {"User-Agent": "HackMate/1.0"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def _get_latest_release(repo: str) -> Optional[dict]:
    import urllib.error
    headers = _github_headers()

    def _fetch(url: str) -> Optional[dict]:
        try:
            data = json.loads(http_get(url, headers=headers, timeout=10))
            # Surface rate limit as a clear error instead of silent None
            if isinstance(data, dict) and "rate limit" in data.get("message", "").lower():
                raise RuntimeError(
                    "GitHub API rate limit exceeded (60 req/hr unauthenticated). "
                    "Wait ~1 hour and rerun, or set a GITHUB_TOKEN environment variable."
                )
            return data
        except RuntimeError:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                try:
                    body = json.loads(e.read())
                except Exception:
                    body = {}
                if "rate limit" in body.get("message", "").lower() or e.code == 429:
                    raise RuntimeError(
                        "GitHub API rate limit exceeded (60 req/hr unauthenticated). "
                        "Wait ~1 hour and rerun, or set a GITHUB_TOKEN environment variable."
                    )
            return None
        except Exception:
            return None

    # Try /latest first (fastest, skips pre-releases)
    result = _fetch(f"https://api.github.com/repos/{repo}/releases/latest")
    if result:
        return result

    # Fall back to releases list — picks first non-draft (covers pre-release-only repos)
    releases = _fetch(f"https://api.github.com/repos/{repo}/releases?per_page=5")
    if isinstance(releases, list):
        for rel in releases:
            if not rel.get("draft", False):
                return rel

    return None

def _find_asset(assets: list, pattern: str) -> Optional[dict]:
    for asset in assets:
        name = asset["name"].lower()
        if pattern.lower() in name and name.endswith(".zip") and "debug" not in name and "devel" not in name and "dsym" not in name:
            return asset
    for asset in assets:
        name = asset["name"].lower()
        if pattern.lower() in name and name.endswith(".zip"):
            return asset
    return None

def download_usbtoolbox_app(dest: Path, progress_cb=None) -> Optional[Path]:
    """Download USBToolBox app (macOS or Windows) into dest/. Returns the
    saved zip's path (truthy) on success, so callers doing automatic USB
    mapping can pull usbdump.exe out of it without a second download."""
    if progress_cb:
        progress_cb("Downloading USBToolBox app...")
    headers = _github_headers()

    # Find latest release that has a macOS or Windows asset
    try:
        releases_raw = json.loads(http_get(
            "https://api.github.com/repos/USBToolBox/Tool/releases?per_page=10",
            headers=headers, timeout=10,
        ))
    except Exception:
        return None

    asset = None
    for release in (releases_raw or []):
        for a in release.get("assets", []):
            name = a["name"].lower()
            if IS_WINDOWS and "windows" in name and name.endswith(".zip"):
                asset = a
                break
            if not IS_WINDOWS and "macos" in name and name.endswith(".zip"):
                asset = a
                break
        if asset:
            break

    if not asset:
        return None

    dest.mkdir(parents=True, exist_ok=True)
    out = dest / asset["name"]
    try:
        out.write_bytes(http_get(asset["browser_download_url"], headers=headers, timeout=60))
        if progress_cb:
            progress_cb(f"USBToolBox saved to {out.name}")
        return out
    except Exception:
        return None

def download_heliport(dest: Path, progress_cb=None) -> bool:
    """Download HeliPort.app (needed with itlwm) into dest/HeliPort.app.zip."""
    if progress_cb:
        progress_cb("Downloading HeliPort.app...")
    try:
        release = _get_latest_release("OpenIntelWireless/HeliPort")
    except RuntimeError as e:
        if progress_cb:
            progress_cb(f"HeliPort download failed: {e}")
        return False
    if not release:
        return False
    assets = release.get("assets", [])
    asset = next((a for a in assets if a["name"].lower().endswith(".dmg") or
                  "heliport" in a["name"].lower()), None)
    if not asset:
        return False
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / asset["name"]
    try:
        out.write_bytes(http_get(asset["browser_download_url"], timeout=60))
        if progress_cb:
            progress_cb(f"HeliPort saved to {out.name}")
        return True
    except Exception:
        return False

def check_kext_sources(kexts: list[KextEntry], progress_cb=None, macos_version: str = "") -> tuple[dict[str, str], dict[str, list]]:
    """
    Resolve every kext's download before touching the USB.

    A kext whose repo has been renamed or deleted only fails once the build is
    already underway, and it is then quietly dropped from config.plist — the user
    finds out when the hardware it drives does not work. Checking first turns
    that into a warning you can act on. Returns (results, release_cache); pass
    the cache to download_kexts so releases are not fetched twice.
    """
    results: dict[str, str] = {}
    cache: dict[str, list] = {}

    repos = [k for k in kexts if k.repo]
    for i, kext in enumerate(repos):
        if progress_cb:
            progress_cb(i, len(repos), f"Checking {kext.name}...")

        if kext.repo not in cache:
            try:
                release = _get_latest_release(kext.repo)
            except RuntimeError as e:
                results[kext.name] = f"ERROR: {e}"
                continue
            cache[kext.repo] = release.get("assets", []) if release else []

        assets = cache[kext.repo]
        if not assets:
            results[kext.name] = f"ERROR: no downloadable release at github.com/{kext.repo}"
        elif kext.name == "AirportItlwm":
            keyword = _AIRPORTITLWM_KEYWORDS.get(macos_version, "")
            if not keyword:
                results[kext.name] = (
                    f"ERROR: AirportItlwm has no build for macOS {macos_version or 'this version'} "
                    f"— use Standard (itlwm) WiFi mode instead"
                )
            elif not any(
                kext.asset_pattern.lower() in a["name"].lower()
                and keyword in a["name"].lower()
                and a["name"].lower().endswith(".zip")
                for a in assets
            ):
                results[kext.name] = (
                    f"ERROR: no AirportItlwm build found for macOS {macos_version} "
                    f"— use Standard (itlwm) WiFi mode instead"
                )
            else:
                results[kext.name] = "OK"
        elif not _find_asset(assets, kext.asset_pattern):
            results[kext.name] = f"ERROR: no asset matching '{kext.asset_pattern}' in latest release"
        else:
            results[kext.name] = "OK"

    for kext in kexts:
        results.setdefault(kext.name, "SKIP (user-generated)")

    return results, cache


def _kext_valid(kext_path: Path) -> bool:
    return (
        kext_path.is_dir() and
        (kext_path / "Contents" / "Info.plist").exists() and
        (kext_path / "Contents" / "Info.plist").stat().st_size > 100
    )

_AIRPORTITLWM_KEYWORDS = {
    "10.13": "highsierra",
    "10.14": "mojave",
    "10.15": "catalina",
    "11": "bigsur",
    "12": "monterey",
    "13": "ventura",
    "14": "sonoma",
}

def download_kexts(kexts: list[KextEntry], dest: Path, progress_cb=None, verify: bool = False,
                   release_cache: dict[str, list] | None = None, macos_version: str = "") -> dict[str, str]:
    dest.mkdir(parents=True, exist_ok=True)
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="hackmate_kexts_"))
    results: dict[str, str] = {}
    seen_repos: dict[str, list] = dict(release_cache or {})

    for i, kext in enumerate(kexts):
        kext_dest = dest / f"{kext.name}.kext"

        if not kext.repo:
            results[kext.name] = "SKIP (user-generated)"
            continue

        if verify and _kext_valid(kext_dest):
            if progress_cb:
                progress_cb(i, len(kexts), f"{kext.name} — already valid, skipping")
            results[kext.name] = "OK (cached)"
            continue

        if progress_cb:
            progress_cb(i, len(kexts), f"Downloading {kext.name}...")

        if kext.repo in seen_repos:
            assets = seen_repos[kext.repo]
        else:
            try:
                release = _get_latest_release(kext.repo)
            except RuntimeError as e:
                results[kext.name] = f"ERROR: {e}"
                continue
            if not release:
                results[kext.name] = "ERROR: could not fetch release"
                continue
            assets = release.get("assets", [])
            seen_repos[kext.repo] = assets

        if kext.name == "AirportItlwm":
            keyword = _AIRPORTITLWM_KEYWORDS.get(macos_version, "")
            if not keyword:
                results[kext.name] = (
                    f"ERROR: AirportItlwm has no build for macOS {macos_version or 'this version'} "
                    f"— use Standard (itlwm) WiFi mode instead"
                )
                continue
            asset = next(
                (a for a in assets
                 if kext.asset_pattern.lower() in a["name"].lower()
                 and keyword in a["name"].lower()
                 and a["name"].lower().endswith(".zip")),
                None,
            )
            if not asset:
                results[kext.name] = (
                    f"ERROR: no AirportItlwm build found for macOS {macos_version} "
                    f"— use Standard (itlwm) WiFi mode instead"
                )
                continue
        else:
            asset = _find_asset(assets, kext.asset_pattern)
            if not asset:
                results[kext.name] = f"ERROR: no asset matching '{kext.asset_pattern}'"
                continue

        try:
            zip_path = _cached_or_download(asset, tmp)
        except Exception as e:
            results[kext.name] = f"ERROR: download failed: {e}"
            continue

        extract_dir = tmp / asset["name"].replace(".zip", "")
        _extract_zip(zip_path, extract_dir)

        kext_name = f"{kext.name}.kext"
        bundle = kext.bundle_name or kext.name
        base = bundle.lower()
        all_kexts = [
            p for p in extract_dir.rglob("*.kext")
            if p.is_dir() and "__MACOSX" not in p.parts
        ]
        found = (
            next((p for p in all_kexts if p.name.lower() == f"{base}.kext"), None) or
            next((p for p in all_kexts if p.name.lower().startswith(base + "_") or p.name.lower().startswith(base + "-")), None) or
            next((p for p in all_kexts if base in p.name.lower()), None)
        )
        if found:
            if kext_dest.exists():
                shutil.rmtree(str(kext_dest))
            shutil.copytree(str(found), str(kext_dest))
            results[kext.name] = f"OK ({asset['name']})"
        else:
            found_names = ", ".join(p.name for p in all_kexts) or "none"
            results[kext.name] = f"ERROR: {kext_name} not found (zip had: {found_names})"

    shutil.rmtree(str(tmp), ignore_errors=True)
    return results


OPENCORE_FALLBACK_VERSION = "1.0.7"
OPENCORE_FALLBACK_URL = (
    f"https://github.com/acidanthera/OpenCorePkg/releases/download/"
    f"{OPENCORE_FALLBACK_VERSION}/OpenCore-{OPENCORE_FALLBACK_VERSION}-DEBUG.zip"
)


def fetch_opencore(tmp: Path, log=None) -> Path:
    """
    Order: GitHub API for the latest release (cached on disk once fetched) →
    newest previously-cached zip → pinned fallback URL. The old code had no
    cache and no fallback, so an API rate limit killed the whole build — the
    second most common failure in hwdb reports (26 of 150)."""
    def _log(msg, level="info"):
        if log:
            log(msg, level)

    cache_dir = _CACHE_ROOT / "opencore"

    # 1. Ask the API what the latest release is
    oc_asset = None
    api_err = None
    try:
        data = json.loads(http_get(
            "https://api.github.com/repos/acidanthera/OpenCorePkg/releases/latest",
            headers=_github_headers(), timeout=15,
        ))
        for asset in data.get("assets", []):
            name = asset["name"].lower()
            if "opencore-" in name and "debug" in name and name.endswith(".zip"):
                oc_asset = asset
                break
    except Exception as e:
        api_err = e

    if oc_asset:
        last_err = None
        for attempt in range(3):
            try:
                return _cached_or_download(oc_asset, tmp, cache_name="opencore")
            except Exception as e:
                last_err = e
                _log(f"  OpenCore download attempt {attempt + 1}/3 failed: {e}", "warn")
        api_err = last_err

    # 2. API or download failed — reuse the newest cached zip
    cached = sorted(cache_dir.glob("OpenCore-*-DEBUG.zip"), reverse=True)
    if cached:
        _log(f"  GitHub unavailable ({api_err}) — using cached {cached[0].name}", "warn")
        return cached[0]

    # 3. Nothing cached — pinned fallback release, no API involved
    _log(f"  GitHub API unavailable ({api_err}) — falling back to OpenCore "
         f"{OPENCORE_FALLBACK_VERSION}", "warn")
    try:
        out = tmp / OPENCORE_FALLBACK_URL.rsplit("/", 1)[-1]
        out.write_bytes(http_get(OPENCORE_FALLBACK_URL, timeout=60))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(out), str(cache_dir / out.name))
        except Exception:
            pass
        return out
    except Exception as e:
        raise RuntimeError(
            f"OpenCore download failed — GitHub API said '{api_err}' and the "
            f"fallback release could not be fetched either ({e}). Check your "
            f"internet connection, or set a GITHUB_TOKEN environment variable "
            f"if you are rate-limited."
        ) from e


if __name__ == "__main__":
    from hardware import scan
    profile = scan()
    kexts = select_kexts(profile)
    vendor = _dmi("sys_vendor") or _dmi("board_vendor")
    tp = _detect_touchpad_type(profile) if profile.platform == "laptop" else "n/a"

    print(f"\n{'─'*65}")
    print(f"  HackMate Kext Selector  —  {len(DB)} kexts in database")
    print(f"{'─'*65}")
    print(f"  CPU:       {profile.cpu_name}")
    print(f"  GPU:       {profile.gpu_name} [{profile.gpu_vendor}]")
    print(f"  Audio:     {profile.audio_codec}  →  layout-id {get_alc_layout(profile.audio_codec)}")
    print(f"  Platform:  {profile.platform}  |  Vendor: {vendor}  |  Touchpad: {tp}")
    print(f"  SMBIOS:    {profile.smbios_model}  |  OC: {profile.oc_platform}")
    print(f"{'─'*65}")
    print(f"\n  {len(kexts)} kexts selected for this machine:\n")
    for k in kexts:
        print(f"  {k.name:<32} # {k.note}")
    print(f"\n  {len(DB) - len(kexts)} kexts in DB not needed for this hardware.")
    print()
