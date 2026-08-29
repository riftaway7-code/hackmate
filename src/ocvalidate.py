import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

from compat import IS_WINDOWS, IS_MACOS, real_home

_CACHE_DIR = real_home() / ".hackmate" / "cache" / "ocvalidate"


def _binary_name() -> str:
    if IS_WINDOWS:
        return "ocvalidate.exe"
    if IS_MACOS:
        return "ocvalidate"
    return "ocvalidate.linux"


def _search(root: Path) -> Path | None:
    name = _binary_name()
    hits = list(root.rglob(name))
    if not hits and not IS_WINDOWS:
        hits = list(root.rglob("ocvalidate")) + list(root.rglob("ocvalidate.linux"))
    return hits[0] if hits else None


def _make_executable(path: Path) -> None:
    if IS_WINDOWS:
        return
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass


def ensure_ocvalidate(oc_extract_dir: Path | None = None, oc_zip: Path | None = None) -> Path | None:
    cached = _CACHE_DIR / _binary_name()
    if cached.exists() and cached.stat().st_size > 10 * 1024:
        _make_executable(cached)
        return cached

    found = None
    if oc_extract_dir and Path(oc_extract_dir).exists():
        found = _search(Path(oc_extract_dir))

    if not found and oc_zip and Path(oc_zip).exists():
        try:
            tmp_root = _CACHE_DIR / "_unzip"
            tmp_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(str(oc_zip)) as z:
                for member in z.namelist():
                    if "ocvalidate" in member.lower():
                        z.extract(member, str(tmp_root))
            found = _search(tmp_root)
        except Exception:
            found = None

    if not found:
        try:
            from kexts import fetch_opencore
            zpath = fetch_opencore(_CACHE_DIR)
            if zpath and Path(zpath).exists():
                return ensure_ocvalidate(oc_zip=Path(zpath))
        except Exception:
            return None
        return None

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(found), str(cached))
        _make_executable(cached)
        return cached
    except Exception:
        _make_executable(found)
        return found


def validate(config_path, oc_extract_dir=None, oc_zip=None) -> tuple[bool, list[str]]:
    config_path = Path(config_path)
    if not config_path.exists():
        return False, [f"config.plist not found at {config_path}"]

    binary = ensure_ocvalidate(oc_extract_dir=oc_extract_dir, oc_zip=oc_zip)
    if not binary:
        return True, ["ocvalidate binary unavailable — skipped"]

    try:
        proc = subprocess.run(
            [str(binary), str(config_path)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:
        return True, [f"ocvalidate could not run ({exc}) — skipped"]

    raw = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    return proc.returncode == 0, lines
