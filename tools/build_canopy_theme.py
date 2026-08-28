import argparse
import io
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BANNER = [
    "██╗  ██╗ █████╗  ██████╗██╗  ██╗███╗   ███╗ █████╗ ████████╗███████╗",
    "██║  ██║██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗╚══██╔══╝██╔════╝",
    "███████║███████║██║     █████╔╝ ██╔████╔██║███████║   ██║   █████╗  ",
    "██╔══██║██╔══██║██║     ██╔═██╗ ██║╚██╔╝██║██╔══██║   ██║   ██╔══╝  ",
    "██║  ██║██║  ██║╚██████╗██║  ██╗██║ ╚═╝ ██║██║  ██║   ██║   ███████╗",
    "╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝",
]

RESOLUTIONS = [(1920, 1080), (2560, 1440), (3840, 2160)]
ACCENT = (34, 211, 238)
SUBTITLE = "OpenCore boot picker   \u00b7   choose a boot option"
HINT = "arrows or mouse to move    enter to boot    space for options    esc to reload"
LEGEND = [
    "Safe Mode  -  starts macOS without extra kexts, for fixing a bad install",
    "Recovery  -  repair the disk, reinstall macOS, or open Terminal",
    "Reset NVRAM  -  clears saved boot settings when the machine won't start",
]

MONO_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
UI_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(candidates, size):
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def draw_apple(px=256):
    s = px * 6
    white = (244, 249, 251, 255)
    mask = Image.new("L", (s, s), 0)
    m = ImageDraw.Draw(mask)
    cx, cy = s // 2, int(s * 0.585)
    rx, ry = int(s * 0.335), int(s * 0.345)

    m.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    dip_w, dip_h = int(s * 0.17), int(s * 0.11)
    m.ellipse((cx - dip_w, cy - ry - dip_h, cx + dip_w, cy - ry + dip_h), fill=0)

    bite_r = int(s * 0.14)
    bx = cx + rx + int(bite_r * 0.18)
    m.ellipse((bx - bite_r, cy - bite_r, bx + bite_r, cy + bite_r), fill=0)

    leaf = Image.new("L", (s, s), 0)
    ld = ImageDraw.Draw(leaf)
    lw, lh = int(s * 0.075), int(s * 0.16)
    lx, ly = cx + int(s * 0.055), int(s * 0.17)
    ld.ellipse((lx - lw, ly - lh, lx + lw, ly + lh), fill=255)
    leaf = leaf.rotate(-38, center=(lx, ly + lh // 3), resample=Image.BICUBIC)
    mask = Image.composite(Image.new("L", (s, s), 255), mask, leaf)

    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (s, s), white), (0, 0), mask)
    return out.resize((px, px), Image.LANCZOS)


def wrap_icns(png_1x, png_2x):
    def chunk(tag, data):
        return tag + struct.pack(">I", len(data) + 8) + data

    body = chunk(b"ic07", png_1x) + chunk(b"ic13", png_2x)
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def _icns_chunks(data):
    off = 8
    out = []
    while off < len(data):
        tag = data[off:off + 4]
        ln = struct.unpack(">I", data[off + 4:off + 8])[0]
        out.append((tag, data[off + 8:off + ln]))
        off += ln
    return out


def tint_icns(path, rgb):
    chunks = _icns_chunks(path.read_bytes())
    outs = []
    for tag, payload in chunks:
        im = Image.open(io.BytesIO(payload)).convert("RGBA")
        r, g, b, a = im.split()
        lum = Image.merge("RGB", (r, g, b)).convert("L")
        tinted = Image.new("RGBA", im.size)
        px_l = lum.load()
        px_a = a.load()
        px_o = tinted.load()
        for y in range(im.height):
            for x in range(im.width):
                t = px_l[x, y] / 255
                px_o[x, y] = (
                    min(255, int(rgb[0] * (0.45 + 0.72 * t))),
                    min(255, int(rgb[1] * (0.45 + 0.72 * t))),
                    min(255, int(rgb[2] * (0.5 + 0.68 * t))),
                    px_a[x, y],
                )
        outs.append(_png_bytes(tinted))
    while len(outs) < 2:
        outs.append(outs[-1])
    path.write_bytes(wrap_icns(outs[0], outs[1]))


def _clean_banner():
    keep = set("█ ")
    rows = ["".join(ch if ch in keep else " " for ch in line).rstrip() for line in BANNER]
    width = max(len(r) for r in rows)
    return [r.ljust(width) for r in rows]


def _banner_cells():
    lines = _clean_banner()
    return [[ch == "█" for ch in row] for row in lines]


def _paint_banner(size, cells, cols, rows, fill):
    img = Image.new("RGBA", (cols * size, rows * size), (0, 0, 0, 0))
    pd = ImageDraw.Draw(img)
    for r, row in enumerate(cells):
        run_start = None
        for c in range(cols + 1):
            on = c < cols and row[c]
            if on and run_start is None:
                run_start = c
            elif not on and run_start is not None:
                pd.rectangle((run_start * size, r * size, c * size - 1, (r + 1) * size - 1), fill=fill)
                run_start = None
    return img


def render_banner_layer(w, h):
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cells = _banner_cells()
    rows = len(cells)
    cols = len(cells[0])
    cell_w = max(2, int(w * 0.52) // cols)
    cell_h = int(cell_w * 1.9)

    marks = _paint_banner(1, cells, cols, rows, (255, 255, 255, 255))
    marks = marks.resize((cols * cell_w, rows * cell_h), Image.NEAREST)
    bx = (w - marks.width) // 2
    by = int(h * 0.13)

    def stamp(dx, dy, rgba):
        solid = Image.new("RGBA", marks.size, rgba)
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        tile.paste(solid, (bx + dx, by + dy), marks)
        return tile

    glow = stamp(0, 0, (ACCENT[0], ACCENT[1], ACCENT[2], 230))
    glow = glow.filter(ImageFilter.GaussianBlur(max(4, cell_w)))
    layer = Image.alpha_composite(layer, glow)
    layer = Image.alpha_composite(layer, stamp(max(3, cell_w // 4), max(3, cell_w // 4), (0, 0, 0, 150)))
    layer = Image.alpha_composite(layer, stamp(0, 0, (236, 252, 254, 255)))

    d = ImageDraw.Draw(layer)
    th = rows * cell_h
    y = by
    sub_font = _font(UI_CANDIDATES, max(16, int(w / 76)))
    sb = d.textbbox((0, 0), SUBTITLE, font=sub_font)
    d.text(((w - (sb[2] - sb[0])) // 2, y + th + int(h * 0.028)), SUBTITLE,
           font=sub_font, fill=(ACCENT[0], ACCENT[1], ACCENT[2], 235))

    leg_font = _font(UI_CANDIDATES, max(13, int(w / 112)))
    lg = int(h * 0.66)
    lh = leg_font.getbbox("Ag")[3] + int(h * 0.012)
    for i, row in enumerate(LEGEND):
        rb = d.textbbox((0, 0), row, font=leg_font)
        rx = (w - (rb[2] - rb[0])) // 2
        d.text((rx + 1, lg + i * lh + 1), row, font=leg_font, fill=(0, 0, 0, 150))
        d.text((rx, lg + i * lh), row, font=leg_font, fill=(206, 224, 230, 210))

    hint_font = _font(UI_CANDIDATES, max(12, int(w / 150)))
    hb = d.textbbox((0, 0), HINT, font=hint_font)
    d.text(((w - (hb[2] - hb[0])) // 2, int(h * 0.86)), HINT,
           font=hint_font, fill=(210, 220, 226, 140))
    return layer


def build_background(src, w, h, blur, brightness, dark):
    base = Image.open(src).convert("RGB")
    scale = max(w / base.width, h / base.height)
    resized = base.resize((int(base.width * scale) + 1, int(base.height * scale) + 1), Image.LANCZOS)
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    bg = resized.crop((left, top, left + w, top + h))
    bg = bg.filter(ImageFilter.GaussianBlur(blur * w / 1920))
    bg = ImageEnhance.Brightness(bg).enhance(brightness)
    bg = ImageEnhance.Color(bg).enhance(0.82)
    bg = Image.alpha_composite(bg.convert("RGBA"), Image.new("RGBA", (w, h), (6, 10, 14, int(255 * dark))))
    bg = Image.alpha_composite(bg, _vignette(w, h))
    bg = Image.alpha_composite(bg, render_banner_layer(w, h))
    return bg.convert("RGB")


def _vignette(w, h):
    small = max(2, w // 10)
    v = Image.new("L", (small, int(small * h / w)), 0)
    vd = ImageDraw.Draw(v)
    vw, vh = v.size
    vd.ellipse((-vw * 0.30, -vh * 0.30, vw * 1.30, vh * 1.30), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(small // 6)).resize((w, h), Image.LANCZOS)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 150))
    layer.putalpha(Image.eval(v, lambda p: int((255 - p) * 0.55)))
    return layer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallpaper", default=r"C:/Users/Raahim Syed/Downloads/macos-tahoe-26-5120x2880-22674.jpg")
    ap.add_argument("--ocbinary", default="/tmp/hmc/OcBinaryData-master")
    ap.add_argument("--goldengate", default="/tmp/hmc/OcBinaryData-master/Resources/Image/Acidanthera/GoldenGate")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "src/assets/canopy/Resources"))
    ap.add_argument("--blur", type=float, default=17.0)
    ap.add_argument("--brightness", type=float, default=0.52)
    ap.add_argument("--dark", type=float, default=0.34)
    args = ap.parse_args()

    out = Path(args.out)
    theme = out / "Image" / "HackMate" / "Core"
    theme.mkdir(parents=True, exist_ok=True)

    gg = Path(args.goldengate)
    copied = 0
    for icns in gg.glob("*.icns"):
        shutil.copy(icns, theme / icns.name)
        copied += 1
    print(f"copied {copied} chrome icons from GoldenGate")

    apple = draw_apple(256)
    ap_png = _png_bytes(apple)
    for nm in ("Apple.icns", "ExtApple.icns"):
        (theme / nm).write_bytes(wrap_icns(ap_png, ap_png))
    print("generated Apple.icns + ExtApple.icns")

    for nm in ("Selected.icns", "Selector.icns", "SetDefault.icns"):
        p = theme / nm
        if p.is_file():
            tint_icns(p, ACCENT)
    print("tinted selection chrome to HackMate cyan")

    restart = theme / "Restart.icns"
    if restart.is_file():
        shutil.copy(restart, theme / "ResetNVRAM.icns")
        print("aliased Restart.icns -> ResetNVRAM.icns")

    for i, (w, h) in enumerate(RESOLUTIONS):
        img = build_background(args.wallpaper, w, h, args.blur, args.brightness, args.dark)
        png = _png_bytes(img)
        data = wrap_icns(png, png)
        name = "Background.icns" if i == 0 else f"Background_{h}p.icns"
        (theme / name).write_bytes(data)
        print(f"  {name}: {w}x{h}  ({len(data)//1024} KB)")

    for sub in ("Font", "Label"):
        src = Path(args.ocbinary) / "Resources" / sub
        dst = out / sub
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"staged Resources/{sub} ({len(list(dst.iterdir()))} files)")

    print(f"theme written to {theme}")


if __name__ == "__main__":
    main()
