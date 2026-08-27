```
██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗
██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝
███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗
██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝
██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝
```


# shoutout
thank you so much GaM1ngN0tDev for making the flutter ui for hackmate!

[![Stars](https://img.shields.io/github/stars/riftaway7-code/hackmate?style=flat&color=gold)](https://github.com/riftaway7-code/hackmate/stargazers)
[![Downloads](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Friftaway7-code.github.io%2Fhackmate%2Fstats.json&query=total_downloads&label=downloads&color=brightgreen&style=flat&cacheSeconds=3600)](https://github.com/riftaway7-code/hackmate/releases)
[![Issues](https://img.shields.io/github/issues/riftaway7-code/hackmate?style=flat&color=red)](https://github.com/riftaway7-code/hackmate/issues)
[![License](https://img.shields.io/github/license/riftaway7-code/hackmate?style=flat&color=blue)](LICENSE)
[![Version](https://img.shields.io/github/v/release/riftaway7-code/hackmate?style=flat&color=green)](https://github.com/riftaway7-code/hackmate/releases)

hackmate automates the whole process of making a bootable opencore hackintosh usb. no manual config.plist editing, no hunting down kexts urself, no macrecovery commands, none of that.

works on linux, windows, and macos as the host os — doesn't matter what ur running it from.

![HackMate demo](demo.gif)

---

## 📢 announcements

full release notes moved to [CHANGELOG.md](CHANGELOG.md) so this section doesn't keep growing forever — check there for the "what changed recently" rundown. quick version: recent work fixed rocket lake getting mislabeled as tiger lake, audited the whole kext db against live github data (fixed ~11 silently-broken kexts, added 6, yanked 3 dead ones), and squashed a batch of quietly-broken-but-still-booted EFI generation bugs in v2.0.0.

**efi health check.** point hackmate at any opencore efi, even one u built by hand, and it'll tell u whats actually wrong: orphaned acpi renames, kexts that'll never inject, usb ports that aren't really mapped, sip decoded flag by flag, deprecated kexts, missing `-no_compat_check`. it's on the welcome screen, or run it from terminal:

```bash
sudo .venv/bin/python3 src/hackmate.py --doctor            # finds your mounted EFI
.venv/bin/python3 src/hackmate.py --doctor /Volumes/EFI/EFI
```

read-only, no root needed, safe to run on a booted system.

**new — kext sources get checked before your usb even gets formatted,** so a dead download source shows up as a warning u can actually do something about instead of a kext just silently going missing.

**v1.3.0** — windows users can just download one `HackMate.exe` from the [releases page](https://github.com/riftaway7-code/hackmate/releases), no python, no venv, no setup.py needed. also fixed the amd config.plist crash, windows ssl error, macos lspci error. config.plist editor added to welcome screen too.

**if u cloned before june 25th (running from `hackmate-linux/`):**
just run ur usual command, hackmate auto-migrates itself to the new `src/` layout and relaunches. no manual steps.

**if ur on macos and got a `lspci not found` error:**
macos is fully supported now. pull latest and rerun.

**if usb formatting fails on windows:**
fixed in latest update, pull and try again. still failing? use the new **already formatted** button — format the usb as fat32 (gpt) in disk management urself first, then pick that option in hackmate.

**if u got `sudo: uv: command not found`:**
don't use `sudo uv run`. always run w/ `sudo .venv/bin/python3 src/hackmate.py` after setup.

**kaby lake (7th gen) users:**
tahoe shows up as an option for ur hardware now. pull latest and rerun.

---

## install

### linux / macos

```bash
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate
python3 setup.py
sudo .venv/bin/python3 src/hackmate.py
```

> always use the full path to the venv python (`.venv/bin/python3`) w/ `sudo` — not `python3` or `uv run`. sudo doesn't inherit ur PATH so it won't find uv or ur user-installed packages.

### windows (exe)

download `HackMate.exe` from the [latest release](https://github.com/riftaway7-code/hackmate/releases/latest) and run it as administrator.

> **antivirus false positives:** some avs (bkav, gridinsoft, zillya) flag the exe as malware. it's a known false positive w/ pyinstaller-built executables — every major av (defender, kaspersky, eset, crowdstrike, sophos) reports it clean. the exe is built transparently from source on github actions if u wanna check: [build logs](https://github.com/riftaway7-code/hackmate/actions/workflows/build-exe.yml).

### windows (from source)

> **has to be run as administrator.** right-click powershell → run as administrator before any of this.

```powershell
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate
python setup.py
.venv\Scripts\python.exe src\hackmate.py
```

> always use `.venv\Scripts\python.exe` to run hackmate — not `python` or `uv run`. the venv is what makes sure all the deps are actually there.

### gui (tkinter, no terminal needed)

prefer a windowed app over the terminal ui? `hackmate_gui.py` is the exact same backend just w/ a tkinter frontend instead of textual — no extra deps, tkinter ships w/ python already.

```bash
sudo .venv/bin/python3 src/hackmate_gui.py      # linux / macos
.venv\Scripts\python.exe src\hackmate_gui.py    # windows, run powershell as administrator
```

### gui (flutter, newer alternative ui)

a separate windowed frontend built in flutter (shoutout GaM1ngN0tDev again) — same python backend underneath, talking to it thru a json-rpc bridge (`src/bridge.py`). build history, log checker, efi health check, disk map, restore, usb mapping, config editor, and the full guided/manual build efi wizard all work. not distributed as a prebuilt exe yet, so u build it urself.

needs the [flutter sdk](https://docs.flutter.dev/get-started/install) + platform build tools (visual studio build tools w/ the "desktop development w/ c++" workload on windows, xcode on macos, gtk3/clang/cmake/ninja on linux — see [flutter's linux setup docs](https://docs.flutter.dev/platform-integration/linux/building)).

```bash
git clone https://github.com/riftaway7-code/hackmate.git
cd hackmate/gui-flutter
flutter pub get
flutter run                # dev mode, picks up connected/desktop targets automatically
# or build a standalone release:
flutter build windows      # -> build/windows/x64/runner/Release/gui_flutter.exe
flutter build macos        # -> build/macos/Build/Products/Release/gui_flutter.app
flutter build linux        # -> build/linux/x64/release/bundle/gui_flutter
```

**windows:** just run the built exe — it prompts for admin (uac) on launch, and the python backend it spawns inherits that automatically, no separate elevation step.

**linux / macos:** the app doesn't self-elevate, so launch it w/ sudo from a terminal same as the tkinter gui:

```bash
sudo ./build/linux/x64/release/bundle/gui_flutter                                    # linux
sudo ./build/macos/Build/Products/Release/gui_flutter.app/Contents/MacOS/gui_flutter  # macos
```

> linux and macos support was just added and hasn't actually been run on either platform yet — this was built and tested on windows only so far. if u hit something broken on linux/macos, open an issue.

---

## what it actually does
1. scans ur hardware (cpu, gpu, audio, ethernet, wifi, touchpad, nvme, thunderbolt)
2. shows u which macos versions are compatible w/ ur exact hardware
3. u pick a usb drive (internal disks are hidden so u can't nuke urself)
4. fully automated from there:
   - formats usb as fat32 + creates the efi structure
   - downloads macos recovery straight from apple
   - generates smbios (serial, mlb, uuid, rom)
   - generates config.plist w/ the correct quirks for ur exact hardware
   - downloads kexts from github releases
   - downloads the latest opencore release
   - generates ssdts from ur actual dsdt using ssdttime

## supported hardware

**cpu generations:** sandy bridge · ivy bridge · haswell · broadwell · skylake · kaby lake · coffee lake · comet lake / ice lake · rocket lake and newer desktops with a supported amd dgpu · amd ryzen / threadripper desktops

**laptops tested:** thinkpad t480s, t480, t470, x1 carbon · dell xps 13/15 · hp elitebook · asus zenbook · acer aspire

**platforms:** laptops, desktops, mini-pcs

**macos versions:** ventura · sonoma · sequoia · tahoe (macos 16)

## after install
- run usbtoolbox (saved to `EFI/HackMate-Extras/`) inside macos to map ur usb ports
- swap out the placeholder `USBMap.kext` w/ the one u generate — or just use hackmate's usb mapping screen

## faq

**do i need a mac to use hackmate?**
nah. hackmate runs on linux, windows, and macos. u can make the usb from any computer u have lying around.

**will this work on my laptop/desktop?**
intel 2nd–10th gen is the normal range. 11th gen and newer intel xe graphics have no macos driver, so those desktops need a supported amd dgpu and those laptops usually arent viable. amd ryzen desktops work w/ the amd vanilla patches. run hackmate and it'll flag dead ends before it builds.

**is this the same as following the dortania opencore guide by hand?**
hackmate uses the exact same tools (macrecovery, ssdttime, opencore) that dortania recommends, just automates every single step of it. the output efi is equivalent to what u'd build by hand — minus the hours of pain.

**can i hackintosh a thinkpad?**
yeah — hackmate was literally built and tested on a thinkpad t480s. intel wifi (itlwm + heliport), trackpad (voodooi2c), all the common thinkpad hardware is supported.

**does it work on windows without python?**
yep. grab `HackMate.exe` from the releases page, no python or deps needed at all.

**does hackmate download the full macos installer for offline installation?**
not currently. hackmate downloads apple's recovery image (about 600 mb), which still downloads the full macos payload from apple after u boot it. if recovery shows `PKDownloadError 8` or ur network blocks apple's installer servers, try a different connection or prepare a full installer separately on a mac. hackmate cannot bypass filtering inside recovery.

**does intel wifi show up as native (built-in) wifi on tahoe?**
not with the onboard intel chip — opensource's AirportItlwm (the kext that makes intel wifi appear as real apple wifi in the menu bar) hasn't had a build past sonoma since mid-2024, so sequoia and tahoe are stuck with itlwm + heliport, which works for internet access but isn't apple-native (no menu bar icon, no airdrop/handoff over wifi). if u want actual native wifi on tahoe — menu bar, airdrop, handoff, all of it — swap in a genuine apple-supported broadcom card (bcm94360cd, dw1560, etc). those use macos's built-in airport driver, same as a real mac, so there's no version-pinned kext to break on any future macos release. hackmate will warn u about this and offer the broadcom-card path when it detects intel-only wifi.

**my antivirus is flagging hackmate.exe**
known false positive w/ pyinstaller-built exes. every major av (defender, kaspersky, eset) reports it clean. built from source on github actions if u wanna verify — [build logs](https://github.com/riftaway7-code/hackmate/actions/workflows/build-exe.yml).

## support

hackmate is free and open source. if it saved u hours of config.plist hell, consider sponsoring:

[![GitHub Sponsors](https://img.shields.io/github/sponsors/riftaway7-code?style=flat&color=ea4aaa)](https://github.com/sponsors/riftaway7-code)

## notes
- macos is sourced directly from apple's servers
- uses the same tools the dortania guide recommends (macrecovery, ssdttime, opencore)
- tested on thinkpad t480s (i5-8350u, intel 8265 wifi, kaby lake-r)
- auto-updates itself on launch via github




### oh right my tiktok is @hackmatetech
- also heres proof @theghostrdr
