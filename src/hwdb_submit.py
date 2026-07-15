"""
Opt-in hardware log submission to github.com/riftaway7-code/hackmate-hwdb.

Consent is asked once, on first launch, with a real working "no" — declining
never blocks any feature of HackMate. Nothing here ever raises into the
build flow: a failed or declined submission is always silent to the user
mid-build, logged at most as a quiet info line.

What gets sent is exactly the hardware fields already visible on-screen
during a normal run (cpu, gpu, audio/wifi/ethernet chipsets, touchpad type,
nvme/thunderbolt presence) plus the build outcome — the same shape as
TEMPLATE.log in the hackmate-hwdb repo. No name, email, serial number, MAC
address, or file paths are included.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date

from hardware import HardwareProfile

# Holds no secret itself; the real GitHub token lives server-side in the
# relay (packaging/hwdb_relay/), never in this client.
RELAY_URL = "https://hackmate-hwdb-relay.riftaway7.workers.dev"

def _get_version() -> str:
    # Mirrors hackmate.py/hackmate_gui.py's _get_version() — .release_tag is
    # written at build time from the actual GitHub release tag. This used
    # to be a hardcoded "v2.0.0" literal, so every hwdb submission ever made
    # claimed "v2.0.0" regardless of what was actually running, making it
    # impossible to tell pre-fix from post-fix reports from the data alone.
    try:
        return (Path(__file__).parent / ".release_tag").read_text().strip() or "dev"
    except Exception:
        return "dev"

VERSION = _get_version()


def _real_home() -> Path:
    import os
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


_CONSENT_PATH = _real_home() / ".hackmate" / "hwdb_consent.json"


def consent_already_asked() -> bool:
    return _CONSENT_PATH.exists()


def has_consented() -> bool:
    try:
        return json.loads(_CONSENT_PATH.read_text()).get("consent", False)
    except Exception:
        return False


def set_consent(consent: bool) -> None:
    _CONSENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONSENT_PATH.write_text(json.dumps({"consent": consent}))


# --- folder resolution, mirrors github.com/riftaway7-code/hackmate-hwdb ---

_AMD_CODENAME_TO_FOLDER = {
    "Zen 5":  "amd-zen5",
    "Zen 4":  "amd-zen4",
    "Zen 3+": "amd-zen3-plus",
    "Zen 3":  "amd-zen3",
    "Zen 2":  "amd-zen2",
    "Zen+":   "amd-zen-plus",
}

_FEATURE_TO_FOLDER = {
    "full":             "full-build-logs",
    "skip_format":      "already-formatted-logs",
    "repair":           "repair-efi-logs",
    "no_usb":           "no-usb-logs",
    "efi_health_check": "efi-health-check-logs",
}


def gen_folder(profile: HardwareProfile) -> str:
    if profile.cpu_vendor == "amd":
        return _AMD_CODENAME_TO_FOLDER.get(profile.cpu_codename, "amd-zen")
    gen = profile.cpu_generation
    if 2 <= gen <= 15:
        return f"intel-gen{gen}"
    return "intel-gen2"  # unknown/unmapped gen — bucket with the floor rather than drop the report


def feature_folder(feature: str, dual_boot: str) -> str:
    if dual_boot:
        return "dual-boot-logs"
    return _FEATURE_TO_FOLDER.get(feature, "full-build-logs")


def _slug(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "unknown-device"


def build_log(
    profile: HardwareProfile,
    feature: str,
    macos_version: str,
    worked: str,          # "build completed" / "build failed" / "partial"
    issues: str,
    dual_boot: str = "",
    hackmate_version: str = VERSION,
) -> str:
    device = profile.smbios_model or f"{profile.cpu_codename or 'unknown'} {profile.platform or 'system'}"
    lines = [
        f"device: {device}",
        f"feature: {feature}" + (f" (dual boot: {dual_boot})" if dual_boot else ""),
        "submitted by: (auto-submitted, opt-in)",
        f"date: {date.today().isoformat()}",
        "",
        "--- hardware ---",
        f"cpu: {profile.cpu_name}",
        f"cpu_generation: {profile.cpu_generation}",
        f"cpu_codename: {profile.cpu_codename}",
        f"platform: {profile.platform}",
        "",
        f"igpu: {profile.gpu_name}",
        f"dgpu: {profile.dgpu_name or 'none'}" + (f" ({profile.dgpu_vendor})" if profile.dgpu_vendor else ""),
        "",
        f"audio_codec: {profile.audio_codec}",
        f"ethernet_chipset: {profile.ethernet_chipset}",
        f"wifi_chipset: {profile.wifi_chipset}",
        "",
        f"touchpad_type: {profile.touchpad_type if profile.has_touchpad else 'n/a'}",
        f"nvme: {'yes' if profile.nvme_present else 'no'}",
        f"thunderbolt: {'yes' if profile.has_thunderbolt else 'no'}",
        "",
        "--- result ---",
        f"hackmate_version: {hackmate_version}",
        f"macos_version: {macos_version}",
        f"worked: {worked}",
        f"issues: {issues or 'none'}",
        "notes: auto-submitted at build completion — confirms the EFI/USB "
        "was generated without error, does not confirm the machine actually "
        "booted macOS successfully (HackMate exits before that point).",
    ]
    return "\n".join(lines)


def submit_log(profile: HardwareProfile, feature: str, log_text: str, dual_boot: str = "") -> None:
    """Best-effort, silent. Never raises — a failed submission must never
    surface as an error in the build flow the user is actually watching."""
    if not RELAY_URL or not has_consented():
        return
    try:
        filename = f"{_slug(profile.smbios_model or profile.cpu_codename or 'device')}.log"
        payload = json.dumps({
            "feature_folder": feature_folder(feature, dual_boot),
            "gen_folder": gen_folder(profile),
            "filename": filename,
            "content": log_text,
        }).encode()
        req = urllib.request.Request(
            RELAY_URL, data=payload, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "HackMate/1.0"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
