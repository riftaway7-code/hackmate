"""
HackMate Bridge — newline-delimited JSON-RPC server over stdio.

Lets external frontends (e.g. the Flutter GUI in gui-flutter/) drive the same
backend used by hackmate.py (TUI) and hackmate_gui.py (Tkinter GUI) without
importing Python directly.

Protocol: one JSON object per line.
  Request:      {"id": <int>, "method": <str>, "params": {...}}
  Response:     {"id": <int>, "result": ...} or {"id": <int>, "error": <str>}
  Notification: {"request_id": <int>, "method": "progress"|"log", "data": {...}}

Notifications carry no "id" key, so a client can never confuse one with the
terminal response to the request that triggered it — match on "request_id"
instead, and only treat a message with no "method" key as a response.

Run with: python src/bridge.py   (or the elevated venv python on Windows)
"""

import sys
import json
import shutil
import uuid
import zipfile
import dataclasses
from pathlib import Path

import compat
from compat import is_admin, IS_WINDOWS
import build_history
import log_checker
import efi_health
import dualboot
import hwdb_submit
import config_editor
import hardware
import recovery
import rationale
import ocvalidate
import build_runner


def _to_jsonable(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def _write_line(obj: dict) -> None:
    try:
        line = json.dumps(obj)
    except Exception as exc:
        line = json.dumps({
            "request_id": obj.get("id", obj.get("request_id")),
            "method": "log",
            "data": {"level": "error", "message": f"serialization error: {exc}"},
        })
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _system_ping(params, emit):
    return {"ok": True, "admin": is_admin(), "platform": "windows" if IS_WINDOWS else "other"}


def _build_history_list(params, emit):
    return _to_jsonable(build_history.list_builds())


def _build_history_get(params, emit):
    entry_id = params["entry_id"]
    return _to_jsonable(build_history.get_build(entry_id))


def _build_history_delete(params, emit):
    entry_id = params["entry_id"]
    return {"deleted": build_history.delete_build(entry_id)}


def _log_checker_analyze_file(params, emit):
    path = params["path"]
    findings = log_checker.analyze_file(path)
    return _to_jsonable(findings)


def _efi_health_audit(params, emit):
    efi_root = Path(params["efi_root"])
    findings = efi_health.audit(efi_root)
    summary = efi_health.summarise(findings)
    return {
        "findings": [
            {"level": level, "title": title, "detail": detail}
            for level, title, detail in findings
        ],
        "summary": summary,
    }


def _dualboot_scan_disks(params, emit):
    disks = dualboot.scan_disks()
    bootloaders = dualboot.scan_all_bootloaders(disks)
    return {
        "disks": _to_jsonable(disks),
        "bootloaders": {part: _to_jsonable(info) for part, info in bootloaders.items()},
    }


def _usb_list_drives(params, emit):
    drives = compat.get_usb_drives()
    return {"drives": [{"device": d, "size": s, "label": l} for d, s, l in drives]}


BACKUPS_DIR = compat.real_home() / "HackMate" / "backups"


def _restore_list_backups(params, emit):
    if not BACKUPS_DIR.exists():
        return {"backups": []}
    backups = sorted(BACKUPS_DIR.glob("EFI_backup_*.zip"), reverse=True)
    return {
        "backups": [
            {
                "filename": b.name,
                "stem": b.stem,
                "size_kb": b.stat().st_size // 1024,
                "mtime": b.stat().st_mtime,
            }
            for b in backups
        ]
    }


def _restore_run(params, emit):
    device = params["device"]
    backup_filename = params["backup_filename"]
    confirm_phrase = params.get("confirm_phrase", "")

    expected_phrase = f"RESTORE {device}"
    if confirm_phrase != expected_phrase:
        raise ValueError(f"confirmation text did not match — type exactly: {expected_phrase}")

    drives = compat.get_usb_drives()
    if not any(d == device for d, _, _ in drives):
        raise RuntimeError(f"{device} is no longer connected — reconnect it and try again")

    candidates = {p.name: p for p in BACKUPS_DIR.glob("EFI_backup_*.zip")} if BACKUPS_DIR.exists() else {}
    backup_path = candidates.get(backup_filename)
    if backup_path is None:
        raise RuntimeError(f"backup not found: {backup_filename}")

    mnt_scratch = None
    if IS_WINDOWS:
        mount_root = Path(f"{compat.get_mount_path(device)}\\")
    else:
        mnt_scratch = Path(compat.get_tmp_dir()) / "hackmate_restore_mount"
        mnt_scratch.mkdir(parents=True, exist_ok=True)
        if not compat.mount_usb(device, str(mnt_scratch)):
            raise RuntimeError(f"Failed to mount {device}")
        mount_root = mnt_scratch

    emit("log", {"level": "info", "message": f"Restoring {backup_path.stem} to {device}..."})

    tmp_extract = mount_root / ".hackmate_restore_tmp"
    try:
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract)
        tmp_extract.mkdir(parents=True)

        with zipfile.ZipFile(backup_path, "r") as z:
            z.extractall(tmp_extract)
        new_efi = tmp_extract / "EFI"
        if not new_efi.is_dir():
            raise RuntimeError("Backup archive does not contain an EFI folder")

        efi_dest = mount_root / "EFI"
        efi_old = mount_root / ".hackmate_restore_old"
        if efi_old.exists():
            shutil.rmtree(efi_old)
        if efi_dest.exists():
            efi_dest.rename(efi_old)
        try:
            new_efi.rename(efi_dest)
        except Exception:
            if efi_old.exists() and not efi_dest.exists():
                efi_old.rename(efi_dest)
            raise
        if efi_old.exists():
            shutil.rmtree(efi_old)

        emit("log", {"level": "ok", "message": f"Restore complete — EFI from {backup_path.stem} written to {device}"})
    finally:
        shutil.rmtree(tmp_extract, ignore_errors=True)
        if mnt_scratch is not None:
            compat.unmount_usb(str(mnt_scratch))

    return {"ok": True}


def _usb_mapping_apply(params, emit):
    import plistlib

    device = params["device"]
    kext_src = Path(params["utbmap_kext_path"])

    if not kext_src.exists():
        raise RuntimeError("UTBMap.kext path not found")
    if not kext_src.name.lower().startswith("utbmap"):
        raise RuntimeError("Select the UTBMap.kext folder, not a file inside it")

    drives = compat.get_usb_drives()
    if not any(d == device for d, _, _ in drives):
        raise RuntimeError(f"{device} is no longer connected — reconnect it and try again")

    mount = compat.get_mount_path(device, skip_format=True)
    try:
        if not IS_WINDOWS:
            compat.mount_usb(device, mount)

        emit("log", {"level": "info", "message": f"Copying {kext_src.name} to {device}..."})
        kext_dest = Path(mount) / "EFI" / "OC" / "Kexts" / "UTBMap.kext"
        if kext_dest.exists():
            shutil.rmtree(kext_dest)
        shutil.copytree(kext_src, kext_dest)

        config_path = Path(mount) / "EFI" / "OC" / "config.plist"
        if config_path.exists():
            try:
                with open(config_path, "rb") as f:
                    cfg = plistlib.load(f)
                for entry in cfg.get("Kernel", {}).get("Add", []):
                    name = entry.get("BundlePath", "").split("/")[0]
                    if name in ("UTBMap.kext", "USBToolBox.kext"):
                        entry["Enabled"] = True
                cfg.setdefault("Kernel", {}).setdefault("Quirks", {})["XhciPortLimit"] = False
                with open(config_path, "wb") as f:
                    plistlib.dump(cfg, f)
                emit("log", {"level": "ok", "message": "config.plist updated (UTBMap enabled, XhciPortLimit off)"})
            except Exception as exc:
                emit("log", {"level": "warn", "message": f"Could not patch config.plist: {exc}"})

        emit("log", {"level": "ok", "message": f"UTBMap.kext applied to {device} — reboot to take effect"})
    finally:
        if not IS_WINDOWS:
            compat.unmount_usb(mount)

    return {"ok": True}


def _hardware_scan(params, emit):
    return _to_jsonable(hardware.scan())


def _hardware_warnings(params, emit):
    profile = hardware.HardwareProfile(**{
        k: v for k, v in params["profile"].items() if k in hardware.HardwareProfile.__dataclass_fields__
    })
    return {"warnings": hardware.hardware_warnings(profile)}


def _hardware_needs_dgpu_prompt(params, emit):
    profile = hardware.HardwareProfile(**{
        k: v for k, v in params["profile"].items() if k in hardware.HardwareProfile.__dataclass_fields__
    })
    return {"needed": hardware.needs_dgpu_disable_prompt(profile)}


def _hardware_manual_options(params, emit):
    return {
        "cpu_options": hardware.CPU_OPTIONS,
        "gpu_options": hardware.GPU_OPTIONS,
        "ethernet_options": hardware.ETHERNET_OPTIONS,
        "wifi_options": hardware.WIFI_OPTIONS,
        "cpu_meta": {k: list(v) for k, v in hardware.CPU_META.items()},
        "smbios_map": {f"{gen}|{platform}": model for (gen, platform), model in hardware.SMBIOS_MAP.items()},
    }


def _rationale_explain(params, emit):
    profile = hardware.HardwareProfile(**{
        k: v for k, v in params["profile"].items() if k in hardware.HardwareProfile.__dataclass_fields__
    })
    decisions = rationale.explain(
        profile,
        macos_major=int(params.get("macos_major", 0) or 0),
        wifi_kext_mode=params.get("wifi_kext_mode", "itlwm"),
        dual_boot=params.get("dual_boot", ""),
    )
    return {"decisions": rationale.to_rows(decisions), "text": rationale.render(decisions)}


def _hardware_save_spec(params, emit):
    profile = hardware.HardwareProfile(**{
        k: v for k, v in params["profile"].items() if k in hardware.HardwareProfile.__dataclass_fields__
    })
    hardware.save_spec(profile, params["path"], macos_major=int(params.get("macos_major", 0) or 0))
    return {"path": params["path"]}


def _hardware_load_spec(params, emit):
    profile, macos_major = hardware.load_spec(params["path"])
    return {"profile": _to_jsonable(profile), "macos_major": macos_major}


def _ocvalidate_check(params, emit):
    target = Path(params["path"])
    if target.is_dir():
        candidate = target / "EFI" / "OC" / "config.plist"
        if not candidate.exists():
            hits = list(target.rglob("config.plist"))
            candidate = hits[0] if hits else candidate
        target = candidate
    ok, lines = ocvalidate.validate(target)
    return {"ok": ok, "lines": lines, "config": str(target)}


def _recovery_compatible_versions(params, emit):
    versions = recovery.compatible_versions(
        params.get("cpu_gen", 0),
        params.get("gpu_vendor", ""),
        params.get("cpu_vendor", "intel"),
        params.get("cpu_codename", ""),
        params.get("gpu_name", ""),
        params.get("cpu_name", ""),
    )
    result = []
    for v in versions:
        d = _to_jsonable(v)
        d["major"] = v.major
        d["slug"] = v.slug
        result.append(d)
    return {"versions": result}


def _recovery_all_versions(params, emit):
    """All known macOS recovery versions, unfiltered by hardware — for
    standalone recovery downloads where the user may want any version."""
    result = []
    for v in recovery.MACOS_VERSIONS:
        d = _to_jsonable(v)
        d["major"] = v.major
        d["slug"] = v.slug
        result.append(d)
    return {"versions": result}


def _recovery_download(params, emit):
    version = recovery.MacOSVersion(**{
        k: v for k, v in params["macos_version"].items()
        if k in recovery.MacOSVersion.__dataclass_fields__
    })
    dest = Path(params["dest"])
    dest.mkdir(parents=True, exist_ok=True)

    def progress_cb(msg):
        emit("progress", {"message": msg})

    ok, msg = recovery.download_recovery(version, dest, progress_cb=progress_cb)
    return {"ok": ok, "message": msg, "dest": str(dest)}


def _build_run(params, emit):
    return build_runner.run(params, emit)


_config_sessions: dict[str, dict] = {}


def _config_editor_find_configs(params, emit):
    return {"paths": [str(p) for p in config_editor.find_configs()]}


def _config_editor_constants(params, emit):
    return {"boot_arg_presets": config_editor.BOOT_ARG_PRESETS}


def _config_session_summary(cfg: dict) -> dict:
    return {
        "kexts": [[name, enabled] for name, enabled in config_editor.get_kext_entries(cfg)],
        "acpi": [[name, enabled] for name, enabled in config_editor.get_acpi_entries(cfg)],
        "boot_args": config_editor.get_boot_args(cfg),
        "serial": config_editor.get_serial_info(cfg),
        "sip_enabled": config_editor.get_sip_enabled(cfg),
        "hide_auxiliary": config_editor.get_hide_auxiliary(cfg),
        "timeout": config_editor.get_timeout(cfg),
        "oc_logging": config_editor.get_oc_logging(cfg),
        "secure_boot_model": config_editor.get_secure_boot_model(cfg),
        "smbios_model": config_editor.get_smbios(cfg),
        "dgpu_disabled": config_editor.get_dgpu_disabled(cfg),
        "igpu_platform_id": config_editor.get_igpu_platform_id(cfg),
    }


def _config_editor_open(params, emit):
    path = Path(params["path"])
    cfg = config_editor.load_config(path)
    session_id = uuid.uuid4().hex
    _config_sessions[session_id] = {"cfg": cfg, "path": path}
    return {"session_id": session_id, "summary": _config_session_summary(cfg)}


def _get_config_session(params: dict) -> dict:
    session_id = params["session_id"]
    session = _config_sessions.get(session_id)
    if session is None:
        raise RuntimeError("config session expired or not found — reopen the file")
    return session


def _config_editor_set_kext_enabled(params, emit):
    session = _get_config_session(params)
    ok = config_editor.set_kext_enabled(session["cfg"], params["name"], bool(params["enabled"]))
    return {"ok": ok}


def _config_editor_set_acpi_enabled(params, emit):
    session = _get_config_session(params)
    ok = config_editor.set_acpi_entry_enabled(session["cfg"], params["name"], bool(params["enabled"]))
    return {"ok": ok}


def _config_editor_set_boot_args(params, emit):
    session = _get_config_session(params)
    config_editor.set_boot_args(session["cfg"], params["args"])
    return {"ok": True}


def _config_editor_set_serial_info(params, emit):
    session = _get_config_session(params)
    config_editor.set_serial_info(
        session["cfg"],
        serial=params.get("serial"),
        mlb=params.get("mlb"),
        uuid=params.get("uuid"),
        rom=params.get("rom"),
    )
    return {"ok": True}


def _config_editor_set_igpu_platform_id(params, emit):
    session = _get_config_session(params)
    config_editor.set_igpu_platform_id(session["cfg"], params["hex"])
    return {"ok": True}


def _config_editor_set_dgpu_disabled(params, emit):
    session = _get_config_session(params)
    config_editor.set_dgpu_disabled(session["cfg"], bool(params["disabled"]))
    return {"ok": True}


def _config_editor_set_simple(params, emit):
    session = _get_config_session(params)
    cfg = session["cfg"]
    if "sip_enabled" in params:
        config_editor.set_sip(cfg, bool(params["sip_enabled"]))
    if "hide_auxiliary" in params:
        config_editor.set_hide_auxiliary(cfg, bool(params["hide_auxiliary"]))
    if "timeout" in params:
        config_editor.set_timeout(cfg, int(params["timeout"]))
    if "oc_logging" in params:
        config_editor.set_oc_logging(cfg, bool(params["oc_logging"]))
    if "secure_boot_model" in params:
        config_editor.set_secure_boot_model(cfg, params["secure_boot_model"])
    if "smbios_model" in params:
        config_editor.set_smbios(cfg, params["smbios_model"])
    return {"ok": True}


def _config_editor_suggest_framebuffers(params, emit):
    return {"suggestions": config_editor.suggest_framebuffers(params["gpu_device_id"])}


def _config_editor_suggest_audio_layouts(params, emit):
    return {"suggestions": config_editor.suggest_audio_layouts(params["codec"])}


def _config_editor_get_raw_value(params, emit):
    session = _get_config_session(params)
    try:
        value = config_editor.get_value(session["cfg"], params["path"])
    except KeyError as exc:
        raise RuntimeError(f"key not found: {exc}")
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {"type": "data", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    return {"type": "other", "value": _to_jsonable(value)}


def _config_editor_set_raw_value(params, emit):
    session = _get_config_session(params)
    coerced = config_editor.coerce_value(params["value"], params["type"])
    config_editor.set_value(session["cfg"], params["path"], coerced)
    return {"ok": True}


def _config_editor_save(params, emit):
    session = _get_config_session(params)
    config_editor.save_config(session["path"], session["cfg"])
    return {"ok": True}


def _config_editor_close(params, emit):
    _config_sessions.pop(params["session_id"], None)
    return {"ok": True}


def _settings_get_log_sharing(params, emit):
    return {"enabled": hwdb_submit.has_consented()}


def _settings_set_log_sharing(params, emit):
    hwdb_submit.set_consent(bool(params["enabled"]))
    return {"enabled": hwdb_submit.has_consented()}


METHODS = {
    "system.ping": _system_ping,
    "build_history.list": _build_history_list,
    "build_history.get": _build_history_get,
    "build_history.delete": _build_history_delete,
    "log_checker.analyze_file": _log_checker_analyze_file,
    "efi_health.audit": _efi_health_audit,
    "dualboot.scan_disks": _dualboot_scan_disks,
    "settings.get_log_sharing": _settings_get_log_sharing,
    "settings.set_log_sharing": _settings_set_log_sharing,
    "usb.list_drives": _usb_list_drives,
    "restore.list_backups": _restore_list_backups,
    "restore.run": _restore_run,
    "usb_mapping.apply": _usb_mapping_apply,
    "config_editor.find_configs": _config_editor_find_configs,
    "config_editor.constants": _config_editor_constants,
    "config_editor.open": _config_editor_open,
    "config_editor.set_kext_enabled": _config_editor_set_kext_enabled,
    "config_editor.set_acpi_enabled": _config_editor_set_acpi_enabled,
    "config_editor.set_boot_args": _config_editor_set_boot_args,
    "config_editor.set_serial_info": _config_editor_set_serial_info,
    "config_editor.set_igpu_platform_id": _config_editor_set_igpu_platform_id,
    "config_editor.set_dgpu_disabled": _config_editor_set_dgpu_disabled,
    "config_editor.set_simple": _config_editor_set_simple,
    "config_editor.suggest_framebuffers": _config_editor_suggest_framebuffers,
    "config_editor.suggest_audio_layouts": _config_editor_suggest_audio_layouts,
    "config_editor.get_raw_value": _config_editor_get_raw_value,
    "config_editor.set_raw_value": _config_editor_set_raw_value,
    "config_editor.save": _config_editor_save,
    "config_editor.close": _config_editor_close,
    "hardware.scan": _hardware_scan,
    "hardware.warnings": _hardware_warnings,
    "hardware.needs_dgpu_prompt": _hardware_needs_dgpu_prompt,
    "hardware.manual_options": _hardware_manual_options,
    "rationale.explain": _rationale_explain,
    "ocvalidate.check": _ocvalidate_check,
    "hardware.save_spec": _hardware_save_spec,
    "hardware.load_spec": _hardware_load_spec,
    "recovery.compatible_versions": _recovery_compatible_versions,
    "recovery.all_versions": _recovery_all_versions,
    "recovery.download": _recovery_download,
    "build.run": _build_run,
}


def _handle(request: dict) -> dict:
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}
    handler = METHODS.get(method)
    if handler is None:
        return {"id": req_id, "error": f"unknown method: {method}"}

    def emit(evt_method: str, data) -> None:
        _write_line({"request_id": req_id, "method": evt_method, "data": _to_jsonable(data)})

    try:
        result = handler(params, emit)
    except Exception as exc:
        return {"id": req_id, "error": str(exc)}
    return {"id": req_id, "result": result}


def main():
    if not is_admin():
        _write_line({"method": "fatal", "data": "HackMate Bridge requires administrator privileges."})
        sys.exit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_line({"id": None, "error": f"invalid JSON: {exc}"})
            continue
        _write_line(_handle(request))


if __name__ == "__main__":
    main()
