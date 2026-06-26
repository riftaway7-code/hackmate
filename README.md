```
██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗
██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝
███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗
██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝
██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝
```

[![Stars](https://img.shields.io/github/stars/riftaway7-code/hackmate?style=flat&color=gold)](https://github.com/riftaway7-code/hackmate/stargazers)
[![Downloads](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Friftaway7-code.github.io%2Fhackmate%2Fstats.json&query=total_downloads&label=downloads&color=brightgreen&style=flat)](https://github.com/riftaway7-code/hackmate/releases)
[![Issues](https://img.shields.io/github/issues/riftaway7-code/hackmate?style=flat&color=red)](https://github.com/riftaway7-code/hackmate/issues)
[![License](https://img.shields.io/github/license/riftaway7-code/hackmate?style=flat&color=blue)](LICENSE)
[![Version](https://img.shields.io/github/v/release/riftaway7-code/hackmate?style=flat&color=green)](https://github.com/riftaway7-code/hackmate/releases)

Automates the entire process of creating a bootable OpenCore hackintosh USB. No manual config.plist editing, no hunting down kexts, no macrecovery commands.

Supports Linux, Windows, and macOS as host operating systems.

---

## 📢 Announcements

**v1.3.0 is out** — Windows users can now download a single `HackMate.exe` from the [releases page](https://github.com/riftaway7-code/hackmate/releases) — no Python, no venv, no setup.py. Also fixes AMD config.plist crash, Windows SSL error, and macOS lspci error. Config.plist editor added to welcome screen.

**If you cloned before June 25th (running from `hackmate-linux/`):**
Just run your usual command — HackMate will auto-migrate itself to the new `src/` layout and relaunch. No manual steps needed.

**If you're on macOS and got a `lspci not found` error:**
macOS is now fully supported. Pull the latest and re-run.

**If USB formatting fails on Windows:**
Fixed in latest update. Pull and try again. If it still fails, use the new **Already Formatted** button — format your USB as FAT32 (GPT) in Disk Management first, then pick that option in HackMate.

**If you got `sudo: uv: command not found`:**
Don't use `sudo uv run`. Always run with `sudo .venv/bin/python3 src/hackmate.py` after setup.

**Kaby Lake (7th gen) users:**
Tahoe now shows as an option for your hardware. Pull the latest and rerun.

---

## Install

### Linux / macOS

```bash
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate
python3 setup.py
sudo .venv/bin/python3 src/hackmate.py
```

> Always use the full path to the venv Python (`.venv/bin/python3`) with `sudo` — not `python3` or `uv run`. sudo does not inherit your PATH so it won't find uv or your user-installed packages.

### Windows (EXE)

Download `HackMate.exe` from the [latest release](https://github.com/riftaway7-code/hackmate/releases/latest) and run as Administrator.

> **Antivirus false positives:** Some AVs (Bkav, Gridinsoft, Zillya) flag the EXE as malware. This is a known false positive with PyInstaller-built executables — every major AV (Defender, Kaspersky, ESET, CrowdStrike, Sophos) reports clean. The EXE is built transparently from source on GitHub Actions: [view build logs](https://github.com/riftaway7-code/hackmate/actions/workflows/build-exe.yml).

### Windows (from source)

> **Must be run as Administrator.** Right-click PowerShell and select "Run as administrator" before running any of these commands.

```powershell
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate
python setup.py
.venv\Scripts\python.exe src\hackmate.py
```

> Always use `.venv\Scripts\python.exe` to run HackMate — not `python` or `uv run`. The venv ensures all dependencies are available.

---

## What it does
1. Scans your hardware (CPU, GPU, audio, ethernet, WiFi, touchpad, NVMe, Thunderbolt)
2. Shows compatible macOS versions based on your hardware
3. You pick a USB drive (internal disks are hidden)
4. Fully automated from there:
   - Formats USB as FAT32 and creates EFI structure
   - Downloads macOS recovery directly from Apple
   - Generates SMBIOS (serial, MLB, UUID, ROM)
   - Generates config.plist
   - Downloads kexts from GitHub releases
   - Downloads latest OpenCore release
   - Generates SSDTs using SSDTTime from your actual DSDT

## After install
- Run USBToolBox inside macOS to map USB ports
- Replace the placeholder USBMap.kext with your generated one

## Support

HackMate is free and open source. If it saved you hours of config.plist hell, consider sponsoring:

[![GitHub Sponsors](https://img.shields.io/github/sponsors/riftaway7-code?style=flat&color=ea4aaa)](https://github.com/sponsors/riftaway7-code)

## Notes
- macOS is sourced directly from Apple
- Uses the same tools recommended by the Dortania guide (macrecovery, SSDTTime)
- Tested on ThinkPad T480s (i5-8350U, Intel 8265 WiFi)
- Auto-updates itself on launch via GitHub
