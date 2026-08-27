# HackMate — Flutter GUI

A native desktop GUI for [HackMate](../README.md), the OpenCore Hackintosh EFI builder. This is a third UI on top of the same backend the TUI (`src/hackmate.py`) and Tkinter GUI (`src/hackmate_gui.py`) use — it doesn't reimplement any hardware detection, config generation, or kext logic itself.

## How it talks to the backend

This app never imports Python. It spawns `hackmate-bridge` (built from `src/bridge.py`) as a subprocess and speaks newline-delimited JSON-RPC with it over stdin/stdout — see `lib/bridge/bridge_client.dart`. Each request gets a response keyed by `id`; the bridge also pushes unsolicited `progress`/`log` notifications keyed by `request_id` during long-running operations (a build, a recovery download) so the UI can stream status without polling.

`bridge_client.dart` looks for `hackmate-bridge(.exe)` bundled next to the Flutter executable first, falling back to other locations for local development — see `_startBackend`/`_startPython` in that file if you need to point it at a dev build.

## Structure

- `lib/app.dart`, `lib/main.dart` — app entry point and top-level widget tree
- `lib/home_shell.dart`, `lib/widgets/side_menu.dart` — the shell/navigation frame around each screen
- `lib/bridge/bridge_client.dart` — the JSON-RPC client described above
- `lib/screens/` — one screen per HackMate feature: build wizard (`build_efi/`), config editor (`config_editor/`), EFI health check, log checker, USB mapping, disk map, recovery download, restore, build history, settings
- `lib/widgets/async_screen.dart` — shared loading/error-state wrapper used by most screens
- `lib/util/folder_picker.dart` — native folder picker helper

## Status

Feature coverage roughly parallels the Python CLI: build EFI, health check, restore EFI, USB mapping, config editor, log checker, disk map. It was built and tested on Windows; Linux and macOS support exists in the code but hasn't been run on either platform yet, so treat those as unverified. Not currently distributed as a prebuilt executable — build it yourself (see below).

## Building

Standard Flutter desktop build:

```bash
flutter pub get
flutter build windows   # or: flutter build linux / flutter build macos
```

You'll also need a `hackmate-bridge(.exe)` binary (built from `src/bridge.py` via PyInstaller — see the root `.github/workflows/build-exe.yml` for the exact build invocation) placed next to the built app for it to actually do anything.

No test suite exists for this Flutter app yet (only the default `flutter_lints` dev dependency in `pubspec.yaml`) — see the root project's `CONTRIBUTING.md` for the Python backend's testing expectations, which this UI ultimately depends on.
