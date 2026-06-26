# HackMate
Automates the entire process of creating a bootable OpenCore hackintosh USB. No manual config.plist editing, no hunting down kexts, no macrecovery commands.

Supports Linux, Windows, and macOS as host operating systems.

---

## 📢 Announcements

**If you cloned before June 25th (running from `hackmate-linux/`):**
Just run your usual command — HackMate will auto-migrate itself to the new `src/` layout and relaunch. No manual steps needed.

**If you're on macOS and got a `lspci not found` error:**
macOS is now fully supported. Just update and re-run:
```bash
git pull && sudo python3 src/hackmate.py
```

**If USB formatting fails on Windows:**
Known issue, being investigated. Workaround: manually format your USB as FAT32 in Disk Management, then re-run HackMate.

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

### Windows
```powershell
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate
python setup.py
# Run as Administrator:
.venv\Scripts\python.exe src\hackmate.py
```

> `setup.py` creates a virtual environment and installs required dependencies. HackMate will also tell you if anything is missing when you launch it.

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

## Notes
- macOS is sourced directly from Apple
- Uses the same tools recommended by the Dortania guide (macrecovery, SSDTTime)
- Tested on ThinkPad T480s (i5-8350U, Intel 8265 WiFi)
- Auto-updates itself on launch via GitHub
