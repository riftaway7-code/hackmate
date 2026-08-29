"""Minimal i18n layer — currently covers only the welcome-screen menu labels
(the `welcome.*` keys below), not the rest of the TUI/GUI (hardware
detection output, config editor, log checker, error messages, wizard flows
are all English-only and not routed through t()). Treat this as a proof of
concept / starting point, not full localization — if you're adding a new
user-facing string elsewhere, it does not need to go through this module
unless you're also extending real coverage to that screen."""

import json
from pathlib import Path
from typing import Optional

from compat import real_home

_CONFIG_PATH = real_home() / ".hackmate" / "settings.json"

_LANGUAGES = ("en", "es", "pt", "zh")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "welcome.subtitle": "Automated OpenCore EFI builder — any hardware",
        "welcome.build_efi": "Build EFI",
        "welcome.build_efi_manual": "Build EFI (Manual)",
        "welcome.pro": "HackMate Pro ($5)",
        "welcome.health_check": "EFI Health Check",
        "welcome.restore_efi": "Restore EFI",
        "welcome.download_recovery": "Download Recovery",
        "welcome.dual_boot": "Dual Boot / Disk Map",
        "welcome.usb_mapping": "USB Mapping",
        "welcome.edit_config": "Edit Config",
        "welcome.check_logs": "Check Logs",
        "welcome.build_history": "Build History",
        "welcome.sharing_on": "Sharing build logs: ON",
        "welcome.sharing_off": "Sharing build logs: OFF",
        "welcome.language": "Language",
        "welcome.quit": "Quit",
    },
    "es": {
        "welcome.subtitle": "Generador automático de EFI OpenCore — cualquier hardware",
        "welcome.build_efi": "Compilar EFI",
        "welcome.build_efi_manual": "Compilar EFI (Manual)",
        "welcome.pro": "HackMate Pro ($5)",
        "welcome.health_check": "Verificación de salud del EFI",
        "welcome.restore_efi": "Restaurar EFI",
        "welcome.download_recovery": "Descargar Recovery",
        "welcome.dual_boot": "Arranque dual / Mapa de disco",
        "welcome.usb_mapping": "Mapeo de USB",
        "welcome.edit_config": "Editar configuración",
        "welcome.check_logs": "Ver registros",
        "welcome.build_history": "Historial de compilaciones",
        "welcome.sharing_on": "Compartir registros de compilación: ACTIVADO",
        "welcome.sharing_off": "Compartir registros de compilación: DESACTIVADO",
        "welcome.language": "Idioma",
        "welcome.quit": "Salir",
    },
    "pt": {
        "welcome.subtitle": "Gerador automático de EFI OpenCore — qualquer hardware",
        "welcome.build_efi": "Compilar EFI",
        "welcome.build_efi_manual": "Compilar EFI (Manual)",
        "welcome.pro": "HackMate Pro ($5)",
        "welcome.health_check": "Verificação de integridade do EFI",
        "welcome.restore_efi": "Restaurar EFI",
        "welcome.download_recovery": "Baixar Recovery",
        "welcome.dual_boot": "Dual Boot / Mapa de disco",
        "welcome.usb_mapping": "Mapeamento USB",
        "welcome.edit_config": "Editar configuração",
        "welcome.check_logs": "Verificar registros",
        "welcome.build_history": "Histórico de compilações",
        "welcome.sharing_on": "Compartilhar registros de compilação: ATIVADO",
        "welcome.sharing_off": "Compartilhar registros de compilação: DESATIVADO",
        "welcome.language": "Idioma",
        "welcome.quit": "Sair",
    },
    "zh": {
        "welcome.subtitle": "自动化 OpenCore EFI 构建工具 — 支持任何硬件",
        "welcome.build_efi": "构建 EFI",
        "welcome.build_efi_manual": "构建 EFI（手动）",
        "welcome.pro": "HackMate Pro（$5）",
        "welcome.health_check": "EFI 健康检查",
        "welcome.restore_efi": "恢复 EFI",
        "welcome.download_recovery": "下载恢复系统",
        "welcome.dual_boot": "双系统 / 磁盘映射",
        "welcome.usb_mapping": "USB 映射",
        "welcome.edit_config": "编辑配置",
        "welcome.check_logs": "查看日志",
        "welcome.build_history": "构建历史",
        "welcome.sharing_on": "共享构建日志：开启",
        "welcome.sharing_off": "共享构建日志：关闭",
        "welcome.language": "语言",
        "welcome.quit": "退出",
    },
}

_LANGUAGE_NAMES = (
    ("en", "English"),
    ("es", "Español"),
    ("pt", "Português"),
    ("zh", "简体中文"),
)

_current_language: Optional[str] = None


def _read_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return {}


def get_language() -> str:
    global _current_language
    if _current_language is not None:
        return _current_language
    lang = _read_config().get("language", "en")
    _current_language = lang if lang in _LANGUAGES else "en"
    return _current_language


def set_language(lang: str) -> None:
    global _current_language
    if lang not in _LANGUAGES:
        lang = "en"
    _current_language = lang
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = _read_config()
    data["language"] = lang
    _CONFIG_PATH.write_text(json.dumps(data, indent=2))


def t(key: str) -> str:
    lang = get_language()
    table = _STRINGS.get(lang, _STRINGS["en"])
    return table.get(key) or _STRINGS["en"].get(key) or key


def available_languages() -> list[tuple[str, str]]:
    return list(_LANGUAGE_NAMES)
