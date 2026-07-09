import urllib.request
import json
import zipfile
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from hardware import HardwareProfile
from compat import IS_WINDOWS

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
    "FakeSMC":           KextEntry("FakeSMC",         "RehabMan/OS-X-FakeSMC-kozlek", "FakeSMC-",           "SMC emulator (legacy, pre-Sandy Bridge)"),
    "RestrictEvents":    KextEntry("RestrictEvents",  "acidanthera/RestrictEvents",   "RestrictEvents-",    "various system event patches"),
    "FeatureUnlock":     KextEntry("FeatureUnlock",   "acidanthera/FeatureUnlock",    "FeatureUnlock-",     "Sidecar, AirPlay, Universal Control on unsupported SMBIOS"),
    "CPUFriend":         KextEntry("CPUFriend",       "acidanthera/CPUFriend",        "CPUFriend-",         "CPU frequency/power management"),
    "NVMeFix":           KextEntry("NVMeFix",         "acidanthera/NVMeFix",          "NVMeFix-",           "NVMe power management + APST"),
    "DebugEnhancer":     KextEntry("DebugEnhancer",   "acidanthera/DebugEnhancer",    "DebugEnhancer-",     "kernel debug logging"),
    "CryptexFixup":      KextEntry("CryptexFixup",    "acidanthera/CryptexFixup",     "CryptexFixup-",      "Ventura+ cryptex on older/AMD hardware"),

    "FakeSMC_ACPISensors": KextEntry("FakeSMC_ACPISensors", "RehabMan/OS-X-FakeSMC-kozlek", "FakeSMC-",  "ACPI sensors plugin for FakeSMC"),
    "FakeSMC_CPUSensors":  KextEntry("FakeSMC_CPUSensors",  "RehabMan/OS-X-FakeSMC-kozlek", "FakeSMC-",  "CPU sensors plugin for FakeSMC"),
    "FakeSMC_GPUSensors":  KextEntry("FakeSMC_GPUSensors",  "RehabMan/OS-X-FakeSMC-kozlek", "FakeSMC-",  "GPU sensors plugin for FakeSMC"),
    "FakeSMC_LPCSensors":  KextEntry("FakeSMC_LPCSensors",  "RehabMan/OS-X-FakeSMC-kozlek", "FakeSMC-",  "LPC sensors plugin for FakeSMC"),
    "FakeSMC_SMMSensors":  KextEntry("FakeSMC_SMMSensors",  "RehabMan/OS-X-FakeSMC-kozlek", "FakeSMC-",  "SMM sensors plugin for FakeSMC"),

    "SMCBatteryManager": KextEntry("SMCBatteryManager","acidanthera/VirtualSMC",      "VirtualSMC-",        "battery status (in VirtualSMC zip)"),
    "SMCProcessor":      KextEntry("SMCProcessor",     "acidanthera/VirtualSMC",      "VirtualSMC-",        "CPU temp sensors (in VirtualSMC zip)"),
    "SMCSuperIO":        KextEntry("SMCSuperIO",       "acidanthera/VirtualSMC",      "VirtualSMC-",        "desktop fan sensors (in VirtualSMC zip)"),
    "SMCLightSensor":    KextEntry("SMCLightSensor",   "acidanthera/VirtualSMC",      "VirtualSMC-",        "ambient light sensor (in VirtualSMC zip)"),
    "SMCDellSensors":    KextEntry("SMCDellSensors",   "acidanthera/VirtualSMC",      "VirtualSMC-",        "Dell fan/temp sensors (in VirtualSMC zip)"),
    "SMCAMDProcessor":   KextEntry("SMCAMDProcessor",  "trulyspinach/AMDRyzenCPUPowerManagement","SMCAMDProcessor-","AMD CPU sensors"),
    "SMCRadeonGPU":      KextEntry("SMCRadeonGPU",     "aluveitie/RadeonSensor",      "SMCRadeonGPU-",      "AMD GPU temp in HWMonitor"),

    "AppleALC":          KextEntry("AppleALC",         "acidanthera/AppleALC",        "AppleALC-",          "audio codec patches via Lilu"),
    "VoodooHDA":         KextEntry("VoodooHDA",        "chris1111/VoodooHDA-OC",      "VoodooHDA-",         "fallback audio for unsupported codecs"),
    "CodecCommander":    KextEntry("CodecCommander",   "acidanthera/AppleALC",        "AppleALC-",          "fixes audio after sleep — bundled workaround via AppleALC"),
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
    "VoodooSMBus":       KextEntry("VoodooSMBus",      "VoodooI2C/VoodooSMBus",       "VoodooSMBus-",       "SMBus trackpad (Synaptics PS2 over SMBus)"),
    "VoodooRMI":         KextEntry("VoodooRMI",        "1Revenger1/VoodooRMI",        "VoodooRMI-",         "Synaptics RMI4 trackpad (better than PS2 on some laptops)"),

    "IntelMausiEthernet":KextEntry("IntelMausiEthernet","acidanthera/IntelMausi",        "IntelMausi-",        "Intel I219/I218/I217 Ethernet", bundle_name="IntelMausi", exe_name="IntelMausi"),
    "AppleIGC":          KextEntry("AppleIGC",         "SongXiaoXi/AppleIGC",         "AppleIGC-",          "Intel I225-V / I226-V 2.5GbE"),
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
    "NullEthernet":      KextEntry("NullEthernet",     "RehabMan/OS-X-Null-Ethernet", "NullEthernet-",      "placeholder ethernet for iMessage/iCloud on WiFi-only"),

    "itlwm":             KextEntry("itlwm",            "OpenIntelWireless/itlwm",     "itlwm_",             "Intel WiFi (needs HeliPort app for menu bar)"),
    "AirportItlwm":      KextEntry("AirportItlwm",     "OpenIntelWireless/itlwm",     "AirportItlwm_",      "Intel WiFi as native AirportBSD (macOS version specific!)"),
    "AirportBrcmFixup":  KextEntry("AirportBrcmFixup", "acidanthera/AirportBrcmFixup","AirportBrcmFixup-",  "Broadcom BCM94352Z/BCM943602CS WiFi patches"),
    "ATH9KFixup":        KextEntry("ATH9KFixup",       "chontos/ATH9KFixup",          "ATH9KFixup-",        "Atheros AR9xxx WiFi patches"),

    "BrcmPatchRAM":      KextEntry("BrcmPatchRAM",     "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM-",      "Broadcom BT (macOS 10.10 and below)"),
    "BrcmPatchRAM2":     KextEntry("BrcmPatchRAM2",    "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM2-",     "Broadcom BT (macOS 10.11-11)"),
    "BrcmPatchRAM3":     KextEntry("BrcmPatchRAM3",    "acidanthera/BrcmPatchRAM",    "BrcmPatchRAM3-",     "Broadcom BT (macOS 12+)"),
    "BrcmFirmwareData":  KextEntry("BrcmFirmwareData", "acidanthera/BrcmPatchRAM",    "BrcmFirmwareData-",  "Broadcom BT firmware data"),
    "BrcmFirmwareRepo":  KextEntry("BrcmFirmwareRepo", "acidanthera/BrcmPatchRAM",    "BrcmFirmwareRepo-",  "Broadcom BT firmware repo (for in-memory loading)"),
    "BrcmBluetoothInjector":KextEntry("BrcmBluetoothInjector","acidanthera/BrcmPatchRAM","BrcmBluetoothInjector-","Broadcom BT injector (macOS 12 and below)"),
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
    "AMDRyzenCPUPowerManagement":KextEntry("AMDRyzenCPUPowerManagement","trulyspinach/AMDRyzenCPUPowerManagement","AMDRyzenCPUPowerManagement-","AMD Ryzen CPU power management"),
    "CpuTopologyRebuild":KextEntry("CpuTopologyRebuild","b00t0x/CpuTopologyRebuild",  "CpuTopologyRebuild-","Alder/Raptor Lake P+E core topology fix"),
    "HibernationFixup":  KextEntry("HibernationFixup", "acidanthera/HibernationFixup","HibernationFixup-",  "sleep/wake stability fix"),

    "ECEnabler":         KextEntry("ECEnabler",        "1Revenger1/ECEnabler",        "ECEnabler-",         "battery EC fields >8-bit (replaces ACPIBatteryManager patches)"),
    "ACPIBatteryManager":KextEntry("ACPIBatteryManager","RehabMan/OS-X-ACPI-Battery-Driver","ACPIBatteryManager-","battery (legacy, use ECEnabler instead on modern OC)"),

    "USBToolBox":        KextEntry("USBToolBox",       "USBToolBox/kext",             "USBToolBox-",        "USB port mapping tool"),
    "UTBMap":            KextEntry("UTBMap",           "",                            "",                   "USB port map (user-generated via USB Mapping after first boot)"),
    "USBInjectAll":      KextEntry("USBInjectAll",     "Sniki/OS-X-USB-Inject-All",   "USBInjectAll-",      "inject all USB ports (use only during mapping, not final EFI)"),
    "XHCI-unsupported":  KextEntry("XHCI-unsupported", "RehabMan/OS-X-USB-Inject-All","XHCI-unsupported-",  "unsupported USB 3.0 controllers (Sandy/Ivy Bridge)"),

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

    "RealtekCardReader": KextEntry("RealtekCardReader","0xFireWolf/RealtekCardReader", "RealtekCardReader-", "Realtek RTS5xxx SD card reader"),
    "RealtekCardReaderFriend":KextEntry("RealtekCardReaderFriend","0xFireWolf/RealtekCardReaderFriend","RealtekCardReaderFriend-","Lilu plugin companion for RealtekCardReader"),
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

def _detect_touchpad_type() -> str:
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_PnPEntity | Where-Object { $_.Name -match 'touchpad|trackpad|synaptics|elan|alps' } | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10
            ).stdout.lower()
        except Exception:
            out = ""
        try:
            pnp = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_PnPEntity | Where-Object { $_.Name -match 'touchpad|trackpad|synaptics|elan|alps' } | Select-Object -ExpandProperty PNPDeviceID"],
                capture_output=True, text=True, timeout=10
            ).stdout.lower()
        except Exception:
            pnp = ""
        combined = out + pnp
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
    if "i2c-hid" in combined or ("i2c" in combined and IS_WINDOWS): return "i2c_hid"
    return "ps2"

def _is_legacy(profile: HardwareProfile) -> bool:
    return profile.cpu_generation > 0 and profile.cpu_generation < 2

def _is_amd_apu(profile: HardwareProfile) -> bool:
    return (profile.cpu_vendor == "amd"
            and profile.gpu_vendor in ("amd", "")
            and any(x in profile.gpu_name.lower() for x in ["vega", "radeon graphics", "renoir", "cezanne", "rembrandt", "phoenix", "navi"]))

def _is_navi2x(profile: HardwareProfile) -> bool:
    name = profile.gpu_name.lower()
    return profile.gpu_vendor == "amd" and any(x in name for x in [
        "rx 6600", "rx 6700", "rx 6800", "rx 6900", "navi 21", "navi 22", "navi 23", "navi 24"])

def _is_hedt(profile: HardwareProfile) -> bool:
    name = profile.cpu_name.lower()
    return any(x in name for x in ["threadripper", "xeon w-", "i9-79", "i9-78", "i7-79", "i7-78"])

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
    tp = _detect_touchpad_type() if profile.platform == "laptop" else "none"
    legacy = _is_legacy(profile)

    add("Lilu")
    add("FakeSMC" if legacy else "VirtualSMC")
    add("RestrictEvents", "FeatureUnlock")

    # AMD APU uses NootedRed instead of WhateverGreen.
    # Intel Arc has no macOS driver at all, so it just gets WhateverGreen
    # (harmless no-op) — efi_check warns about the unsupported GPU separately.
    if _is_amd_apu(profile):
        add("NootedRed")
    else:
        add("WhateverGreen")

    if legacy:
        add("FakeSMC_ACPISensors", "FakeSMC_CPUSensors", "FakeSMC_GPUSensors",
            "FakeSMC_LPCSensors", "FakeSMC_SMMSensors")
    else:
        add("SMCProcessor")
        if profile.platform == "laptop":
            add("SMCBatteryManager", "SMCLightSensor")
        else:
            add("SMCSuperIO")
        if "dell" in vendor:
            add("SMCDellSensors")
        if profile.gpu_vendor == "amd" and not _is_amd_apu(profile):
            add("SMCRadeonGPU")
        if profile.cpu_vendor == "amd":
            add("SMCAMDProcessor")

    codec = profile.audio_codec.lower()
    alc_supported = any(k.lower() in codec for k in ALC_LAYOUTS)
    if alc_supported or not profile.audio_codec:
        add("AppleALC")
    else:
        add("VoodooHDA")
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
    if wchip == "intel":
        chosen = "AirportItlwm" if wifi_kext_mode == "AirportItlwm" else "itlwm"
        add(chosen, "IntelBluetoothFirmware", "IntelBTPatcher", "BlueToolFixup")
    elif wchip == "broadcom":
        add("AirportBrcmFixup", "BrcmPatchRAM3", "BrcmFirmwareData", "BrcmBluetoothInjector", "BlueToolFixup")
    elif wchip == "atheros":
        add("ATH9KFixup")

    if _is_navi2x(profile):
        add("NootRX")
    if profile.gpu_vendor == "amd" and not _is_amd_apu(profile):
        add("RadeonSensor")

    add("CPUFriend")
    if profile.cpu_generation >= 12:
        add("CpuTopologyRebuild")
    if legacy:
        add("NullCPUPowerManagement")
    if profile.cpu_vendor == "amd":
        # Matches Dortania's AMD Vanilla set. AMFIPass (an OCLP root-patching
        # kext) and GenericUSBXHCI (pre-native-XHCI era) are not part of it.
        add("AMDRyzenCPUPowerManagement", "AmdTSCSync", "CryptexFixup")
    if _is_hedt(profile):
        add("ForgedInvariant")

    if profile.nvme_present:
        add("NVMeFix")

    # USBToolBox.kext enables port discovery; UTBMap.kext is a placeholder the
    # user replaces after running USBToolBox inside macOS (HackMate → USB Mapping)
    add("USBToolBox", "UTBMap")
    if profile.cpu_generation <= 3:
        add("XHCI-unsupported")

    # IOElectrify/ThunderboltReset are unmaintained; modern OC handles TB natively

    if "lenovo" in vendor:
        add("YogaSMC")
    if "asus" in vendor or "asustek" in vendor:
        add("AsusSMC")

    if _has_card_reader():
        add("RealtekCardReader", "RealtekCardReaderFriend")

    return selected

def _get_latest_release(repo: str) -> Optional[dict]:
    import ssl
    headers = {"User-Agent": "HackMate/1.0"}

    def _fetch(url: str) -> Optional[dict]:
        ctx = ssl.create_default_context()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                data = json.loads(r.read())
                # Surface rate limit as a clear error instead of silent None
                if isinstance(data, dict) and "rate limit" in data.get("message", "").lower():
                    raise RuntimeError(
                        "GitHub API rate limit exceeded (60 req/hr unauthenticated). "
                        "Wait ~1 hour and rerun, or set a GITHUB_TOKEN environment variable."
                    )
                return data
        except RuntimeError:
            raise
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

def download_usbtoolbox_app(dest: Path, progress_cb=None) -> bool:
    """Download USBToolBox app (macOS or Windows) into dest/."""
    if progress_cb:
        progress_cb("Downloading USBToolBox app...")
    import ssl as _ssl
    ctx = _ssl.create_default_context()
    headers = {"User-Agent": "HackMate/1.0"}

    # Find latest release that has a macOS or Windows asset
    releases_raw = None
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/USBToolBox/Tool/releases?per_page=10",
            headers=headers,
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            releases_raw = json.loads(r.read())
    except Exception:
        return False

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
        return False

    dest.mkdir(parents=True, exist_ok=True)
    out = dest / asset["name"]
    try:
        req = urllib.request.Request(asset["browser_download_url"], headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            out.write_bytes(r.read())
        if progress_cb:
            progress_cb(f"USBToolBox saved to {out.name}")
        return True
    except Exception:
        return False

def download_heliport(dest: Path, progress_cb=None) -> bool:
    """Download HeliPort.app (needed with itlwm) into dest/HeliPort.app.zip."""
    if progress_cb:
        progress_cb("Downloading HeliPort.app...")
    release = _get_latest_release("OpenIntelWireless/HeliPort")
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
        req = urllib.request.Request(asset["browser_download_url"],
                                     headers={"User-Agent": "HackMate/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            out.write_bytes(r.read())
        if progress_cb:
            progress_cb(f"HeliPort saved to {out.name}")
        return True
    except Exception:
        return False

def check_kext_sources(kexts: list[KextEntry], progress_cb=None) -> tuple[dict[str, str], dict[str, list]]:
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

def download_kexts(kexts: list[KextEntry], dest: Path, progress_cb=None, verify: bool = False,
                   release_cache: dict[str, list] | None = None) -> dict[str, str]:
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / "_tmp"
    tmp.mkdir(exist_ok=True)
    results: dict[str, str] = {}
    # Reuse releases already resolved by check_kext_sources — the unauthenticated
    # GitHub API allows only 60 requests an hour.
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

        asset = _find_asset(assets, kext.asset_pattern)
        if not asset:
            results[kext.name] = f"ERROR: no asset matching '{kext.asset_pattern}'"
            continue

        zip_path = tmp / asset["name"]
        try:
            import ssl as _ssl
            _ctx = _ssl.create_default_context()
            _req = urllib.request.Request(
                asset["browser_download_url"],
                headers={"User-Agent": "HackMate/1.0"},
            )
            with urllib.request.urlopen(_req, context=_ctx, timeout=60) as _r:
                zip_path.write_bytes(_r.read())
        except Exception as e:
            results[kext.name] = f"ERROR: download failed: {e}"
            continue

        # Verify downloaded zip size matches what GitHub reported
        expected_size = asset.get("size", 0)
        actual_size = zip_path.stat().st_size
        if expected_size and abs(actual_size - expected_size) > 1024:
            results[kext.name] = f"ERROR: size mismatch (got {actual_size}, expected {expected_size})"
            continue

        extract_dir = tmp / asset["name"].replace(".zip", "")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(str(extract_dir))

        kext_name = f"{kext.name}.kext"
        bundle = kext.bundle_name or kext.name
        base = bundle.lower()
        all_kexts = [p for p in extract_dir.rglob("*.kext") if p.is_dir()]
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

if __name__ == "__main__":
    from hardware import scan
    profile = scan()
    kexts = select_kexts(profile)
    vendor = _dmi("sys_vendor") or _dmi("board_vendor")
    tp = _detect_touchpad_type() if profile.platform == "laptop" else "n/a"

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
