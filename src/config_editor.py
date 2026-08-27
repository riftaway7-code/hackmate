"""
Config.plist editor logic — parse, read, write OpenCore config.plist entries.
"""

import plistlib
import re
from pathlib import Path
from typing import Any

def parse_boot_args(args_str: str) -> dict[str, str | bool]:
    result: dict[str, str | bool] = {}
    for token in args_str.split():
        if "=" in token:
            key, val = token.split("=", 1)
            result[key] = val
        else:
            result[token] = True
    return result

def serialize_boot_args(args: dict[str, str | bool]) -> str:
    parts = []
    for key, val in args.items():
        if val is True:
            parts.append(key)
        elif val is not False and val != "":
            parts.append(f"{key}={val}")
    return " ".join(parts)

# The long NVRAM UUID key
_NVRAM_KEY = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
_NVRAM_UI  = "4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14"

def _resolve_path(cfg: dict, path: str) -> tuple[dict, str]:
    """Walk dot-separated path, return (parent_dict, final_key)."""
    parts = path.split(".")
    node = cfg
    for part in parts[:-1]:
        if part not in node:
            raise KeyError(f"Key '{part}' not found")
        node = node[part]
    return node, parts[-1]

def get_value(cfg: dict, path: str) -> Any:
    node, key = _resolve_path(cfg, path)
    return node[key]

def set_value(cfg: dict, path: str, value: Any) -> None:
    node, key = _resolve_path(cfg, path)
    node[key] = value

def get_boot_args(cfg: dict) -> dict[str, str | bool]:
    try:
        raw = cfg["NVRAM"]["Add"][_NVRAM_KEY]["boot-args"]
        return parse_boot_args(raw)
    except (KeyError, TypeError):
        return {}

def set_boot_args(cfg: dict, args: dict[str, str | bool]) -> None:
    cfg.setdefault("NVRAM", {}).setdefault("Add", {}).setdefault(_NVRAM_KEY, {})
    cfg["NVRAM"]["Add"][_NVRAM_KEY]["boot-args"] = serialize_boot_args(args)

def get_sip_enabled(cfg: dict) -> bool:
    """SIP enabled = csr-active-config is all zeros."""
    try:
        val = cfg["NVRAM"]["Add"][_NVRAM_KEY]["csr-active-config"]
        return all(b == 0 for b in val)
    except (KeyError, TypeError):
        return True

def set_sip(cfg: dict, enabled: bool) -> None:
    cfg.setdefault("NVRAM", {}).setdefault("Add", {}).setdefault(_NVRAM_KEY, {})
    cfg["NVRAM"]["Add"][_NVRAM_KEY]["csr-active-config"] = (
        bytes(4) if enabled else bytes([0x03, 0x00, 0x00, 0x00])
    )

def get_hide_auxiliary(cfg: dict) -> bool:
    try:
        return cfg["Misc"]["Boot"]["HideAuxiliary"]
    except (KeyError, TypeError):
        return True

def set_hide_auxiliary(cfg: dict, val: bool) -> None:
    cfg.setdefault("Misc", {}).setdefault("Boot", {})["HideAuxiliary"] = val

def get_timeout(cfg: dict) -> int:
    try:
        return int(cfg["Misc"]["Boot"]["Timeout"])
    except (KeyError, TypeError, ValueError):
        return 5

def set_timeout(cfg: dict, val: int) -> None:
    cfg.setdefault("Misc", {}).setdefault("Boot", {})["Timeout"] = val

def get_oc_logging(cfg: dict) -> bool:
    """OC file logging = Target 67."""
    try:
        return int(cfg["Misc"]["Debug"]["Target"]) > 0
    except (KeyError, TypeError, ValueError):
        return False

def set_oc_logging(cfg: dict, enabled: bool) -> None:
    cfg.setdefault("Misc", {}).setdefault("Debug", {})
    cfg["Misc"]["Debug"]["Target"] = 67 if enabled else 0
    cfg["Misc"]["Debug"]["AppleDebug"] = enabled
    cfg["Misc"]["Debug"]["ApplePanic"] = enabled
    cfg["Misc"]["Debug"]["DisableWatchDog"] = enabled

def get_secure_boot_model(cfg: dict) -> str:
    try:
        return cfg["Misc"]["Security"]["SecureBootModel"]
    except (KeyError, TypeError):
        return "Disabled"

def set_secure_boot_model(cfg: dict, val: str) -> None:
    cfg.setdefault("Misc", {}).setdefault("Security", {})["SecureBootModel"] = val

def get_smbios(cfg: dict) -> str:
    try:
        return cfg["PlatformInfo"]["Generic"]["SystemProductName"]
    except (KeyError, TypeError):
        return ""

def set_smbios(cfg: dict, val: str) -> None:
    cfg.setdefault("PlatformInfo", {}).setdefault("Generic", {})["SystemProductName"] = val

_IGPU_PATH = "PciRoot(0x0)/Pci(0x2,0x0)"

# device_id (lowercase) → [(platform_id_hex, label), ...]
IGPU_FRAMEBUFFERS: dict[str, list[tuple[str, str]]] = {
    # Sandy Bridge
    "0116": [("00000100", "HD 3000 — laptop")],
    "0126": [("00000100", "HD 3000 — laptop")],
    # Ivy Bridge
    "0166": [("03006601", "HD 4000 — laptop (recommended)"), ("04006601", "HD 4000 — laptop 13\"")],
    "0162": [("0a006601", "HD 4000 — desktop"), ("07006201", "HD 4000 — headless")],
    # Haswell
    "0416": [("0600260a", "HD 4600 — laptop (recommended)")],
    "0412": [("0300220d", "HD 4600 — desktop")],
    "0d26": [("0500260a", "Iris Pro 5200 — laptop")],
    # Broadwell
    "1616": [("06002616", "HD 5500 — laptop (recommended)")],
    "1626": [("06002616", "HD 6000 — laptop (recommended)")],
    # Skylake
    "1916": [("00001619", "HD 520 — laptop (recommended)")],
    "191b": [("00001619", "HD 530 — laptop (recommended)")],
    "1912": [("00001219", "HD 530 — desktop"), ("01001219", "HD 530 — headless")],
    "1926": [("00001619", "Iris 540/550 — laptop (recommended)")],
    # Kaby Lake
    "5916": [("00001b59", "HD 620 — laptop (recommended)"), ("00001659", "HD 620 — laptop alt")],
    "591b": [("00001b59", "HD 630 — laptop (recommended)")],
    "5912": [("00001259", "HD 630 — desktop")],
    # Kaby Lake-R
    "5917": [("0000c087", "UHD 620 — laptop (recommended)")],
    # Whiskey Lake / Coffee Lake-R
    "3ea0": [("00009b3e", "UHD 620 — laptop (recommended)")],
    "3ea9": [("00009b3e", "UHD 620 — laptop (recommended)")],
    # Coffee Lake
    "3e92": [("07009b3e", "UHD 630 — desktop (recommended)")],
    "3e91": [("07009b3e", "UHD 630 — desktop")],
    "3e98": [("07009b3e", "UHD 630 — desktop"), ("00009b3e", "UHD 630 — laptop")],
    # Comet Lake
    "9bc4": [("0900a53e", "UHD 630 — laptop (recommended)")],
    "9bca": [("00009b3e", "UHD 620 — laptop (recommended)")],
    "9bc8": [("07009b3e", "UHD 630 — desktop")],
    # Ice Lake
    "8a52": [("0000528a", "Iris Plus — laptop (recommended)")],
    "8a51": [("0000528a", "Iris Plus — laptop")],
}

def suggest_framebuffers(gpu_device_id: str) -> list[tuple[str, str]]:
    """Return list of (hex, label) suggestions for a GPU device ID."""
    return IGPU_FRAMEBUFFERS.get(gpu_device_id.lower(), [])

def get_igpu_platform_id(cfg: dict) -> str:
    try:
        props = cfg["DeviceProperties"]["Add"][_IGPU_PATH]
        val = props.get("AAPL,ig-platform-id", props.get("AAPL,snb-platform-id"))
        return val.hex()
    except (KeyError, TypeError, AttributeError):
        return ""

def set_igpu_platform_id(cfg: dict, hex_str: str) -> None:
    if not hex_str:
        return
    cfg.setdefault("DeviceProperties", {}).setdefault("Add", {}).setdefault(_IGPU_PATH, {})
    props = cfg["DeviceProperties"]["Add"][_IGPU_PATH]
    key = (
        "AAPL,snb-platform-id"
        if "AAPL,snb-platform-id" in props and "AAPL,ig-platform-id" not in props
        else "AAPL,ig-platform-id"
    )
    props[key] = bytes.fromhex(hex_str)

# AppleALC supported layouts per codec — most common/reliable ones only
AUDIO_LAYOUTS: dict[str, list[tuple[int, str]]] = {
    "ALC256":  [(21, "most laptops"), (11, "alt"), (13, "alt")],
    "ALC257":  [(21, "most laptops"), (11, "alt"), (99, "alt")],
    "ALC255":  [(71, "most laptops"), (53, "alt"), (96, "alt")],
    "ALC269":  [(11, "most laptops"), (21, "alt"), (29, "ThinkPad"), (76, "Dell"), (88, "HP")],
    "ALC295":  [(28, "most laptops"), (77, "alt"), (88, "alt")],
    "ALC298":  [(47, "most laptops"), (72, "alt"), (28, "ThinkPad")],
    "ALC285":  [(21, "most laptops"), (61, "alt"), (71, "alt")],
    "ALC294":  [(21, "most laptops"), (97, "alt")],
    "ALC236":  [(14, "most laptops"), (36, "alt"), (100, "alt")],
    "ALC282":  [(25, "most laptops"), (27, "alt")],
    "ALC283":  [(66, "most laptops"), (13, "alt")],
    "ALC289":  [(87, "most laptops"), (93, "alt")],
    "ALC280":  [(3, "most laptops"), (5, "alt"), (28, "alt")],
    "ALC292":  [(28, "most laptops"), (12, "alt"), (15, "alt")],
    "ALC293":  [(28, "most laptops"), (44, "alt"), (3, "alt")],
    "ALC1220": [(7, "most desktops"), (11, "alt"), (16, "Gigabyte")],
    "ALC1150": [(1, "most desktops"), (7, "alt"), (11, "alt")],
    "ALC700":  [(33, "most desktops"), (35, "alt"), (66, "alt")],
    "ALC887":  [(7, "most desktops"), (11, "alt"), (17, "alt")],
    "ALC892":  [(7, "most desktops"), (12, "alt"), (15, "alt")],
    "ALC897":  [(11, "most desktops"), (66, "alt")],
}

def suggest_audio_layouts(codec: str) -> list[tuple[int, str]]:
    """Return list of (layout_id, description) for the given audio codec."""
    codec = codec.upper()
    for key, layouts in AUDIO_LAYOUTS.items():
        if key in codec:
            return layouts
    return []

_DGPU_PATH = "PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)"

def get_dgpu_disabled(cfg: dict) -> bool:
    try:
        dp = cfg["DeviceProperties"]["Add"]
        if dp.get(_IGPU_PATH, {}).get("disable-external-gpu") == bytes([1, 0, 0, 0]):
            return True
        return dp.get(_DGPU_PATH, {}).get("disable-gpu") == bytes([1, 0, 0, 0])
    except (KeyError, TypeError):
        return False

def set_dgpu_disabled(cfg: dict, disabled: bool) -> None:
    dp = cfg.setdefault("DeviceProperties", {}).setdefault("Add", {})
    if disabled:
        # WhateverGreen can disable every external GPU from the stable IGPU
        # path. This avoids guessing a PEG/dGPU PCI path that varies by board.
        dp.setdefault(_IGPU_PATH, {})["disable-external-gpu"] = bytes([1, 0, 0, 0])
    else:
        if _IGPU_PATH in dp:
            dp[_IGPU_PATH].pop("disable-external-gpu", None)
            if not dp[_IGPU_PATH]:
                del dp[_IGPU_PATH]
        # Clean up configs created by older HackMate versions, which guessed a
        # fixed dGPU path and wrote disable-gpu there.
        if _DGPU_PATH in dp:
            dp[_DGPU_PATH].pop("disable-gpu", None)
            dp[_DGPU_PATH].pop("name", None)
            if not dp[_DGPU_PATH]:
                del dp[_DGPU_PATH]

def get_kext_entries(cfg: dict) -> list[tuple[str, bool]]:
    kexts = cfg.get("Kernel", {}).get("Add", [])
    return [
        (k.get("BundlePath", "").removesuffix(".kext"), bool(k.get("Enabled", True)))
        for k in kexts
    ]

def set_kext_enabled(cfg: dict, name: str, enabled: bool) -> bool:
    kexts = cfg.get("Kernel", {}).get("Add", [])
    for k in kexts:
        if k.get("BundlePath", "").removesuffix(".kext") == name:
            k["Enabled"] = enabled
            return True
    return False

def get_acpi_entries(cfg: dict) -> list[tuple[str, bool]]:
    entries = cfg.get("ACPI", {}).get("Add", [])
    return [
        (e.get("Path", "").removesuffix(".aml"), bool(e.get("Enabled", True)))
        for e in entries
    ]

def set_acpi_entry_enabled(cfg: dict, name: str, enabled: bool) -> bool:
    entries = cfg.get("ACPI", {}).get("Add", [])
    for e in entries:
        if e.get("Path", "").removesuffix(".aml") == name:
            e["Enabled"] = enabled
            return True
    return False

def get_serial_info(cfg: dict) -> dict[str, str]:
    generic = cfg.get("PlatformInfo", {}).get("Generic", {})
    rom = generic.get("ROM", b"")
    return {
        "serial": generic.get("SystemSerialNumber", ""),
        "mlb": generic.get("MLB", ""),
        "uuid": generic.get("SystemUUID", ""),
        "rom": rom.hex() if isinstance(rom, (bytes, bytearray)) else "",
    }

def set_serial_info(
    cfg: dict,
    serial: str | None = None,
    mlb: str | None = None,
    uuid: str | None = None,
    rom: str | None = None,
) -> None:
    generic = cfg.setdefault("PlatformInfo", {}).setdefault("Generic", {})
    if serial is not None:
        generic["SystemSerialNumber"] = serial
    if mlb is not None:
        generic["MLB"] = mlb
    if uuid is not None:
        generic["SystemUUID"] = uuid
    if rom is not None:
        generic["ROM"] = bytes.fromhex(rom.replace(":", "").replace(" ", ""))

BOOT_ARG_PRESETS: dict[str, dict[str, str | bool]] = {
    "Verbose":       {"-v": True, "keepsyms": "1", "debug": "0x100"},
    "Disable Nvidia":{"nv_disable": "1"},
    "Safe mode":     {"-x": True},
    "No sleep":      {"darkwake": "0"},
    "USB reset":     {"uia_exclude": ""},
}

def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        return plistlib.load(f)

def save_config(path: Path, cfg: dict) -> None:
    with open(path, "wb") as f:
        plistlib.dump(cfg, f)

def find_configs() -> list[Path]:
    """Find config.plist files on mounted volumes."""
    candidates = []

    import platform
    system = platform.system()

    if system == "Linux":
        search_roots = (
            [Path("/mnt")] +                            # direct mount (sudo mount /dev/sdX /mnt)
            list(Path("/mnt").glob("*")) +              # named mounts under /mnt
            list(Path("/run/media").glob("*/*")) +      # udisks auto-mount
            list(Path("/media").glob("*/*"))            # older udisks
        )
    elif system == "Darwin":
        search_roots = list(Path("/Volumes").iterdir())
    else:
        # Windows: check drive letters E–Z
        search_roots = [Path(f"{c}:\\") for c in "EFGHIJKLMNOPQRSTUVWXYZ"
                        if Path(f"{c}:\\").exists()]

    for root in search_roots:
        cfg = root / "EFI" / "OC" / "config.plist"
        if cfg.exists():
            candidates.append(cfg)

    return candidates

def coerce_value(raw: str, type_hint: str) -> Any:
    if type_hint == "bool":
        return raw.lower() in ("true", "yes", "1", "on")
    if type_hint == "int":
        return int(raw)
    if type_hint == "data":
        return bytes.fromhex(raw.replace(" ", ""))
    return raw  # string
