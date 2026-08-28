import argparse
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ACCENT = (34, 211, 238)
DEFAULT_ENTRIES = ["macOS", "Safe Mode", "Recovery", "Windows", "UEFI Shell", "Reset NVRAM"]
UI_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size):
    for c in UI_CANDIDATES:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def _first_png_from_icns(path):
    d = path.read_bytes()
    i = d.index(b"\x89PNG\r\n\x1a\n")
    end = len(d)
    for j in range(i + 8, len(d) - 8):
        if d[j:j + 4] == b"IEND":
            end = j + 8
            break
    return Image.open(io.BytesIO(d[i:end])).convert("RGBA")


def _rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)


def render(theme_dir, entries, minimal, selected, out_path):
    core = Path(theme_dir) / "Image" / "HackMate" / "Core"
    bg = _first_png_from_icns(core / "Background.icns").convert("RGBA")
    w, h = bg.size
    canvas = bg.copy()
    d = ImageDraw.Draw(canvas)

    hd = _first_png_from_icns(core / "HardDrive.icns")
    tile = int(w * 0.062)
    gap = int(tile * 0.55)
    n = len(entries)
    total = n * tile + (n - 1) * gap
    x0 = (w - total) // 2
    y0 = int(h * 0.44)

    label_font = _font(max(13, int(w / 110)))
    for idx, name in enumerate(entries):
        tx = x0 + idx * (tile + gap)
        if idx == selected:
            pad = int(tile * 0.14)
            for k, a in ((pad + 6, 60), (pad + 2, 110), (pad - 2, 220)):
                _rounded(d, (tx - k, y0 - k, tx + tile + k, y0 + tile + k),
                         r=int(tile * 0.22), outline=(*ACCENT, a), width=3)
            _rounded(d, (tx - pad, y0 - pad, tx + tile + pad, y0 + tile + pad),
                     r=int(tile * 0.2), fill=(*ACCENT, 40))
        icon = hd.resize((tile, tile), Image.LANCZOS)
        canvas.paste(icon, (tx, y0), icon)
        d = ImageDraw.Draw(canvas)
        tb = d.textbbox((0, 0), name, font=label_font)
        d.text((tx + (tile - (tb[2] - tb[0])) // 2, y0 + tile + int(h * 0.012)),
               name, font=label_font, fill=(230, 238, 242, 235))

    if not minimal:
        cy = int(h * 0.945)
        cr = int(w * 0.014)
        for cx in (w // 2 - int(w * 0.03), w // 2 + int(w * 0.03)):
            d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), outline=(220, 228, 232, 180), width=3)

    canvas.convert("RGB").save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default=str(Path(__file__).resolve().parents[1] / "src/assets/canopy/Resources"))
    ap.add_argument("--entries", default=",".join(DEFAULT_ENTRIES))
    ap.add_argument("--minimal", action="store_true")
    ap.add_argument("--selected", type=int, default=0)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "src/assets/canopy/preview.png"))
    args = ap.parse_args()

    out = render(args.theme, [e for e in args.entries.split(",") if e], args.minimal, args.selected, args.out)
    print(f"wrote {out}  ({Image.open(out).size})")


if __name__ == "__main__":
    main()
