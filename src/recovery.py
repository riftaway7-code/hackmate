import urllib.request
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass


MACRECOVERY_URL = "https://raw.githubusercontent.com/acidanthera/OpenCorePkg/master/Utilities/macrecovery/macrecovery.py"
MACRECOVERY_PATH = Path(__file__).parent / "macrecovery.py"


@dataclass
class MacOSVersion:
    name: str
    version: str          # human readable e.g. "13"
    board_id: str
    mlb: str
    os_flag: str = ""     # "--os latest" for Tahoe
    min_gen: int = 0      # minimum CPU generation supported
    max_gen: int = 99     # maximum CPU generation supported
    nvidia_ok: bool = True
    notes: str = ""


MACOS_VERSIONS = [
    MacOSVersion("macOS Tahoe (26)",      "26", "Mac-CFF7D910A743CAAF", "00000000000000000", os_flag="--os latest", min_gen=8,  notes="Latest — Intel 8th gen+"),
    MacOSVersion("macOS Sequoia (15)",    "15", "Mac-7BA5B2D9E42DDD94", "00000000000000000", min_gen=7,  notes="Intel 7th gen+"),
    MacOSVersion("macOS Sonoma (14)",     "14", "Mac-827FAC58A8FDFA22", "00000000000000000", min_gen=7,  notes="Intel 7th gen+"),
    MacOSVersion("macOS Ventura (13)",    "13", "Mac-B4831CEBD52A0C4C", "00000000000000000", min_gen=6,  notes="Intel 6th gen+"),
    MacOSVersion("macOS Monterey (12)",   "12", "Mac-E43C1C25D4880AD6", "00000000000000000", min_gen=5,  notes="Intel 5th gen+"),
    MacOSVersion("macOS Big Sur (11)",    "11", "Mac-2BD1B31983FE1663", "00000000000000000", min_gen=4,  notes="Intel 4th gen+"),
    MacOSVersion("macOS Catalina (10.15)","15", "Mac-CFF7D910A743CAAF", "00000000000PHCD00", min_gen=4,  nvidia_ok=False, notes="Last 32-bit app support"),
    MacOSVersion("macOS Mojave (10.14)",  "14", "Mac-7BA5B2DFE22DDD8C", "00000000000KXPG00", min_gen=3,  nvidia_ok=False, notes="Last Metal-optional"),
    MacOSVersion("macOS High Sierra (10.13)","13","Mac-7BA5B2D9E42DDD94","00000000000J80300",min_gen=2,  nvidia_ok=True,  notes="Last NVIDIA web driver support"),
    MacOSVersion("macOS Sierra (10.12)",  "12", "Mac-77F17D7DA9285301", "00000000000J0DX00", min_gen=2,  nvidia_ok=True,  notes=""),
    MacOSVersion("macOS El Capitan (10.11)","11","Mac-FFE5EF870D7BA81A","00000000000GQRX00",min_gen=2,  nvidia_ok=True,  notes=""),
    MacOSVersion("macOS Yosemite (10.10)","10", "Mac-E43C1C25D4880AD6", "00000000000GDVW00", min_gen=2,  nvidia_ok=True,  notes=""),
]


def compatible_versions(cpu_gen: int, gpu_vendor: str, cpu_vendor: str = "intel") -> list[MacOSVersion]:
    result = []
    for v in MACOS_VERSIONS:
        # Per the Dortania guide, AMD Ryzen/Threadripper CPUs do not follow
        # Intel's generation-based macOS compatibility restrictions. All Ryzen
        # CPUs (Zen through Zen 5) support macOS Sierra through current with
        # appropriate AMD Vanilla kernel patches. The only hardware filter for
        # AMD is GPU compatibility (NVIDIA not supported on Mojave+).
        if cpu_vendor != "amd":
            if cpu_gen < v.min_gen:
                continue
            if cpu_gen > v.max_gen:
                continue
        if gpu_vendor == "nvidia" and not v.nvidia_ok:
            continue
        result.append(v)
    return result


def ensure_macrecovery() -> Path:
    if not MACRECOVERY_PATH.exists():
        urllib.request.urlretrieve(MACRECOVERY_URL, str(MACRECOVERY_PATH))
    return MACRECOVERY_PATH


def download_recovery(version: MacOSVersion, dest: Path, progress_cb=None) -> tuple[bool, str]:
    """Download macOS recovery to dest folder. Returns (success, message)."""
    try:
        script = ensure_macrecovery()
    except Exception as e:
        return False, f"Failed to download macrecovery.py: {e}"

    dest.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(script),
        "-b", version.board_id,
        "-m", version.mlb,
    ]
    if version.os_flag:
        cmd += version.os_flag.split()
    cmd += ["download", "--outdir", str(dest)]

    if progress_cb:
        progress_cb("Connecting to Apple servers...")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        last_msg = ""
        for line in proc.stdout:
            line = line.strip()
            if line and line != last_msg:
                last_msg = line
                if progress_cb:
                    progress_cb(line)
        proc.wait()
        if proc.returncode != 0:
            return False, f"macrecovery exited with code {proc.returncode}"
    except Exception as e:
        return False, f"Download failed: {e}"

    # macrecovery downloads BaseSystem.dmg + BaseSystem.chunklist (or RecoveryImage)
    files = list(dest.glob("*.dmg")) + list(dest.glob("*.chunklist")) + list(dest.glob("com.apple.*"))
    if not files:
        return False, "No recovery files found after download"

    return True, f"Downloaded {len(files)} file(s) to {dest}"


if __name__ == "__main__":
    from hardware import scan
    profile = scan()
    versions = compatible_versions(profile.cpu_generation, profile.gpu_vendor, profile.cpu_vendor)
    print(f"\nCompatible macOS versions for Gen {profile.cpu_generation} {profile.cpu_vendor.upper()} [{profile.gpu_vendor} GPU]:\n")
    for i, v in enumerate(versions):
        note = f"  ({v.notes})" if v.notes else ""
        print(f"  {i+1}. {v.name}{note}")
