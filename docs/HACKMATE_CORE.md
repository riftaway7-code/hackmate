# HackMate-Core

A branded graphical boot picker for OpenCore.

When you boot a HackMate EFI you normally land on OpenCore's built-in text
picker &mdash; white text on black, no mouse, no context. HackMate-Core replaces
that with a welcoming screen: the HackMate banner over a blurred macOS Tahoe
backdrop, mouse support, readable entry names, and a short legend explaining what
Safe Mode / Recovery / Reset NVRAM actually do.

## What it is (and isn't)

It is **not** a fork of OpenCore. The bootloader running underneath is the
unmodified official `OpenCore.efi` release. HackMate-Core is two things:

1. An **OpenCanopy theme** &mdash; a `Resources/` folder (background image, icons,
   fonts, labels). OpenCanopy is Acidanthera's own graphical picker, shipped
   with every OpenCore release as `OpenCanopy.efi`.
2. A **config profile** &mdash; a handful of `config.plist` keys that switch the
   picker on and point it at the theme.

Nothing about the boot chain, security model, or update path changes. You can
turn it off by regenerating the config without the option.

## Enabling it

### From a build

Pass `hackmate_core=True`:

```python
config = config_gen.generate(profile, smbios, macos_major, hackmate_core=True)
```

or set `params["hackmate_core"] = True` before calling `build_runner.run()`.
`build_runner` then copies the theme and `OpenCanopy.efi` into the EFI
automatically, next to the other drivers.

### What it changes in config.plist

| Key | Value |
| --- | --- |
| `Misc > Boot > PickerMode` | `External` |
| `Misc > Boot > PickerVariant` | `HackMate\Core` |
| `Misc > Boot > PickerAttributes` | existing bits OR `0x91` (volume icon + pointer + flavour) |
| `UEFI > Drivers` | `OpenCanopy.efi` appended |
| `UEFI > Output > ProvideConsoleGop` | `True` |

### Files added to the EFI

```
EFI/OC/Drivers/OpenCanopy.efi
EFI/OC/Resources/Font/            (bitmap font, from OcBinaryData)
EFI/OC/Resources/Label/           (prerendered entry labels, from OcBinaryData)
EFI/OC/Resources/Image/HackMate/Core/
    Background.icns               (1080p; also Background_1440p / _2160p)
    Cursor / Selected / Selector / SetDefault / Left / Right / HardDrive .icns
    Apple / Windows / Shell / Tool / ... .icns
```

## Rebuilding the theme

`tools/build_canopy_theme.py` regenerates `src/assets/canopy/Resources/`:

```
python tools/build_canopy_theme.py \
    --wallpaper /path/to/wallpaper.jpg \
    --ocbinary  /path/to/OcBinaryData \
    --goldengate /path/to/OcBinaryData/Resources/Image/Acidanthera/GoldenGate
```

It composites the `BANNER` from `src/hackmate.py` (block characters only) over
the wallpaper &mdash; blurred, darkened, slightly desaturated &mdash; adds the
subtitle and legend, and writes `Background.icns` at three resolutions. Icons are
copied from Acidanthera's GoldenGate set; `Apple.icns` is generated. `--blur`,
`--brightness`, and `--dark` tune the backdrop.

The `.icns` files are the standard Apple ICNS container wrapping a PNG in an
`ic07` and an `ic13` chunk; for the background both chunks hold the full-resolution
image (OpenCanopy renders whichever it reads &mdash; a half-size `ic07` shows up
centred and small).

## Testing without hardware

`tools/build_hackmate_core_efi.py` assembles a minimal test ESP from an OpenCore
release and a Sample-derived `config.plist`, then `tools/qemu_canopy_shot.py`
boots it in QEMU + OVMF and screenshots the picker over the QEMU monitor. Run
`ocvalidate` on the generated `config.plist` first &mdash; it should report no
issues.

A real hardware-specific HackMate config will fault under QEMU (its quirks assume
real silicon); use the minimal test config to iterate on the picker itself.

## Resolution

`Background.icns` is centred, not stretched. The theme ships 1080p, 1440p and
2160p variants (`Background.icns`, `Background_1440p.icns`, `Background_2160p.icns`).
For a display that isn't one of those, regenerate with `RESOLUTIONS` edited, or
accept letterboxing against `DefaultBackgroundColor` (black by default).
