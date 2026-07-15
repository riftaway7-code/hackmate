import os
import urllib.request
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass


MACRECOVERY_URL = "https://raw.githubusercontent.com/acidanthera/OpenCorePkg/master/Utilities/macrecovery/macrecovery.py"

def _macrecovery_path() -> Path:
    # In a PyInstaller frozen EXE, __file__ is inside _MEIPASS (read-only).
    # macrecovery.py is bundled there; return that path directly.
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "macrecovery.py"
    return Path(__file__).parent / "macrecovery.py"

MACRECOVERY_PATH = _macrecovery_path()


@dataclass
class MacOSVersion:
    name: str
    version: str          # marketing version, e.g. "13" or "10.15"
    board_id: str
    mlb: str
    os_flag: str = ""     # "--os latest" for Tahoe
    min_gen: int = 0      # minimum CPU generation supported
    max_gen: int = 99     # maximum CPU generation supported
    nvidia_ok: bool = True
    notes: str = ""

    @property
    def slug(self) -> str:
        """Filesystem-safe unique id. Big Sur (11) and El Capitan (10.11) must
        not share a recovery cache directory."""
        return self.version.replace(".", "_")

    @property
    def major(self) -> int:
        """Major version used for boot-arg decisions. Legacy releases are 10.x,
        so their major is 10 — not the minor number after the dot."""
        return int(self.version.split(".")[0])


MACOS_VERSIONS = [
    MacOSVersion("macOS Tahoe (26)",      "26", "Mac-CFF7D910A743CAAF", "00000000000000000", os_flag="--os latest", min_gen=7,  notes="Latest — Intel 7th gen+ (Nvidia dGPU must be disabled in BIOS)"),
    MacOSVersion("macOS Sequoia (15)",    "15", "Mac-7BA5B2D9E42DDD94", "00000000000000000", os_flag="--os latest", min_gen=7,  notes="Intel 7th gen+"),
    MacOSVersion("macOS Sonoma (14)",     "14", "Mac-827FAC58A8FDFA22", "00000000000000000", os_flag="--os latest", min_gen=7,  notes="Intel 7th gen+"),
    MacOSVersion("macOS Ventura (13)",    "13", "Mac-B4831CEBD52A0C4C", "00000000000000000", min_gen=6,  notes="Intel 6th gen+"),
    MacOSVersion("macOS Monterey (12)",   "12", "Mac-E43C1C25D4880AD6", "00000000000000000", min_gen=5,  notes="Intel 5th gen+"),
    MacOSVersion("macOS Big Sur (11)",    "11", "Mac-2BD1B31983FE1663", "00000000000000000", min_gen=4,  notes="Intel 4th gen+"),
    MacOSVersion("macOS Catalina (10.15)","10.15", "Mac-CFF7D910A743CAAF", "00000000000PHCD00", min_gen=4,  nvidia_ok=False, notes="Last 32-bit app support"),
    MacOSVersion("macOS Mojave (10.14)",  "10.14", "Mac-7BA5B2DFE22DDD8C", "00000000000KXPG00", min_gen=3,  nvidia_ok=True,  notes="Last Metal-optional, last NVIDIA web driver support (Kepler/Maxwell/Pascal)"),
    MacOSVersion("macOS High Sierra (10.13)","10.13","Mac-7BA5B2D9E42DDD94","00000000000J80300",min_gen=2,  nvidia_ok=True,  notes=""),
    MacOSVersion("macOS Sierra (10.12)",  "10.12", "Mac-77F17D7DA9285301", "00000000000J0DX00", min_gen=2,  nvidia_ok=True,  notes=""),
    MacOSVersion("macOS El Capitan (10.11)","10.11","Mac-FFE5EF870D7BA81A","00000000000GQRX00",min_gen=2,  nvidia_ok=True,  notes=""),
    MacOSVersion("macOS Yosemite (10.10)","10.10", "Mac-E43C1C25D4880AD6", "00000000000GDVW00", min_gen=2,  nvidia_ok=True,  notes=""),
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
    cache = _CACHE_DIR / version.slug
    if not cache.exists():
        return []
    files = list(cache.glob("*.dmg")) + list(cache.glob("*.chunklist")) + list(cache.glob("com.apple.*"))
    return files


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

    script_args = [
        "-b", version.board_id,
        "-m", version.mlb,
    ]
    if version.os_flag:
        script_args += version.os_flag.split()
    script_args += ["download", "--outdir", str(dest)]

    if progress_cb:
        progress_cb("Connecting to Apple servers...")

    # If Apple's CDN stalls mid-request, urlopen calls inside macrecovery.py have no
    # timeout of their own — without a watchdog here, this hangs forever with zero
    # feedback instead of failing with a retryable error.
    STALL_TIMEOUT = 120  # seconds with no output before giving up

    try:
        if getattr(sys, "frozen", False):
            # In a PyInstaller EXE, sys.executable is HackMate.exe — can't use it to run scripts.
            # Run macrecovery.py in-process via runpy on a worker thread (so a stall can be
            # detected and reported instead of blocking the whole app), streaming stdout
            # line-by-line as it's written rather than buffering until completion.
            import runpy, io, threading, time

            last_lines: list[str] = []

            class _LiveStream(io.TextIOBase):
                def __init__(self, cb, activity):
                    self._cb = cb
                    self._pending = ""
                    self._activity = activity

                def write(self, s):
                    self._activity[0] = time.monotonic()
                    # macrecovery.py reports download progress with \r (in-place
                    # refresh), not \n — without this translation those updates
                    # sit in the buffer until the download fully finishes and
                    # prints a real newline, so the UI looks frozen at whatever
                    # percentage it last showed for the whole download.
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
        cache = _CACHE_DIR / version.slug
        cache.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, cache / f.name)
    except Exception:
        pass

    return True, f"Downloaded {len(files)} file(s) to {dest}"


if __name__ == "__main__":
    from hardware import scan
    profile = scan()
    versions = compatible_versions(profile.cpu_generation, profile.gpu_vendor, profile.cpu_vendor)
    print(f"\nCompatible macOS versions for Gen {profile.cpu_generation} {profile.cpu_vendor.upper()} [{profile.gpu_vendor} GPU]:\n")
    for i, v in enumerate(versions):
        note = f"  ({v.notes})" if v.notes else ""
        print(f"  {i+1}. {v.name}{note}")
