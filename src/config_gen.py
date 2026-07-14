import plistlib
from pathlib import Path
from hardware import HardwareProfile
from kexts import KextEntry, select_kexts, get_alc_layout
from smbios import SMBIOSData
from compat import IS_WINDOWS, dmi_vendor, cpu_core_count

IG_PLATFORM_IDS: dict[str, bytes] = {
    # Sandy Bridge
    "hd3000":    bytes([0x00, 0x00, 0x01, 0x00]),   # AAPL,snb-platform-id
    # Ivy Bridge
    "hd4000":    bytes([0x04, 0x00, 0x66, 0x01]),
    "hd2500":    bytes([0x03, 0x00, 0x66, 0x01]),
    # Haswell
    "hd4400":    bytes([0x00, 0x00, 0x16, 0x0A]),
    "hd4600":    bytes([0x04, 0x00, 0x12, 0x04]),
    "hd5000":    bytes([0x05, 0x00, 0x26, 0x0A]),
    "iris5100":  bytes([0x05, 0x00, 0x26, 0x0A]),
    # Broadwell
    "hd5500":    bytes([0x00, 0x00, 0x16, 0x16]),
    "hd6000":    bytes([0x00, 0x00, 0x26, 0x16]),
    "iris6100":  bytes([0x00, 0x00, 0x26, 0x16]),
    # Skylake
    "hd515":     bytes([0x00, 0x00, 0x1E, 0x19]),
    "hd520":     bytes([0x00, 0x00, 0x16, 0x19]),
    "hd530":     bytes([0x00, 0x00, 0x12, 0x19]),
    "iris540":   bytes([0x00, 0x00, 0x26, 0x19]),
    # Kaby Lake
    "hd615":     bytes([0x00, 0x00, 0x1B, 0x59]),
    "hd620":     bytes([0x00, 0x00, 0x16, 0x59]),
    "hd630":     bytes([0x03, 0x00, 0x12, 0x59]),
    "iris640":   bytes([0x00, 0x00, 0x26, 0x59]),
    # Kaby Lake-R / Coffee Lake laptop (Dortania recommended: 0x3EA50004)
    "uhd620":    bytes([0x04, 0x00, 0xA5, 0x3E]),
    # Coffee Lake desktop
    "uhd630_dt": bytes([0x07, 0x00, 0x9B, 0x3E]),
    # Coffee Lake laptop
    "uhd630_mb": bytes([0x06, 0x00, 0x9B, 0x3E]),
    # Comet Lake laptop
    "uhd620_cml":bytes([0x00, 0x00, 0x3E, 0x9B]),
    # Comet Lake desktop
    "uhd630_cml":bytes([0x03, 0x00, 0x92, 0x3E]),
    # Ice Lake
    "iris_ice":  bytes([0x00, 0x00, 0x52, 0x8A]),
    # Tiger Lake
    "iris_tgl":  bytes([0x00, 0x00, 0x49, 0x9A]),
    # Alder Lake (no iGPU support in macOS natively, needs NootedBlue or patch)
    "uhd770":    bytes([0x00, 0x00, 0xA6, 0x46]),
    # Headless variants (when dGPU drives display)
    "uhd620_headless":    bytes([0x03, 0x00, 0x9B, 0x3E]),
    "uhd630_headless":    bytes([0x00, 0x00, 0x9B, 0x3E]),
    "uhd630_dt_headless": bytes([0x02, 0x00, 0x9B, 0x3E]),
    "iris_tgl_headless":  bytes([0x02, 0x00, 0x49, 0x9A]),
}

DEVICE_IDS: dict[str, bytes] = {
    # Fake device-id to match known-good framebuffers
    "kbl_r":     bytes([0xA0, 0x3E, 0x00, 0x00]),   # spoof UHD 620 as 3EA0
    "cfl_h":     bytes([0x9B, 0x3E, 0x00, 0x00]),   # spoof as 3E9B
}

def _igpu_config(profile: HardwareProfile, headless: bool = False) -> tuple[bytes, bytes | None]:
    """Returns (ig-platform-id, device-id or None)"""
    gen = profile.cpu_generation
    name = profile.gpu_name.lower()
    platform = profile.oc_platform.lower()

    if gen == 2:
        return IG_PLATFORM_IDS["hd3000"], None
    elif gen == 3:
        return IG_PLATFORM_IDS["hd4000"], None
    elif gen == 4:
        if "iris" in name:     return IG_PLATFORM_IDS["iris5100"], None
        if "hd 5000" in name:  return IG_PLATFORM_IDS["hd5000"], None
        if "hd 4600" in name:  return IG_PLATFORM_IDS["hd4600"], None
        return IG_PLATFORM_IDS["hd4400"], None
    elif gen == 5:
        if "iris" in name:     return IG_PLATFORM_IDS["iris6100"], None
        return IG_PLATFORM_IDS["hd5500"], None
    elif gen == 6:
        if "iris" in name:     return IG_PLATFORM_IDS["iris540"], None
        if "530" in name:      return IG_PLATFORM_IDS["hd530"], None
        if "515" in name:      return IG_PLATFORM_IDS["hd515"], None
        return IG_PLATFORM_IDS["hd520"], None
    elif gen == 7:
        if "iris" in name:     return IG_PLATFORM_IDS["iris640"], None
        if "630" in name:      return IG_PLATFORM_IDS["hd630"], None
        if "615" in name:      return IG_PLATFORM_IDS["hd615"], None
        return IG_PLATFORM_IDS["hd620"], None
    elif gen in (8, 9):
        if headless:
            if profile.platform == "desktop":
                return IG_PLATFORM_IDS["uhd630_dt_headless"], None
            if "uhd 630" in name:
                return IG_PLATFORM_IDS["uhd630_headless"], None
            return IG_PLATFORM_IDS["uhd620_headless"], None
        if profile.platform == "desktop":
            return IG_PLATFORM_IDS["uhd630_dt"], None
        # Kaby Lake-R / Whiskey Lake / Coffee Lake laptop - UHD 620
        if "uhd 620" in name or "kaby lake-r" in platform or "whiskey" in platform:
            return IG_PLATFORM_IDS["uhd620"], DEVICE_IDS["kbl_r"]
        if "uhd 630" in name:
            return IG_PLATFORM_IDS["uhd630_mb"], DEVICE_IDS["cfl_h"]
        return IG_PLATFORM_IDS["uhd620"], DEVICE_IDS["kbl_r"]
    elif gen == 10:
        if "ice lake" in platform:
            return IG_PLATFORM_IDS["iris_ice"], None
        if profile.platform == "desktop":
            return IG_PLATFORM_IDS["uhd630_cml"], None
        return IG_PLATFORM_IDS["uhd620_cml"], None
    elif gen == 11:
        if headless:
            return IG_PLATFORM_IDS["iris_tgl_headless"], None
        return IG_PLATFORM_IDS["iris_tgl"], None
    elif gen >= 12:
        return IG_PLATFORM_IDS["uhd770"], None

    return IG_PLATFORM_IDS["uhd620"], None

LOAD_ORDER = [
    "Lilu", "FakeSMC", "VirtualSMC",
    "WhateverGreen", "NootedRed", "NootRX",
    "AppleALC", "VoodooHDA", "CodecCommander",
    "RestrictEvents", "FeatureUnlock", "CryptexFixup",
    "CPUFriend",
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
    "HibernationFixup", "NVMeFix",
    "IntelMausiEthernet", "AppleIGC", "AppleIntelE1000e", "AppleIntelI210Ethernet",
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
    "VoodooI2CAtmel","VoodooI2CFTE","VoodooI2CGoodix",
    "VoodooSMBus", "VoodooRMI",
    "YogaSMC", "AsusSMC",
    "BrightnessKeys", "NoTouchID",
    "USBToolBox", "UTBMap", "USBInjectAll", "XHCI-unsupported",
    "RealtekCardReader", "RealtekCardReaderFriend", "Sinetek-rtsx",
    "JMicronATA", "AHCIPortInjector",
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
    # USBToolBox port maps are pure Info.plist bundles — giving them an
    # ExecutablePath makes OpenCore fail to inject the map once it's enabled.
    "UTBMap", "UTBDefault",
}

# Min/Max kernel versions for version-specific kexts.
# Windows must not overlap between kexts that replace one another, or both load
# at once and conflict. Darwin: 14=10.10, 18=10.14, 19=10.15, 20=11, 21=12, 22=13
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

    # Embedded controller. The laptop table also declares _SB.USBX, so laptops
    # must not additionally load SSDT-USBX or the device is defined twice.
    if profile.platform == "laptop":
        ssdts.append("SSDT-EC-USBX")
    else:
        ssdts.append("SSDT-EC")

    # Backlight (laptop only)
    if profile.platform == "laptop":
        ssdts.append("SSDT-PNLF")

    # AWAC clock fix — Z390/B460+ desktops (gen 9+); laptops never have AWAC
    if gen >= 9 and profile.platform == "desktop":
        ssdts.append("SSDT-AWAC")

    # PMC fix — Coffee Lake (gen 8) desktop
    if gen >= 8 and profile.platform == "desktop":
        ssdts.append("SSDT-PMC")

    # I2C GPIO — needed for I2C trackpad
    if has_i2c:
        ssdts.append("SSDT-GPI0")
        ssdts.append("SSDT-XOSI")

    return ssdts

# An ACPI rename is only safe when the SSDT that defines its replacement is
# actually loaded. Renaming _OSI to XOSI without SSDT-XOSI, for example, points
# every firmware _OSI call at a method that does not exist.
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

    # XOSI spoof — lets the DSDT's Windows-only branches run under macOS.
    # SSDT-XOSI supplies the XOSI method these renames point at.
    add("OSID to XSID", "4F534944", "58534944")
    add("_OSI to XOSI", "5F4F5349", "584F5349")

    # Instant-wake fix. The DSDT's _PRW objects call GPRW; we rename the stock
    # GPRW aside to XGPR so SSDT-GPRW can supply a GPRW that masks GPE 0x6D/0x0D
    # and delegates everything else back to XGPR.
    add("GPRW to XGPR", "47505257", "58475052")

    return patches

def _device_properties(profile: HardwareProfile, layout_id: int) -> dict:
    props: dict[str, dict] = {}

    # Intel iGPU
    if profile.gpu_vendor == "intel" and "arc" not in profile.gpu_name.lower():
        headless = bool(profile.dgpu_vendor)
        platform_id, device_id = _igpu_config(profile, headless=headless)
        igpu_props: dict = {
            "AAPL,ig-platform-id": platform_id,
        }
        # Sandy Bridge uses different key
        if profile.cpu_generation == 2:
            igpu_props = {"AAPL,snb-platform-id": platform_id}

        if device_id:
            igpu_props["device-id"] = device_id

        if headless:
            igpu_props["disable-external-gpu"] = bytes([0x01, 0x00, 0x00, 0x00])

        if profile.platform == "laptop":
            # Framebuffer patch for laptop: set stolenmem + cursormem
            igpu_props["framebuffer-patch-enable"] = bytes([0x01, 0x00, 0x00, 0x00])
            igpu_props["framebuffer-stolenmem"]    = bytes([0x00, 0x00, 0x00, 0x04])  # 64MB
            igpu_props["framebuffer-fbmem"]        = bytes([0x00, 0x00, 0x00, 0x00])

        props["PciRoot(0x0)/Pci(0x2,0x0)"] = igpu_props

    # Audio layout-id
    layout_bytes = layout_id.to_bytes(4, "little")
    props["PciRoot(0x0)/Pci(0x1f,0x3)"] = {
        "layout-id": layout_bytes,
    }

    # Intel I225/I226 ethernet fix (needs device-id spoof)
    if profile.ethernet_chipset in ("i225", "i226"):
        props["PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0)"] = {
            "device-id":     bytes([0xF2, 0x15, 0x00, 0x00]),
            "PCI-Subchannel": bytes([0x00]),
            "built-in":      bytes([0x01]),
        }

    if profile.ethernet_chipset and profile.ethernet_chipset not in ("none",):
        if profile.ethernet_chipset in ("i219", "i218", "i217"):
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
        nvme_path = "PciRoot(0x0)/Pci(0x1D,0x0)"
        if nvme_path not in props:
            props[nvme_path] = {}
        props[nvme_path]["built-in"] = bytes([0x01])

    return {"Add": props, "Delete": {}}

def _cpu_needs_spoof(profile: HardwareProfile) -> tuple[bytes, bytes] | None:
    name = profile.cpu_name.lower()
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
        "CustomSMBIOSGuid":           False,
        "DisableIoMapper":            True,    # disable VT-d (enable in BIOS after install)
        "DisableLinkeditJettison":    True,
        "DisableRtcChecksum":         False,
        "ExtendBTFeatureFlags":       True,    # for BT fixes
        "IncreasePciBarSize":         False,
        "LapicKernelPanic":           False,   # HP laptops need True
        "LegacyCommpage":             False,
        "PanicNoKextDump":            True,
        "PowerTimeoutKernelPanic":    True,
        "ProvideCurrentCpuInfo":      True,
        "SetApfsTrimTimeout":         -1,
        "XhciPortLimit":              False,   # use USB map
    }

    if "hp" in dmi_vendor():
        quirks["LapicKernelPanic"] = True

    # AMD: disable Intel-only quirks
    if profile.cpu_vendor == "amd":
        quirks["AppleCpuPmCfgLock"]  = False
        quirks["AppleXcpmCfgLock"]   = False
        quirks["ProvideCurrentCpuInfo"] = False

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

def _amd_kernel_patches(profile: HardwareProfile) -> list[dict]:
    # Full AMD vanilla kernel patches from https://github.com/AMD-OSX/AMD_Vanilla
    # Required for AMD CPUs (Ryzen/Threadripper) to boot macOS
    cores = cpu_core_count()
    core_hex = format(cores, "02x")

    def p(comment, base, find, replace, count=1, min_k="", max_k="", identifier="kernel"):
        return {
            "Arch":         "x86_64",
            "Base":         base,
            "Comment":      f"AMD - {comment}",
            "Count":        count,
            "Enabled":      True,
            "Find":         bytes.fromhex(find.replace(" ", "")) if find else b"",
            "Identifier":   identifier,
            "Limit":        0,
            "Mask":         b"",
            "MaxKernel":    max_k,
            "MinKernel":    min_k,
            "Replace":      bytes.fromhex(replace.replace(" ", "")),
            "ReplaceMask":  b"",
            "Skip":         0,
        }

    return [
        # cpuid_set_cpufamily — make macOS treat AMD as supported Intel family
        p("cpuid_set_cpufamily",
          "_cpuid_set_cpufamily",
          "B9 78000000 31C0 39D9 75 13",
          "B8 A1000000 31C0 31C0 31C0 EB 02",
          min_k="20.0.0"),

        # cpuid_set_info_rdmsr — prevent RDMSR crash on AMD
        p("cpuid_set_info_rdmsr",
          "_cpuid_set_info_rdmsr",
          "B9 000000C0 0F32",
          "B9 000000C0 31C0",
          count=4, min_k="20.0.0"),

        # commpage_populate — disable commpage CPU features AMD doesn't have
        p("commpage_populate",
          "_commpage_populate",
          "EB 4E",
          "EB 00",
          min_k="20.0.0"),

        # mp_cpus_callin — patch CPU count with actual core count
        p("mp_cpus_callin",
          "_mp_cpus_callin",
          "B8 01000000",
          f"B8 {core_hex}000000",
          min_k="20.0.0"),

        # cpuid_vmm_present — prevent VMM detection hang
        p("cpuid_vmm_present",
          "_cpuid_vmm_present",
          "B8 01000000 C3",
          "B8 00000000 C3",
          min_k="20.0.0"),

    ]

def _nvram_section(profile: HardwareProfile, layout_id: int, macos_major: int = 0) -> dict:
    boot_args = [
        "-v",                  # verbose on first boot (remove after working)
        "debug=0x100",         # don't panic on kernel error
        "keepsyms=1",          # keep symbols for debug
        "-no_compat_check",    # bypass board ID check in boot.efi
        f"alcid={layout_id}",
    ]

    if macos_major >= 15:
        # Sequoia+: RestrictEvents VMM spoof so macOS doesn't see unsupported Intel hardware
        boot_args.append("revpatch=sbvmm")
        # Lilu hardcodes a max-supported-kernel-version check per release and
        # refuses to let ANY of its plugins inject (WhateverGreen, AppleALC,
        # itlwm, VirtualSMC, ...) on a macOS newer than what that Lilu build
        # currently whitelists — shows up as generic injection failures like
        # "Invalid Parameter" on brand-new macOS versions. Bypass the gate.
        boot_args.append("-lilubetaall")

    if profile.cpu_vendor == "amd":
        boot_args.append("npci=0x2000")   # AMD PCI fix

    if profile.gpu_vendor == "nvidia":
        boot_args.append("nv_disable=1")  # disable NVIDIA (unsupported on modern macOS)

    if profile.dgpu_vendor == "amd":
        boot_args.append("-radvesa")

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
            "AudioCodec":    0,
            "AudioDevice":   "",
            "AudioOutMask":  -1,
            "AudioSupport":  False,
            "PlayChime":     "Disabled",
            "SetupDelay":    0,
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
            "ConsoleMode":   "",
            "DirectGopRendering": False,
            "ForceResolution": False,
            "GopPassThrough": "Disabled",
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
            "TscSyncTimeout":               0,
            "UnblockFsConnect":             any(v in dmi_vendor() for v in ("lenovo", "dell", "hp")),
        },
        "ReservedMemory": [],
    }

def _booter_section(profile: HardwareProfile, resizable_bar: bool = False) -> dict:
    is_z390_or_hedt = profile.cpu_generation >= 9

    return {
        "MmioWhitelist": [],
        "Patch":         [],
        "Quirks": {
            "AllowRelocationBlock":     False,
            "AvoidRuntimeDefrag":       True,
            "DevirtualiseMmio":         is_z390_or_hedt,
            "DisableSingleUser":        False,
            "DisableVariableWrite":     False,
            "DiscardHibernateMap":      False,
            "EnableSafeModeSlide":      True,
            "EnableWriteUnprotector":   True,
            "FixupAppleEfiImages":      True,
            "ForceBooterSignature":     False,
            "ForceExitBootServices":    False,
            "ProtectMemoryRegions":     False,
            "ProtectSecureBoot":        False,
            "ProtectUefiServices":      True,
            "ProvideCustomSlide":       True,
            "ProvideMaxSlide":          0,
            "RebuildAppleMemoryMap":    False,
            "ResizeAppleGpuBars":       0 if resizable_bar else -1,
            "SetupVirtualMap":          True,
            "SignalAppleOS":            True,
            "SyncRuntimePermissions":   False,
        },
    }

def generate(profile: HardwareProfile, smbios: SMBIOSData, macos_major: int = 0, wifi_kext_mode: str = "itlwm", dual_boot: str = "") -> dict:
    kexts = select_kexts(profile, wifi_kext_mode=wifi_kext_mode)
    layout_id = get_alc_layout(profile.audio_codec)
    ssdts = _required_ssdts(profile, kexts)

    return {
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
        "DeviceProperties": _device_properties(profile, layout_id),
        "Kernel":           _kernel_section(profile, kexts),
        "Misc": {
            "BlessOverride": [],
            "Boot": {
                "ConsoleAttributes":  0,
                "HibernateMode":      "None",
                "HideAuxiliary":      False,
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
                "Target":             3,
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
        "NVRAM":            _nvram_section(profile, layout_id, macos_major),
        "PlatformInfo":     _platform_info(smbios),
        "UEFI":             _uefi_section(profile, dual_boot=dual_boot),
    }

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
