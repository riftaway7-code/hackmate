"""
One-time "what's new" notice for the HackMate-Core graphical boot picker.
Mirrors discord_prompt.py's storage pattern (shared ~/.hackmate/ dir,
SUDO_USER-aware home resolution).
"""

import json
from pathlib import Path


def _real_home() -> Path:
    import os
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


_NOTICE_PATH = _real_home() / ".hackmate" / "hackmate_core_notice.json"


def already_shown() -> bool:
    return _NOTICE_PATH.exists()


def mark_shown() -> None:
    _NOTICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _NOTICE_PATH.write_text(json.dumps({"shown": True}))
