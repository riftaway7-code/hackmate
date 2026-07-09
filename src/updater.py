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

# Every module hackmate.py can import. A file missing from this list is never
# downloaded, so shipping a new module without adding it here leaves anyone who
# auto-updates with an ImportError on launch.
FILES = [
    "hackmate.py",
    "hackmate_gui.py",
    "hardware.py",
    "kexts.py",
    "config_gen.py",
    "smbios.py",
    "recovery.py",
    "ssdt.py",
    "updater.py",
    "efi_check.py",
    "efi_health.py",
    "efi_doctor.py",
    "compat.py",
    "oc_log.py",
    "config_editor.py",
    "log_checker.py",
    "dualboot.py",
    "partutil.py",
    "project_stats.py",
]


def _get(url: str) -> dict | list | None:
    import ssl, urllib.error
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                return json.loads(r.read())
        except (ssl.SSLError, urllib.error.URLError):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                return json.loads(r.read())
    except Exception:
        return None


def _get_remote_sha() -> str | None:
    data = _get(API_URL)
    return data["sha"] if data else None


def _get_local_sha() -> str | None:
    if _is_frozen():
        # When packaged as EXE, .version is bundled into sys._MEIPASS at build time
        try:
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            return (meipass / ".version").read_text().strip()
        except Exception:
            return None
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
    import ssl, urllib.error
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/src/{filename}"
    dest = Path(__file__).parent / filename
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                dest.write_bytes(r.read())
        except (ssl.SSLError, urllib.error.URLError):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                dest.write_bytes(r.read())
        return True
    except Exception:
        return False


def _ping_launch() -> None:
    """Silent launch counter — increments on every startup."""
    try:
        url = "https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=riftaway7-code-hackmate-launch&count_bg=%2300ff88&title_bg=%23000&title=launches&edge_flat=true"
        urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"}), timeout=3)
    except Exception:
        pass


def _is_frozen() -> bool:
    """True when running as a PyInstaller-bundled EXE."""
    return getattr(sys, "frozen", False)


def _get_latest_exe_url() -> str | None:
    """Return the direct download URL for the latest HackMate.exe release asset."""
    data = _get(f"https://api.github.com/repos/{REPO}/releases/latest")
    if not data:
        return None
    for asset in data.get("assets", []):
        if asset["name"].endswith(".exe"):
            return asset["browser_download_url"]
    return None


def check_update_silent() -> tuple[bool, str, list[str]]:
    """Check for updates without any prompts. Returns (has_update, remote_sha, changelog)."""
    remote_sha = _get_remote_sha()
    if not remote_sha:
        return False, "", []
    local_sha = _get_local_sha()
    if remote_sha == local_sha:
        return False, remote_sha, []
    changelog = _get_changelog(local_sha, remote_sha) if local_sha else []
    return True, remote_sha, changelog


def check_and_update(silent: bool = False) -> bool:
    _ping_launch()
    print("Checking for updates...", end=" ", flush=True)

    remote_sha = _get_remote_sha()
    if not remote_sha:
        print("(offline, skipping)")
        return False

    local_sha = _get_local_sha()
    base_dir  = Path(__file__).parent

    # When running as a frozen EXE, we can't update .py files —
    # the bundle is read-only. Instead, point the user to the new release.
    if _is_frozen():
        if remote_sha == local_sha:
            print("up to date.")
            return False

        short     = remote_sha[:7]
        changelog = _get_changelog(local_sha, remote_sha) if local_sha else []
        exe_url   = _get_latest_exe_url()

        print(f"new version available ({short})\n")
        if changelog:
            print("  What's new:")
            for msg in changelog:
                print(f"    • {msg}")
        print()
        print("  To update, download the new HackMate.exe from:")
        print(f"  https://github.com/{REPO}/releases/latest")
        if exe_url:
            print(f"  Direct link: {exe_url}")
        print()
        try:
            input("  Press Enter to continue with the current version...")
        except (EOFError, KeyboardInterrupt):
            pass
        return False

    # Running from source — update .py files as normal
    missing = [f for f in FILES if not (base_dir / f).exists()]

    if remote_sha == local_sha:
        if not missing:
            print("up to date.")
            return False
        # Already on the right commit but some modules never landed — an older
        # updater didn't know about them. Repair silently; asking here would let
        # the user decline into an app that cannot import its own modules.
        print(f"repairing {len(missing)} missing file(s)...")
        failed = [f for f in missing if not _download_file(f, remote_sha)]
        for f in missing:
            print(f"  {'✗' if f in failed else '✓'} {f}")
        if failed:
            print(f"\n  Warning: could not fetch {', '.join(failed)}")
            return False
        print("\n  Repair complete — restarting...\n")
        return True

    short = remote_sha[:7]
    print(f"new version available ({short})\n")

    changelog = _get_changelog(local_sha, remote_sha) if local_sha else []
    if changelog:
        print("  What's new:")
        for msg in changelog:
            print(f"    • {msg}")
    else:
        print("  (changelog unavailable)")
    print()

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

    if not failed:
        VERSION_FILE.write_text(remote_sha)
    else:
        print(f"\n  Warning: {len(failed)} file(s) failed: {', '.join(failed)}")

    print("\n  Update complete — restarting...\n")
    return True
