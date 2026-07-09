"""
`hackmate.py --doctor [path]` — audit an OpenCore EFI from the terminal.

Reads only, needs no root, and needs no TUI, so it is safe to run against a
booted system's own EFI partition and easy to paste into a bug report.
"""

import sys
from pathlib import Path

from efi_health import audit, format_report, summarise


def find_efi_candidates() -> list:
    """Mounted volumes that look like they hold an OpenCore EFI."""
    roots = [Path("/Volumes"), Path("/media"), Path("/mnt")]
    found = []

    for root in roots:
        if not root.is_dir():
            continue
        try:
            volumes = list(root.iterdir())
        except PermissionError:
            continue
        for volume in volumes:
            for efi in (volume / "EFI", volume):
                try:
                    if not efi.is_dir():
                        continue
                    children = {c.name.lower() for c in efi.iterdir() if c.is_dir()}
                except (PermissionError, OSError):
                    continue
                if "oc" in children:
                    found.append(efi)
                    break

    return found


def _usage(candidates: list) -> None:
    print("\nUsage: hackmate.py --doctor [/path/to/EFI]\n")
    print("  Audits an OpenCore EFI folder — the one containing OC/ and BOOT/.\n")
    if candidates:
        print("  Detected on this system:")
        for path in candidates:
            print(f"    {path}")
        print()
    else:
        print("  No mounted EFI found. Mount the EFI partition first, e.g.:")
        if sys.platform == "darwin":
            print("    sudo diskutil mount disk0s1\n")
        else:
            print("    sudo mount /dev/sda1 /mnt/efi\n")


def main(argv: list) -> int:
    args = [a for a in argv[1:] if a != "--doctor"]
    candidates = find_efi_candidates()

    if args:
        target = Path(args[0]).expanduser()
    elif len(candidates) == 1:
        target = candidates[0]
        print(f"Auditing the only EFI found: {target}")
    else:
        _usage(candidates)
        return 1 if not candidates else 2

    if not target.is_dir():
        print(f"Not a directory: {target}")
        return 1

    # Accept either the EFI folder or the volume that contains it.
    if not any(c.name.lower() == "oc" for c in target.iterdir() if c.is_dir()):
        nested = target / "EFI"
        if nested.is_dir():
            target = nested

    findings = audit(target)
    print(format_report(findings, target))

    return 1 if summarise(findings)["critical"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
