"""
Orchestrates a full EFI build/repair for the bridge, mirroring
hackmate_gui.py's InstallScreen.run_install step for step so the Flutter
frontend produces byte-identical output to the Tkinter GUI.
"""

import datetime
import plistlib
import shutil
import traceback
import zipfile
from pathlib import Path

import compat
from compat import IS_WINDOWS
from hardware import HardwareProfile
from recovery import MacOSVersion, download_recovery, _ensure_cert_bundle_env
from smbios import generate as gen_smbios, SMBIOSData
from config_gen import (
    generate as gen_config, write_plist, sync_executable_paths,
    strip_missing_ssdts, _required_ssdts,
)
from kexts import select_kexts, download_kexts, download_heliport, download_usbtoolbox_app, fetch_opencore
from auto_usb_map import generate_auto_map, write_map_kext
from ssdt import generate as gen_ssdts, generate_disable_ssdt
from efi_check import check as efi_check
from config_editor import set_dgpu_disabled
import build_history
import hwdb_submit


def _profile_from_dict(d: dict) -> HardwareProfile:
    return HardwareProfile(**{k: v for k, v in d.items() if k in HardwareProfile.__dataclass_fields__})


def _version_from_dict(d: dict) -> MacOSVersion:
    return MacOSVersion(**{k: v for k, v in d.items() if k in MacOSVersion.__dataclass_fields__})


def run(params: dict, emit) -> dict:
    _ensure_cert_bundle_env()

    profile = _profile_from_dict(params["profile"])
    version = _version_from_dict(params["macos_version"]) if params.get("macos_version") else None
    device: str = params["device"]
    repair: bool = bool(params.get("repair", False))
    skip_format: bool = bool(params.get("skip_format", False))
    wifi_kext_mode: str = params.get("wifi_kext_mode", "itlwm")
    disable_dgpu: bool = bool(params.get("disable_dgpu", False))
    dual_boot: str = params.get("dual_boot", "")
    hackmate_core: bool = bool(params.get("hackmate_core", False))
    local_output_path: str = params.get("local_output_path", "")
    confirm_phrase: str = params.get("confirm_phrase", "")

    local_mode = (device == "local")

    expected_phrase = f"WRITE {device}"
    if confirm_phrase != expected_phrase:
        raise ValueError(f"confirmation text did not match — type exactly: {expected_phrase}")

    if not local_mode:
        drives = compat.get_usb_drives()
        if not any(d == device for d, _, _ in drives):
            raise RuntimeError(f"{device} is no longer connected — reconnect it and try again")

    tmp = Path(compat.get_tmp_dir())
    tmp.mkdir(parents=True, exist_ok=True)
    mount = local_output_path if local_mode else compat.get_mount_path(device, skip_format=(skip_format or repair))

    log_lines: list[str] = []

    def ui(pct, msg):
        emit("progress", {"pct": pct, "message": msg})

    def log(msg, level="info"):
        log_lines.append(msg)
        emit("log", {"level": level, "message": msg})

    config_path = None
    truly_manual: list[str] = []

    try:
        if local_mode:
            ui(2, "Preparing EFI output folder...")
            log("── Local EFI mode: generating EFI folder without USB", "header")
            Path(mount).mkdir(parents=True, exist_ok=True)
            log(f"Output folder: {mount}", "ok")
        elif repair or skip_format:
            ui(2, "Mounting USB partition...")
            if repair:
                log("── Repair mode: skipping format and recovery download", "header")
            else:
                log("── Already formatted: skipping format step", "header")
            if not IS_WINDOWS:
                if not compat.mount_usb(device, mount):
                    raise RuntimeError(f"Failed to mount {device}")
            log(f"Mounted at {mount}", "ok")

            existing_efi = Path(f"{mount}") / "EFI" if not IS_WINDOWS else Path(f"{mount}\\EFI")
            if repair and existing_efi.exists():
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = compat.real_home() / "HackMate" / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_zip = backup_dir / f"EFI_backup_{ts}.zip"
                file_count = 0
                mount_root = Path(f"{mount}\\") if IS_WINDOWS else Path(f"{mount}")
                with zipfile.ZipFile(backup_zip, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in existing_efi.rglob("*"):
                        if f.is_file():
                            z.write(f, f.relative_to(mount_root))
                            file_count += 1
                size_mb = backup_zip.stat().st_size / 1024 / 1024
                log(f"── EFI backed up: {file_count} files, {size_mb:.1f} MB → {backup_zip}", "ok")
        else:
            ui(2, f"Formatting {device} as FAT32...")
            log(f"── Formatting {device}...", "header")
            fmt_ok = compat.format_usb(device, mount)
            if not fmt_ok:
                raise RuntimeError(f"Failed to format {device}")
            log(f"Formatted {device} as FAT32 (GPT+ESP)", "ok")

        ui(8, "Creating EFI structure...")
        efi = Path(f"{mount}") / "EFI" if not IS_WINDOWS else Path(f"{mount}\\EFI")
        oc_dir = efi / "OC"
        boot_dir = efi / "BOOT"
        kext_dir = oc_dir / "Kexts"
        acpi_dir = oc_dir / "ACPI"
        driver_dir = oc_dir / "Drivers"
        for d in [efi, oc_dir, boot_dir, kext_dir, acpi_dir, driver_dir]:
            d.mkdir(parents=True, exist_ok=True)
        log("EFI folder structure ready.", "ok")

        if not repair and not local_mode:
            ui(10, f"Downloading {version.name} recovery from Apple...")
            log(f"── Fetching {version.name} from Apple CDN...", "header")
            recovery_dest = tmp / "recovery"

            def recovery_progress(msg):
                level = "ok" if ("complete" in msg.lower() or "verification" in msg.lower()) else "info"
                log(f"  {msg}", level)

            ok, msg = download_recovery(version, recovery_dest, progress_cb=recovery_progress)
            if not ok:
                raise RuntimeError(f"Recovery download failed: {msg}")
            log(msg, "ok")

            ui(28, "Copying recovery to USB...")
            log("── Copying recovery to USB (may take 1-2 min for large images)...", "header")
            files = list(recovery_dest.iterdir())
            total_bytes = sum(f.stat().st_size for f in files if f.is_file())
            log(f"  {len(files)} file(s), {total_bytes // 1024 // 1024} MB to write", "info")
            com_apple = efi.parent / "com.apple.recovery.boot"
            if com_apple.exists():
                shutil.rmtree(str(com_apple))
            com_apple.mkdir(parents=True)
            for src in files:
                mb = src.stat().st_size // 1024 // 1024
                log(f"  Writing {src.name} ({mb} MB)...", "info")
                shutil.copy2(str(src), str(com_apple / src.name))
                log(f"  {src.name} written", "ok")
            log("Recovery copied to USB.", "ok")
        else:
            log("  Skipping recovery download (repair mode)", "info")

        ui(35, "Generating SMBIOS...")
        log("── Generating SMBIOS...", "header")
        smbios = None

        if repair:
            existing_config = oc_dir / "config.plist"
            if existing_config.exists():
                try:
                    with open(str(existing_config), "rb") as f:
                        old_cfg = plistlib.load(f)
                    pi = old_cfg.get("PlatformInfo", {}).get("Generic", {})
                    if pi.get("SystemSerialNumber") and pi.get("MLB"):
                        smbios = SMBIOSData(
                            model=pi.get("SystemProductName", profile.smbios_model),
                            serial=pi["SystemSerialNumber"],
                            board_serial=pi["MLB"],
                            system_uuid=pi.get("SystemUUID", ""),
                            rom=pi.get("ROM", b"").hex() if isinstance(pi.get("ROM"), bytes) else pi.get("ROM", ""),
                        )
                        log("  Reusing existing SMBIOS (serial preserved)", "ok")
                except Exception as e:
                    log(f"  Could not read existing SMBIOS ({e}), generating fresh", "info")
        elif not local_mode:
            # A full (non-repair) build reformats the USB, which would wipe
            # any prior config.plist — except when skip_format is set, where
            # the old EFI (and its real SMBIOS identity) is still sitting
            # right there. Regenerating without warning silently invalidates
            # the existing USB port map and can reset app-license activation
            # tied to the old serial/MLB.
            existing_config = oc_dir / "config.plist"
            if existing_config.exists():
                try:
                    with open(str(existing_config), "rb") as f:
                        old_cfg = plistlib.load(f)
                    old_serial = old_cfg.get("PlatformInfo", {}).get("Generic", {}).get("SystemSerialNumber", "")
                    if old_serial and not old_serial.startswith("0000000"):
                        log(
                            f"  This EFI already has a real SMBIOS identity (serial {old_serial}). "
                            "A fresh Build generates a new one, which invalidates any existing USB "
                            "port map and can reset app-license activation tied to the old identity. "
                            "Use Repair EFI instead if this system is already installed and working.",
                            "warn",
                        )
                except Exception:
                    pass

        if smbios is None:
            smbios = gen_smbios(profile)

        log(f"  Model:   {smbios.model}", "ok")
        log(f"  Serial:  {smbios.serial}", "ok")
        log(f"  MLB:     {smbios.board_serial}", "ok")
        log(f"  UUID:    {smbios.system_uuid}", "ok")

        ui(40, "Generating config.plist...")
        log("── Generating config.plist...", "header")
        macos_major = version.major if version else 0
        config = gen_config(profile, smbios, macos_major, wifi_kext_mode=wifi_kext_mode, dual_boot=dual_boot, hackmate_core=hackmate_core)
        if disable_dgpu:
            set_dgpu_disabled(config, True)
            log("  dGPU disabled in DeviceProperties", "ok")
        config_path = oc_dir / "config.plist"
        write_plist(config, config_path)
        log(f"  config.plist written ({config_path.stat().st_size} bytes)", "ok")

        ui(45, "Selecting kexts...")
        log("── Selecting kexts...", "header")
        kexts = select_kexts(profile, wifi_kext_mode=wifi_kext_mode)
        log(f"  {len(kexts)} kexts selected for this hardware", "ok")

        ui(50, f"{'Verifying' if repair else 'Downloading'} {len(kexts)} kexts...")
        log(f"── {'Verifying and updating' if repair else 'Downloading'} kexts from GitHub...", "header")

        def kext_progress(i, n, msg):
            pct = 50 + int((i / n) * 30)
            ui(pct, msg)
            log(f"  [{i + 1}/{n}] {msg}", "info")

        results = download_kexts(
            kexts, kext_dir, progress_cb=kext_progress, verify=repair,
            macos_version=version.version if version else "",
        )
        ok_count = sum(1 for v in results.values() if v.startswith("OK"))
        log(f"  {ok_count} kexts downloaded successfully", "ok")
        failed_kexts = {name for name, res in results.items() if res.startswith("ERROR")}
        for name, result in results.items():
            if result.startswith("ERROR"):
                log(f"  WARN: {name} — {result}", "warn")

        cfg = plistlib.loads(config_path.read_bytes())

        if failed_kexts:
            before = len(cfg["Kernel"]["Add"])
            cfg["Kernel"]["Add"] = [
                k for k in cfg["Kernel"]["Add"]
                if not any(name in k.get("BundlePath", "") for name in failed_kexts)
            ]
            removed = before - len(cfg["Kernel"]["Add"])
            if removed:
                log(f"  Removed {removed} failed kext(s) from config.plist to keep EFI bootable", "warn")

        corrected = sync_executable_paths(cfg, kext_dir)
        if corrected:
            log(f"  Corrected ExecutablePath for {len(corrected)} kext(s)", "ok")

        config_path.write_bytes(plistlib.dumps(cfg, fmt=plistlib.FMT_XML))

        extras_dir = Path(mount) / "EFI" / "HackMate-Extras"
        if wifi_kext_mode == "itlwm":
            heliport_ok = download_heliport(extras_dir, progress_cb=lambda m: log(f"  {m}", "info"))
            if heliport_ok:
                log("  HeliPort saved to EFI/HackMate-Extras/", "ok")
            else:
                log("  HeliPort download failed — get it from github.com/OpenIntelWireless/HeliPort", "warn")
        usbtoolbox_zip = download_usbtoolbox_app(extras_dir, progress_cb=lambda m: log(f"  {m}", "info"))
        if usbtoolbox_zip:
            log("  USBToolBox app saved to EFI/HackMate-Extras/", "ok")
        else:
            log("  USBToolBox download failed — get it from github.com/USBToolBox/Tool", "warn")

        auto_map = generate_auto_map(usbtoolbox_zip, tmp, log=log)
        if auto_map:
            write_map_kext(auto_map, kext_dir)
            for entry in cfg.get("Kernel", {}).get("Add", []):
                name = entry.get("BundlePath", "").split("/")[0]
                if name in ("UTBMap.kext", "USBToolBox.kext"):
                    entry["Enabled"] = True
            cfg.setdefault("Kernel", {}).setdefault("Quirks", {})["XhciPortLimit"] = False
            corrected = sync_executable_paths(cfg, kext_dir)
            if corrected:
                log(f"  Corrected ExecutablePath for {len(corrected)} kext(s): {', '.join(corrected)}", "ok")
            config_path.write_bytes(plistlib.dumps(cfg, fmt=plistlib.FMT_XML))
            log("  UTBMap.kext auto-generated and enabled — run USB Mapping later for a more precise map", "ok")

        min_efi = 50 * 1024
        min_hfsplus = 20 * 1024
        oc_required = [
            (boot_dir / "BOOTx64.efi", min_efi),
            (oc_dir / "OpenCore.efi", min_efi),
            (driver_dir / "OpenRuntime.efi", min_efi),
            (driver_dir / "HfsPlus.efi", min_hfsplus),
        ]
        oc_valid = repair and all(f.exists() and f.stat().st_size > min_size for f, min_size in oc_required)

        if oc_valid:
            ui(88, "OpenCore files valid — skipping download")
            log("── OpenCore already valid, skipping download", "ok")
        else:
            ui(82, "Downloading OpenCore...")
            log("── Downloading OpenCore...", "header")
            oc_zip = fetch_opencore(tmp, log)

            if oc_zip:
                log(f"  Downloaded {oc_zip.name}", "ok")

                oc_extract = tmp / "oc_extracted"
                with zipfile.ZipFile(str(oc_zip)) as z:
                    z.extractall(str(oc_extract))

                x64_root = oc_extract / "X64"
                search_root = x64_root if x64_root.exists() else oc_extract

                for fname, fdest in [
                    ("BOOTx64.efi", boot_dir / "BOOTx64.efi"),
                    ("OpenCore.efi", oc_dir / "OpenCore.efi"),
                ]:
                    found = list(search_root.rglob(fname))
                    if found:
                        shutil.copy(str(found[0]), str(fdest))
                        log(f"  {fname} copied", "ok")

                base_drivers = ["OpenRuntime.efi", "HfsPlus.efi", "ResetNvramEntry.efi"]
                if dual_boot in ("linux", "both"):
                    base_drivers.append("OpenLinuxBoot.efi")
                for driver in base_drivers:
                    found = list(search_root.rglob(driver))
                    if found:
                        shutil.copy(str(found[0]), str(driver_dir / driver))
                        log(f"  Driver: {driver}", "ok")

                hfsplus_dest = driver_dir / "HfsPlus.efi"
                if not hfsplus_dest.exists():
                    log("  HfsPlus.efi not in OC zip — fetching from OcBinaryData...", "info")
                    hfsplus_url = "https://raw.githubusercontent.com/acidanthera/OcBinaryData/master/Drivers/HfsPlus.efi"
                    last_err = None
                    for attempt in range(3):
                        try:
                            data = compat.http_get(hfsplus_url, timeout=15)
                            if not compat.is_valid_pe_binary(data, min_hfsplus):
                                raise ValueError(f"corrupt download ({len(data)} bytes, bad PE header)")
                            hfsplus_dest.write_bytes(data)
                            log("  HfsPlus.efi downloaded", "ok")
                            break
                        except Exception as e:
                            last_err = e
                            log(f"  HfsPlus.efi download attempt {attempt + 1}/3 failed: {e}", "warn")
                    else:
                        log(f"  HfsPlus.efi download failed: {last_err}", "error")

                if hackmate_core:
                    try:
                        import hackmate_core as _hc

                        if _hc.available():
                            _hc.install_resources(oc_dir, search_root, log=log)
                        else:
                            log("  HackMate-Core: theme assets missing, skipped", "warn")
                    except Exception as e:
                        log(f"  HackMate-Core: install failed: {e}", "error")
            else:
                log("  Could not find OpenCore release asset", "error")

        ssdt_backup_dir = None
        if repair and acpi_dir.exists() and any(acpi_dir.iterdir()):
            ssdt_backup_dir = tmp / "acpi_backup"
            shutil.copytree(str(acpi_dir), str(ssdt_backup_dir))
            shutil.rmtree(str(acpi_dir))
            acpi_dir.mkdir(parents=True)

        ui(90, "Generating SSDTs with SSDTTime...")
        log("── Generating SSDTs with SSDTTime...", "header")
        ssdts = _required_ssdts(profile, kexts)
        log(f"  Need: {', '.join(ssdts)}", "info")

        ssdt_results = gen_ssdts(
            needed=ssdts,
            acpi_dir=acpi_dir,
            tmp=tmp,
            progress_cb=lambda m: log(f"  {m}", "info"),
            cpu_generation=profile.cpu_generation,
        )

        ok_ssdts = [n for n, s in ssdt_results.items() if s == "OK"]
        skip_ssdts = [n for n, s in ssdt_results.items() if s.startswith("SKIP")]
        err_ssdts = [n for n, s in ssdt_results.items() if s.startswith("ERROR")]

        if repair and ssdt_backup_dir and not ok_ssdts:
            log("  All SSDTs failed — restoring previous SSDTs", "warn")
            shutil.rmtree(str(acpi_dir))
            shutil.copytree(str(ssdt_backup_dir), str(acpi_dir))

        if skip_ssdts or err_ssdts:
            with open(str(config_path), "rb") as f:
                cfg = plistlib.load(f)
            missing = [n for n in skip_ssdts + err_ssdts if not (acpi_dir / f"{n}.aml").exists()]
            _, patches_gone = strip_missing_ssdts(cfg, missing)
            with open(str(config_path), "wb") as f:
                plistlib.dump(cfg, f)
            if patches_gone:
                log(f"  Removed {patches_gone} ACPI rename(s) left without their SSDT", "info")

        if profile.wifi_chipset == "realtek" and profile.wifi_pci_device >= 0:
            disable_result = generate_disable_ssdt(
                acpi_dir, tmp,
                profile.wifi_pci_device, max(profile.wifi_pci_function, 0),
                ssdt_name="SSDT-DSBL-WIFI", table_id="WIFI",
            )
            log(f"  Realtek WiFi disable SSDT: {disable_result}", "info")
            if disable_result.startswith("OK"):
                with open(str(config_path), "rb") as f:
                    cfg = plistlib.load(f)
                cfg.setdefault("ACPI", {}).setdefault("Add", []).append({
                    "Comment": "SSDT-DSBL-WIFI",
                    "Enabled": True,
                    "Path": "SSDT-DSBL-WIFI.aml",
                })
                with open(str(config_path), "wb") as f:
                    plistlib.dump(cfg, f)

        for n in ok_ssdts:
            log(f"  {n}.aml", "ok")
        for n in skip_ssdts:
            reason = ssdt_results.get(n, "")
            not_required = "not required" in reason or "not present" in reason
            log(f"  {n} — {reason}", "info" if not_required else "warn")
        for n in err_ssdts:
            log(f"  {n} — {ssdt_results[n]}", "error")

        truly_manual = [
            n for n in skip_ssdts + err_ssdts
            if not ("not required" in ssdt_results.get(n, "") or "not present" in ssdt_results.get(n, ""))
        ]
        if truly_manual:
            note = acpi_dir / "README_MANUAL_SSDTS.txt"
            note.write_text(
                "These SSDTs need manual installation:\n\n"
                + "\n".join(f"  - {n}.aml" for n in truly_manual)
                + "\n\nDownload prebuilt SSDTs from:\n"
                "  https://dortania.github.io/Getting-Started-With-ACPI/\n"
            )
            log(f"  {len(truly_manual)} SSDTs need manual install — see README_MANUAL_SSDTS.txt", "warn")

        ui(97, "Running EFI sanity check...")
        log("", "info")
        log("── EFI Sanity Check ──────────────────────────────", "header")
        issues = efi_check(efi, profile)
        errors = [m for lvl, m in issues if lvl == "error"]
        warnings = [m for lvl, m in issues if lvl == "warn"]
        infos = [m for lvl, m in issues if lvl == "info"]
        oks = [m for lvl, m in issues if lvl == "ok"]
        for lvl, m in issues:
            if lvl != "ok":
                prefix = {"error": "✗", "warn": "⚠", "info": "ℹ"}.get(lvl, "•")
                log(f"  {prefix} {m}", lvl)
        if oks:
            log(f"  ✓ {len(oks)} checks passed", "ok")
        log("──────────────────────────────────────────────────", "header")
        if errors:
            log(f"  {len(errors)} error(s) — must fix before booting", "error")
            if warnings:
                log(f"  {len(warnings)} warning(s)", "warn")
            if infos:
                log(f"  {len(infos)} recommendation(s)", "info")
        elif warnings:
            log(f"  {len(warnings)} warning(s) — review before booting", "warn")
            if infos:
                log(f"  {len(infos)} recommendation(s)", "info")
        elif infos:
            log(f"  {len(infos)} recommendation(s) — {len(oks)} checks passed", "info")
        else:
            log(f"  All {len(oks)} checks passed", "ok")

        if not local_mode:
            ui(99, "Unmounting USB...")
            compat.unmount_usb(mount)
        shutil.rmtree(str(tmp), ignore_errors=True)

        if local_mode:
            ui(100, "EFI folder ready!")
            log("", "info")
            log("══════════════════════════════════════════════════", "header")
            log("  EFI folder generated!", "ok")
            log(f"  Saved to: {mount}", "info")
            if truly_manual:
                log("  ! Some SSDTs need manual install (see README_MANUAL_SSDTS.txt)", "warn")
            log("  Copy the EFI folder to your drive's EFI partition.", "info")
            log("══════════════════════════════════════════════════", "header")
        else:
            mode_label = "Repair complete" if repair else f"Done! {version.name} EFI ready"
            ui(100, f"{mode_label} on {device}")
            log("", "info")
            log("══════════════════════════════════════════════════", "header")
            log("  USB is ready!", "ok")
            if truly_manual:
                log("  ! Some SSDTs need manual install (see README_MANUAL_SSDTS.txt)", "warn")
            log("  Configure BIOS settings, then boot from the USB.", "info")
            log("══════════════════════════════════════════════════", "header")

        try:
            feature = "no_usb" if local_mode else ("repair" if repair else ("skip_format" if skip_format else "full"))
            log_text = hwdb_submit.build_log(
                profile, feature, version.name if version else "unknown",
                worked="build completed", issues="none", dual_boot=dual_boot,
                wifi_kext_mode=wifi_kext_mode, full_log="\n".join(log_lines),
            )
            hwdb_submit.submit_log(profile, feature, log_text, dual_boot=dual_boot)
        except Exception:
            pass

        try:
            build_history.save_build(
                profile=profile,
                macos_version=version.name if version else "unknown",
                config_path=config_path,
                efi_output_path=Path(mount),
                wifi_kext_mode=wifi_kext_mode,
                dual_boot=dual_boot,
            )
        except Exception:
            pass

        return {
            "ok": True,
            "efi_path": str(efi),
            "needs_manual_ssdts": truly_manual,
            "show_bios_checklist": (not repair and not local_mode),
            "macos_name": version.name if version else "",
            "device": device,
        }

    except Exception as e:
        ui(0, f"Error: {e}")
        log(f"FATAL: {e}", "error")
        log(traceback.format_exc(), "error")
        try:
            compat.unmount_usb(mount)
        except Exception:
            pass
        shutil.rmtree(str(tmp), ignore_errors=True)

        try:
            feature = "no_usb" if local_mode else ("repair" if repair else ("skip_format" if skip_format else "full"))
            issues = str(e)
            tb = traceback.extract_tb(e.__traceback__)
            if tb:
                last = tb[-1]
                issues = f"{e} (at {Path(last.filename).name}:{last.lineno} in {last.name}: {last.line})"
            log_text = hwdb_submit.build_log(
                profile, feature, version.name if version else "unknown",
                worked="build failed", issues=issues, dual_boot=dual_boot,
                wifi_kext_mode=wifi_kext_mode, full_log="\n".join(log_lines),
            )
            hwdb_submit.submit_log(profile, feature, log_text, dual_boot=dual_boot)
        except Exception:
            pass

        raise
