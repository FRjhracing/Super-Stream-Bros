#!/usr/bin/env python3
"""
make_sample_assets.py - generic, copyright-free sample overlay assets for Super Stream Bros.

    python tools\\render\\make_sample_assets.py            (needs Pillow: pip install pillow)

Writes (never overwrites unless --force):
  overlays\\melee_themes\\Default\\overlay.png    blank side panel: empty bars/slots where the renderer puts text,
                                                 pictures and stock icons; transparent webcam hole
  overlays\\melee_themes\\Default\\default.png    plain player picture (used when a player has no start.gg picture)
  overlays\\melee_themes\\Default\\theme.json
  overlays\\ultimate\\emblem.png                  plain centre logo for the Ultimate scoreboard
  overlays\\ultimate\\default_pfp.png             plain player picture
  then run overlays\\ultimate\\make_frame.py to build frame.png from layout.json + emblem.png.

The positions come from the same numbers the renderer uses (vod_overlay.py LAYOUT, or melee_themes\\layout.json),
so the sample always lines up with the rendered text. Replace any file with your own art of the same size.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
MELEE = os.path.join(HERE, "overlays", "melee_themes")
ULT = os.path.join(HERE, "overlays", "ultimate")
FORCE = "--force" in sys.argv
SCALE = 2  # panel drawn at 2x (1214x2160) for a crisp result; the renderer scales it to panel_w

# Defaults = vod_overlay.py LAYOUT (PROTOCOL's stream); melee_themes\layout.json overrides them.
L = {"panel_w": 607, "cam": [16, 37, 580, 326],
     "p1": {"name_right": 452, "name_cy": 631, "pfp": [488, 590, 77], "stock": [540, 627, 47]},
     "p2": {"name_right": 455, "name_cy": 737, "pfp": [488, 698, 79], "stock": [540, 750, 47]},
     "round": {"cx": 303, "cy": 846}, "name_size": 46, "round_size": 50}
lf = os.path.join(MELEE, "layout.json")
if os.path.isfile(lf):
    with open(lf, encoding="utf-8-sig") as f:
        for k, v in json.load(f).items():
            if isinstance(v, dict) and isinstance(L.get(k), dict):
                L[k].update(v)
            elif not k.startswith("_"):
                L[k] = v

BG_TOP, BG_BOT = (28, 34, 48), (14, 17, 25)
BAR, BAR_EDGE, SLOT, ACCENT = (44, 48, 58), (70, 76, 90), (60, 64, 76), (90, 120, 170)


def save(img, path):
    if os.path.exists(path) and not FORCE:
        print(f"  kept (exists): {path}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print(f"  wrote {path}")


def font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def melee_panel():
    s = SCALE
    w, h = L["panel_w"] * s, 1080 * s
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # vertical gradient
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)) + (255,))
    d.line([(w - 2 * s, 0), (w - 2 * s, h)], fill=ACCENT + (255,), width=2 * s)  # edge towards the game
    # Webcam hole: transparent, with a frame around it.
    x, y, cw, ch = L["cam"]
    d.rounded_rectangle([(x - 4) * s, (y - 4) * s, (x + cw + 4) * s, (y + ch + 4) * s], 10 * s, outline=ACCENT + (255,), width=3 * s)
    d.rectangle([x * s, y * s, (x + cw) * s - 1, (y + ch) * s - 1], fill=(0, 0, 0, 0))
    # Player rows: a name bar ending past the right-aligned name, a picture circle, a stock icon slot.
    for key in ("p1", "p2"):
        p = L[key]
        cy, half = p["name_cy"], L["name_size"] // 2 + 10
        d.rounded_rectangle([24 * s, (cy - half) * s, (p["name_right"] + 18) * s, (cy + half) * s], 14 * s,
                            fill=BAR + (255,), outline=BAR_EDGE + (255,), width=2 * s)
        px, py, ps = p["pfp"]
        d.ellipse([(px - 3) * s, (py - 3) * s, (px + ps + 3) * s, (py + ps + 3) * s], fill=SLOT + (255,), outline=ACCENT + (255,), width=2 * s)
        sx, sy, ss = p["stock"]
        d.rounded_rectangle([(sx - 3) * s, (sy - 3) * s, (sx + ss + 3) * s, (sy + ss + 3) * s], 6 * s, outline=BAR_EDGE + (255,), width=2 * s)
    # Round bar, centred where the round text goes.
    r, half = L["round"], L["round_size"] // 2 + 12
    bw = min(520, 2 * r["cx"] - 40)
    d.rounded_rectangle([(r["cx"] - bw // 2) * s, (r["cy"] - half) * s, (r["cx"] + bw // 2) * s, (r["cy"] + half) * s], 16 * s,
                        fill=BAR + (255,), outline=ACCENT + (255,), width=2 * s)
    # Free space between the webcam and the names: a quiet "SAMPLE" mark (your logo would go here). Drawn on
    # its own layer and blended: ImageDraw replaces pixels, so drawing the faint text straight onto the panel
    # would punch see-through holes in it. The bottom of the panel stays free for seasonal scenery
    # (melee_themes\make_theme_art.py).
    mark = Image.new("RGBA", img.size)
    md = ImageDraw.Draw(mark)
    f = font(40 * s)
    t = "SAMPLE OVERLAY"
    tw = md.textlength(t, font=f)
    top = L["cam"][1] + L["cam"][3]
    bottom = L["p1"]["name_cy"] - L["name_size"] // 2 - 10
    if bottom - top < 60:  # no room there: bottom of the panel
        top, bottom = 930, 1000
    md.text(((w - tw) / 2, ((top + bottom) / 2) * s - 26 * s), t, font=f, fill=(255, 255, 255, 40))
    return Image.alpha_composite(img, mark)


def picture(size, bg=(70, 76, 90), fg=(150, 158, 175)):
    img = Image.new("RGBA", (size, size), bg + (255,))
    d = ImageDraw.Draw(img)
    c = size / 2
    d.ellipse([c - size * 0.18, size * 0.2, c + size * 0.18, size * 0.56], fill=fg + (255,))     # head
    d.ellipse([c - size * 0.34, size * 0.62, c + size * 0.34, size * 1.2], fill=fg + (255,))     # shoulders
    return img


def emblem(size=660):
    img = Image.new("RGBA", (size, size // 2))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, size - 4, size // 2 - 4], size // 8, fill=(34, 37, 43, 255), outline=(96, 102, 114, 255), width=8)
    f = font(size // 7)
    t = "YOUR LOGO"
    d.text(((size - d.textlength(t, font=f)) / 2, size // 4 - size // 12), t, font=f, fill=(220, 226, 240, 255))
    return img


def main():
    print("Super Stream Bros sample assets")
    save(melee_panel(), os.path.join(MELEE, "Default", "overlay.png"))
    save(picture(256), os.path.join(MELEE, "Default", "default.png"))
    tj = os.path.join(MELEE, "Default", "theme.json")
    if not os.path.exists(tj):
        with open(tj, "w", encoding="utf-8") as f:
            json.dump({"name": "Default"}, f)
    save(emblem(), os.path.join(ULT, "emblem.png"))
    save(picture(256), os.path.join(ULT, "default_pfp.png"))
    print("Next: python tools\\render\\overlays\\ultimate\\make_frame.py   (builds frame.png from layout.json + emblem.png)")


if __name__ == "__main__":
    main()
