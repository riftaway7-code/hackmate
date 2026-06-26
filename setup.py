#!/usr/bin/env python3
import subprocess
import sys
import os
from pathlib import Path

DEPENDENCIES = [
    ("textual", "textual"),
]

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


def find_uv() -> str | None:
    """Find uv executable."""
    from shutil import which
    return which("uv")


def create_venv_uv(uv: str) -> bool:
    """Create venv using uv."""
    print(f"Creating virtual environment with uv at {VENV_DIR}...")
    result = subprocess.run([uv, "venv", str(VENV_DIR)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False
    print("  OK")
    return True


def create_venv_stdlib() -> bool:
    """Create venv using stdlib."""
    print(f"Creating virtual environment at {VENV_DIR}...")
    result = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)],
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


def get_venv_pip() -> list[str]:
    """Get pip command for venv."""
    python = get_venv_python()
    return [python, "-m", "pip"]


def install_deps_uv(uv: str) -> list[str]:
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


def install_deps_pip() -> list[str]:
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
            if not create_venv_stdlib():
                sys.exit(1)
            failed = install_deps_pip()
            print()
            if failed:
                print(f"Failed to install: {', '.join(failed)}")
                sys.exit(1)
            print_instructions()
    else:
        # Already in venv, just install
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
