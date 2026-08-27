import hashlib
import os
import re
import urllib.request
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass


# Pinned to a specific OpenCorePkg release tag rather than `master` — this
# runs unreviewed on every non-frozen install that doesn't already have
# macrecovery.py cached (ensure_macrecovery() below), so tracking master
# means an upstream change lands on users' machines with zero review here.
# Bump deliberately when picking up a newer OpenCorePkg release; keep this in
# sync with the tag build-exe.yml's "Download macrecovery.py" step fetches
# and with whatever ocvalidate version .github/workflows/test.yml targets.
MACRECOVERY_URL = "https://raw.githubusercontent.com/acidanthera/OpenCorePkg/1.0.7/Utilities/macrecovery/macrecovery.py"

def _macrecovery_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "macrecovery.py"
    return Path(__file__).parent / "macrecovery.py"

MACRECOVERY_PATH = _macrecovery_path()

# Bumped on every frozen-exe in-process download attempt so a stalled/abandoned
# worker thread (still running after we've given up and returned) knows not to
# clobber sys.argv/sys.stdout out from under a newer attempt when it finally exits.
_download_generation = [0]


@dataclass
class MacOSVersion:
    name: str
    version: str          # marketing version, e.g. "13" or "10.15"
    board_id: str
    mlb: str
    os_flag: str = ""     # "-os latest" for Tahoe
    min_gen: int = 0      # minimum CPU generation supported
    max_gen: int = 99     # maximum CPU generation supported
    notes: str = ""

    @property
    def slug(self) -> str:
        """Filesystem-safe unique id. Big Sur (11) and El Capitan (10.11) must
        not share a recovery cache directory."""
        return self.version.replace(".", "_")

    @property
    def cache_key(self) -> str:
        """Invalidate cached images whenever their Apple query changes."""
        query = "\0".join((
            self.version,
            self.board_id,
            self.mlb,
            self.os_flag or "default",
        ))
        digest = hashlib.sha256(query.encode()).hexdigest()[:12]
        return f"{self.slug}-{digest}"

    @property
    def major(self) -> int:
        """Major version used for boot-arg decisions. Legacy releases are 10.x,
        so their major is 10 — not the minor number after the dot."""
        return int(self.version.split(".")[0])


MACOS_VERSIONS = [
    MacOSVersion("macOS Tahoe (26)",      "26", "Mac-CFF7D910A743CAAF", "00000000000000000", os_flag="-os latest", min_gen=7,  notes="Latest — Intel 7th gen+ (Nvidia dGPU must be disabled in BIOS)"),
    MacOSVersion("macOS Sequoia (15)",    "15", "Mac-7BA5B2D9E42DDD94", "00000000000000000", min_gen=7,  notes="Intel 7th gen+"),
    MacOSVersion("macOS Sonoma (14)",     "14", "Mac-827FAC58A8FDFA22", "00000000000000000", min_gen=7,  notes="Intel 7th gen+"),
    MacOSVersion("macOS Ventura (13)",    "13", "Mac-B4831CEBD52A0C4C", "00000000000000000", min_gen=6,  notes="Intel 6th gen+"),
    MacOSVersion("macOS Monterey (12)",   "12", "Mac-E43C1C25D4880AD6", "00000000000000000", min_gen=2,  notes="Intel 2nd gen+ (Sandy Bridge) — last version supporting pre-Skylake CPUs"),
    MacOSVersion("macOS Big Sur (11)",    "11", "Mac-2BD1B31983FE1663", "00000000000000000", min_gen=4,  notes="Intel 4th gen+"),
    MacOSVersion("macOS Catalina (10.15)","10.15", "Mac-CFF7D910A743CAAF", "00000000000PHCD00", min_gen=4, notes="First release without 32-bit app support"),
    MacOSVersion("macOS Mojave (10.14)",  "10.14", "Mac-7BA5B2DFE22DDD8C", "00000000000KXPG00", min_gen=3, notes="Last release with 32-bit app support; NVIDIA Kepler only"),
    MacOSVersion("macOS High Sierra (10.13)","10.13","Mac-7BA5B2D9E42DDD94","00000000000J80300",min_gen=2, notes="Last NVIDIA Web Driver release for Maxwell and Pascal"),
    MacOSVersion("macOS Sierra (10.12)",  "10.12", "Mac-77F17D7DA9285301", "00000000000J0DX00", min_gen=2, notes=""),
    MacOSVersion("macOS El Capitan (10.11)","10.11","Mac-FFE5EF870D7BA81A","00000000000GQRX00",min_gen=2, notes=""),
    MacOSVersion("macOS Yosemite (10.10)","10.10", "Mac-E43C1C25D4880AD6", "00000000000GDVW00", min_gen=2, notes=""),
]


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _minimum_macos_version(
    cpu_gen: int,
    cpu_vendor: str,
    cpu_codename: str = "",
) -> str:
    """Return the oldest installer that can support this CPU family."""
    if cpu_vendor == "amd":
        codename = cpu_codename.lower()
        if "zen 5" in codename:
            return "15"
        if "zen 4" in codename:
            return "13"
        if "zen 3" in codename:
            return "11"
        if "zen 2" in codename:
            return "10.15"
        if cpu_gen >= 12:
            return "13"
        if cpu_gen >= 11:
            return "11"
        if cpu_gen >= 10:
            return "10.15"
        return "10.13"

    if cpu_gen >= 11:
        return "11"
    if cpu_gen >= 10:
        return "10.15"
    if cpu_gen >= 8:
        return "10.13"
    if cpu_gen >= 7:
        return "10.12"
    if cpu_gen >= 6:
        return "10.11"
    return "10.10"


def _nvidia_max_macos_version(gpu_name: str) -> str | None:
    """Return the newest accelerated macOS release for an NVIDIA GPU."""
    name = gpu_name.lower()

    if (
        "titan rtx" in name
        or re.search(r"\brtx\s*[2345]\d{2,3}\b", name)
        or re.search(r"\bgtx\s*16\d{2}\b", name)
    ):
        return None

    if (
        re.search(r"\bgtx\s*(?:10\d{2}|9\d{2}|7(?:45|50)(?:\s*ti)?)\b", name)
        or re.search(r"\bgt\s*10(?:10|30)\b", name)
        or re.search(r"\bquadro\s+[pm]\d{3,4}\b", name)
        or re.search(r"\bquadro\s+k(?:620|1200|2200)\b", name)
        or "titan x" in name
    ):
        return "10.13"

    if (
        re.search(r"\bgtx\s*(?:6(?:60|70|80|90)|7(?:60|70|80)(?:\s*ti)?)\b", name)
        or (
            re.search(r"\b(?:gtx\s+)?titan(?:\s+(?:black|z))?\b", name)
            and "titan x" not in name
        )
        or (
            re.search(r"\bquadro\s+k\d{3,4}\b", name)
            and not re.search(r"\bquadro\s+k(?:620|1200|2200)\b", name)
        )
    ):
        return "11"

    # Low-end 600/700 cards were sold with both Fermi and Kepler cores.
    # Without a PCI core identifier, High Sierra is the safe common ceiling.
    return "10.13"


def compatible_versions(
    cpu_gen: int,
    gpu_vendor: str,
    cpu_vendor: str = "intel",
    cpu_codename: str = "",
    gpu_name: str = "",
) -> list[MacOSVersion]:
    minimum_version = _minimum_macos_version(
        cpu_gen,
        cpu_vendor,
        cpu_codename,
    )
    nvidia_maximum = (
        _nvidia_max_macos_version(gpu_name)
        if gpu_vendor == "nvidia"
        else None
    )
    result = []
    for v in MACOS_VERSIONS:
        if _version_key(v.version) < _version_key(minimum_version):
            continue
        if (
            nvidia_maximum
            and _version_key(v.version) > _version_key(nvidia_maximum)
        ):
            continue
        if cpu_vendor != "amd":
            if cpu_gen < v.min_gen:
                continue
            if cpu_gen > v.max_gen:
                continue
        result.append(v)
    return result


def ensure_macrecovery() -> Path:
    if getattr(sys, "frozen", False):
        # Bundled EXE: macrecovery.py is in _MEIPASS, already exists
        return MACRECOVERY_PATH
    if not MACRECOVERY_PATH.exists():
        import ssl, urllib.error
        ctx = ssl.create_default_context()
        try:
            req = urllib.request.Request(MACRECOVERY_URL, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                MACRECOVERY_PATH.write_bytes(r.read())
        except (ssl.SSLError, urllib.error.URLError):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(MACRECOVERY_URL, headers={"User-Agent": "HackMate/1.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                MACRECOVERY_PATH.write_bytes(r.read())
    return MACRECOVERY_PATH


def _real_home() -> Path:
    import os
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()

_CACHE_DIR = _real_home() / ".hackmate" / "cache" / "recovery"


def _cached_recovery_files(version: MacOSVersion) -> list[Path]:
    """Return cached recovery files for this version if they exist."""
    cache = _CACHE_DIR / version.cache_key
    if not cache.exists():
        return []
    files = list(cache.glob("*.dmg")) + list(cache.glob("*.chunklist")) + list(cache.glob("com.apple.*"))
    return files


def macrecovery_args(
    version: MacOSVersion,
    outdir: Path | None = None,
) -> list[str]:
    args = [
        "-b", version.board_id,
        "-m", version.mlb,
    ]
    if version.os_flag:
        args.extend(version.os_flag.split())
    args.append("download")
    if outdir is not None:
        args.extend(["--outdir", str(outdir)])
    return args


def _ensure_cert_bundle_env() -> None:
    """macrecovery.py (vendored from Acidanthera, re-downloaded fresh at every
    build — never hand-edit it) calls urlopen() with no SSL context of its
    own, so it trusts whatever urllib's default HTTPS context resolves to.
    On some Windows installs — frozen PyInstaller EXEs especially — that
    default fails to bridge to the system root store and raises
    CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate
    partway through the recovery download. Point OpenSSL at certifi's CA
    bundle via SSL_CERT_FILE, which urllib's default context creation reads
    at call time, so macrecovery.py picks it up with zero changes to it.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass


def download_recovery(version: MacOSVersion, dest: Path, progress_cb=None) -> tuple[bool, str]:
    """Download macOS recovery to dest folder, retrying transient failures.
    Returns (success, message)."""
    last_result = (False, "")
    for attempt in range(3):
        ok, msg = _download_recovery_once(version, dest, progress_cb=progress_cb)
        if ok:
            return ok, msg
        last_result = (ok, msg)
        if attempt < 2:
            if progress_cb:
                progress_cb(f"Retrying download (attempt {attempt + 2}/3)...")
            import time
            time.sleep(3)
    return last_result


def _download_recovery_once(version: MacOSVersion, dest: Path, progress_cb=None) -> tuple[bool, str]:
    import shutil

    _ensure_cert_bundle_env()

    # Use cached files if available
    cached = _cached_recovery_files(version)
    if cached:
        if progress_cb:
            progress_cb(f"Using cached recovery ({len(cached)} files)...")
        dest.mkdir(parents=True, exist_ok=True)
        for f in cached:
            shutil.copy2(f, dest / f.name)
        return True, f"Copied {len(cached)} file(s) from cache"

    try:
        script = ensure_macrecovery()
    except Exception as e:
        return False, f"Failed to download macrecovery.py: {e}"

    dest.mkdir(parents=True, exist_ok=True)

    script_args = macrecovery_args(version, dest)

    if progress_cb:
        progress_cb("Connecting to Apple servers...")

    STALL_TIMEOUT = 120  # seconds with no output before giving up

    try:
        if getattr(sys, "frozen", False):
            import runpy, io, threading, time

            last_lines: list[str] = []

            class _LiveStream(io.TextIOBase):
                def __init__(self, cb, activity):
                    self._cb = cb
                    self._pending = ""
                    self._activity = activity

                def write(self, s):
                    self._activity[0] = time.monotonic()
                    self._pending += s.replace("\r", "\n")
                    while "\n" in self._pending:
                        line, self._pending = self._pending.split("\n", 1)
                        line = line.strip()
                        if line:
                            last_lines.append(line)
                            del last_lines[:-5]
                            if self._cb:
                                self._cb(line)
                    return len(s)

                def flush(self):
                    pass

            activity = [time.monotonic()]
            result = {}

            _download_generation[0] += 1
            gen = _download_generation[0]

            def _run():
                old_argv, old_stdout = sys.argv[:], sys.stdout
                sys.argv = [str(script)] + script_args
                sys.stdout = _LiveStream(progress_cb, activity)
                try:
                    runpy.run_path(str(script), run_name="__main__")
                    result["exit_code"] = 0
                except SystemExit as e:
                    result["exit_code"] = e.code if isinstance(e.code, int) else 0
                except Exception as e:
                    result["error"] = str(e)
                finally:
                    # Only restore globals if we're still the current attempt —
                    # a stalled thread that's since been abandoned must not
                    # stomp on a newer retry's sys.argv/sys.stdout.
                    if _download_generation[0] == gen:
                        sys.stdout = old_stdout
                        sys.argv = old_argv

            worker = threading.Thread(target=_run, daemon=True)
            worker.start()
            while worker.is_alive():
                worker.join(timeout=5)
                if worker.is_alive() and time.monotonic() - activity[0] > STALL_TIMEOUT:
                    return False, (
                        f"Recovery download stalled (no response for {STALL_TIMEOUT}s) — "
                        "Apple's CDN may be unreachable right now. Try again."
                    )
            if "error" in result:
                return False, f"Download failed: {result['error']}"
            if result.get("exit_code", 0) != 0:
                detail = " | ".join(last_lines) if last_lines else "no output captured"
                return False, f"macrecovery exited with code {result['exit_code']}: {detail}"
        else:
            import threading, time, queue as _queue

            cmd = [sys.executable, str(script)] + script_args
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            line_q = _queue.Queue()

            def _reader():
                for line in proc.stdout:
                    line_q.put(line)
                line_q.put(None)

            threading.Thread(target=_reader, daemon=True).start()

            last_msg = ""
            last_lines: list[str] = []
            while True:
                try:
                    line = line_q.get(timeout=STALL_TIMEOUT)
                except _queue.Empty:
                    proc.kill()
                    return False, (
                        f"Recovery download stalled (no response for {STALL_TIMEOUT}s) — "
                        "Apple's CDN may be unreachable right now. Try again."
                    )
                if line is None:
                    break
                line = line.strip()
                if line and line != last_msg:
                    last_msg = line
                    last_lines.append(line)
                    del last_lines[:-5]
                    if progress_cb:
                        progress_cb(line)
            proc.wait()
            if proc.returncode != 0:
                detail = " | ".join(last_lines) if last_lines else "no output captured"
                return False, f"macrecovery exited with code {proc.returncode}: {detail}"
    except Exception as e:
        return False, f"Download failed: {e}"

    files = list(dest.glob("*.dmg")) + list(dest.glob("*.chunklist")) + list(dest.glob("com.apple.*"))
    if not files:
        return False, "No recovery files found after download"

    # Cache for future use
    try:
        cache = _CACHE_DIR / version.cache_key
        cache.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, cache / f.name)
    except Exception:
        pass

    return True, f"Downloaded {len(files)} file(s) to {dest}"


if __name__ == "__main__":
    from hardware import scan
    profile = scan()
    versions = compatible_versions(
        profile.cpu_generation,
        profile.gpu_vendor,
        profile.cpu_vendor,
        profile.cpu_codename,
        profile.gpu_name,
    )
    print(f"\nCompatible macOS versions for Gen {profile.cpu_generation} {profile.cpu_vendor.upper()} [{profile.gpu_vendor} GPU]:\n")
    for i, v in enumerate(versions):
        note = f"  ({v.notes})" if v.notes else ""
        print(f"  {i+1}. {v.name}{note}")
