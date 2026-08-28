import shutil
from pathlib import Path

THEME = "HackMate\\Core"
RESOURCES = Path(__file__).resolve().parent / "assets" / "canopy" / "Resources"
EXTRA_DRIVERS = ["OpenCanopy.efi"]

_POINTER = 0x0010
_FLAVOUR = 0x0080
_VOLUME_ICON = 0x0001
PICKER_ATTRIBUTES = _VOLUME_ICON | _POINTER | _FLAVOUR


def available() -> bool:
    return (RESOURCES / "Image" / "HackMate" / "Core" / "Background.icns").is_file()


def apply_to_config(config: dict) -> None:
    boot = config.setdefault("Misc", {}).setdefault("Boot", {})
    boot["PickerMode"] = "External"
    boot["PickerVariant"] = THEME
    boot["PickerAttributes"] = int(boot.get("PickerAttributes", 0)) | PICKER_ATTRIBUTES
    boot["PickerAudioAssist"] = bool(boot.get("PickerAudioAssist", False))

    uefi = config.setdefault("UEFI", {})
    drivers = uefi.setdefault("Drivers", [])
    present = {d.get("Path") for d in drivers if isinstance(d, dict)}
    for name in EXTRA_DRIVERS:
        if name not in present:
            drivers.append({
                "Arguments": "", "Comment": "HackMate-Core graphical picker",
                "Enabled": True, "LoadEarly": False, "Path": name,
            })

    out = uefi.setdefault("Output", {})
    out["ProvideConsoleGop"] = True
    if out.get("Resolution", "Max") in ("", "Auto"):
        out["Resolution"] = "Max"


def install_resources(oc_dir, oc_release_root, log=None) -> list[str]:
    if log is None:
        def log(msg, level="info"):
            print(msg)

    oc_dir = Path(oc_dir)
    installed = []

    dst_res = oc_dir / "Resources"
    if dst_res.exists():
        shutil.rmtree(dst_res)
    shutil.copytree(RESOURCES, dst_res)
    installed.append("Resources/")
    log("  HackMate-Core: Resources/ installed", "ok")

    driver_dir = oc_dir / "Drivers"
    driver_dir.mkdir(parents=True, exist_ok=True)
    root = Path(oc_release_root)
    for name in EXTRA_DRIVERS:
        found = list(root.rglob(name))
        if found:
            shutil.copy(str(found[0]), str(driver_dir / name))
            installed.append(name)
            log(f"  HackMate-Core: driver {name}", "ok")
        else:
            log(f"  HackMate-Core: {name} not found in OpenCore release", "warn")
    return installed
