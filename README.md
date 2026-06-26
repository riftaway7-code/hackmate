# HackMate

## 📢 Announcements

**If you cloned before June 2026 (using `hackmate-linux/` or `hackmate-windows/`):**
The codebase has been unified. Re-clone and use `src/` instead:
```bash
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate/src
sudo python3 hackmate.py   # Linux/macOS
```
The old `hackmate-linux/` and `hackmate-windows/` folders no longer exist.

**If you're on macOS and got a `lspci not found` error:**
macOS is now a supported host OS. Pull the latest and re-run from `src/`:
```bash
git pull
cd src
sudo python3 hackmate.py
```

**If USB formatting fails on Windows:**
This is a known issue being investigated. Workaround: manually format your USB as FAT32 in Disk Management, then re-run HackMate — it will detect the drive and skip the format step.

---

Automates the entire process of creating a bootable OpenCore hackintosh USB. No manual config.plist editing, no hunting down kexts, no macrecovery commands.

## Platform

`src/` works on Linux, Windows, and macOS from a single codebase.

---

## Linux

**Requirements:** Python 3.10+, root access

```bash
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate/src
pip install textual
sudo python3 hackmate.py
```

## Windows

**Requirements:** Python 3.10+, administrator access

```powershell
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate\src
pip install textual
# Right-click → Run as Administrator, or from an admin terminal:
python hackmate.py
```

## macOS

**Requirements:** Python 3.10+, sudo access

```bash
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate/src
pip3 install textual
sudo python3 hackmate.py
```

> Works on both real Macs and hackintoshes. Uses `system_profiler` for hardware detection and `diskutil` for USB formatting.

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
