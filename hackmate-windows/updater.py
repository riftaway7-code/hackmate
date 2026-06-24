"""
Auto-updater: checks GitHub for new commits and downloads updated files in-place.
"""

import urllib.request
import json
from pathlib import Path

REPO     = "riftaway7-code/hackmate"
BRANCH   = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/hackmate-windows"
API_URL  = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"

VERSION_FILE = Path(__file__).parent / ".version"

FILES = [
    "hackmate.py", "hardware.py", "kexts.py", "config_gen.py",
    "smbios.py", "recovery.py", "ssdt.py", "ai_fallback.py", "updater.py",
    "efi_check.py",
]


def _get_remote_sha() -> str | None:
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "HackMate/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())["sha"]
    except Exception:
        return None


def check_and_update(silent: bool = False) -> bool:
    remote_sha = _get_remote_sha()
    if not remote_sha:
        return False

    base_dir = Path(__file__).parent
    local_sha = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""
    missing = [f for f in FILES if not (base_dir / f).exists()]

    if remote_sha == local_sha and not missing:
        return False

    if not silent:
        print("HackMate update available — downloading...")

    updated = False
    for fname in FILES:
        url = f"{RAW_BASE}/{fname}"
        dest = base_dir / fname
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                new_content = r.read()
            if dest.exists() and dest.read_bytes() == new_content:
                continue
            dest.write_bytes(new_content)
            updated = True
        except Exception:
            pass

    VERSION_FILE.write_text(remote_sha)
    if updated and not silent:
        print("Updated. Restarting...")
    return updated or bool(missing)
