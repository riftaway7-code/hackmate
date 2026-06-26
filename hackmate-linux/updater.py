"""
Migration stub: moves hackmate-linux/ users to src/ automatically.
"""

import sys
import json
import urllib.request
from pathlib import Path

REPO    = "riftaway7-code/hackmate"
BRANCH  = "main"
API_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"

FILES = [
    "hackmate.py", "compat.py", "updater.py",
    "hardware/__init__.py", "hardware/detect.py", "hardware/smbios.py",
    "efi/__init__.py", "efi/config_gen.py", "efi/kexts.py",
    "efi/ssdt.py", "efi/efi_check.py",
    "recovery/__init__.py", "recovery/recovery.py",
]


def check_and_update(silent: bool = False) -> bool:
    src_dir = Path(__file__).parent.parent / "src"
    src_dir.mkdir(exist_ok=True)

    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "HackMate/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            sha = json.loads(r.read())["sha"]
    except Exception:
        return False

    version_file = src_dir / ".version"
    try:
        local_sha = version_file.read_text().strip()
    except Exception:
        local_sha = ""

    if sha == local_sha and all((src_dir / f).exists() for f in FILES):
        return False

    print("HackMate has moved to src/ — migrating your installation...")
    for filename in FILES:
        url = f"https://raw.githubusercontent.com/{REPO}/{sha}/src/{filename}"
        try:
            dest = src_dir / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                dest.write_bytes(r.read())
            print(f"  ✓ {filename}")
        except Exception:
            print(f"  ✗ {filename}")

    version_file.write_text(sha)
    print("Migration complete.\n")
    return True
