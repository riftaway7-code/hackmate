"""
Auto-updater for HackMate.
Checks GitHub for new commits and downloads updated .py files in-place.
"""

import os
import sys
import urllib.request
import json
from pathlib import Path

REPO       = "riftaway7-code/hackmate"
BRANCH     = "main"
RAW_BASE   = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/src"
API_URL    = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
VERSION_FILE = Path(__file__).parent / ".version"

FILES = [
    "hackmate.py",
    "hardware.py",
    "kexts.py",
    "config_gen.py",
    "smbios.py",
    "recovery.py",
    "ssdt.py",
    "updater.py",
    "efi_check.py",
    "compat.py",
]


def _get_remote_sha() -> str | None:
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "HackMate/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())["sha"]
    except Exception:
        return None


def _get_local_sha() -> str | None:
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return None


def _download_file(filename: str, sha: str) -> bool:
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/src/{filename}"
    dest = Path(__file__).parent / filename
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            dest.write_bytes(r.read())
        return True
    except Exception:
        return False


def check_and_update(silent: bool = False) -> bool:
    if not silent:
        print("Checking for updates...", end=" ", flush=True)

    remote_sha = _get_remote_sha()
    if not remote_sha:
        if not silent:
            print("(offline, skipping)")
        return False

    base_dir = Path(__file__).parent
    local_sha = _get_local_sha()
    missing = [f for f in FILES if not (base_dir / f).exists()]

    if remote_sha == local_sha and not missing:
        if not silent:
            print("up to date.")
        return False

    if not silent:
        short = remote_sha[:7]
        print(f"update found ({short}), downloading...")

    failed = []
    for filename in FILES:
        ok = _download_file(filename, remote_sha)
        if not silent:
            status = "✓" if ok else "✗"
            print(f"  {status} {filename}")
        if not ok:
            failed.append(filename)

    VERSION_FILE.write_text(remote_sha)

    if failed and not silent:
        print(f"  Warning: {len(failed)} file(s) failed to update: {', '.join(failed)}")

    if not silent:
        print("Update complete — restarting...\n")

    return True
