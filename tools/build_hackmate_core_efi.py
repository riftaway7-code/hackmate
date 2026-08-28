import argparse
import plistlib
import shutil
from pathlib import Path


def driver(path, early=False):
    return {"Path": path, "Enabled": True, "Arguments": "", "Comment": "", "LoadEarly": early}


def tool(name, path, flavour="Auto", aux=False):
    return {
        "Name": name, "Path": path, "Enabled": True, "Arguments": "",
        "Comment": "", "Auxiliary": aux, "Flavour": flavour,
        "RealPath": False, "TextMode": False, "FullNvramAccess": False,
    }


def entry(name, path, flavour="Auto", args=""):
    return {
        "Name": name, "Path": path, "Enabled": True, "Arguments": args,
        "Comment": "", "Auxiliary": False, "Flavour": flavour,
        "TextMode": False,
    }


def patch_config(base):
    with open(base, "rb") as f:
        c = plistlib.load(f)

    boot = c["Misc"]["Boot"]
    boot.update({
        "PickerMode": "External",
        "PickerVariant": "HackMate\\Core",
        "PickerAttributes": 145,
        "ShowPicker": True,
        "Timeout": 0,
        "HideAuxiliary": False,
        "PollAppleHotKeys": True,
        "TakeoffDelay": 0,
        "PickerAudioAssist": False,
        "LauncherOption": "Disabled",
    })

    sec = c["Misc"]["Security"]
    sec.update({
        "ScanPolicy": 0,
        "SecureBootModel": "Disabled",
        "Vault": "Optional",
        "AllowSetDefault": True,
        "DmgLoading": "Any",
        "ExposeSensitiveData": 6,
        "BlacklistAppleUpdate": True,
        "EnablePassword": False,
    })

    dbg = c["Misc"]["Debug"]
    dbg.update({
        "Target": 67, "AppleDebug": True, "ApplePanic": True,
        "DisableWatchDog": True, "SysReport": False, "DisplayDelay": 0,
        "DisplayLevel": 2147483650,
    })

    c["Misc"]["Tools"] = [
        tool("UEFI Shell", "OpenShell.efi", "UEFIShell:Tool", aux=True),
        tool("Reset NVRAM", "CleanNvram.efi", "NVRAMReset:Reset", aux=True),
        tool("List Partitions", "ListPartitions.efi", "Tool", aux=True),
    ]
    c["Misc"]["Entries"] = [
        entry("macOS", "OpenShell.efi", "Apple:Auto", ""),
        entry("Safe Mode", "OpenShell.efi", "Apple:Auto", "-x"),
        entry("Recovery", "OpenShell.efi", "AppleRecv:Apple", "-r"),
        entry("Windows", "OpenShell.efi", "Windows:Auto", "-w"),
    ]

    uefi = c["UEFI"]
    uefi["Drivers"] = [
        driver("OpenRuntime.efi"),
        driver("OpenCanopy.efi"),
        driver("CrScreenshotDxe.efi"),
    ]
    uefi["APFS"]["MinDate"] = -1
    uefi["APFS"]["MinVersion"] = -1
    uefi["Output"].update({
        "Resolution": "1920x1080",
        "ProvideConsoleGop": True,
        "ClearScreenOnModeSwitch": False,
        "GopBurstMode": False,
        "UIScale": 1,
    })
    uefi["Input"].update({"KeySupport": True, "KeySupportMode": "Auto", "PointerSupport": False})
    uefi["ProtocolOverrides"]["AppleBootPolicy"] = True

    for section, keys in {
        "ACPI": ["Add", "Delete", "Patch"],
        "Kernel": ["Add", "Block", "Force", "Patch"],
    }.items():
        for k in keys:
            c[section][k] = []

    nv = c["NVRAM"]
    g_ui = "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14"
    g_boot = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
    nv.setdefault("Add", {}).setdefault(g_ui, {})
    nv["Add"][g_ui]["DefaultBackgroundColor"] = b"\x00\x00\x00\x00"
    nv["Add"].setdefault(g_boot, {})
    nv["Add"][g_boot]["boot-args"] = "-v keepsyms=1"
    nv["Add"][g_boot]["prev-lang:kbd"] = b"en-US:0"

    pi = c["PlatformInfo"]
    pi["Automatic"] = True
    pi["UpdateSMBIOS"] = True
    pi["UpdateSMBIOSMode"] = "Create"
    pi["Generic"]["SystemProductName"] = "iMacPro1,1"
    pi["Generic"]["SpoofVendor"] = True

    return c


def assemble(oc_root, theme_root, out, cfg):
    esp = Path(out)
    if esp.exists():
        shutil.rmtree(esp)
    x64 = Path(oc_root) / "X64" / "EFI"

    (esp / "EFI" / "BOOT").mkdir(parents=True)
    shutil.copy(x64 / "BOOT" / "BOOTx64.efi", esp / "EFI" / "BOOT" / "BOOTx64.efi")

    oc = esp / "EFI" / "OC"
    (oc / "Drivers").mkdir(parents=True)
    (oc / "Tools").mkdir()
    (oc / "ACPI").mkdir()
    (oc / "Kexts").mkdir()
    shutil.copy(x64 / "OC" / "OpenCore.efi", oc / "OpenCore.efi")
    for d in ("OpenRuntime.efi", "OpenCanopy.efi", "CrScreenshotDxe.efi"):
        shutil.copy(x64 / "OC" / "Drivers" / d, oc / "Drivers" / d)
    for t in ("OpenShell.efi", "CleanNvram.efi", "ListPartitions.efi"):
        shutil.copy(x64 / "OC" / "Tools" / t, oc / "Tools" / t)

    shutil.copytree(Path(theme_root), oc / "Resources")

    with open(oc / "config.plist", "wb") as f:
        plistlib.dump(cfg, f, sort_keys=False)

    return esp, oc / "config.plist"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oc", default="C:/Users/RAAHIM~1/AppData/Local/Temp/hmc/oc")
    ap.add_argument("--theme", default=str(Path(__file__).resolve().parents[1] / "src/assets/canopy/Resources"))
    ap.add_argument("--out", default="C:/Users/RAAHIM~1/AppData/Local/Temp/hmc/esp")
    args = ap.parse_args()

    sample = Path(args.oc) / "Docs" / "Sample.plist"
    cfg = patch_config(sample)
    esp, cfg_path = assemble(args.oc, args.theme, args.out, cfg)
    print(f"ESP assembled at {esp}")
    print(f"config.plist at {cfg_path}")
    total = sum(1 for _ in esp.rglob("*") if _.is_file())
    print(f"{total} files")


if __name__ == "__main__":
    main()
