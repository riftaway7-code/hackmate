#!/usr/bin/env python3
# NOTE: this file must stay parseable and runnable on Python 3.8+.
# It is the first thing users run, often with the stock system python3
# (macOS ships 3.9), so it cannot use 3.10+ syntax such as `str | None`.
import subprocess
import sys
import os
from pathlib import Path
from typing import Optional

DEPENDENCIES = [
    ("textual", "textual"),
]

# hackmate/src uses PEP 604 unions (`X | None`), which need 3.10+ at runtime.
MIN_PYTHON = (3, 10)

PROJECT_DIR = Path(__file__).parent.resolve()
VENV_DIR = PROJECT_DIR / ".venv"


def ask(prompt: str) -> bool:
    while True:
        ans = input(prompt).strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def is_in_venv() -> bool:
    return hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)


def find_uv() -> Optional[str]:
    """Find uv executable."""
    from shutil import which
    return which("uv")


def _version_of(python: str) -> Optional[tuple]:
    """Return (major, minor) for a python executable, or None if it won't run."""
    try:
        out = subprocess.run(
            [python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        major, minor = out.stdout.split()
        return (int(major), int(minor))
    except ValueError:
        return None


def find_modern_python() -> Optional[str]:
    """
    Find an interpreter new enough to run HackMate.

    The interpreter running setup.py is often the stock system python3 (3.9 on
    macOS), which cannot run src/hackmate.py. Building the venv from it would
    produce a venv that crashes on first launch, so prefer a newer one.
    """
    from shutil import which

    if sys.version_info[:2] >= MIN_PYTHON:
        return sys.executable

    for minor in range(13, MIN_PYTHON[1] - 1, -1):
        candidate = which(f"python3.{minor}")
        if candidate and (_version_of(candidate) or (0, 0)) >= MIN_PYTHON:
            return candidate

    for name in ("python3", "python"):
        candidate = which(name)
        if candidate and (_version_of(candidate) or (0, 0)) >= MIN_PYTHON:
            return candidate

    return None


def print_python_too_old(found: str) -> None:
    want = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    have = f"{sys.version_info[0]}.{sys.version_info[1]}"
    print(f"ERROR: HackMate needs Python {want} or newer, but only {have} was found.")
    print(f"       (running as: {found})\n")
    if sys.platform == "darwin":
        print("  macOS ships Python 3.9. Install a newer one, then re-run this script:")
        print("    brew install python@3.12")
    elif sys.platform == "win32":
        print("  Install Python from https://python.org/downloads (check 'Add to PATH').")
    else:
        print("  Install a newer Python, e.g.:")
        print("    sudo apt install python3.12 python3.12-venv     # Debian/Ubuntu")
        print("    sudo dnf install python3.12                     # Fedora")
    print("\n  Or install 'uv' (picks its own Python automatically):")
    print("    curl -LsSf https://astral.sh/uv/install.sh | sh")


def create_venv_uv(uv: str) -> bool:
    """Create venv using uv, pinned to a version that can run HackMate."""
    print(f"Creating virtual environment with uv at {VENV_DIR}...")
    want = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    result = subprocess.run([uv, "venv", "--python", f">={want}", str(VENV_DIR)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        # Older uv builds don't understand a range specifier — retry without the pin.
        result = subprocess.run([uv, "venv", str(VENV_DIR)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False
    print("  OK")
    return True


def create_venv_stdlib(python: str) -> bool:
    """Create venv using stdlib, from an interpreter new enough to run HackMate."""
    print(f"Creating virtual environment at {VENV_DIR}...")
    print(f"  Using {python}")
    result = subprocess.run([python, "-m", "venv", str(VENV_DIR)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False
    print("  OK")
    return True


def get_venv_python() -> str:
    """Get path to venv python."""
    if sys.platform == "win32":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python3")


def get_venv_pip():
    """Get pip command for venv."""
    python = get_venv_python()
    return [python, "-m", "pip"]


def install_deps_uv(uv: str):
    """Install dependencies using uv pip."""
    failed = []
    for name, pkg in DEPENDENCIES:
        print(f"Installing {name}...")
        result = subprocess.run(
            [uv, "pip", "install", "--python", get_venv_python(), pkg],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ERROR: failed to install {name}")
            print(result.stderr.strip())
            failed.append(name)
        else:
            print("  OK")
    return failed


def install_deps_pip():
    """Install dependencies using pip."""
    failed = []
    pip_cmd = get_venv_pip()
    for name, pkg in DEPENDENCIES:
        print(f"Installing {name}...")
        result = subprocess.run(
            [*pip_cmd, "install", pkg],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ERROR: failed to install {name}")
            print(result.stderr.strip())
            failed.append(name)
        else:
            print("  OK")
    return failed


def print_instructions():
    """Print run instructions based on platform."""
    venv_python = get_venv_python()
    print("\nAll dependencies installed. You can now run HackMate:\n")
    if sys.platform == "win32":
        print(f"  {venv_python} src\\hackmate.py  (as Administrator)")
    else:
        print(f"  sudo {venv_python} src/hackmate.py")
    print()
    print("Or activate the venv first:")
    if sys.platform == "win32":
        print(f"  .venv\\Scripts\\activate")
        print(f"  python src\\hackmate.py  (as Administrator)")
    else:
        print(f"  source .venv/bin/activate")
        print(f"  sudo python3 src/hackmate.py")


def print_uv_instructions():
    """Print uv-specific run instructions."""
    venv_python = get_venv_python()
    print("\nAll dependencies installed. You can now run HackMate:\n")
    if sys.platform == "win32":
        print(f"  {venv_python} src\\hackmate.py  (as Administrator)")
    else:
        print(f"  sudo {venv_python} src/hackmate.py")
    print()
    print("  NOTE: Do not use 'sudo uv run' — sudo won't find uv in your PATH.")


def main():
    print("\n=== HackMate Setup ===\n")
    print("The following dependencies are required to run HackMate:\n")
    for name, _ in DEPENDENCIES:
        print(f"  - {name}")
    print()

    if not ask("Would you like to install them now? [y/n]: "):
        print()
        if not ask("Are you sure? HackMate will NOT work without these dependencies. Skip anyway? [y/n]: "):
            pass  # fall through to install
        else:
            print("\nSkipping install. Run setup.py again when you're ready.")
            sys.exit(0)

    print()

    uv = find_uv()

    # Create venv if not already in one
    if not is_in_venv():
        if uv and ask(f"Found 'uv' on PATH. Use uv for setup? [y/n]: "):
            if not create_venv_uv(uv):
                sys.exit(1)
            failed = install_deps_uv(uv)
            print()
            if failed:
                print(f"Failed to install: {', '.join(failed)}")
                sys.exit(1)
            print_uv_instructions()
        else:
            # Never build the venv from an interpreter too old to run HackMate —
            # the venv would inherit that version and crash on first launch.
            python = find_modern_python()
            if not python:
                print()
                print_python_too_old(sys.executable)
                sys.exit(1)
            if not create_venv_stdlib(python):
                sys.exit(1)
            failed = install_deps_pip()
            print()
            if failed:
                print(f"Failed to install: {', '.join(failed)}")
                sys.exit(1)
            print_instructions()
    else:
        # Already in venv — installing deps into a venv too old to run HackMate
        # would look like success right up until the app fails to start.
        if sys.version_info[:2] < MIN_PYTHON:
            print()
            print_python_too_old(sys.executable)
            print("\n  This venv is too old. Deactivate it, delete .venv, and re-run setup.py.")
            sys.exit(1)
        if uv:
            failed = install_deps_uv(uv)
        else:
            failed = install_deps_pip()
        print()
        if failed:
            print(f"Failed to install: {', '.join(failed)}")
            print("Try running: pip install " + " ".join(p for _, p in DEPENDENCIES))
            sys.exit(1)
        else:
            print("All dependencies installed.")


if __name__ == "__main__":
    main()
