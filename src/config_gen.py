import plistlib
import time
from pathlib import Path
from hardware import HardwareProfile, has_macos_supported_gpu
from kexts import KextEntry, select_kexts, get_alc_layout
from smbios import SMBIOSData
from compat import IS_WINDOWS, dmi_field, dmi_vendor, cpu_core_count, http_get, real_home

AMD_VANILLA_URL = "https://raw.githubusercontent.com/AMD-OSX/AMD_Vanilla/master/patches.plist"
_AMD_VANILLA_CACHE = real_home() / ".hackmate" / "cache" / "amd_vanilla" / "patches.plist"
_AMD_VANILLA_TTL = 24 * 3600

IG_PLATFORM_IDS: dict[str, bytes] = {
    # Sandy Bridge
    "snb_mobile": bytes([0x00, 0x00, 0x01, 0x00]),
    "snb_desktop": bytes([0x10, 0x00, 0x03, 0x00]),
    "snb_headless": bytes([0x00, 0x00, 0x05, 0x00]),
    # Ivy Bridge
    "ivb_mobile": bytes([0x03, 0x00, 0x66, 0x01]),
    "ivb_desktop": bytes([0x0A, 0x00, 0x66, 0x01]),
    "ivb_headless": bytes([0x07, 0x00, 0x62, 0x01]),
    # Haswell
    "hsw_mobile_iris": bytes([0x05, 0x00, 0x26, 0x0A]),
    "hsw_mobile": bytes([0x06, 0x00, 0x26, 0x0A]),
    "hsw_desktop": bytes([0x03, 0x00, 0x22, 0x0D]),
    "hsw_headless": bytes([0x04, 0x00, 0x12, 0x04]),
    # Broadwell
    "bdw_mobile": bytes([0x06, 0x00, 0x26, 0x16]),
    "bdw_desktop": bytes([0x07, 0x00, 0x22, 0x16]),
    # Skylake
    "skl_mobile": bytes([0x00, 0x00, 0x16, 0x19]),
    "skl_mobile_hd510": bytes([0x00, 0x00, 0x1B, 0x19]),
    "skl_desktop": bytes([0x00, 0x00, 0x12, 0x19]),
    "skl_headless": bytes([0x01, 0x00, 0x12, 0x19]),
    # Kaby Lake
    "hd615":     bytes([0x00, 0x00, 0x1B, 0x59]),
    "hd620":     bytes([0x00, 0x00, 0x16, 0x59]),
    "hd630_dt":  bytes([0x00, 0x00, 0x12, 0x59]),
    "hd630_mb":  bytes([0x00, 0x00, 0x1B, 0x59]),
    "hd630_headless": bytes([0x03, 0x00, 0x12, 0x59]),
    "iris640":   bytes([0x00, 0x00, 0x26, 0x59]),
    # Kaby Lake-R laptop
    "uhd620_kblr": bytes([0x00, 0x00, 0xC0, 0x87]),
    # Coffee/Whiskey/Comet Lake laptop
    "uhd620_mb": bytes([0x00, 0x00, 0x9B, 0x3E]),
    # Coffee Lake desktop
    "uhd630_dt": bytes([0x07, 0x00, 0x9B, 0x3E]),
    # Coffee Lake laptop
    "uhd630_mb": bytes([0x09, 0x00, 0xA5, 0x3E]),
    # Connectorless desktop framebuffers (dGPU drives the display)
    "uhd630_cfl_headless": bytes([0x03, 0x00, 0x91, 0x3E]),
    "uhd630_cml_headless": bytes([0x03, 0x00, 0xC8, 0x9B]),
    # Ice Lake
    "iris_ice":  bytes([0x00, 0x00, 0x52, 0x8A]),
}

DEVICE_IDS: dict[str, bytes] = {
    # Fake device-id to match known-good framebuffers
    "snb_display": bytes([0x26, 0x01, 0x00, 0x00]),
    "snb_headless": bytes([0x02, 0x01, 0x00, 0x00]),
    "hsw":       bytes([0x12, 0x04, 0x00, 0x00]),   # spoof HD 42xx/44xx as HD 4600
    "skl_hd510": bytes([0x02, 0x19, 0x00, 0x00]),   # enable unsupported mobile HD 510
    "skl_p530_mobile": bytes([0x16, 0x19, 0x00, 0x00]),
    "skl_p530_desktop": bytes([0x1B, 0x19, 0x00, 0x00]),
    "kbl_hd620": bytes([0x16, 0x59, 0x00, 0x00]),
    "kbl_hd630_mobile": bytes([0x1B, 0x59, 0x00, 0x00]),
    "kbl_hd630_desktop": bytes([0x12, 0x59, 0x00, 0x00]),
    "kbl_r":     bytes([0x16, 0x59, 0x00, 0x00]),   # spoof UHD 620 as 5916
    "cfl_h":     bytes([0x9B, 0x3E, 0x00, 0x00]),   # spoof as 3E9B
}

def _igpu_config(
    profile: HardwareProfile,
    headless: bool = False,
    macos_major: int = 0,
) -> tuple[bytes, bytes | None]:
    """Returns (ig-platform-id, device-id or None)"""
    gen = profile.cpu_generation
    name = profile.gpu_name.lower()
    platform = f"{profile.cpu_codename} {profile.oc_platform}".lower()

    if gen == 2:
        if profile.platform == "laptop":
            return IG_PLATFORM_IDS["snb_mobile"], None
        if headless:
            return IG_PLATFORM_IDS["snb_headless"], DEVICE_IDS["snb_headless"]
        return IG_PLATFORM_IDS["snb_desktop"], DEVICE_IDS["snb_display"]
    elif gen == 3:
        if profile.platform == "laptop":
            return IG_PLATFORM_IDS["ivb_mobile"], None
        if headless:
            return IG_PLATFORM_IDS["ivb_headless"], None
        return IG_PLATFORM_IDS["ivb_desktop"], None
    elif gen == 4:
        if profile.platform == "laptop":
            if "iris" in name or "5000" in name:
                return IG_PLATFORM_IDS["hsw_mobile_iris"], None
            return IG_PLATFORM_IDS["hsw_mobile"], DEVICE_IDS["hsw"]
        platform_id = (
            IG_PLATFORM_IDS["hsw_headless"]
            if headless else
            IG_PLATFORM_IDS["hsw_desktop"]
        )
        if "4200" in name or "4400" in name:
            return platform_id, DEVICE_IDS["hsw"]
        return platform_id, None
    elif gen == 5:
        if profile.platform == "laptop":
            return IG_PLATFORM_IDS["bdw_mobile"], None
        # Broadwell has no documented connectorless framebuffer.
        return IG_PLATFORM_IDS["bdw_desktop"], None
    elif gen == 6:
        if macos_major >= 13:
            if profile.platform == "laptop":
                if "530" in name:
                    return IG_PLATFORM_IDS["hd630_mb"], DEVICE_IDS["kbl_hd630_mobile"]
                return IG_PLATFORM_IDS["hd620"], DEVICE_IDS["kbl_hd620"]
            platform_id = (
                IG_PLATFORM_IDS["hd630_headless"]
                if headless else
                IG_PLATFORM_IDS["hd630_dt"]
            )
            return platform_id, DEVICE_IDS["kbl_hd630_desktop"]
        if profile.platform == "laptop":
            if "p530" in name or "550" in name:
                return IG_PLATFORM_IDS["skl_mobile"], DEVICE_IDS["skl_p530_mobile"]
            if "510" in name:
                return IG_PLATFORM_IDS["skl_mobile_hd510"], DEVICE_IDS["skl_hd510"]
            return IG_PLATFORM_IDS["skl_mobile"], None
        platform_id = (
            IG_PLATFORM_IDS["skl_headless"]
            if headless else
            IG_PLATFORM_IDS["skl_desktop"]
        )
        if "p530" in name:
            return platform_id, DEVICE_IDS["skl_p530_desktop"]
        return platform_id, None
    elif gen == 7:
        if "iris" in name:     return IG_PLATFORM_IDS["iris640"], None
        if "630" in name:
            if headless:
                return IG_PLATFORM_IDS["hd630_headless"], None
            if profile.platform == "laptop":
                return IG_PLATFORM_IDS["hd630_mb"], None
            return IG_PLATFORM_IDS["hd630_dt"], None
        if "615" in name:      return IG_PLATFORM_IDS["hd615"], None
        return IG_PLATFORM_IDS["hd620"], None
    elif gen in (8, 9):
        if headless:
            return IG_PLATFORM_IDS["uhd630_cfl_headless"], None
        if profile.platform == "desktop":
            return IG_PLATFORM_IDS["uhd630_dt"], None
        if "kaby lake-r" in platform:
            return IG_PLATFORM_IDS["uhd620_kblr"], DEVICE_IDS["kbl_r"]
        if "630" in name:
            return IG_PLATFORM_IDS["uhd630_mb"], DEVICE_IDS["cfl_h"]
        return IG_PLATFORM_IDS["uhd620_mb"], DEVICE_IDS["cfl_h"]
    elif gen == 10:
        if "ice lake" in platform:
            return IG_PLATFORM_IDS["iris_ice"], None
        if profile.platform == "desktop":
            if headless:
                return IG_PLATFORM_IDS["uhd630_cml_headless"], None
            return IG_PLATFORM_IDS["uhd630_dt"], None
        if "630" in name:
            return IG_PLATFORM_IDS["uhd630_mb"], DEVICE_IDS["cfl_h"]
        return IG_PLATFORM_IDS["uhd620_mb"], DEVICE_IDS["cfl_h"]
    elif gen >= 11:
        # Apple never shipped a driver for Intel Xe graphics. There is no
        # valid Tiger/Alder/Raptor/Arrow Lake framebuffer to inject.
        return b"", None

    return IG_PLATFORM_IDS["uhd620_mb"], None

LOAD_ORDER = [
    "Lilu", "FakeSMC", "VirtualSMC",
    "WhateverGreen", "NootedRed", "NootRX",
    "AppleALC", "VoodooHDA", "CodecCommander",
    "RestrictEvents", "FeatureUnlock", "CryptexFixup",
    "CPUFriend", "IntelMKLFixup",
    "AMDRyzenCPUPowerManagement", "SMCAMDProcessor",
    "SMCBatteryManager", "SMCProcessor", "SMCSuperIO", "SMCLightSensor",
    "SMCDellSensors", "SMCRadeonGPU",
    "FakeSMC_ACPISensors","FakeSMC_CPUSensors","FakeSMC_GPUSensors",
    "FakeSMC_LPCSensors","FakeSMC_SMMSensors",
    "FakePCIID",
    "FakePCIID_XHCIMux","FakePCIID_Broadcom_WiFi",
    "FakePCIID_Intel_HDMI_Audio","FakePCIID_Intel_HD_Graphics",
    "FakePCIID_BCM57XX_as_BCM57765",
    "ECEnabler", "ACPIBatteryManager",
    "NullCPUPowerManagement", "CpuTopologyRebuild",
    "AmdTSCSync", "ForgedInvariant", "VoodooTSCSync",
    "HibernationFixup", "NVMeFix", "RTCMemoryFixup",
    "IntelMausiEthernet", "AppleIGC", "AppleIntelE1000e", "AppleIntelI210Ethernet", "AppleIGB",
    "RealtekRTL8111", "RealtekRTL8100", "RealtekR1000", "LucyRTL8125Ethernet",
    "AtherosE2200Ethernet", "AtherosL1Ethernet", "AtherosL1eEthernet", "BCM5722D",
    "NullEthernet",
    "itlwm", "AirportItlwm", "AirportBrcmFixup", "ATH9KFixup",
    "IntelBluetoothFirmware", "IntelBTPatcher", "IntelBluetoothInjector",
    "BrcmFirmwareData", "BrcmFirmwareRepo",
    "BrcmPatchRAM", "BrcmPatchRAM2", "BrcmPatchRAM3", "BrcmBluetoothInjector",
    "BlueToolFixup",
    "RadeonSensor",
    "VoodooInput",
    "VoodooPS2Controller","VoodooPS2Keyboard","VoodooPS2Mouse","VoodooPS2Trackpad",
    "VoodooGPIO", "VoodooI2C",
    "VoodooI2CHID","VoodooI2CSynaptics","VoodooI2CELAN",
    "VoodooI2CAtmel","VoodooI2CFTE","VoodooI2CGoodix","AlpsHID",
    "VoodooSMBus", "VoodooRMI",
    "YogaSMC", "AsusSMC",
    "BrightnessKeys", "NoTouchID",
    "USBToolBox", "UTBMap", "USBInjectAll", "XHCI-unsupported", "GenericUSBXHCI",
    "RealtekCardReader", "RealtekCardReaderFriend", "Sinetek-rtsx",
    "JMicronATA", "AHCIPortInjector", "Innie",
    "DebugEnhancer",
]

# Kexts that have no executable (plist-only)
NO_EXECUTABLE = {
    "FakePCIID_XHCIMux", "FakePCIID_Broadcom_WiFi",
    "FakePCIID_Intel_HDMI_Audio", "FakePCIID_Intel_HD_Graphics",
    "FakePCIID_BCM57XX_as_BCM57765",
    "FakeSMC_ACPISensors", "FakeSMC_CPUSensors", "FakeSMC_GPUSensors",
    "FakeSMC_LPCSensors", "FakeSMC_SMMSensors",
    "NullEthernet",
    "VoodooGPIO",
    "UTBMap", "UTBDefault",
}

KERNEL_VERSIONS: dict[str, tuple[str, str]] = {
    "BrcmPatchRAM":        ("", "14.9.9"),     # macOS 10.10 and below
    "BrcmPatchRAM2":       ("15.0.0", "18.9.9"),  # macOS 10.11-10.14
    "BrcmPatchRAM3":       ("19.0.0", ""),     # macOS 10.15+
    "BrcmBluetoothInjector":("", "20.9.9"),   # macOS 11 and below (BlueToolFixup takes over on 12+)
    "BlueToolFixup":       ("21.0.0", ""),     # macOS 12+
    "IntelBTPatcher":      ("20.0.0", ""),     # macOS 11+
    "IntelBluetoothInjector":("", "20.9.9"),  # macOS 11 and below
    "AirportItlwm":        ("19.0.0", ""),     # macOS 10.15+
    "XHCI-unsupported":    ("", "19.9.9"),     # macOS 10.15 and below
    "CryptexFixup":        ("22.0.0", ""),     # macOS 13+
}

def _sort_kexts(kexts: list[KextEntry]) -> list[KextEntry]:
    order = {name: i for i, name in enumerate(LOAD_ORDER)}
    return sorted(kexts, key=lambda k: order.get(k.name, 999))

def _kext_entry(kext: KextEntry, enabled: bool = True) -> dict:
    has_exe = kext.name not in NO_EXECUTABLE
    min_k, max_k = KERNEL_VERSIONS.get(kext.name, ("", ""))
    return {
        "Arch":           "x86_64",
        "BundlePath":     f"{kext.name}.kext",
        "Comment":        kext.note,
        "Enabled":        enabled,
        "ExecutablePath": f"Contents/MacOS/{kext.exe_name or kext.name}" if has_exe else "",
        "MaxKernel":      max_k,
        "MinKernel":      min_k,
        "PlistPath":      "Contents/Info.plist",
    }

def _required_ssdts(profile: HardwareProfile, kexts: list[KextEntry]) -> list[str]:
    ssdts = []
    gen = profile.cpu_generation
    kext_names = {k.name for k in kexts}
    has_i2c = any(k.name.startswith("VoodooI2C") for k in kexts)

    # CPU power management — always
    ssdts.append("SSDT-PLUG")

    ssdts.append("SSDT-GPRW")

    if gen in (2, 3):
        ssdts.append("SSDT-IMEI")

    if profile.platform == "laptop":
        ssdts.append("SSDT-EC-USBX")
    else:
        ssdts.append("SSDT-EC")
        if gen >= 6:
            ssdts.append("SSDT-USBX")

    # Backlight (laptop only)
    if profile.platform == "laptop":
        ssdts.append("SSDT-PNLF")

    # AWAC clock fix — Z390/B460+ desktops (gen 9+); laptops never have AWAC
    if gen >= 9 and profile.platform == "desktop" and profile.cpu_vendor == "intel":
        ssdts.append("SSDT-AWAC")

    # PMC fix — Coffee Lake (gen 8) desktop
    if gen >= 8 and profile.platform == "desktop" and profile.cpu_vendor == "intel":
        ssdts.append("SSDT-PMC")

    # I2C GPIO — needed for I2C trackpad
    if has_i2c:
        ssdts.append("SSDT-GPI0")
        ssdts.append("SSDT-XOSI")

    return ssdts

PATCH_REQUIRES_SSDT: dict[str, str] = {
    "OSID to XSID":  "SSDT-XOSI",
    "_OSI to XOSI":  "SSDT-XOSI",
    "GPRW to XGPR":  "SSDT-GPRW",
}

def _acpi_add(ssdts: list[str]) -> list[dict]:
    return [
        {
            "Comment":  ssdt,
            "Enabled":  True,
            "Path":     f"{ssdt}.aml",
        }
        for ssdt in ssdts
    ]

def _acpi_patches(profile: HardwareProfile, ssdts: list[str]) -> list[dict]:
    """
    Build the ACPI rename list. Every rename here redirects a firmware symbol at
    a replacement supplied by an SSDT, so a rename is only emitted when the SSDT
    providing that replacement is in `ssdts`.
    """
    patches = []
    loaded = set(ssdts)

    def patch(comment, find, replace, count=0, table=""):
        return {
            "Base":             "",
            "BaseSkip":         0,
            "Comment":          comment,
            "Count":            count,
            "Enabled":          True,
            "Find":             bytes.fromhex(find),
            "Limit":            0,
            "Mask":             b"",
            "OemTableId":       b"",
            "Replace":          bytes.fromhex(replace),
            "ReplaceMask":      b"",
            "Skip":             0,
            "TableLength":      0,
            "TableSignature":   table.encode() if table else b"",
        }

    def add(comment, find, replace, **kw):
        required = PATCH_REQUIRES_SSDT.get(comment)
        if required and required not in loaded:
            return
        patches.append(patch(comment, find, replace, **kw))

    add("OSID to XSID", "4F534944", "58534944")
    add("_OSI to XOSI", "5F4F5349", "584F5349")

    add("GPRW to XGPR", "47505257", "58475052")

    return patches

def _device_properties(
    profile: HardwareProfile,
    layout_id: int,
    audio_enabled: bool = True,
    macos_major: int = 0,
) -> dict:
    props: dict[str, dict] = {}

    # Intel iGPU
    if (
        profile.gpu_vendor == "intel"
        and profile.cpu_generation <= 10
        and "arc" not in profile.gpu_name.lower()
    ):
        # Laptop internal panels are wired to the iGPU even when a discrete GPU
        # is present. Use a connectorless framebuffer only when a supported AMD
        # desktop dGPU is expected to drive the display. Unsupported dGPUs are
        # disabled later only when the user explicitly chooses that option.
        headless = profile.platform == "desktop" and profile.dgpu_vendor == "amd"
        platform_id, device_id = _igpu_config(
            profile,
            headless=headless,
            macos_major=macos_major,
        )
        igpu_props: dict = {
            "AAPL,ig-platform-id": platform_id,
        }
        # Sandy Bridge uses different key
        if profile.cpu_generation == 2:
            igpu_props = {"AAPL,snb-platform-id": platform_id}

        if device_id:
            igpu_props["device-id"] = device_id

        if profile.cpu_generation == 6 and macos_major >= 13:
            # WhateverGreen recommends this alongside the Kaby Lake spoof to
            # avoid Skylake display corruption on Ventura and newer.
            igpu_props["AAPL,GfxYTile"] = bytes([0x01, 0x00, 0x00, 0x00])

        if profile.platform == "laptop" and profile.cpu_generation == 4:
            # Haswell laptop framebuffers need the documented 9 MB cursor patch.
            igpu_props["framebuffer-patch-enable"] = bytes([0x01, 0x00, 0x00, 0x00])
            igpu_props["framebuffer-cursormem"] = bytes([0x00, 0x00, 0x90, 0x00])
        elif profile.platform == "laptop" and profile.cpu_generation >= 5:
            # Safe fallback for firmware locked to 32 MB DVMT pre-allocation.
            igpu_props["framebuffer-patch-enable"] = bytes([0x01, 0x00, 0x00, 0x00])
            igpu_props["framebuffer-stolenmem"]    = bytes([0x00, 0x00, 0x30, 0x01])
            igpu_props["framebuffer-fbmem"]        = bytes([0x00, 0x00, 0x90, 0x00])

        props["PciRoot(0x0)/Pci(0x2,0x0)"] = igpu_props

    if audio_enabled:
        layout_bytes = layout_id.to_bytes(4, "little")
        if profile.audio_pci_device >= 0 and profile.audio_pci_function >= 0:
            audio_path = (
                f"PciRoot(0x0)/Pci(0x{profile.audio_pci_device:x},"
                f"0x{profile.audio_pci_function:x})"
            )
        else:
            audio_path = "PciRoot(0x0)/Pci(0x1f,0x3)"
        props[audio_path] = {
            "layout-id": layout_bytes,
        }

    # Intel I225/I226 ethernet fix (needs device-id spoof)
    if profile.ethernet_chipset in ("i225", "i226"):
        if profile.ethernet_pci_device >= 0 and profile.ethernet_pci_function >= 0:
            i225_path = (
                f"PciRoot(0x0)/Pci(0x{profile.ethernet_pci_device:x},"
                f"0x{profile.ethernet_pci_function:x})"
            )
        else:
            i225_path = "PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)"
        props[i225_path] = {
            "device-id":     bytes([0xF2, 0x15, 0x00, 0x00]),
            "PCI-Subchannel": bytes([0x00]),
            "built-in":      bytes([0x01]),
        }

    if profile.ethernet_chipset and profile.ethernet_chipset not in ("none",):
        if profile.ethernet_pci_device >= 0 and profile.ethernet_pci_function >= 0:
            eth_path = (
                f"PciRoot(0x0)/Pci(0x{profile.ethernet_pci_device:x},"
                f"0x{profile.ethernet_pci_function:x})"
            )
        elif profile.ethernet_chipset in ("i219", "i218", "i217"):
            eth_path = "PciRoot(0x0)/Pci(0x1F,0x6)"
        elif profile.ethernet_chipset in ("rtl8111", "rtl8168", "rtl8125"):
            eth_path = "PciRoot(0x0)/Pci(0x1C,0x0)/Pci(0x0,0x0)"
        else:
            eth_path = None
        if eth_path:
            if eth_path not in props:
                props[eth_path] = {}
            props[eth_path]["built-in"] = bytes([0x01])

    if profile.nvme_present:
        if profile.nvme_pci_device >= 0 and profile.nvme_pci_function >= 0:
            nvme_path = (
                f"PciRoot(0x0)/Pci(0x{profile.nvme_pci_device:x},"
                f"0x{profile.nvme_pci_function:x})"
            )
        else:
            nvme_path = "PciRoot(0x0)/Pci(0x1D,0x0)"
        if nvme_path not in props:
            props[nvme_path] = {}
        props[nvme_path]["built-in"] = bytes([0x01])

    return {"Add": props, "Delete": {}}

def _cpu_needs_spoof(profile: HardwareProfile) -> tuple[bytes, bytes] | None:
    name = profile.cpu_name.lower()
    if profile.cpu_vendor == "intel" and profile.cpu_generation >= 11:
        # OpenCore's documented Rocket Lake and newer recommendation: expose
        # the Comet Lake 0x0A0655 CPUID so XCPM can initialize.
        return (
            bytes.fromhex("55060A00" + "00000000" * 3),
            bytes.fromhex("FFFFFFFF" + "00000000" * 3),
        )
    if "pentium" in name or "celeron" in name:
        return (
            bytes.fromhex("EA060900" + "00000000" * 3),
            bytes.fromhex("FFFFFFFF" + "00000000" * 3),
        )
    if "xeon" in name:
        return (
            bytes.fromhex("EB060900" + "00000000" * 3),
            bytes.fromhex("FFFFFFFF" + "00000000" * 3),
        )
    return None

def _kernel_section(profile: HardwareProfile, kexts: list[KextEntry]) -> dict:
    sorted_kexts = _sort_kexts(kexts)

    # Quirks
    quirks = {
        "AppleCpuPmCfgLock":          True,   # assume CFG Lock can't be disabled
        "AppleXcpmCfgLock":           True,
        "AppleXcpmExtraMsrs":         _cpu_needs_spoof(profile) is not None,
        "AppleXcpmForceBoost":        False,
        "CustomPciSerialDevice":      False,
        "CustomSMBIOSGuid":           False,
        "DisableIoMapper":            True,    # disable VT-d (enable in BIOS after install)
        "DisableIoMapperMapping":     False,
        "DisableLinkeditJettison":    True,
        "DisableRtcChecksum":         False,
        "ExtendBTFeatureFlags":       True,    # for BT fixes
        "ExternalDiskIcons":          False,
        "ForceAquantiaEthernet":      False,
        "ForceSecureBootScheme":      False,
        "IncreasePciBarSize":         False,
        "LapicKernelPanic":           False,   # HP laptops need True
        "LegacyCommpage":             False,
        "PanicNoKextDump":            True,
        "PowerTimeoutKernelPanic":    True,
        "ProvideCurrentCpuInfo":      True,
        "SetApfsTrimTimeout":         -1,
        "ThirdPartyDrives":           False,
        "XhciPortLimit":              False,
    }

    if "hp" in dmi_vendor():
        quirks["LapicKernelPanic"] = True

    # AMD: disable Intel-only quirks
    if profile.cpu_vendor == "amd":
        quirks["AppleCpuPmCfgLock"]  = False
        quirks["AppleXcpmCfgLock"]   = False
        # Required by the universal AMD Vanilla patch set.
        quirks["ProvideCurrentCpuInfo"] = True

    # AMD needs extra kernel patches
    patches = []
    if profile.cpu_vendor == "amd":
        patches = _amd_kernel_patches(profile)

    emulate: dict = {
        "Cpuid1Data":  b"",
        "Cpuid1Mask":  b"",
        "DummyPowerManagement": False,
        "MaxKernel":   "",
        "MinKernel":   "",
    }
    if profile.cpu_generation <= 3:
        emulate["DummyPowerManagement"] = True
    spoof = _cpu_needs_spoof(profile)
    if spoof:
        emulate["Cpuid1Data"] = spoof[0]
        emulate["Cpuid1Mask"] = spoof[1]

    return {
        "Add":     [_kext_entry(k, enabled=(k.name != "UTBMap")) for k in sorted_kexts],
        "Block":   [],
        "Emulate": emulate,
        "Force":   [],
        "Patch":   patches,
        "Quirks":  quirks,
        "Scheme": {
            "CustomKernel": False,
            "FuzzyMatch":   True,
            "KernelArch":   "x86_64",
            "KernelCache":  "Auto",
        },
    }

def _amd_vanilla_raw() -> bytes:
    if _AMD_VANILLA_CACHE.exists():
        age = time.time() - _AMD_VANILLA_CACHE.stat().st_mtime
        if age < _AMD_VANILLA_TTL:
            return _AMD_VANILLA_CACHE.read_bytes()

    try:
        data = http_get(AMD_VANILLA_URL, timeout=30)
        plistlib.loads(data)
    except Exception:
        if _AMD_VANILLA_CACHE.exists():
            return _AMD_VANILLA_CACHE.read_bytes()
        return Path(__file__).with_name("amd_patches.plist").read_bytes()

    try:
        _AMD_VANILLA_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _AMD_VANILLA_CACHE.write_bytes(data)
    except Exception:
        pass
    return data


def _amd_kernel_patches(profile: HardwareProfile) -> list[dict]:
    patches = plistlib.loads(_amd_vanilla_raw())["Kernel"]["Patch"]

    cores = profile.core_count or cpu_core_count()
    if not 1 <= cores <= 255:
        raise ValueError(f"Invalid AMD physical core count: {cores}")

    # AMD Vanilla ships four version-specific core-count patches. Byte 1 of
    # each Replace value is the user-supplied physical core count.
    for patch in patches:
        if "Force cpuid_cores_per_package" not in patch.get("Comment", ""):
            continue
        replacement = bytearray(patch["Replace"])
        replacement[1] = cores
        patch["Replace"] = bytes(replacement)

    return patches

def _nvram_section(
    profile: HardwareProfile,
    layout_id: int,
    macos_major: int = 0,
    audio_enabled: bool = True,
) -> dict:
    boot_args = [
        "-v",                  # verbose on first boot (remove after working)
        "debug=0x100",         # don't panic on kernel error
        "keepsyms=1",          # keep symbols for debug
        "-no_compat_check",    # bypass board ID check in boot.efi
    ]
    if audio_enabled:
        boot_args.append(f"alcid={layout_id}")

    if macos_major >= 15 and not has_macos_supported_gpu(profile):
        # Sequoia+: RestrictEvents VMM spoof so macOS doesn't see unsupported Intel hardware.
        # Only needed when there's no natively-accelerated GPU to fall back on — on real
        # supported iGPUs/dGPUs this fights WhateverGreen's actual acceleration patches
        # and panics at ExitBootServices.
        boot_args.append("revpatch=sbvmm")
        boot_args.append("-lilubetaall")

    if profile.cpu_vendor == "amd":
        boot_args.append("npci=0x2000")   # AMD PCI fix

    if profile.gpu_vendor == "nvidia" or profile.dgpu_vendor == "nvidia":
        boot_args.append("nv_disable=1")  # disable NVIDIA (unsupported on modern macOS)

    if profile.platform == "laptop" and profile.gpu_vendor == "intel":
        boot_args.append("agdpmod=vit9696")  # iGPU display patch (WhateverGreen)
        boot_args.append("darkwake=0")        # prevent random sleep wakes

    return {
        "Add": {
            "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14": {
                "DefaultBackgroundColor": bytes([0x00, 0x00, 0x00, 0x00]),
                "UIScale":                bytes([0x01]),   # 0x02 for HiDPI
            },
            "7C436110-AB2A-4BBB-A880-FE41995C9F82": {
                "boot-args":          " ".join(boot_args),
                "csr-active-config":  bytes([0x00, 0x00, 0x00, 0x00]),  # SIP enabled
                "prev-lang:kbd":      "en-US:0".encode(),
                "run-efi-updater":    "No",
            },
        },
        "Delete": {
            "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14": [],
            "7C436110-AB2A-4BBB-A880-FE41995C9F82": ["boot-args"],
        },
        "LegacyOverwrite": False,
        "LegacySchema":    {},
        "WriteFlash":       True,
    }

def _platform_info(smbios: SMBIOSData) -> dict:
    return {
        "Automatic":          True,
        "CustomMemory":       False,
        "Generic": {
            "AdviseFeatures":     False,
            "MLB":                smbios.board_serial,
            "MaxBIOSVersion":     False,
            "ProcessorType":      0,
            "ROM":                bytes.fromhex(smbios.rom),
            "SpoofVendor":        True,
            "SystemMemoryStatus": "Auto",
            "SystemProductName":  smbios.model,
            "SystemSerialNumber": smbios.serial,
            "SystemUUID":         smbios.system_uuid,
        },
        "UpdateDataHub":   True,
        "UpdateNVRAM":     True,
        "UpdateSMBIOS":    True,
        "UpdateSMBIOSMode":"Create",
        "UseRawUuidEncoding": False,
    }

def _uefi_section(profile: HardwareProfile, dual_boot: str = "") -> dict:
    drivers = [
        {"Arguments": "", "Comment": "Runtime services",    "Enabled": True, "LoadEarly": False, "Path": "OpenRuntime.efi"},
        {"Arguments": "", "Comment": "HFS+ filesystem",     "Enabled": True, "LoadEarly": False, "Path": "HfsPlus.efi"},
        {"Arguments": "", "Comment": "NVRAM reset entry",   "Enabled": True, "LoadEarly": False, "Path": "ResetNvramEntry.efi"},
    ]
    if dual_boot in ("linux", "both"):
        drivers.append({"Arguments": "", "Comment": "Linux EFI scanning", "Enabled": True, "LoadEarly": False, "Path": "OpenLinuxBoot.efi"})

    return {
        "APFS": {
            "EnableJumpstart":   True,
            "GlobalConnect":     False,
            "HideVerbose":       True,
            "JumpstartHotPlug":  False,
            "MinDate":           0,     # 0 = any date (allow older macOS)
            "MinVersion":        0,
        },
        "Audio": {
            "AudioCodec":         0,
            "AudioDevice":        "",
            "AudioOutMask":       -1,
            "AudioSupport":       False,
            "DisconnectHda":      False,
            "MaximumGain":        -15,
            "MinimumAssistGain":  -30,
            "MinimumAudibleGain": -55,
            "PlayChime":          "Disabled",
            "ResetTrafficClass":  False,
            "SetupDelay":         0,
        },
        "AppleInput": {
            "AppleEvent":                    "Builtin",
            "CustomDelays":                  False,
            "GraphicsInputMirroring":        True,
            "KeyInitialDelay":               50,
            "KeySubsequentDelay":            5,
            "PointerDwellClickTimeout":       0,
            "PointerDwellDoubleClickTimeout": 0,
            "PointerDwellRadius":             0,
            "PointerPollMask":               -1,
            "PointerPollMax":                80,
            "PointerPollMin":                10,
            "PointerSpeedDiv":               1,
            "PointerSpeedMul":               1,
        },
        "ConnectDrivers": True,
        "Drivers":        drivers,
        "Input": {
            "KeyFiltering":   False,
            "KeyForgetThreshold": 5,
            "KeySupport":     True,
            "KeySupportMode": "Auto",
            "KeySwap":        False,
            "PointerSupport": False,
            "PointerSupportMode": "ASUS",
            "TimerResolution": 50000,
        },
        "Output": {
            "ClearScreenOnModeSwitch": False,
            "ConsoleFont":   "",
            "ConsoleMode":   "",
            "DirectGopRendering": False,
            "ForceResolution": False,
            "GopBurstMode":  False,
            "GopPassThrough": (
                "Disabled" if has_macos_supported_gpu(profile) else "Enabled"
            ),
            "IgnoreTextInGraphics": False,
            "InitialMode":   "Text",
            "ProvideConsoleGop": True,
            "ReconnectGraphicsOnConnect": False,
            "ReconnectOnResChange": False,
            "ReplaceTabWithSpace": False,
            "Resolution":    "Max",
            "SanitiseClearScreen": False,
            "TextRenderer":  "BuiltinGraphics",
            "UIScale":       -1,
            "UgaPassThrough": False,
        },
        "ProtocolOverrides": {
            "AppleAudio":        False,
            "AppleBootPolicy":   False,
            "AppleDebugLog":     False,
            "AppleEg2Info":      False,
            "AppleFramebufferInfo": False,
            "AppleImageConversion": False,
            "AppleImg4Verification": False,
            "AppleKeyMap":       False,
            "AppleRtcRam":       False,
            "AppleSecureBoot":   False,
            "AppleSmcIo":        False,
            "AppleUserInterfaceTheme": False,
            "DataHub":           False,
            "DeviceProperties":  False,
            "FirmwareVolume":    False,
            "HashServices":      False,
            "OSInfo":            False,
            "PciIo":             False,
            "UnicodeCollation":  False,
        },
        "Quirks": {
            "ActivateHpetSupport":          False,
            "DisableSecurityPolicy":        True,
            "EnableVectorAcceleration":     profile.platform == "desktop",
            "EnableVmx":                    False,
            "ExitBootServicesDelay":        0,
            "ForceOcWriteFlash":            True,
            "ForgeUefiSupport":             False,
            "IgnoreInvalidFlexRatio":       "lenovo" in dmi_vendor(),
            "ReleaseUsbOwnership":          True,
            "ReloadOptionRoms":             False,
            "RequestBootVarRouting":        True,
            "ResizeGpuBars":                -1,
            "ResizeUsePciRbIo":             False,
            "ShimRetainProtocol":           False,
            "TscSyncTimeout":               0,
            "UnblockFsConnect":             any(v in dmi_vendor() for v in ("lenovo", "dell", "hp")),
        },
        "ReservedMemory": [],
        "Unload":         [],
    }

def _booter_section(profile: HardwareProfile, resizable_bar: bool = False) -> dict:
    platform = f"{profile.cpu_codename} {profile.oc_platform}".lower()
    board = dmi_field("board_name").lower()
    intel = profile.cpu_vendor.lower() == "intel"
    amd = profile.cpu_vendor.lower() == "amd"

    # Coffee Lake+ and Ryzen use the MAT-aware combination recommended by the
    # OpenCore guide. Firmware-specific exceptions can still be diagnosed from
    # the authoritative "OCABC: MAT support is 0/1" debug-log line.
    modern_memory_map = amd or (intel and profile.cpu_generation >= 8)

    ice_lake = "ice lake" in platform
    comet_lake = "comet lake" in platform
    modern_amd_board = any(chipset in board for chipset in ("x570", "b550", "a520", "trx40"))
    setup_virtual_map = not (
        (intel and (ice_lake or comet_lake or profile.cpu_generation >= 11))
        or modern_amd_board
    )

    z390_or_z490 = any(chipset in board for chipset in ("z390", "z490"))
    hedt = profile.cpu_family.lower() == "hedt"
    devirtualise_mmio = ice_lake or (comet_lake and profile.platform == "desktop")
    devirtualise_mmio = devirtualise_mmio or z390_or_z490 or hedt or "trx40" in board
    protect_uefi_services = ice_lake or (comet_lake and profile.platform == "desktop")
    protect_uefi_services = protect_uefi_services or z390_or_z490

    return {
        "MmioWhitelist": [],
        "Patch":         [],
        "Quirks": {
            "AllowRelocationBlock":     False,
            "AvoidRuntimeDefrag":       True,
            "ClearTaskSwitchBit":       False,
            "DevirtualiseMmio":         devirtualise_mmio,
            "DisableSingleUser":        False,
            "DisableVariableWrite":     False,
            "DiscardHibernateMap":      False,
            "EnableSafeModeSlide":      True,
            "EnableWriteUnprotector":   not modern_memory_map,
            "FixupAppleEfiImages":      True,
            "ForceBooterSignature":     False,
            "ForceExitBootServices":    False,
            "ProtectMemoryRegions":     False,
            "ProtectSecureBoot":        False,
            "ProtectUefiServices":      protect_uefi_services,
            "ProvideCustomSlide":       True,
            "ProvideMaxSlide":          0,
            "RebuildAppleMemoryMap":    modern_memory_map,
            "ResizeAppleGpuBars":       0 if resizable_bar else -1,
            "SetupVirtualMap":          setup_virtual_map,
            "SignalAppleOS":            True,
            "SyncRuntimePermissions":   modern_memory_map,
        },
    }

def generate(profile: HardwareProfile, smbios: SMBIOSData, macos_major: int = 0, wifi_kext_mode: str = "itlwm", dual_boot: str = "", hackmate_core: bool = False) -> dict:
    kexts = select_kexts(profile, wifi_kext_mode=wifi_kext_mode)
    layout_id = get_alc_layout(profile.audio_codec)
    audio_enabled = any(kext.name == "AppleALC" for kext in kexts)
    ssdts = _required_ssdts(profile, kexts)

    config = {
        "ACPI": {
            "Add":    _acpi_add(ssdts),
            "Delete": [],
            "Patch":  _acpi_patches(profile, ssdts),
            "Quirks": {
                "FadtEnableReset":      False,
                "NormalizeHeaders":     False,
                "RebaseRegions":        False,
                "ResetHwSig":           False,
                "ResetLogoStatus":      True,
                "SyncTableIds":         False,
            },
        },
        "Booter":           _booter_section(profile, resizable_bar=profile.resizable_bar),
        "DeviceProperties": _device_properties(
            profile,
            layout_id,
            audio_enabled,
            macos_major,
        ),
        "Kernel":           _kernel_section(profile, kexts),
        "Misc": {
            "BlessOverride": [],
            "Boot": {
                "ConsoleAttributes":  0,
                "HibernateMode":      "None",
                "HibernateSkipsPicker": False,
                "HideAuxiliary":      False,
                "InstanceIdentifier": "",
                "LauncherOption":     "Full" if dual_boot else "Disabled",
                "LauncherPath":       "Default",
                "PickerAttributes":   1,
                "PickerAudioAssist":  False,
                "PickerMode":         "Builtin",
                "PickerVariant":      "Auto",
                "PollAppleHotKeys":   True,
                "ShowPicker":         True,
                "TakeoffDelay":       0,
                "Timeout":            5,
            },
            "Debug": {
                "AppleDebug":         False,
                "ApplePanic":         False,
                "DisableWatchDog":    True,
                "DisplayDelay":       0,
                "DisplayLevel":       2147483650,
                "LogModules":         "*",
                "SysReport":          False,
                "Target":             71,
            },
            "Entries":  [],
            "Security": {
                "AllowSetDefault":        True,
                "ApECID":                 0,
                "AuthRestart":            False,
                "BlacklistAppleUpdate":   True,
                "DmgLoading":             "Any",
                "EnablePassword":         False,
                "ExposeSensitiveData":    6,
                "HaltLevel":              2147483648,
                "PasswordHash":           b"",
                "PasswordSalt":           b"",
                "ScanPolicy":             0,
                "SecureBootModel":        "Disabled",
                "Vault":                  "Optional",
            },
            "Serial":   {"Init": False, "Override": False},
            "Tools":    [],
        },
        "NVRAM":            _nvram_section(profile, layout_id, macos_major, audio_enabled),
        "PlatformInfo":     _platform_info(smbios),
        "UEFI":             _uefi_section(profile, dual_boot=dual_boot),
    }

    if hackmate_core:
        import hackmate_core as _hc

        if _hc.available():
            style = hackmate_core if isinstance(hackmate_core, str) else "full"
            _hc.apply_to_config(config, style=style)

    return config

def sync_executable_paths(config: dict, kext_dir: Path) -> list[str]:
    """
    Rewrite every kext's ExecutablePath from the bundle that was actually
    downloaded, reading CFBundleExecutable out of its Info.plist.

    The name of a kext's binary is not reliably its bundle name (itlwm.kext ships
    `itlwm`, IntelMausi.kext ships `IntelMausi`) and plist-only bundles such as
    USB port maps have no binary at all. An ExecutablePath that points at a file
    which is not there makes OpenCore refuse to inject the kext, so the bundle on
    disk is the only trustworthy source. Returns the BundlePaths that changed.
    """
    fixed: list[str] = []

    for entry in config.get("Kernel", {}).get("Add", []):
        bundle_path = entry.get("BundlePath", "")
        if not bundle_path:
            continue

        kext = kext_dir / bundle_path
        info = kext / "Contents" / "Info.plist"
        if not info.exists():
            continue

        try:
            plist = plistlib.loads(info.read_bytes())
        except Exception:
            continue

        exe = plist.get("CFBundleExecutable", "")
        want = f"Contents/MacOS/{exe}" if exe else ""
        if want and not (kext / want).exists():
            want = ""

        if entry.get("ExecutablePath", "") != want:
            entry["ExecutablePath"] = want
            fixed.append(bundle_path)

    return fixed

def strip_missing_ssdts(config: dict, missing: list[str]) -> tuple[int, int]:
    """
    Drop ACPI/Add entries for SSDTs that could not be generated, along with any
    rename that depended on them.

    A rename left behind after its SSDT is dropped points firmware symbols at a
    replacement that no longer exists, which is worse than applying no patch at
    all. Returns (tables_removed, patches_removed).
    """
    gone = set(missing)
    if not gone:
        return 0, 0

    acpi = config.setdefault("ACPI", {})

    tables = acpi.get("Add", [])
    bad_paths = {f"{name}.aml" for name in gone}
    kept_tables = [e for e in tables if e.get("Path", "") not in bad_paths]
    acpi["Add"] = kept_tables

    patches = acpi.get("Patch", [])
    kept_patches = [
        p for p in patches
        if PATCH_REQUIRES_SSDT.get(p.get("Comment", "")) not in gone
    ]
    acpi["Patch"] = kept_patches

    return len(tables) - len(kept_tables), len(patches) - len(kept_patches)

def write_plist(config: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(config, f, fmt=plistlib.FMT_XML, sort_keys=False)

if __name__ == "__main__":
    from hardware import scan
    from smbios import generate as gen_smbios

    profile = scan()
    smbios = gen_smbios(profile)
    config = generate(profile, smbios)

    out = Path("/tmp/config.plist")
    write_plist(config, out)

    kexts = select_kexts(profile)
    layout_id = get_alc_layout(profile.audio_codec)
    ssdts = _required_ssdts(profile, kexts)
    igpu_id, dev_id = _igpu_config(profile)

    print(f"\n{'─'*60}")
    print(f"  HackMate config.plist Generator")
    print(f"{'─'*60}")
    print(f"  SMBIOS:      {smbios.model}")
    print(f"  Serial:      {smbios.serial}")
    print(f"  MLB:         {smbios.board_serial}")
    print(f"  iGPU ID:     {igpu_id.hex()}")
    print(f"  Audio:       layout-id {layout_id} ({profile.audio_codec})")
    print(f"  SSDTs:       {', '.join(ssdts)}")
    print(f"  Kexts:       {len(kexts)}")
    print(f"  Boot args:   {config['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82']['boot-args']}")
    print(f"{'─'*60}")
    print(f"\n  Written to: {out}")
    print(f"  Size: {out.stat().st_size} bytes")
    print()
