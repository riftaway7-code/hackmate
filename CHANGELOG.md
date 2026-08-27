# Changelog

Notable changes to HackMate, newest first. This started partway through the project's life — full history before this file existed is in `git log` and the [GitHub releases page](https://github.com/riftaway7-code/hackmate/releases). The README's old "announcements" section is being retired in favor of this file going forward.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- Rocket Lake CPUs were getting mislabeled as Tiger Lake, which threw off GPU/platform detection.
- Full audit of the kext database against live GitHub data: fixed ~11 kexts that were silently broken (repo renamed/deleted, or the download pattern stopped matching) — including FakeSMC, VoodooHDA, NullEthernet, and the whole BrcmPatchRAM Bluetooth family.

### Added
- Pre-build hardware warnings for configurations that just won't boot: AMD laptop CPUs, mobile Atom/Celeron/Pentium, Rocket Lake with no dGPU (no video output), Atheros WiFi past High Sierra.
- 6 new kexts added to the database; 3 removed that have no working source anywhere anymore.

### Changed
- Cleaned up unnecessary comment bloat across the codebase.

## [2.0.0] - 2026-07-12

Biggest correctness release at the time — went through the whole generation pipeline and found bugs that were producing EFIs that booted but were quietly broken underneath.

### Fixed
- `setup.py` crashed on macOS: stock macOS ships Python 3.9, and `setup.py` had 3.10-only syntax. Now runs on 3.8+.
- ACPI renames were applied without the SSDT that made them safe — `_OSI` was renamed to `XOSI` on every desktop and PS/2-only laptop with nothing actually defining `XOSI`. A rename now only happens if the table supplying its replacement is present.
- The instant-wake fix was backwards: it renamed each device's `_PRW` and left an `XPRW` method nothing called. Fixed to the standard `GPRW` → `XGPR` with SSDT-GPRW supplying the replacement.
- Intel WiFi never loaded — `itlwm.kext` was given another kext's binary name, so OpenCore refused to inject it. `ExecutablePath` is now read straight from each bundle's own `Info.plist`.
- USB port maps were doing nothing — the map's `ExecutablePath` pointed at a binary plist-only bundles don't have, and applying a map was disabling `USBToolBox.kext` (the thing that actually reads the map).
- Laptops were loading two ACPI tables that both defined `_SB.USBX`.
- Recovery downloads for 5 macOS versions shared a cache directory (Big Sur/El Capitan, Monterey/Sierra, etc.) and could serve the wrong image.
- MLB board serials were 16 characters instead of the correct 17.
- Kexts were getting auto-added from GitHub repos that no longer exist.
- Bluetooth kexts had overlapping kernel-version windows.
- `iasl` was looked up under the wrong filename, silently killing SSDT compilation on every platform.
- Windows Ethernet detection used a deprecated query that could grab a VPN/tunnel adapter instead of the real NIC.

### Added
- EFI Health Check — point HackMate at any OpenCore EFI (including hand-built ones) and it reports orphaned ACPI renames, kexts that will never inject, USB ports that aren't really mapped, decoded SIP flags, deprecated kexts, and missing `-no_compat_check`. Available from the welcome screen or via `--doctor` on the CLI.
- Kext download sources are now checked before the USB gets formatted, so a dead source shows up as an actionable warning instead of a kext silently going missing.

## [1.3.0] - 2026 (date not recorded)

### Added
- Windows users can download a single `HackMate.exe` from the releases page — no Python, no venv, no `setup.py`.
- config.plist editor added to the welcome screen.

### Fixed
- AMD config.plist crash.
- Windows SSL error.
- macOS `lspci` error (macOS is fully supported as a host OS).
