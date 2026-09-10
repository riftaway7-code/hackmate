# Changelog

Notable changes to HackMate, newest first. This started partway through the project's life — full history before this file existed is in `git log` and the [GitHub releases page](https://github.com/riftaway7-code/hackmate/releases). The README's old "announcements" section is being retired in favor of this file going forward.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [4.0.0] - 2026-09-09

The biggest correctness pass since 2.0.0. Most of it is hardware detection: whole families of CPUs, GPUs, and NICs were being misidentified, and the wrong identification quietly produced an EFI that booted but had the wrong SMBIOS, the wrong framebuffer, or a NIC/audio device that never came up. Also ships HackMate-Core (a branded graphical boot picker) and a "why" explanation for every choice the generator makes.

### Fixed

**CPU / platform identification**
- Intel gen-11 desktops (Rocket Lake) were labeled Tiger Lake, which cascaded into the wrong GPU and platform handling. `oc_platform` was also being computed before platform detection had run.
- Intel Core Ultra 100-series (Meteor Lake) was unrecognized and silently fell back to a Kaby Lake framebuffer.
- Ryzen 2000/3000-series G/U-suffix APUs were classified as a later Zen architecture than they are.
- AMD Zen 4/5 desktops were given the Intel-only `CpuTopologyRebuild` kext, and a desktop chassis was being misdetected as a laptop running on a UPS.
- Pentium/Celeron CPUID spoofing now follows the CPU generation, and those chips are capped at Monterey (the last release they can run).

**GPU**
- macOS GPU detection, when it saw both an iGPU and a dGPU, discarded whichever one it decided was the "loser" entirely instead of keeping both.
- AMD RX Vega APUs were classified as discrete cards; modern `NNNM`-style iGPU names weren't recognized as APUs at all.
- Intel iGPU + AMD dGPU desktops never got `NootRX`/`RadeonSensor` for the discrete card.
- `nv_disable=1` was never applied on Optimus laptops (Intel iGPU + Nvidia dGPU).
- An unsupported Nvidia GPU was blocking *every* macOS version, which defeated the GOP-passthrough fallback that exists for exactly that case.
- GOP passthrough was never enabled for systems with no GPU at all, and there was no warning either.

**SMBIOS**
- AMD laptops were handed Intel-only `MacBookPro16,x` SMBIOS models.

**Storage / networking / audio device properties**
- The NVMe "built-in" device property was hardcoded to one fixed PCI path — wrong on many boards.
- I225/I226 spoofs and the Realtek / I219 built-in properties were likewise pinned to fixed PCI paths.
- Linux ethernet detection had no I225/I226 branches, so those NICs were left unidentified.
- Linux audio detection could pick a GPU's HDMI audio function over the real onboard codec.
- Onboard audio `layout-id` was injected on the Intel PCH path only, leaving AMD boards silent.

**ACPI**
- `SSDT-AWAC` and `SSDT-PMC` were being injected on every modern AMD desktop, where neither belongs.

**BIOS guidance**
- The BIOS checklist was missing IOMMU guidance for AMD and, in one path, suggested disabling the system's only GPU.

**Kext database**
- Full audit against live GitHub data fixed ~11 kexts that were silently broken (repo renamed/deleted, or the release asset pattern stopped matching) — including FakeSMC, VoodooHDA, NullEthernet, and the whole BrcmPatchRAM Bluetooth family.
- 3 kexts removed that no longer have a working source anywhere.

**Other**
- CI suite is green again (had 7 pre-existing failures).

### Added
- **HackMate-Core** — a branded graphical OpenCore boot picker built on an OpenCanopy theme (the picker chrome only; the OpenCore binaries are unmodified). On by default with a first-run notice, wired through both the TUI and CLI build paths, with a QEMU test harness and a `--minimal` preview mode.
- **Rationale / explain** — every decision the config.plist generator makes now comes with a plain-language reason and a link to the relevant Dortania section.
- **`ocvalidate`** — OpenCore's own validator is run against the generated config as part of the build.
- **Live AMD_Vanilla patches** — the AMD kernel patches are fetched from upstream with a 24-hour cache, falling back to the bundled copy offline.
- **GitHub release metadata caching** — release lookups are cached on disk, and `GH_TOKEN` / the `gh` CLI are used for auth when available (avoids rate limits).
- **Hardware spec files** — describe a target machine in a file to generate an EFI for hardware you're not currently running on.
- Pre-build hardware warnings for configs that simply won't boot: AMD laptop CPUs, mobile Atom/Celeron/Pentium, Rocket Lake with no dGPU (no video out), Atheros WiFi past High Sierra.
- Chipset-aware SSDT selection, closer to Dortania's prebuilt SSDT matrix; `SSDT-GPI0` now targets the real GPIO controller path pulled from the DSDT.
- 6 new kexts in the database.
- Test coverage for previously untested modules: `discord_prompt`, `config_editor`, `project_stats`, `efi_doctor`, `oc_log`.
- **HackMate Community** — a Reddit-style discussion board hosted on GitHub Pages.

### Changed
- Kext load order (`LOAD_ORDER`) is now complete, and touchpad kext selection trusts `profile.touchpad_type`.
- Cleaned up comment bloat across the codebase.

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
