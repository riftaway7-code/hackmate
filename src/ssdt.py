"""
Automated SSDT generation via SSDTTime (corpnewt/SSDTTime).

3-tier fallback per SSDT:
  Tier 1: SSDTTime          — machine-specific, uses real DSDT, best quality
  Tier 2: Template + iasl   — generic DSL compiled at runtime for standard hardware
  Tier 3: Bundled .aml      — precompiled binary in src/assets/acpi/, last resort

Flow:
  1. Download SSDTTime repo ZIP (includes bundled iasl for Linux)
  2. Inspect DSDT (detect AWAC, EC name, iGPU name, CPU path, GPIO)
  3. Probe run (DSDT path + Q) to capture and parse the menu
  4. For each SSDT: Tier 1 → Tier 2 → Tier 3
  5. Copy .aml files to acpi_dir
"""

import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional
from compat import IS_WINDOWS, get_dsdt, find_iasl, chmod_iasl, real_home

SSDTTIME_ZIP_URL = "https://github.com/corpnewt/SSDTTime/archive/refs/heads/master.zip"
SSDTTIME_DIR = real_home() / ".hackmate" / "cache" / "ssdttime"

def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets" / "acpi"
    return Path(__file__).parent / "assets" / "acpi"

_ASSETS = _assets_dir()

# Map our SSDT names → keywords to search for in SSDTTime's menu output
SSDT_MENU_KEYWORDS: dict[str, list[str]] = {
    "SSDT-PLUG":    ["plugintype", "plugin-type", "plugin type"],
    "SSDT-EC-USBX": ["fakeec laptop", "fake ec laptop"],
    "SSDT-EC":      ["fakeec", "fake ec"],
    "SSDT-PNLF":    ["pnlf", "backlight"],
    "SSDT-AWAC":    ["awac"],
    "SSDT-GPI0":    ["gpi0", "gpio"],
    "SSDT-XOSI":    ["xosi", "fakeosi", "fake osi"],
    "SSDT-HPET":    ["fixhpet", "hpet", "irq conflict"],
    "SSDT-PMC":     ["pmc", "pmcr"],
    "SSDT-USBX":    ["usbx"],
}

# SSDTs SSDTTime has no equivalent for
MANUAL_SSDTS: set[str] = {"SSDT-RHUB", "SSDT-CPUR", "SSDT-UNC", "SSDT-RTC0-RANGE"}

# Double-braces {{ }} are literal braces in the f-string/format output.

# Takes no substitutions, so it is compiled verbatim — single braces only.
XOSI_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "ACDT", "OsIdXosi", 0x00000000)
{
    Method (XOSI, 1, NotSerialized)
    {
        If (_OSI ("Darwin"))
        {
            Return (Zero)
        }
        If (Arg0 == "Windows 2009") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2012") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2013") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2015") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2016") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2017") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2017.2") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2018") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2018.2") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2019") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2020") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2021") { Return (0xFFFFFFFF) }
        If (Arg0 == "Windows 2022") { Return (0xFFFFFFFF) }
        Return (_OSI (Arg0))
    }
}
"""

GPIO_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "SsdtGpio", 0x00001000)
{{
    External ({gpio_path}, DeviceObj)
    Scope ({gpio_path})
    {{
        Method (_STA, 0, NotSerialized)
        {{
            If (_OSI ("Darwin"))
            {{
                Return (0x0F)
            }}
            Else
            {{
                Return (Zero)
            }}
        }}
    }}
}}
"""

PLUG_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "CpuPlug", 0x00003000)
{{
    External ({cpu_path}, ProcessorObj)
    Scope ({cpu_path})
    {{
        Method (_DSM, 4, NotSerialized)
        {{
            If (_OSI ("Darwin"))
            {{
                If (!Arg2) {{ Return (Buffer (One) {{ 0x03 }}) }}
                Return (Package (0x02) {{ "plugin-type", One }})
            }}
            Return (Zero)
        }}
    }}
}}
"""

EC_USBX_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "UsbcEc", 0x00000002)
{{
    Device (_SB.EC)
    {{
        Name (_HID, "ACID0001")
        Method (_STA, 0, NotSerialized)
        {{
            If (_OSI ("Darwin")) {{ Return (0x0F) }}
            Return (Zero)
        }}
    }}
    Device (_SB.USBX)
    {{
        Name (_ADR, Zero)
        Method (_DSM, 4, NotSerialized)
        {{
            If (!Arg2) {{ Return (Buffer (One) {{ 0x03 }}) }}
            Return (Package (0x08)
            {{
                "kUSBSleepPowerSupply",      0x13EC,
                "kUSBSleepPortCurrentLimit", 0x0834,
                "kUSBWakePowerSupply",       0x13EC,
                "kUSBWakePortCurrentLimit",  0x0834
            }})
        }}
    }}
}}
"""

EC_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "FakeEC", 0x00000001)
{{
    Device (_SB.EC)
    {{
        Name (_HID, "ACID0001")
        Method (_STA, 0, NotSerialized)
        {{
            If (_OSI ("Darwin")) {{ Return (0x0F) }}
            Return (Zero)
        }}
    }}
}}
"""

PNLF_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "bklt", 0x00000000)
{{
    External (_SB.PCI0.{igpu_name}, DeviceObj)
    Scope (_SB.PCI0.{igpu_name})
    {{
        Device (PNLF)
        {{
            Name (_HID, EisaId ("APP0002"))
            Name (_CID, "backlight")
            Name (_UID, {uid})
            Name (_STA, 0x0B)
        }}
    }}
}}
"""

USBX_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "USBX", 0x00000001)
{{
    Device (_SB.USBX)
    {{
        Name (_ADR, Zero)
        Method (_DSM, 4, NotSerialized)
        {{
            If (!Arg2) {{ Return (Buffer (One) {{ 0x03 }}) }}
            Return (Package (0x08)
            {{
                "kUSBSleepPowerSupply",      0x13EC,
                "kUSBSleepPortCurrentLimit", 0x0834,
                "kUSBWakePowerSupply",       0x13EC,
                "kUSBWakePortCurrentLimit",  0x0834
            }})
        }}
    }}
}}
"""

PMC_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "CORP", "PMCR", 0x00000000)
{{
    External (_SB.PCI0, DeviceObj)
    Scope (_SB.PCI0)
    {{
        Device (PMCR)
        {{
            Name (_HID, EisaId ("APP9876"))
            Method (_STA, 0, NotSerialized)
            {{
                If (_OSI ("Darwin")) {{ Return (0x0B) }}
                Return (Zero)
            }}
            Name (_CRS, ResourceTemplate ()
            {{
                Memory32Fixed (ReadWrite, 0xFE000000, 0x00010000)
            }})
        }}
    }}
}}
"""

GPRW_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "HACK", "GPRW", 0x00000000)
{
    External (XGPR, MethodObj)

    Method (GPRW, 2, NotSerialized)
    {
        If ((0x6D == Arg0))
        {
            Return (Package (0x02)
            {
                0x6D,
                Zero
            })
        }
        If ((0x0D == Arg0))
        {
            Return (Package (0x02)
            {
                0x0D,
                Zero
            })
        }
        Return (XGPR (Arg0, Arg1))
    }
}
"""

IMEI_DSL_TEMPLATE = """\
DefinitionBlock ("", "SSDT", 2, "HACK", "IMEI", 0x00000000)
{
    External (_SB_.PCI0, DeviceObj)

    Scope (\\_SB.PCI0)
    {
        Device (IMEI)
        {
            Name (_ADR, 0x00160000)
        }
    }
}
"""

def _inspect_dsdt(dsdt_path: Path) -> dict:
    """
    Scan the raw DSDT binary for key device names.
    Returns defaults when a device is absent — callers must not assume presence.
    """
    try:
        data = dsdt_path.read_bytes()
    except Exception:
        return {"has_awac": False, "ec_name": "EC0", "igpu_name": "GFX0",
                "cpu_path": r"\_SB.PR00", "has_gpi0": False, "has_gprw": False,
                "has_acpi0007": None}

    has_awac = b"ACPI000E" in data
    has_gprw = b"GPRW" in data
    has_acpi0007 = b"ACPI0007" in data

    ec_name = "EC0"
    for candidate in (b"EC0 ", b"H_EC", b"ECDV", b"EC0_"):
        if candidate.rstrip(b"_ ") in data or candidate in data:
            ec_name = candidate.rstrip(b"_ ").decode()
            break

    igpu_name = "GFX0" if b"GFX0" in data else ("IGPU" if b"IGPU" in data else "GFX0")

    # Modern DSDTs declare CPUs as Device objects under \_SB (PR00, optionally
    # nested under CPUS). Some older/OEM firmware instead uses the legacy
    # ACPI Processor() object form (\_PR.CPU0) — a template SSDT-PLUG built
    # against a blindly-guessed \_SB.PR00 path on one of those systems
    # references a device that doesn't exist and silently does nothing.
    cpu_path = r"\_SB.PR00"
    cpu_path_confident = True
    if b"PR00" not in data and b"CPUS" in data:
        cpu_path = r"\_SB.CPUS.PR00"
    elif b"PR00" not in data and b"CPUS" not in data:
        cpu_path_confident = False
        if b"CPU0" in data:
            cpu_path = r"\_PR.CPU0"

    has_gpi0 = b"GPI0" in data or b"GPIO" in data

    return {
        "has_awac":  has_awac,
        "ec_name":   ec_name,
        "igpu_name": igpu_name,
        "cpu_path":  cpu_path,
        "cpu_path_confident": cpu_path_confident,
        "has_gpi0":  has_gpi0,
        "has_gprw":  has_gprw,
        "has_acpi0007": has_acpi0007,
    }

def _compile_dsl(dsl: str, name: str, acpi_dir: Path, iasl) -> bool:
    """Write DSL to temp file, compile with iasl, return True if .aml produced."""
    if not iasl:
        return False
    dsl_file = acpi_dir / f"{name}.dsl"
    try:
        dsl_file.write_text(dsl)
        subprocess.run([str(iasl), str(dsl_file)], capture_output=True, timeout=15)
        try:
            dsl_file.unlink()
        except Exception:
            pass
        return (acpi_dir / f"{name}.aml").exists()
    except Exception:
        return False

def _build_xosi_ssdt(acpi_dir: Path, ssdttime_dir: Path) -> bool:
    iasl = find_iasl(ssdttime_dir)
    return _compile_dsl(XOSI_DSL_TEMPLATE, "SSDT-XOSI", acpi_dir, iasl)

_INTEL_GPIO_HIDS = (
    "INT33FF", "INT344B", "INT3450", "INT345D", "INT34BB",
    "INT3455", "INT34C5", "INT34C6", "INTC1055", "INTC1056",
)
_I2C_HID_IDS = ("PNP0C50", "ACPI0C50")
_SCOPE_OPENERS = ("Scope", "Device", "PowerResource", "Processor", "ThermalZone")
_NODE_RE = re.compile(
    r"^(\s*)(?:" + "|".join(_SCOPE_OPENERS) + r")\s*\(\s*([\\\^A-Za-z_][\w\\.\^]*)"
)


def _decompile_dsdt(dsdt_path: Path, iasl) -> Optional[str]:
    if not iasl:
        return None
    try:
        work = dsdt_path.parent / "_gpio_decomp"
        work.mkdir(exist_ok=True)
        target = work / "DSDT.aml"
        target.write_bytes(dsdt_path.read_bytes())
        subprocess.run([str(iasl), "-d", str(target)], capture_output=True, timeout=40, cwd=str(work))
        dsl = work / "DSDT.dsl"
        return dsl.read_text(errors="replace") if dsl.exists() else None
    except Exception:
        return None


def _qualified_path(lines: list[str], idx: int) -> Optional[str]:
    own = _NODE_RE.match(lines[idx])
    if not own:
        return None
    parts = [own.group(2)]
    cur_indent = len(own.group(1))
    for j in range(idx - 1, -1, -1):
        m = _NODE_RE.match(lines[j])
        if not m:
            continue
        ind = len(m.group(1))
        if ind < cur_indent:
            parts.append(m.group(2))
            cur_indent = ind
            if ind == 0 or m.group(2).startswith("\\"):
                break
    parts.reverse()
    joined = ".".join(p.strip("\\") for p in parts if p not in ("\\", "^"))
    return "\\" + joined


def _block_end(lines: list[str], idx: int) -> int:
    base = len(lines[idx]) - len(lines[idx].lstrip())
    for j in range(idx + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped:
            continue
        ind = len(lines[j]) - len(lines[j].lstrip())
        if ind <= base and stripped.startswith("}"):
            return j
    return len(lines) - 1


def _gpio_controller_path(dsl: str) -> Optional[str]:
    lines = dsl.splitlines()
    candidates = []
    for i, line in enumerate(lines):
        m = _NODE_RE.match(line)
        if not m or not line.lstrip().startswith("Device"):
            continue
        name = m.group(2).strip("\\^")
        head = "\n".join(lines[i + 1:i + 16])
        own_hid = any(hid in head for hid in _INTEL_GPIO_HIDS)
        if not (own_hid or name in ("GPI0", "GPIO")):
            continue
        path = _qualified_path(lines, i)
        if not path:
            continue
        rank = 2 if name in ("GPI0", "GPIO") else 1
        candidates.append((rank, len(m.group(1)), path))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][2]


def _touchpad_gpio_source(dsl: str) -> Optional[str]:
    lines = dsl.splitlines()
    for i, line in enumerate(lines):
        m = _NODE_RE.match(line)
        if not m or not line.lstrip().startswith("Device"):
            continue
        end = _block_end(lines, i)
        body = "\n".join(lines[i:end + 1])
        if not any(hid in body for hid in _I2C_HID_IDS):
            continue
        gi = re.search(r'GpioInt\s*\([^)]*?"([^"]+)"', body, re.DOTALL)
        if gi:
            src = gi.group(1)
            return src if src.startswith("\\") else "\\" + src.strip("\\")
    return None


def _build_gpio_ssdt(dsdt_path: Path, acpi_dir: Path, ssdttime_dir: Path, ssdt_name: str = "SSDT-GPI0") -> bool:
    try:
        iasl = find_iasl(ssdttime_dir)
        gpio_path = None

        dsl = _decompile_dsdt(dsdt_path, iasl)
        if dsl:
            gpio_path = _touchpad_gpio_source(dsl) or _gpio_controller_path(dsl)

        if not gpio_path:
            data = dsdt_path.read_bytes()
            for name in (b"GPI0", b"GPIO"):
                if data.find(name) != -1:
                    gpio_path = f"\\_SB.PCI0.{name.decode()}"
                    break

        if not gpio_path:
            return False
        if not gpio_path.startswith("\\"):
            gpio_path = "\\" + gpio_path

        dsl_out = GPIO_DSL_TEMPLATE.format(gpio_path=gpio_path)
        return _compile_dsl(dsl_out, ssdt_name, acpi_dir, iasl)
    except Exception:
        return False

def _build_from_template(ssdt: str, acpi_dir: Path, ssdttime_dir: Path,
                         dsdt_info: dict, cpu_generation: int) -> bool:
    """
    Tier 2: compile a generic DSL template for the given SSDT.
    Returns True if .aml was produced.
    """
    iasl = find_iasl(ssdttime_dir)
    if not iasl:
        return False

    uid = _pnlf_uid(cpu_generation)

    templates = {
        "SSDT-PLUG":    PLUG_DSL_TEMPLATE.format(cpu_path=dsdt_info.get("cpu_path", r"\_SB.PR00")),
        "SSDT-EC-USBX": EC_USBX_DSL_TEMPLATE.format(),
        "SSDT-EC":      EC_DSL_TEMPLATE.format(),
        "SSDT-PNLF":    PNLF_DSL_TEMPLATE.format(
                            igpu_name=dsdt_info.get("igpu_name", "GFX0"), uid=uid),
        "SSDT-USBX":    USBX_DSL_TEMPLATE.format(),
        "SSDT-PMC":     PMC_DSL_TEMPLATE.format(),
        "SSDT-XOSI":    XOSI_DSL_TEMPLATE,
        "SSDT-GPRW":    GPRW_DSL_TEMPLATE,
        "SSDT-IMEI":    IMEI_DSL_TEMPLATE,
    }

    dsl = templates.get(ssdt)
    if not dsl:
        return False

    return _compile_dsl(dsl, ssdt, acpi_dir, iasl)

def _use_bundled(ssdt: str, acpi_dir: Path, cpu_generation: int) -> bool:
    """
    Tier 3: copy a precompiled .aml from src/assets/acpi/.
    SSDT-PNLF picks the UID-specific variant.
    """
    if ssdt == "SSDT-PNLF":
        uid = _pnlf_uid(cpu_generation)
        src = _ASSETS / f"SSDT-PNLF-UID{uid}.aml"
        if src.exists():
            import shutil as _sh
            _sh.copy2(str(src), str(acpi_dir / "SSDT-PNLF.aml"))
            return True
        return False

    src = _ASSETS / f"{ssdt}.aml"
    if src.exists():
        import shutil as _sh
        _sh.copy2(str(src), str(acpi_dir / f"{ssdt}.aml"))
        return True
    return False

def _ensure_ssdttime() -> Path:
    """Download and extract SSDTTime if not present. Returns path to SSDTTime.py."""
    script = SSDTTIME_DIR / "SSDTTime.py"
    if script.exists():
        return script

    SSDTTIME_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = SSDTTIME_DIR / "ssdttime.zip"
    from compat import http_get
    zip_path.write_bytes(http_get(SSDTTIME_ZIP_URL, timeout=60))

    with zipfile.ZipFile(str(zip_path)) as z:
        z.extractall(str(SSDTTIME_DIR))
    zip_path.unlink()

    extracted = SSDTTIME_DIR / "SSDTTime-master"
    for item in extracted.iterdir():
        dest = SSDTTIME_DIR / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(str(dest))
            else:
                dest.unlink()
        shutil.move(str(item), str(dest))
    extracted.rmdir()

    chmod_iasl(SSDTTIME_DIR)
    return script

def _ensure_iasl(script: Optional[Path], ssdttime_dir: Path):
    """
    Make sure the iasl compiler is on disk, returning its path or None.

    SSDTTime fetches iasl the first time it starts, but HackMate only launches it
    when a DSDT was found. On hosts where no DSDT can be read (macOS exposes
    none), iasl would never arrive and every template compile would fail, so
    launch SSDTTime once purely to let it bootstrap the compiler.
    """
    iasl = find_iasl(ssdttime_dir)
    if iasl or not script:
        return iasl

    try:
        _run(script, "Q\n", timeout=90)
    except Exception:
        return None

    chmod_iasl(ssdttime_dir)
    return find_iasl(ssdttime_dir)

def _parse_menu(output: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in output.splitlines():
        m = re.match(r"\s*(\d+)\.\s+(.+)", line)
        if not m:
            continue
        num, label = m.group(1), m.group(2).lower()
        for ssdt, keywords in SSDT_MENU_KEYWORDS.items():
            if ssdt in mapping:
                continue
            if any(kw in label for kw in keywords):
                mapping[ssdt] = num
    return mapping

def _run(script: Path, input_text: str, timeout: int = 60) -> str:
    result = subprocess.run(
        [sys.executable, "-u", str(script.name)],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(script.parent),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return result.stdout + result.stderr

def _pnlf_uid(cpu_generation: int) -> str:
    if cpu_generation in (2, 3): return "14"   # Sandy/Ivy Bridge
    if cpu_generation in (4, 5): return "15"   # Haswell/Broadwell
    if cpu_generation in (6, 7): return "16"   # Skylake/Kaby Lake
    return "19"                                 # Coffee Lake+ / AMD

def generate(
    needed: list[str],
    acpi_dir: Path,
    tmp: Path,
    progress_cb=None,
    cpu_generation: int = 0,
) -> dict[str, str]:
    """
    Generate SSDTs for every name in `needed`, copy .aml files to `acpi_dir`.
    Returns {ssdt_name: "OK" | "SKIP: ..." | "ERROR: ..."}.

    Tier 1 (SSDTTime) → Tier 2 (template+iasl) → Tier 3 (bundled .aml)
    """
    results: dict[str, str] = {}
    cb = progress_cb or (lambda m: None)

    doable = [n for n in needed if n not in MANUAL_SSDTS]
    manual = [n for n in needed if n in MANUAL_SSDTS]
    for n in manual:
        results[n] = "SKIP: no SSDTTime equivalent — install manually"

    if not doable:
        return results

    cb("Downloading SSDTTime...")
    try:
        script = _ensure_ssdttime()
        cb(f"  SSDTTime ready at {script}")
    except Exception as e:
        # SSDTTime unavailable — fall back to templates + bundles for everything
        cb(f"  SSDTTime unavailable: {e} — using templates/bundles")
        script = None

    cb("Extracting DSDT from system ACPI tables...")
    dsdt = get_dsdt(tmp)
    if dsdt:
        cb(f"  DSDT: {dsdt.stat().st_size:,} bytes")
        dsdt_info = _inspect_dsdt(dsdt)
    else:
        cb("  DSDT not found — using generic templates")
        dsdt_info = {"has_awac": False, "ec_name": "EC0", "igpu_name": "GFX0",
                     "cpu_path": r"\_SB.PR00", "has_gpi0": False, "has_gprw": False,
                     "has_acpi0007": None}

    ssdttime_dir = script.parent if script else SSDTTIME_DIR

    iasl = _ensure_iasl(script, ssdttime_dir)
    if iasl:
        cb(f"  iasl ready: {iasl.name}")
    else:
        cb("  iasl unavailable — falling back to bundled ACPI tables")

    menu_map: dict[str, str] = {}
    if script and dsdt:
        cb("Probing SSDTTime menu...")
        try:
            probe_out = _run(script, f"{dsdt}\nQ\n", timeout=30)
            menu_map = _parse_menu(probe_out)
            if not menu_map:
                cb("  Re-probing (alternate path)...")
                try:
                    probe_out2 = _run(script, f"\n{dsdt}\nQ\n", timeout=30)
                    menu_map = _parse_menu(probe_out2)
                except Exception:
                    pass
        except Exception as e:
            cb(f"  SSDTTime probe failed: {e} — using templates/bundles")

        if menu_map:
            cb(f"  {len(menu_map)} menu options detected: {', '.join(menu_map.keys())}")

    acpi_dir.mkdir(parents=True, exist_ok=True)
    results_dir = script.parent / "Results" if script else None

    for ssdt in doable:

        if ssdt == "SSDT-AWAC" and not dsdt_info.get("has_awac"):
            results[ssdt] = "SKIP: AWAC clock not present in this system — not required"
            continue

        if ssdt == "SSDT-GPRW" and dsdt and not dsdt_info.get("has_gprw"):
            results[ssdt] = "SKIP: no GPRW method in this DSDT — not required"
            continue

        if ssdt in ("SSDT-GPI0", "SSDT-GPIO"):
            cb(f"Generating {ssdt}...")
            if dsdt and _build_gpio_ssdt(dsdt, acpi_dir, ssdttime_dir, ssdt):
                cb(f"  {ssdt}.aml")
                results[ssdt] = "OK"
            elif _use_bundled(ssdt, acpi_dir, cpu_generation):
                cb(f"  {ssdt}.aml (bundled fallback)")
                results[ssdt] = "OK"
            else:
                results[ssdt] = "ERROR: GPI0/GPIO device not found in DSDT"
            continue

        if ssdt == "SSDT-XOSI" and not (menu_map.get(ssdt) and script and dsdt):
            cb("Generating SSDT-XOSI from template...")
            if _build_xosi_ssdt(acpi_dir, ssdttime_dir):
                results[ssdt] = "OK"
            elif _use_bundled(ssdt, acpi_dir, cpu_generation):
                results[ssdt] = "OK"
            else:
                results[ssdt] = "ERROR: could not compile SSDT-XOSI template"
            continue

        choice = menu_map.get(ssdt)
        tier1_ok = False

        if choice and script and dsdt:
            cb(f"Generating {ssdt}...")
            if results_dir and results_dir.exists():
                shutil.rmtree(str(results_dir))

            stdin = f"D\n{dsdt}\n{choice}\n"
            if ssdt == "SSDT-PNLF":
                stdin += f"{_pnlf_uid(cpu_generation)}\n"
            stdin += "\n\nQ\n"

            try:
                _run(script, stdin, timeout=30)
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                cb(f"  SSDTTime failed: {e}")

            found_amls = list(results_dir.rglob("*.aml")) if results_dir and results_dir.exists() else []
            if found_amls:
                dst = acpi_dir / f"{ssdt}.aml"
                shutil.copy2(str(found_amls[0]), str(dst))
                cb(f"  {dst.name}")
                tier1_ok = True
            if results_dir and results_dir.exists():
                shutil.rmtree(str(results_dir))

        if tier1_ok:
            results[ssdt] = "OK"
            continue

        if ssdt == "SSDT-PLUG" and dsdt_info.get("has_acpi0007"):
            results[ssdt] = (
                "ERROR: this system defines CPUs as ACPI0007 devices — needs "
                "SSDT-PLUG-ALT, which only SSDTTime can generate correctly "
                "(it wasn't reachable this run). Retry the build, or run "
                "SSDTTime yourself (https://github.com/corpnewt/SSDTTime) "
                "against this machine's DSDT and add the SSDT-PLUG-ALT.aml "
                "it produces to EFI/OC/ACPI manually."
            )
            continue

        if ssdt == "SSDT-PLUG" and dsdt_info.get("has_acpi0007") is None:
            results[ssdt] = (
                "ERROR: could not read this system's DSDT, so whether it "
                "needs SSDT-PLUG or SSDT-PLUG-ALT can't be determined — "
                "injecting the wrong one can hang the boot before the "
                "picker appears. Retry the build (SSDTTime may reach the "
                "real DSDT next time), or run SSDTTime yourself "
                "(https://github.com/corpnewt/SSDTTime) against this "
                "machine's DSDT and add whichever SSDT-PLUG variant it "
                "produces to EFI/OC/ACPI manually."
            )
            continue

        if ssdt == "SSDT-PLUG" and not dsdt_info.get("cpu_path_confident", True):
            results[ssdt] = (
                "ERROR: this system's DSDT doesn't declare CPUs under the "
                "usual \\_SB.PR00 path SSDT-PLUG templates target — it may "
                "use the older ACPI Processor() object form instead, which "
                "needs a different injection technique. Injecting a template "
                "built against a guessed path does nothing silently. Retry "
                "the build (SSDTTime may reach the real DSDT next time), or "
                "run SSDTTime yourself (https://github.com/corpnewt/SSDTTime) "
                "against this machine's DSDT and add the SSDT-PLUG.aml it "
                "produces to EFI/OC/ACPI manually."
            )
            continue

        cb(f"Generating {ssdt} from template...")
        if _build_from_template(ssdt, acpi_dir, ssdttime_dir, dsdt_info, cpu_generation):
            cb(f"  {ssdt}.aml (template)")
            results[ssdt] = "OK"
            continue

        if _use_bundled(ssdt, acpi_dir, cpu_generation):
            cb(f"  {ssdt}.aml (bundled fallback)")
            results[ssdt] = "OK"
            continue

        if not choice and ssdt not in ("SSDT-GPI0", "SSDT-GPIO", "SSDT-XOSI"):
            results[ssdt] = f"SKIP: '{ssdt}' not found in SSDTTime and no template available"
        else:
            results[ssdt] = f"ERROR: all generation methods failed for {ssdt}"

    return results


def generate_disable_ssdt(
    acpi_dir: Path,
    tmp: Path,
    device: int,
    function: int,
    ssdt_name: str = "SSDT-DSBL",
    table_id: str = "DSBL",
) -> str:
    import pci_disable

    dsdt = get_dsdt(tmp)
    if not dsdt:
        return "SKIP: no DSDT available"

    dsdt_data = dsdt.read_bytes()
    device_path = pci_disable.find_device_path_by_pci_address(dsdt_data, device, function)
    if not device_path:
        return "SKIP: device not found (or ambiguous) in DSDT"

    ssdttime_dir = SSDTTIME_DIR
    iasl = find_iasl(ssdttime_dir)
    dsl = pci_disable.build_disable_ssdt(device_path, table_id=table_id)
    if _compile_dsl(dsl, ssdt_name, acpi_dir, iasl):
        return f"OK: {device_path} disabled"
    return "ERROR: could not compile disable SSDT"
