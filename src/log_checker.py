"""
Hackintosh log analyzer — parses OpenCore boot logs, kernel panic files,
and generic boot output to identify issues and suggest specific fixes.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    severity: str           # "critical", "warning", "info"
    category: str
    title: str
    explanation: str
    fix_steps: list[str]
    context_lines: list[str] = field(default_factory=list)
    confidence: str = "likely"  # "definitive", "likely", "possible"


@dataclass
class _Pattern:
    regex: str
    severity: str
    category: str
    title: str
    explanation: str
    fix_steps: list[str]
    confidence: str = "likely"
    tag: str = ""
    suppresses: list[str] = field(default_factory=list)


# ── OC log pattern database ────────────────────────────────────────────────────

OC_PATTERNS: list[_Pattern] = [

    # ── USB ───────────────────────────────────────────────────────────────────
    _Pattern(
        regex=r"Still waiting for root device",
        severity="critical", category="usb",
        title="USB ports not mapped — macOS cannot find the disk",
        explanation=(
            "macOS is searching for the boot drive over USB but has no port map loaded. "
            "This is the single most common reason installs stall after the Apple logo."
        ),
        fix_steps=[
            "Boot into macOS recovery or a working macOS install.",
            "Download and run USBToolBox (github.com/USBToolBox/tool).",
            "Map your USB ports and export USBMap.kext.",
            "Replace EFI/OC/Kexts/USBMap.kext with the one you generated.",
            "Reboot.",
        ],
        confidence="definitive", tag="usb-root",
        suppresses=["usb-port-limit", "usb-xhci"],
    ),
    _Pattern(
        regex=r"XhciPortLimit.*true|USB.*port.*limit.*patch|USBInjectAll",
        severity="warning", category="usb",
        title="USB port limit patch active — causes panics on macOS 12+",
        explanation=(
            "XhciPortLimit or USBInjectAll is enabled. On macOS Monterey and newer "
            "this causes kernel panics. A proper USB port map is the correct fix."
        ),
        fix_steps=[
            "Disable XhciPortLimit in config.plist → Kernel → Quirks.",
            "Generate a USB map with USBToolBox and use USBMap.kext instead.",
        ],
        confidence="definitive", tag="usb-port-limit",
    ),
    _Pattern(
        regex=r"AppleUSBXHCI.*reset|XHCI.*reset.*loop",
        severity="warning", category="usb",
        title="USB controller (XHCI) reset loop",
        explanation="The XHCI USB controller is repeatedly resetting.",
        fix_steps=[
            "Try different USB ports — prefer USB 2.0 during install.",
            "Disable XhciPortLimit if enabled.",
            "Add EHCIMBFix quirk if on Haswell or older.",
        ],
        confidence="likely", tag="usb-xhci",
    ),

    # ── Boot / UEFI ────────────────────────────────────────────────────────────
    _Pattern(
        regex=r"Err\(0xE\).*root_hash|OCB:.*root_hash|EB.*LD.*root_hash",
        severity="critical", category="boot",
        title="Recovery image root hash check failed",
        explanation=(
            "boot.efi rejected the macOS recovery image because SecureBootModel is "
            "set to a value that enforces hash verification."
        ),
        fix_steps=[
            "Open config.plist → Misc → Security → SecureBootModel.",
            "Set SecureBootModel to Disabled.",
            "Save and reboot.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"Err\(0xE\).*EB\.LD|OCB:.*EB\.LD",
        severity="critical", category="boot",
        title="OpenCore could not load a critical EFI stage file",
        explanation=(
            "A critical EFI binary during the bootloader handoff failed to load — "
            "it may be missing, the wrong architecture, or corrupt."
        ),
        fix_steps=[
            "Run HackMate → Restore EFI to redownload OpenCore and all drivers.",
            "Make sure you're using the RELEASE build of OpenCore, not DEBUG.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"^OC: Failed to load|^OCB: Failed to load",
        severity="critical", category="boot",
        title="OpenCore failed to load a required file",
        explanation="A file OpenCore was configured to load does not exist or cannot be read.",
        fix_steps=[
            "Run HackMate → Restore EFI to redownload all OC files.",
            "Check the file path in config.plist matches what's on the EFI partition.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"Failed to find.*\.efi|missing.*\.efi driver",
        severity="critical", category="boot",
        title="A UEFI driver (.efi) is missing from the EFI partition",
        explanation="OpenCore tried to load a driver that doesn't exist on disk.",
        fix_steps=[
            "Remove entries in config.plist → UEFI → Drivers for drivers you don't have.",
            "Or run Restore EFI to redownload all drivers.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"board.id.*not supported|board.id.*mismatch|EB:.*no.*board",
        severity="critical", category="boot",
        title="Board ID rejected — boot.efi refused to load",
        explanation=(
            "macOS's boot.efi checks your board ID against a whitelist and "
            "it failed. This is expected on non-Apple hardware and needs a workaround."
        ),
        fix_steps=[
            "Add -no_compat_check to boot-args in config.plist → NVRAM → 7C436110-AB2A-4BBB-A880-FE41995C9F82 → boot-args.",
            "Or use a SMBIOS model that is whitelisted for your macOS version.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"Blocked by.*security policy|apfs.*security.*policy|OCB:.*security",
        severity="critical", category="boot",
        title="Boot blocked by security policy",
        explanation="OpenCore's or Apple's security policy is preventing the OS from loading.",
        fix_steps=[
            "Set SecureBootModel to Disabled in config.plist → Misc → Security.",
            "Set DmgLoading to Any in config.plist → Misc → Security.",
            "Set ScanPolicy to 0 to allow scanning all drives and partitions.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"vault.*key.*mismatch|OCB:.*vault|vault.*invalid",
        severity="critical", category="boot",
        title="OpenCore Vault key mismatch",
        explanation=(
            "Vault is enabled but the vault.plist or public key doesn't match "
            "the files on the EFI partition. OpenCore refuses to boot."
        ),
        fix_steps=[
            "Disable Vault: set Vault to Optional in config.plist → Misc → Security.",
            "Or regenerate: run create_vault.sh from OpenCorePkg/Utilities/CreateVault/.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"NVRAM.*not.*found|NVRAM.*emulat.*fail|LegacyEnable",
        severity="warning", category="boot",
        title="NVRAM emulation not working — settings may not persist",
        explanation=(
            "NVRAM is not writable. Boot-args, SIP flags, and other settings "
            "set by the bootloader won't persist across reboots."
        ),
        fix_steps=[
            "Add OpenVariableRuntimeDxe.efi to UEFI → Drivers in config.plist.",
            "Enable LegacyEnable and configure LegacySchema in config.plist → NVRAM.",
            "Or enable native NVRAM support in BIOS if your firmware supports it.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"OCB:.*no.*entries|OC:.*no.*bootable|no.*boot.*entry.*found",
        severity="critical", category="boot",
        title="No bootable macOS entry found in picker",
        explanation="OpenCore finished scanning and found nothing to boot.",
        fix_steps=[
            "Set ScanPolicy to 0 in config.plist → Misc → Security to scan everything.",
            "Check BlessOverride if your macOS volume is on an unusual path.",
            "If fresh install: make sure you're selecting the USB recovery, not the EFI shell.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"HideAuxiliary.*true|auxiliary.*not.*show|recovery.*hidden",
        severity="info", category="boot",
        title="Recovery entry is hidden by HideAuxiliary",
        explanation=(
            "HideAuxiliary=True hides recovery, reset NVRAM, and tool entries from the picker."
        ),
        fix_steps=[
            "Press Space in the OpenCore picker to reveal hidden entries.",
            "Or set HideAuxiliary to False in config.plist → Misc → Boot.",
        ],
        confidence="definitive",
    ),

    # ── Memory map ────────────────────────────────────────────────────────────
    _Pattern(
        regex=r"OCABC.*MMIO.*stall|OCABC: MMIO",
        severity="critical", category="memory",
        title="Memory map MMIO stall — system will hang at boot",
        explanation=(
            "The firmware's memory map contains MMIO regions that macOS's kernel "
            "can't handle directly. Without DevirtualiseMmio these cause hangs."
        ),
        fix_steps=[
            "Enable DevirtualiseMmio in config.plist → Booter → Quirks.",
            "Enable MmioWhitelist and add your platform's MMIO ranges.",
            "Use SSDTTime → FixHPET to identify the required whitelist ranges.",
            "AMD platforms may also need EnableWriteUnprotector.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"malloc.*failed|OCABC.*alloc.*fail|alloc.*size.*failed",
        severity="warning", category="memory",
        title="Memory allocation failure during boot",
        explanation="OpenCore or a driver couldn't allocate memory — memory map issue.",
        fix_steps=[
            "Enable ProtectUefiServices in config.plist → Booter → Quirks.",
            "Enable RebuildAppleMemoryMap.",
            "Enable SyncRuntimePermissions.",
        ],
        confidence="possible",
    ),
    _Pattern(
        regex=r"OCABC.*slide|EnableSafeModeSlide|slide=0x",
        severity="warning", category="memory",
        title="KASLR slide value is zero or invalid",
        explanation=(
            "The KASLR slide value macOS uses for memory layout randomization is "
            "invalid, which can cause random boot failures or memory corruption."
        ),
        fix_steps=[
            "Enable ProvideCustomSlide in config.plist → Booter → Quirks.",
            "If that's already on and still failing, calculate a specific safe slide value "
            "using the Dortania OpenCore Post-Install memory guide.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"IOMMU.*enabled|VT.d.*active|DisableIoMapper",
        severity="warning", category="memory",
        title="VT-d / IOMMU is enabled — may cause memory instability",
        explanation=(
            "VT-d (Intel Virtualization for Directed I/O) can cause DMA memory "
            "mapping conflicts with macOS on hackintosh hardware."
        ),
        fix_steps=[
            "Disable VT-d in BIOS → Advanced → CPU Configuration → VT-d.",
            "Or enable DisableIoMapper in config.plist → Kernel → Quirks.",
        ],
        confidence="likely",
    ),

    # ── CPU / Power ───────────────────────────────────────────────────────────
    _Pattern(
        regex=r"MSR.*0[xX][Ee]2|CFG.?[Ll]ock|cfg.lock.*enabled",
        severity="critical", category="cpu",
        title="CFG Lock is on — MSR 0xE2 is write-protected",
        explanation=(
            "The BIOS has locked CPU register MSR 0xE2, which controls power management states. "
            "macOS needs to write to this register. Without unlocking it, you'll get kernel "
            "panics or the CPU will run at full speed permanently."
        ),
        fix_steps=[
            "Preferred: Disable CFG Lock in BIOS (look in Advanced → Power, CPU Config, or Overclocking).",
            "If no BIOS option exists: enable AppleXcpmCfgLock in config.plist → Kernel → Quirks.",
            "On Ivy Bridge and older, also enable AppleCpuPmCfgLock.",
            "You can verify CFG Lock status with ControlMsrE2.efi from OpenCorePkg.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"cpuid.*unsupported|Unsupported CPU|AMD.*kernel.*patch.*fail|amd.*vanilla.*patch",
        severity="critical", category="cpu",
        title="CPU not supported — AMD kernel patches missing or misconfigured",
        explanation=(
            "macOS's XNU kernel doesn't support AMD CPUs natively. "
            "The AMD vanilla kernel patches are either absent or the core count is wrong."
        ),
        fix_steps=[
            "Get the full patch set for your Zen generation from github.com/AMD-OSX/AMD_Vanilla.",
            "In config.plist → Kernel → Patch: make sure ALL patches from that set are present and enabled.",
            "Set the correct core count in the patches: 4=04, 6=06, 8=08, 12=0C, 16=10, 24=18, 32=20.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"XCPM.*not.*supported|xcpm.*init.*fail|ProvideCurrentCpuInfo.*missing",
        severity="warning", category="cpu",
        title="XCPM CPU power management failed to initialize",
        explanation=(
            "Extended CPU Power Management couldn't start. "
            "This means CPU frequency scaling won't work correctly."
        ),
        fix_steps=[
            "For AMD: Enable ProvideCurrentCpuInfo in config.plist → Kernel → Quirks.",
            "For Intel: Make sure your SMBIOS matches your CPU generation.",
            "Check that CPUFriend.kext (if used) has the right frequency data for your SMBIOS.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"TSC.*deadline.*not.*supported|TSC.*not.*sync|CpuTscSync",
        severity="warning", category="cpu",
        title="TSC timestamp counters not synchronized across cores",
        explanation=(
            "The CPU's timestamp counters aren't synced, which causes timing issues "
            "and can lead to random hangs or audio glitches."
        ),
        fix_steps=[
            "Enable TSCSync in config.plist → Kernel → Quirks.",
            "On HEDT platforms (X299, TRX40): use CpuTscSync.kext instead.",
            "On AMD: CpuTscSync is not needed — enable DisableRtcChecksum instead.",
        ],
        confidence="likely",
    ),

    # ── Kexts ─────────────────────────────────────────────────────────────────
    _Pattern(
        regex=r"Could not load.*\.kext|Failed to inject.*kext|kext.*load.*fail",
        severity="critical", category="kext",
        title="A kext failed to inject",
        explanation=(
            "One or more kernel extensions couldn't be loaded. "
            "The kext may be missing, its bundle structure may be broken, "
            "or the ExecutablePath in config.plist is wrong."
        ),
        fix_steps=[
            "Run HackMate → Restore EFI to redownload all kexts.",
            "Check that each kext has the correct bundle structure: "
            "MyKext.kext/Contents/MacOS/MyKext",
            "Verify ExecutablePath in config.plist → Kernel → Add matches exactly.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"Lilu.*not found|requires.*Lilu|depends.*on.*Lilu",
        severity="critical", category="kext",
        title="Lilu.kext is missing or loaded in the wrong order",
        explanation=(
            "Almost every Acidanthera kext (WhateverGreen, AppleALC, VirtualSMC, NVMeFix…) "
            "requires Lilu to be loaded first. If Lilu is missing or loads after them, "
            "they all silently fail or crash."
        ),
        fix_steps=[
            "Make sure Lilu.kext is present in EFI/OC/Kexts/.",
            "In config.plist → Kernel → Add: Lilu.kext MUST be the first entry.",
            "Run Restore EFI if Lilu is missing.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"VirtualSMC.*init.*fail|SMCBatteryManager.*fail|VirtualSMC.*not.*loaded",
        severity="critical", category="kext",
        title="VirtualSMC failed to initialize",
        explanation=(
            "VirtualSMC emulates Apple's SMC hardware. Without it macOS can't read "
            "temperature sensors, battery levels, or fan speeds — and may refuse to boot."
        ),
        fix_steps=[
            "Make sure VirtualSMC.kext loads after Lilu.kext (but before its plugins).",
            "Don't mix VirtualSMC and FakeSMC — remove one completely.",
            "Redownload VirtualSMC from github.com/acidanthera/VirtualSMC/releases.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"kext.*dependency.*not found|dependency.*missing.*kext",
        severity="warning", category="kext",
        title="Kext dependency missing",
        explanation=(
            "A kext requires another kext that isn't present or hasn't loaded yet."
        ),
        fix_steps=[
            "Check the failing kext's Info.plist → OSBundleLibraries for required deps.",
            "Add the missing dependency to EFI/OC/Kexts/ and config.plist.",
            "Make sure load order in config.plist puts dependencies first.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"duplicate.*kext|kext.*already.*loaded|kext.*injected.*twice",
        severity="warning", category="kext",
        title="Duplicate kext detected — will cause conflicts",
        explanation="The same kext is being loaded twice.",
        fix_steps=[
            "Check EFI/OC/Kexts/ for .kext folders with the same name.",
            "Check config.plist → Kernel → Add for duplicate entries.",
            "Remove the duplicate from both the folder and config.plist.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"itlwm.*not.*loaded|AirportItlwm.*version.*mismatch|airportitlwm.*wrong.*macos",
        severity="warning", category="kext",
        title="AirportItlwm version doesn't match your macOS version",
        explanation=(
            "AirportItlwm is compiled against a specific macOS version and will fail "
            "silently if you use the wrong build."
        ),
        fix_steps=[
            "Download the AirportItlwm build that matches your exact macOS version.",
            "For example: AirportItlwm_v2.3.0_stable_Sonoma14.kext for Sonoma.",
            "Alternatively, use itlwm.kext (not version-specific) + HeliPort app.",
        ],
        confidence="likely",
    ),

    # ── ACPI / SSDTs ──────────────────────────────────────────────────────────
    _Pattern(
        regex=r"ACPI.*Error.*AE_NOT_FOUND|ACPI.*\_SB.*not.*found|SSDT.*path.*not.*exist",
        severity="warning", category="acpi",
        title="ACPI object not found — SSDT path mismatch with your DSDT",
        explanation=(
            "An SSDT references an ACPI device or method path that doesn't exist "
            "in your system's DSDT. Common cause: your BIOS uses PCI0 but the SSDT "
            "expects PC00, or vice versa."
        ),
        fix_steps=[
            "Dump your DSDT using SSDTTime or OpenCore's ACPI dumps.",
            "Open it in MaciASL and check the exact path (PCI0 vs PC00, EC0 vs EC, etc.).",
            "Regenerate SSDTs with SSDTTime using your actual DSDT as input.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"ACPI.*Error.*AE_ALREADY_EXISTS|duplicate.*SSDT|SSDT.*conflict",
        severity="warning", category="acpi",
        title="ACPI object already exists — SSDT conflict",
        explanation=(
            "Two SSDTs define the same ACPI object. The second definition is silently "
            "ignored, which can cause subtle failures."
        ),
        fix_steps=[
            "Check EFI/OC/ACPI/ for duplicate SSDT files.",
            "Remove duplicates and verify config.plist → ACPI → Add matches what's on disk.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"DSDT.*checksum.*invalid|DSDT.*corrupt|DSDT.*bad.*checksum",
        severity="critical", category="acpi",
        title="DSDT is corrupt or has invalid checksum",
        explanation=(
            "The main ACPI table has a bad checksum. This usually happens when a "
            "DSDT is patched directly and the checksum isn't updated."
        ),
        fix_steps=[
            "Never patch the DSDT directly — use SSDTs for all patches.",
            "Remove any DSDT.aml from EFI/OC/ACPI/ if you added one.",
            "Delete and regenerate your SSDTs from scratch using SSDTTime.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"VoodooI2C.*gpio.*timeout|GPIO.*controller.*timeout|SSDT.GPI0.*missing",
        severity="warning", category="acpi",
        title="VoodooI2C GPIO timeout — I2C trackpad not initializing",
        explanation=(
            "VoodooI2C needs a GPIO interrupt pin configured via ACPI. "
            "The GPIO controller isn't responding in time."
        ),
        fix_steps=[
            "Make sure SSDT-GPI0.aml is in EFI/OC/ACPI/ and listed in config.plist → ACPI → Add.",
            "Also ensure SSDT-XOSI.aml is present (tells ACPI to behave like Windows).",
            "Load order in config.plist must be: VoodooI2C.kext first, then satellite kexts (VoodooI2CHID, etc.).",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"SSDT-EC.*not found|embedded controller.*not found|EC.*ACPI.*missing",
        severity="warning", category="acpi",
        title="Embedded Controller SSDT missing",
        explanation=(
            "macOS expects an Embedded Controller at a specific ACPI path. "
            "Without the EC SSDT, USB power and laptop battery may not work."
        ),
        fix_steps=[
            "Use SSDTTime to generate SSDT-EC.aml (desktop) or SSDT-EC-USBX.aml (laptop).",
            "Place it in EFI/OC/ACPI/ and add to config.plist → ACPI → Add.",
        ],
        confidence="likely",
    ),

    # ── GPU / Display ──────────────────────────────────────────────────────────
    _Pattern(
        regex=r"WhateverGreen.*fail|WEG.*patch.*fail|ig.platform.id.*0x00000000",
        severity="critical", category="gpu",
        title="WhateverGreen framebuffer patch failed",
        explanation=(
            "WhateverGreen couldn't apply the Intel iGPU framebuffer patches. "
            "The ig-platform-id doesn't match your iGPU, or the iGPU isn't enabled "
            "in BIOS."
        ),
        fix_steps=[
            "Enable iGPU in BIOS and set it as primary display.",
            "Check DeviceProperties → PciRoot(0x0)/Pci(0x2,0x0) → AAPL,ig-platform-id.",
            "Use HackMate config editor → Framebuffer section to pick the right id for your GPU.",
            "Make sure WhateverGreen.kext loads after Lilu.kext.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"AGPM.*fail|AppleGraphicsPowerManagement.*init.*fail",
        severity="warning", category="gpu",
        title="GPU power management (AGPM) failed to initialize",
        explanation=(
            "Apple GPU Power Management couldn't start. Usually a SMBIOS mismatch "
            "or the GPU not being recognized as a supported model."
        ),
        fix_steps=[
            "Make sure your SMBIOS model matches your GPU generation.",
            "For AMD dGPU: add agdpmod=pikera to boot-args.",
            "Try a different SMBIOS that explicitly supports your GPU family.",
        ],
        confidence="possible",
    ),
    _Pattern(
        regex=r"AppleIntelFramebuffer.*connector.*type.*mismatch|connector.*patch.*need",
        severity="warning", category="gpu",
        title="iGPU connector type mismatch",
        explanation=(
            "The framebuffer connector types don't match your physical display outputs. "
            "This causes blank screens on specific ports."
        ),
        fix_steps=[
            "Use Hackintool → Patch tab to identify and patch your connector types.",
            "Check the WhateverGreen FAQ on Dortania for your specific iGPU and display output.",
            "Common fix: set connector type 0x00040000 for HDMI, 0x00080000 for DP.",
        ],
        confidence="possible",
    ),
    _Pattern(
        regex=r"nv_disable|nvidia.*disabled|GeForce.*not.*supported.*macOS",
        severity="info", category="gpu",
        title="Nvidia GPU disabled (correct behavior on macOS 12+)",
        explanation=(
            "Nvidia dGPUs are not supported on macOS Monterey and newer. "
            "nv_disable=1 correctly disables it so the iGPU is used instead."
        ),
        fix_steps=[
            "This is expected and correct. Make sure nv_disable=1 is in boot-args.",
            "All display output must go through the Intel iGPU.",
            "If on High Sierra: Nvidia Web Drivers may work for older cards.",
        ],
        confidence="definitive",
    ),

    # ── Audio ──────────────────────────────────────────────────────────────────
    _Pattern(
        regex=r"AppleALC.*layout.*not found|layout.id.*not.*supported|alcid.*fail",
        severity="warning", category="audio",
        title="Audio layout ID not supported for this codec",
        explanation=(
            "The alcid value in boot-args doesn't correspond to a layout that "
            "AppleALC supports for your audio codec. Audio will be silent."
        ),
        fix_steps=[
            "Find your codec name (e.g. ALC256, ALC1220) in your BIOS specs or lspci.",
            "Check supported layouts at: github.com/acidanthera/AppleALC/wiki/Supported-codecs",
            "Try these common alcid values one at a time: 1, 2, 3, 11, 13, 28, 56, 66, 97.",
            "Use HackMate config editor → Audio section for codec-specific suggestions.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"com\.apple\.driver\.AppleHDA.*panic|AppleHDA.*crash|AppleHDA.*init.*fail",
        severity="warning", category="audio",
        title="AppleHDA audio driver crashed",
        explanation=(
            "The HDA audio driver crashed. Usually caused by AppleALC trying to apply "
            "a patch that doesn't work with the current alcid value."
        ),
        fix_steps=[
            "Make sure AppleALC.kext loads after Lilu.kext.",
            "Try a different alcid value in boot-args.",
            "If persistent: try VoodooHDA as a fallback (lower quality but more compatible).",
        ],
        confidence="likely",
    ),

    # ── Network ───────────────────────────────────────────────────────────────
    _Pattern(
        regex=r"itlwm.*fail|AirportItlwm.*fail|intel.*wifi.*not.*load",
        severity="warning", category="network",
        title="Intel WiFi kext failed",
        explanation="itlwm or AirportItlwm couldn't initialize the Intel wireless card.",
        fix_steps=[
            "AirportItlwm is macOS-version specific — download the build matching your macOS.",
            "Or use itlwm.kext (not version-specific) + install HeliPort for the UI.",
            "Don't load itlwm and AirportItlwm at the same time — pick one.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"AirportBrcmFixup.*fail|brcmfx.*init.*fail|Broadcom.*wifi.*not.*attach",
        severity="warning", category="network",
        title="Broadcom WiFi kext failed",
        explanation="AirportBrcmFixup couldn't initialize the Broadcom wireless card.",
        fix_steps=[
            "Make sure AirportBrcmFixup.kext loads after Lilu.kext.",
            "Add brcmfx-driver=2 to boot-args for injection mode.",
            "BCM94360/BCM943602 are natively supported — you may not need AirportBrcmFixup.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"IntelMausiEthernet.*fail|AppleIGC.*fail|RealtekRTL.*fail|LucyRTL.*fail",
        severity="warning", category="network",
        title="Ethernet driver failed to initialize",
        explanation="The ethernet driver couldn't attach to the NIC.",
        fix_steps=[
            "Intel I219/I218/I217 → IntelMausiEthernet.kext",
            "Intel I225/I226 (2.5G) → AppleIGC.kext",
            "Realtek RTL8111/8168 → RealtekRTL8111.kext",
            "Realtek RTL8125 (2.5G) → LucyRTL8125Ethernet.kext",
            "Make sure you're using the kext that matches your NIC chipset.",
        ],
        confidence="likely",
    ),

    # ── Sleep / Wake ──────────────────────────────────────────────────────────
    _Pattern(
        regex=r"hibernation.*fail|sleepimage.*fail|HibernationFixup.*fail",
        severity="warning", category="sleep",
        title="Hibernation / sleep image failure",
        explanation=(
            "macOS couldn't save or restore the hibernation (sleep) image. "
            "This causes wake failures and potential data loss."
        ),
        fix_steps=[
            "Add HibernationFixup.kext to your EFI.",
            "Disable hibernation: sudo pmset -a hibernatemode 0",
            "Delete old sleep image: sudo rm /var/vm/sleepimage",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"darkwake.*fail|IOPMSystem.*wake.*fail|sleep.*not.*work",
        severity="warning", category="sleep",
        title="Sleep/wake instability",
        explanation="The system is failing to enter or properly wake from sleep.",
        fix_steps=[
            "Add darkwake=0 to boot-args to disable dark wake entirely.",
            "Disable Power Nap: System Settings → Battery → uncheck Power Nap.",
            "Make sure NVMeFix.kext is loaded if you have an NVMe drive.",
            "USB wake issues are common — USBMap.kext helps prevent unwanted wakes.",
        ],
        confidence="possible",
    ),

    # ── Security / SIP ────────────────────────────────────────────────────────
    _Pattern(
        regex=r"SIP.*blocking|csr.active.config.*0x[^07]|amfi.*denied.*kext",
        severity="warning", category="security",
        title="SIP is blocking a required operation",
        explanation=(
            "System Integrity Protection is preventing something the hackintosh setup needs. "
            "Partial SIP disable is usually required."
        ),
        fix_steps=[
            "Set csr-active-config to 03080000 in config.plist → NVRAM for standard partial disable.",
            "Or 67080000 to fully disable SIP (less secure but solves most issues).",
            "Make this change in the NVRAM section, not just in Terminal.",
        ],
        confidence="likely",
    ),
    _Pattern(
        regex=r"AMFI.*denied|AppleMobileFileIntegrity.*deny|amfi.*policy.*block",
        severity="warning", category="security",
        title="AMFI (file integrity check) blocked an operation",
        explanation=(
            "Apple Mobile File Integrity is blocking code that isn't Apple-signed."
        ),
        fix_steps=[
            "Add amfi_get_out_of_my_way=1 to boot-args (temporary — disables AMFI).",
            "Or use RestrictEvents.kext with revpatch=sbvmm boot-arg.",
        ],
        confidence="likely",
    ),

    # ── Disk / NVMe ───────────────────────────────────────────────────────────
    _Pattern(
        regex=r"IONVMeFamily.*panic|NVMe.*crash|NVMe.*fatal",
        severity="critical", category="disk",
        title="NVMe driver crash — APST power state incompatibility",
        explanation=(
            "Apple's NVMe driver panicked on your drive, almost always because "
            "the drive's autonomous power state transitions (APST) aren't compatible "
            "with Apple's driver."
        ),
        fix_steps=[
            "Add NVMeFix.kext to your EFI — it patches APST for non-Apple drives.",
            "If still crashing: add nvme=0x9 to boot-args to disable APST entirely.",
            "Some Samsung drives also need -nvme_wait_for_quiesce in boot-args.",
        ],
        confidence="definitive",
    ),
    _Pattern(
        regex=r"APFS.*container.*not found|apfs.*mount.*fail|apfs.*no.*valid.*container",
        severity="critical", category="disk",
        title="APFS volume could not be mounted",
        explanation=(
            "macOS couldn't find or mount the APFS container. "
            "Often caused by USB mapping issues making the drive invisible."
        ),
        fix_steps=[
            "First check: is 'Still waiting for root device' also in the log? Fix that first.",
            "Add NVMeFix.kext if booting from NVMe.",
            "Make sure SetApfsTrimTimeout is not set to 0.",
        ],
        confidence="likely",
    ),
]


# ── Kernel panic reason → fix database ────────────────────────────────────────

PANIC_REASONS: list[tuple[str, Finding]] = [
    ("Still waiting for root device", Finding(
        severity="critical", category="usb",
        title="Kernel panic: USB ports not mapped",
        explanation=(
            "macOS panicked because it can't find the boot drive over USB. "
            "No USB port map is loaded."
        ),
        fix_steps=[
            "Run USBToolBox inside macOS to map your ports and generate USBMap.kext.",
            "Replace the placeholder USBMap.kext in EFI/OC/Kexts/ with your generated one.",
            "During install: try using a USB 2.0 port — they're more reliable before mapping.",
        ],
        confidence="definitive",
    )),
    ("MSR_PKG_CST_CONFIG_CONTROL", Finding(
        severity="critical", category="cpu",
        title="Kernel panic: CFG Lock write caused immediate crash",
        explanation=(
            "macOS attempted to write to MSR 0xE2 (CPU power management) but the "
            "BIOS has it locked. The kernel panicked immediately on boot."
        ),
        fix_steps=[
            "Disable CFG Lock in BIOS (usually in Advanced → CPU or Power submenu).",
            "If no BIOS option: enable AppleXcpmCfgLock in config.plist → Kernel → Quirks.",
        ],
        confidence="definitive",
    )),
    ("IONVMeFamily", Finding(
        severity="critical", category="disk",
        title="Kernel panic: NVMe driver crashed — APST incompatibility",
        explanation=(
            "Apple's NVMe driver panicked on your drive. Non-Apple NVMe drives "
            "frequently have incompatible autonomous power state transitions."
        ),
        fix_steps=[
            "Add NVMeFix.kext to EFI/OC/Kexts/ and config.plist → Kernel → Add.",
            "If still panicking: add nvme=0x9 to boot-args to disable APST.",
        ],
        confidence="definitive",
    )),
    ("AppleACPIPlatform", Finding(
        severity="critical", category="acpi",
        title="Kernel panic: ACPI subsystem crashed",
        explanation=(
            "The ACPI platform driver panicked. Caused by a bad SSDT, wrong ACPI "
            "path, or conflicting DSDT patches."
        ),
        fix_steps=[
            "Remove SSDTs one at a time and reboot to isolate the bad one.",
            "Regenerate all SSDTs using SSDTTime from a fresh DSDT dump.",
            "Don't patch the DSDT directly — always use SSDTs.",
        ],
        confidence="likely",
    )),
    ("com.apple.iokit.IOUSBHostFamily", Finding(
        severity="critical", category="usb",
        title="Kernel panic: USB host controller crashed",
        explanation="The USB host controller driver panicked.",
        fix_steps=[
            "Generate a proper USBMap.kext with USBToolBox.",
            "Disable XhciPortLimit in config.plist if it's enabled.",
            "Try booting from a USB 2.0 port instead of 3.0.",
        ],
        confidence="likely",
    )),
    ("AppleIntelMEI", Finding(
        severity="critical", category="kext",
        title="Kernel panic: Intel MEI (Management Engine) driver crashed",
        explanation=(
            "The Intel Management Engine Interface driver panicked. The ME firmware "
            "version doesn't match what macOS expects."
        ),
        fix_steps=[
            "Block this driver: add com.apple.driver.AppleIntelMEI to Kernel → Block in config.plist.",
        ],
        confidence="likely",
    )),
    ("com.apple.driver.AppleACPIEC", Finding(
        severity="critical", category="acpi",
        title="Kernel panic: Embedded Controller driver crashed",
        explanation=(
            "The EC driver panicked — usually because your laptop's EC has registers "
            "wider than 8 bits, which macOS doesn't support natively."
        ),
        fix_steps=[
            "Add ECEnabler.kext to EFI/OC/Kexts/ — patches EC field access width.",
            "Make sure SSDT-EC-USBX.aml is present (required for laptops).",
        ],
        confidence="likely",
    )),
    ("com.apple.filesystems.apfs", Finding(
        severity="critical", category="disk",
        title="Kernel panic: APFS filesystem driver crashed",
        explanation=(
            "The APFS driver panicked. On hackintosh this almost always means "
            "NVMe APST incompatibility or a USB mapping issue."
        ),
        fix_steps=[
            "Add NVMeFix.kext to your EFI.",
            "Also verify USB mapping is correct — APFS can panic if the volume isn't found cleanly.",
        ],
        confidence="likely",
    )),
    ("VoodooI2C", Finding(
        severity="warning", category="input",
        title="Kernel panic: VoodooI2C trackpad driver crashed",
        explanation="The I2C trackpad driver panicked — usually a GPIO interrupt issue.",
        fix_steps=[
            "Make sure SSDT-GPI0.aml and SSDT-XOSI.aml are in EFI/OC/ACPI/.",
            "Check VoodooI2C.kext loads before its satellite kexts in config.plist.",
            "Use the right satellite: VoodooI2CHID for most, VoodooI2CSynaptics for Synaptics.",
        ],
        confidence="likely",
    )),
    ("ApplePS2Controller", Finding(
        severity="warning", category="input",
        title="Kernel panic: PS/2 controller crashed",
        explanation="VoodooPS2Controller panicked on the PS/2 keyboard or trackpad.",
        fix_steps=[
            "Redownload VoodooPS2Controller from the latest GitHub release.",
            "Make sure only one PS/2 kext is loaded — not both VoodooPS2 and another.",
        ],
        confidence="likely",
    )),
    ("IOMMU", Finding(
        severity="critical", category="memory",
        title="Kernel panic: IOMMU / VT-d memory conflict",
        explanation="VT-d caused a DMA memory mapping conflict with macOS.",
        fix_steps=[
            "Disable VT-d in BIOS → Advanced → CPU Configuration → VT-d.",
            "Or enable DisableIoMapper in config.plist → Kernel → Quirks.",
        ],
        confidence="definitive",
    )),
    ("AppleMobileFileIntegrity", Finding(
        severity="warning", category="security",
        title="Kernel panic: AMFI security check failed",
        explanation="Apple's file integrity check panicked on unsigned code.",
        fix_steps=[
            "Add amfi_get_out_of_my_way=1 to boot-args (temporary workaround).",
            "Set csr-active-config to disable SIP partially.",
        ],
        confidence="likely",
    )),
    ("com.apple.driver.AppleHDA", Finding(
        severity="warning", category="audio",
        title="Kernel panic: HDA audio driver crashed",
        explanation=(
            "The HDA driver panicked. AppleALC may be injecting a wrong layout ID."
        ),
        fix_steps=[
            "Try a different alcid value in boot-args.",
            "Make sure AppleALC.kext loads after Lilu.kext.",
        ],
        confidence="likely",
    )),
    ("page fault", Finding(
        severity="critical", category="kext",
        title="Kernel panic: page fault — kext accessing invalid memory",
        explanation=(
            "A kernel extension tried to access memory it shouldn't. "
            "Check 'Kernel Extensions in backtrace' for the guilty kext."
        ),
        fix_steps=[
            "Identify the guilty kext in the backtrace (look for non-Apple bundle IDs).",
            "Redownload that kext from its official GitHub release.",
            "If it's an Acidanthera kext: review the corresponding config.plist settings.",
        ],
        confidence="likely",
    )),
    ("Unsupported CPU", Finding(
        severity="critical", category="cpu",
        title="Kernel panic: AMD CPU not supported — patches required",
        explanation=(
            "macOS's kernel doesn't support AMD CPUs natively. "
            "The AMD vanilla patches are missing or have wrong core count."
        ),
        fix_steps=[
            "Get the full patch set from github.com/AMD-OSX/AMD_Vanilla for your Zen generation.",
            "Apply ALL patches in config.plist → Kernel → Patch.",
            "Set the correct core count in each patch that contains it.",
        ],
        confidence="definitive",
    )),
    ("com.apple.driver.AppleIntelSlimMemoryController", Finding(
        severity="critical", category="memory",
        title="Kernel panic: Intel memory controller driver crashed",
        explanation=(
            "Usually indicates a SMBIOS mismatch or iGPU framebuffer not properly initialized."
        ),
        fix_steps=[
            "Make sure your SMBIOS model matches your CPU generation.",
            "Verify ig-platform-id is set correctly for your iGPU in DeviceProperties.",
        ],
        confidence="likely",
    )),
    ("MSR_IA32_POWER_CTL", Finding(
        severity="warning", category="cpu",
        title="CPU power control register access denied",
        explanation=(
            "macOS tried to access a CPU power control MSR that isn't accessible. "
            "Common on some AMD platforms."
        ),
        fix_steps=[
            "Enable ProvideCurrentCpuInfo in config.plist → Kernel → Quirks.",
            "Make sure you're using the correct AMD kernel patches for your Zen generation.",
        ],
        confidence="likely",
    )),
]

# Known Acidanthera kexts with their common failure hints
_ACIDANTHERA_HINTS: dict[str, str] = {
    "com.acidanthera.WhateverGreen": "WhateverGreen crashed — verify ig-platform-id and GPU DeviceProperties.",
    "com.acidanthera.AppleALC": "AppleALC crashed — try a different alcid value in boot-args.",
    "com.acidanthera.VirtualSMC": "VirtualSMC crashed — check it loads after Lilu, no FakeSMC conflict.",
    "com.acidanthera.Lilu": "Lilu itself crashed — very unusual. Redownload from github.com/acidanthera/Lilu/releases.",
    "com.acidanthera.NVMeFix": "NVMeFix crashed on your NVMe drive — try nvme=0x9 in boot-args.",
    "com.acidanthera.CPUFriend": "CPUFriend crashed — check CPUFriendDataProvider matches your SMBIOS.",
    "com.acidanthera.HibernationFixup": "HibernationFixup crashed — check hibernatemode is set correctly.",
    "com.acidanthera.RestrictEvents": "RestrictEvents crashed — redownload latest release.",
    "as.lvs1974.CPUFriend": "CPUFriend crashed — check CPUFriendDataProvider matches your SMBIOS.",
    "org.netkas.FakeSMC": "FakeSMC crashed — migrate to VirtualSMC instead.",
}


# ── Context extraction ─────────────────────────────────────────────────────────

def _extract_context(lines: list[str], idx: int, radius: int = 2) -> list[str]:
    start = max(0, idx - radius)
    end   = min(len(lines), idx + radius + 1)
    out   = []
    for i in range(start, end):
        prefix = "→ " if i == idx else "  "
        out.append(prefix + lines[i].rstrip()[:120])
    return out


# ── Log type detection ─────────────────────────────────────────────────────────

def _detect_log_type(text: str) -> str:
    if re.search(r"panic\(cpu \d+ caller 0x[0-9a-f]+\)", text, re.I) or \
       "Backtrace (CPU" in text:
        return "kernel_panic"
    if any(m in text for m in ("OC:", "OCABC:", "OCB:", "OCDM:", "OCM:", "OCLP:")):
        return "oc_log"
    return "generic"


# ── OC log analyzer ────────────────────────────────────────────────────────────

def _analyze_oc_log(text: str) -> list[Finding]:
    lines = text.splitlines()
    findings: list[Finding] = []
    seen: set[str] = set()
    suppressed: set[str] = set()

    for pat in OC_PATTERNS:
        if pat.tag and pat.tag in suppressed:
            continue
        for i, line in enumerate(lines):
            if re.search(pat.regex, line, re.IGNORECASE):
                if pat.title in seen:
                    break
                seen.add(pat.title)
                findings.append(Finding(
                    severity=pat.severity,
                    category=pat.category,
                    title=pat.title,
                    explanation=pat.explanation,
                    fix_steps=list(pat.fix_steps),
                    context_lines=_extract_context(lines, i),
                    confidence=pat.confidence,
                ))
                for s in pat.suppresses:
                    suppressed.add(s)
                break

    return findings


# ── Kernel panic analyzer ──────────────────────────────────────────────────────

def _analyze_kernel_panic(text: str) -> list[Finding]:
    findings: list[Finding] = []

    # Extract panic reason string
    m = re.search(
        r'panic\(cpu \d+ caller 0x[0-9a-f]+\):\s*["\']?([^"\'\n]{3,200})["\']?',
        text, re.IGNORECASE
    )
    panic_reason = m.group(1).strip() if m else ""

    # Match against known panic reasons
    matched = False
    for keyword, template in PANIC_REASONS:
        if keyword.lower() in (panic_reason + text[:4000]).lower():
            f = Finding(
                severity=template.severity,
                category=template.category,
                title=template.title,
                explanation=template.explanation,
                fix_steps=list(template.fix_steps),
                context_lines=[f"  Panic reason: {panic_reason}"] if panic_reason else [],
                confidence=template.confidence,
            )
            findings.append(f)
            matched = True
            break

    if not matched and panic_reason:
        findings.append(Finding(
            severity="critical",
            category="unknown",
            title=f"Kernel panic: {panic_reason[:90]}",
            explanation=(
                "The kernel panicked with an unrecognized message. "
                "Check the 'Kernel Extensions in backtrace' section to identify the guilty kext."
            ),
            fix_steps=[
                "Find non-Apple kexts in the 'Kernel Extensions in backtrace' section below.",
                "Search the exact panic message on r/hackintosh or Dortania forums.",
                "Boot with -v (verbose) + -x (safe mode) to get more information.",
            ],
            context_lines=[f"  Panic reason: {panic_reason}"],
            confidence="possible",
        ))

    # Parse kext backtrace section
    kext_m = re.search(
        r"Kernel Extensions in backtrace:(.*?)(?:\n\n|\nDependency|\Z)",
        text, re.DOTALL
    )
    if kext_m:
        bundle_ids: list[str] = []
        for line in kext_m.group(1).strip().splitlines():
            bm = re.search(r"([\w.]+\.[\w.]+)\([\d.]+\)", line)
            if bm:
                bid = bm.group(1)
                if bid not in bundle_ids:
                    bundle_ids.append(bid)

        # Check top kexts for known Acidanthera hints
        for bid in bundle_ids[:3]:
            if bid in _ACIDANTHERA_HINTS:
                findings.append(Finding(
                    severity="warning",
                    category="kext",
                    title=f"Acidanthera kext in panic backtrace: {bid.split('.')[-1]}",
                    explanation=_ACIDANTHERA_HINTS[bid],
                    fix_steps=["See the kext's GitHub repo for config requirements."],
                    context_lines=[f"  Backtrace kext: {bid}"],
                    confidence="likely",
                ))
                break

        # Unknown third-party kext at top of backtrace
        top = bundle_ids[0] if bundle_ids else ""
        if top and not (top.startswith("com.apple") or top.startswith("com.acidanthera")):
            findings.append(Finding(
                severity="critical",
                category="kext",
                title=f"Third-party kext at top of panic backtrace: {top}",
                explanation=(
                    f"'{top}' is the first kext in the panic backtrace, "
                    "making it the most likely cause of the crash."
                ),
                fix_steps=[
                    f"Disable or remove {top} from your EFI and config.plist.",
                    "Redownload the latest release of this kext.",
                    "Verify it's compatible with your macOS version.",
                ],
                context_lines=[f"  Top backtrace kext: {top}"],
                confidence="likely",
            ))

    return findings


# ── Generic / fallback ─────────────────────────────────────────────────────────

def _analyze_generic(text: str) -> list[Finding]:
    return _analyze_oc_log(text)


# ── Hardware-aware enrichment ──────────────────────────────────────────────────

def _enrich(findings: list[Finding], profile) -> None:
    for f in findings:
        if f.category == "audio" and getattr(profile, "audio_codec", ""):
            codec = profile.audio_codec.upper()
            f.explanation += f" (Your codec: {codec}.)"
            f.fix_steps.insert(
                0,
                f"For {codec}: look up supported layout IDs at "
                "github.com/acidanthera/AppleALC/wiki/Supported-codecs"
            )
        if f.category == "gpu" and getattr(profile, "gpu_device_id", ""):
            f.explanation += f" (Your iGPU device ID: {profile.gpu_device_id}.)"
        if f.category == "cpu" and getattr(profile, "cpu_vendor", "") == "amd":
            if "CFG Lock" in f.title:
                f.fix_steps.append(
                    "Note: AMD CPUs don't have CFG Lock. "
                    "If you see this on AMD it may be a false positive from a different MSR."
                )
        if f.category == "usb" and getattr(profile, "platform", "") == "laptop":
            for step in f.fix_steps:
                if "USBToolBox" in step:
                    f.fix_steps.append(
                        "On laptops, use USB 2.0 ports during install — 3.0 ports "
                        "are frequently remapped and may not work before USBMap is loaded."
                    )
                    break


# ── Sort + dedup ───────────────────────────────────────────────────────────────

_SEV = {"critical": 0, "warning": 1, "info": 2}


def _sort(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (_SEV.get(f.severity, 9), f.category))


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze(text: str, profile=None) -> list[Finding]:
    """
    Analyze a log string. Auto-detects log type.
    Pass a HardwareProfile for hardware-specific suggestions.
    Returns findings sorted by severity.
    """
    log_type = _detect_log_type(text)

    if log_type == "kernel_panic":
        findings = _analyze_kernel_panic(text)
        # Also scan for OC patterns — panic files sometimes embed OC log output
        extra = _analyze_oc_log(text)
        existing = {f.title for f in findings}
        for f in extra:
            if f.title not in existing:
                findings.append(f)
    elif log_type == "oc_log":
        findings = _analyze_oc_log(text)
    else:
        findings = _analyze_generic(text)

    if not findings:
        findings = [Finding(
            severity="info",
            category="general",
            title="No known issues detected",
            explanation=(
                "No recognized error patterns were found in this log. "
                "The log may be clean, or the issue isn't in our database yet."
            ),
            fix_steps=[
                "If you're still having problems, post the full log on r/hackintosh.",
                "Enable verbose boot (-v boot-arg) and OC file logging for more detail.",
            ],
            confidence="possible",
        )]

    if profile is not None:
        _enrich(findings, profile)

    return _sort(findings)


def analyze_file(path: str | Path, profile=None) -> list[Finding]:
    """Read a file and return findings."""
    try:
        text = Path(path).read_text(errors="replace")
    except Exception as e:
        return [Finding(
            severity="critical",
            category="general",
            title="Could not read log file",
            explanation=str(e),
            fix_steps=["Check the file path and permissions and try again."],
        )]
    return analyze(text, profile)
