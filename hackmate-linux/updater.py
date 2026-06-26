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
    "hackmate.py", "hardware.py", "kexts.py", "config_gen.py",
    "smbios.py", "recovery.py", "ssdt.py", "updater.py",
    "efi_check.py", "compat.py",
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
            req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                (src_dir / filename).write_bytes(r.read())
            print(f"  ✓ {filename}")
        except Exception:
            print(f"  ✗ {filename}")

    version_file.write_text(sha)
    print("Migration complete.\n")
    return True
