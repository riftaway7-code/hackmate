# HackMate
Automates the entire process of creating a bootable OpenCore hackintosh USB. No manual config.plist editing, no hunting down kexts, no macrecovery commands.

## Platform

`src/` works on both Linux and Windows from a single codebase.

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
