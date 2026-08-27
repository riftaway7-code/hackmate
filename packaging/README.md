# packaging/

## `hiddenimports_desktop.txt` / `hiddenimports_bridge.txt`

Single source of truth for PyInstaller's `--hidden-import` list — one module name per line, no comments (both the CI workflow and `HackMate-GUI.spec` parse these as plain line lists).

- `hiddenimports_desktop.txt` — shared by the TUI (`src/hackmate.py`) and Tkinter GUI (`src/hackmate_gui.py`) builds. Their dependency sets have always been identical in practice, so one file covers both.
- `hiddenimports_bridge.txt` — the JSON-RPC bridge (`src/bridge.py`), used by the Flutter GUI. Its import graph is different (no `tkinter`, no `i18n`, etc.), so it's tracked separately.

**When you add a new `src/*.py` module that any of these entry points import**, add it to the relevant file here — it's the only place that needs updating now. Previously this list was duplicated by hand across `.github/workflows/build-exe.yml` (twice) and `HackMate-GUI.spec` (a fourth copy that had already drifted — it was missing `updater`), so a new module was 3-4 places to remember and easy to miss in one of them.

## `hwdb_relay/`

Cloudflare Worker backing the opt-in hardware-DB submission feature (`src/hwdb_submit.py`). See `hwdb_relay/DEPLOY.md`.
