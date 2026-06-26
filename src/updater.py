"""
Auto-updater for HackMate.
Checks GitHub for new commits, shows changelog, asks user before updating.
"""

import os
import sys
import urllib.request
import json
from pathlib import Path

REPO         = "riftaway7-code/hackmate"
BRANCH       = "main"
API_URL      = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
COMPARE_URL  = f"https://api.github.com/repos/{REPO}/compare/{{base}}...{{head}}"
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
    # Legacy flat names kept for users who have not yet migrated to package layout
]


def _get(url: str) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _get_remote_sha() -> str | None:
    data = _get(API_URL)
    return data["sha"] if data else None


def _get_local_sha() -> str | None:
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return None


def _get_changelog(base_sha: str, head_sha: str) -> list[str]:
    """Return list of commit messages between base and head."""
    if not base_sha:
        return []
    data = _get(COMPARE_URL.format(base=base_sha, head=head_sha))
    if not data or "commits" not in data:
        return []
    messages = []
    for commit in reversed(data["commits"]):
        msg = commit.get("commit", {}).get("message", "").splitlines()[0].strip()
        if msg:
            messages.append(msg)
    return messages


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
    print("Checking for updates...", end=" ", flush=True)

    remote_sha = _get_remote_sha()
    if not remote_sha:
        print("(offline, skipping)")
        return False

    local_sha  = _get_local_sha()
    base_dir   = Path(__file__).parent
    missing    = [f for f in FILES if not (base_dir / f).exists()]

    if remote_sha == local_sha and not missing:
        print("up to date.")
        return False

    short = remote_sha[:7]
    print(f"new version available ({short})\n")

    # Show changelog
    changelog = _get_changelog(local_sha, remote_sha) if local_sha else []
    if changelog:
        print("  What's new:")
        for msg in changelog:
            print(f"    • {msg}")
    else:
        print("  (changelog unavailable)")
    print()

    # Ask user
    try:
        ans = input("  Update now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Skipping update.")
        return False

    if ans in ("n", "no"):
        print("  Skipping update.\n")
        return False

    print()
    failed = []
    for filename in FILES:
        ok = _download_file(filename, remote_sha)
        print(f"  {'✓' if ok else '✗'} {filename}")
        if not ok:
            failed.append(filename)

    VERSION_FILE.write_text(remote_sha)

    if failed:
        print(f"\n  Warning: {len(failed)} file(s) failed: {', '.join(failed)}")

    print("\n  Update complete — restarting...\n")
    return True
