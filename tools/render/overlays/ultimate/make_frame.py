"""Build the empty Ultimate scoreboard frame (no names/scores) from layout.json + emblem.png.

Usage:  python make_frame.py              (needs Pillow; run from any folder)
        python make_frame.py --glow 165,115,255,100    one-off glow color + alpha

Logo: emblem.png next to this script (sample: "YOUR LOGO"; replace it with yours). Only if it is missing, the
emblem is cut out of ..\\melee_themes\\Default\\overlay.png at EMBLEM_BOX (an old PROTOCOL-specific shortcut).
Writes next to this script:
  frame.png        1920x1080, transparent except the top scoreboard. ultimate_overlay.py draws on it.
  frame_layers\\    01_glow, 02_plates, 03_bars, 04_emblem (full canvas each, for paint.net:
                   Layers > Import from File in number order) + Preview.png on a grey background.

Look: colours from layout.json (the package ships a neutral grey sample), laid out as a 16:9 scoreboard:
a name plate in each top corner with a picture circle, name bar, score box and a line under it
(round / best of), logo in the middle. Glow (alpha 0 = off): grow the shape, blur, keep it outside the shape.
"""
import json
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAYOUT = os.path.join(HERE, "layout.json")
EMBLEM = os.path.join(HERE, "emblem.png")
MELEE_OVERLAY = os.path.join(ROOT, "melee_themes", "Default", "overlay.png")  # ROOT = tools\\render\\overlays
EMBLEM_BOX = (40, 345, 590, 595)  # emblem in the Melee overlay, in its 606x1080 stream pixels
SS = 2  # supersampling for smooth edges


def grow(mask, px):
    """Dilate a mask by about px pixels (blur + threshold)."""
    return mask.filter(ImageFilter.GaussianBlur(max(0.5, px / 2))).point(lambda v: 255 if v > 8 else 0)


def cut_emblem():
    """Cut the protocol emblem (orange rings, black, stick, blue letters) out of the Melee overlay,
    same mask as Seasonal\\Halloween\\make_halloween_art.py uses for its emblem glow."""
    base = Image.open(MELEE_OVERLAY).convert("RGBA")
    u = base.width / 606
    x1, y1, x2, y2 = [round(v * u) for v in EMBLEM_BOX]
    crop = base.crop((x1, y1, x2, y2))
    h, s, v = crop.convert("RGB").convert("HSV").split()
    orange = ImageChops.multiply(h.point(lambda x: 255 if 4 <= x <= 30 else 0), s.point(lambda x: 255 if x > 120 else 0))
    dark = v.point(lambda x: 255 if x < 25 else 0)
    m = ImageChops.lighter(orange, dark)
    m = ImageChops.invert(grow(ImageChops.invert(grow(m, 3 * u)), 3 * u))  # close small gaps
    # everything not reachable from outside (letters, dots, gaps between rings) is part of the emblem
    small = m.resize((crop.width // 6, crop.height // 6), Image.BILINEAR).point(lambda x: 255 if x > 64 else 0)
    ImageDraw.floodfill(small, (0, 0), 128)
    holes = small.point(lambda x: 255 if x == 0 else 0).resize(crop.size, Image.BILINEAR)
    m = ImageChops.lighter(m, holes.filter(ImageFilter.GaussianBlur(u)).point(lambda x: 255 if x > 100 else 0))
    m = m.filter(ImageFilter.GaussianBlur(0.7 * u))  # soft edge
    crop.putalpha(m)
    crop = crop.crop(m.getbbox())
    crop.save(EMBLEM)
    print("wrote", os.path.relpath(EMBLEM, ROOT))
    return crop


def gradient(size, top, bottom):
    w, h = size
    col = Image.new("RGBA", (1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)) + (255,))
    return col.resize((w, h))


def main():
    L = json.load(open(LAYOUT, encoding="utf-8"))
    C = {k: tuple(v) for k, v in L["colors"].items() if not k.startswith("_")}
    G = dict(L["glow"])
    for a in sys.argv[1:]:
        if a.startswith("--glow"):
            vals = [int(x) for x in sys.argv[sys.argv.index(a) + 1].split(",")]
            G["color"], G["alpha"] = vals[:3], (vals[3] if len(vals) > 3 else G["alpha"])
    W, H = L["canvas"]
    big = (W * SS, H * SS)
    s = lambda box: [v * SS for v in box]
    R = L["radius"]

    plates, bars = Image.new("RGBA", big), Image.new("RGBA", big)
    shape = Image.new("L", big, 0)  # everything solid, for the glow
    for key in ("p1", "p2"):
        P = L[key]
        x1, y1, x2, y2 = s(P["plate"])
        m = Image.new("L", big, 0)
        ImageDraw.Draw(m).rounded_rectangle((x1, y1, x2, y2), R["plate"] * SS, fill=255)
        shape = ImageChops.lighter(shape, m)
        rim = Image.new("RGBA", big, C["plate_rim"] + (255,))
        rim.putalpha(m)
        plates.alpha_composite(rim)
        inner = Image.new("L", big, 0)
        ImageDraw.Draw(inner).rounded_rectangle((x1 + 3 * SS, y1 + 3 * SS, x2 - 3 * SS, y2 - 3 * SS),
                                                (R["plate"] - 3) * SS, fill=255)
        g = Image.new("RGBA", big)
        g.paste(gradient((x2 - x1, y2 - y1), C["plate_top"], C["plate_bottom"]), (x1, y1))
        g.putalpha(ImageChops.multiply(inner, g.getchannel("A")))
        plates.alpha_composite(g)

        d = ImageDraw.Draw(bars)
        for box, fill, edge, r in ((P["name"], C["bar"], C["bar_edge"], R["bar"]),
                                   (P["score"], C["score"], C["score_edge"], R["score"])):
            bx1, by1, bx2, by2 = s(box)
            d.rounded_rectangle((bx1, by1, bx2, by2), r * SS, fill=edge + (255,))
            d.rounded_rectangle((bx1 + 2 * SS, by1 + 2 * SS, bx2 - 2 * SS, by2 - 3 * SS), (r - 2) * SS, fill=fill + (255,))
        cx, cy, r = s(P["pfp"])
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=C["bar_edge"] + (255,))
        d.ellipse((cx - r + 2 * SS, cy - r + 2 * SS, cx + r - 2 * SS, cy + r - 3 * SS), fill=C["bar"] + (255,))

    emblem_src = Image.open(EMBLEM).convert("RGBA") if os.path.isfile(EMBLEM) else cut_emblem()
    lw = L["logo"]["width"] * SS
    lh = round(emblem_src.height * lw / emblem_src.width)
    em = emblem_src.resize((lw, lh), Image.LANCZOS)
    emblem = Image.new("RGBA", big)
    emblem.alpha_composite(em, (L["logo"]["cx"] * SS - lw // 2, L["logo"]["top"] * SS))
    shape = ImageChops.lighter(shape, emblem.getchannel("A").point(lambda v: 255 if v > 100 else 0))

    halo = grow(shape, G["spread"] * SS).filter(ImageFilter.GaussianBlur(G["blur"] * SS))
    halo = ImageChops.multiply(halo.point(lambda v: round(v * G["alpha"] / 255)), ImageChops.invert(shape))
    glow = Image.new("RGBA", big, tuple(G["color"]) + (255,))
    glow.putalpha(halo)

    out = os.path.join(HERE, "frame_layers")
    os.makedirs(out, exist_ok=True)
    flat = Image.new("RGBA", (W, H))
    for name, im in (("01_glow.png", glow), ("02_plates.png", plates), ("03_bars.png", bars), ("04_emblem.png", emblem)):
        im = im.resize((W, H), Image.LANCZOS)
        im.save(os.path.join(out, name))
        flat = Image.alpha_composite(flat, im)
    flat.save(os.path.join(HERE, "frame.png"))
    prev = Image.new("RGBA", (W, H), (110, 120, 110, 255))
    prev.alpha_composite(flat)
    prev.convert("RGB").save(os.path.join(out, "Preview.png"))
    print("wrote UltimateOverlay\\frame.png + frame_layers\\")


if __name__ == "__main__":
    main()
