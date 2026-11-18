#!/usr/bin/env python3
"""
make_theme_art.py - draw a seasonal version of YOUR stream overlay (needs Pillow: pip install pillow).

    python tools\\render\\overlays\\melee_themes\\make_theme_art.py Halloween
    python tools\\render\\overlays\\melee_themes\\make_theme_art.py Winter --base "D:\\art\\my_panel.png"

Reads (never modifies):
    Default\\overlay.png        your normal side panel (or --base)
    layout.json                 where the names / pictures / round bar are (same file as the renderer and OBS)
    <Theme>\\art.json           optional: which kit and where things go (see below)
Writes, in <Theme>\\ (made if missing):
    overlay.png                 the themed panel: the dock shows it when the theme is picked in its ⚙
                                (and VOD renders with "season": "<Theme>")
    overlay_layers\\NN_*.png    every piece as its own full-size transparent layer, to touch up in an
                                image editor (paint.net / GIMP / Photoshop: import them in number order)
    Preview_small.png           the result at stream size, webcam hole in magenta
    theme.json                  only if missing (name + example round names for the kit)

The art goes where your layout has room: by default the "scene" box from under the round bar to the
bottom of the panel. Everything is placed in fractions of that box, so it follows your layout.

art.json (all optional; positions in 1920x1080 stream pixels):
{
  "kit": "halloween",              "halloween" or "winter" (default: from the theme name, else halloween)
  "scene": [0, 900, 607, 1080],    box for the scenery (x1, y1, x2, y2)
  "tint": [40, 0, 70, 70],         colour laid over the panel (r, g, b, alpha 0-255); [0,0,0,0] = none
  "pumpkin": [400, 1000, 70, 56],  halloween: jack-o'-lantern centre x, y, width, height; false = none
  "seed": 57                       changes the random bits (fog, branches, snowflakes)
}
Add your own kit: write a function like kit_winter() below and add it to KITS.
"""
import argparse
import json
import math
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = {"panel_w": 607, "cam": [16, 37, 580, 326], "round": {"cx": 303, "cy": 846}, "round_box": [520, 64],
          "p1": {"name_cy": 631}, "p2": {"name_cy": 737}}
CLEAR = (0, 0, 0, 0)
BLACK = (0, 0, 0, 255)


# ------------------------------------------------------------------ helpers
def layer(size):
    return Image.new("RGBA", size, CLEAR)


def mask_of(size, polys):
    m = Image.new("L", size, 0)
    md = ImageDraw.Draw(m)
    for p in polys:
        md.polygon(p, fill=255)
    return m


def grow(mask, px):
    """Dilate a mask by about px pixels (blur + threshold)."""
    return mask.filter(ImageFilter.GaussianBlur(max(0.5, px / 2))).point(lambda v: 255 if v > 8 else 0)


def apply_mask(img, mask):
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img


def font(px):
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(p):
            return ImageFont.truetype(p, max(8, int(px)))
    return ImageFont.load_default()


class Canvas:
    """Maps stream pixels (1920x1080 frame, panel at 0,0) to the overlay image's pixels."""

    def __init__(self, size, panel_w, scene):
        self.size = size
        self.u = size[0] / panel_w           # image px per stream px
        self.sy = size[1] / 1080
        self.x1, self.y1, self.x2, self.y2 = scene
        self.w, self.h = self.x2 - self.x1, self.y2 - self.y1
        self.k = self.h / 200                # scenery scale: designed for a 200 px tall scene

    def P(self, x, y):
        return (x * self.u, y * self.sy)

    def at(self, fx, fy):
        """A point in the scene box by fractions (0..1), in stream px."""
        return (self.x1 + fx * self.w, self.y1 + fy * self.h)


# ------------------------------------------------------------------ pumpkin (halloween)
ORANGE, ORANGE_DK = (189, 84, 44, 255), (119, 55, 33, 255)
STEM, STEM_DK = (92, 120, 52, 255), (58, 78, 33, 255)
GLOW, GLOW_HI = (255, 196, 61, 255), (255, 236, 150, 255)
FACE = {  # jack-o'-lantern face, in a 2200 x 1060 body centred on (1280, 705)
    "body": (1280, 705, 2200, 1060),
    "eyes": [(720, 225, 340, 200), (1840, 225, 340, 200)],
    "nose": (1280, 290, 140, 110),
    "mouth": [(470, 420), (640, 450), (690, 530), (760, 460), (1000, 470), (1250, 480), (1500, 470),
              (1720, 460), (1800, 550), (1860, 450), (2090, 420), (2060, 560), (1990, 760), (1880, 960),
              (1690, 1035), (1640, 920), (1560, 1050), (1280, 1080), (1000, 1050), (940, 900), (880, 1030),
              (700, 950), (560, 770), (490, 570)],
}


def tri(cx, cy, w, h):
    return [(cx - w / 2, cy + h / 2), (cx + w / 2, cy + h / 2), (cx, cy - h / 2)]


def shrink(pts, k):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return [(cx + (x - cx) * k, cy + (y - cy) * k) for x, y in pts]


def lobes(d, cx, cy, w, h, ol):
    spec = [(-0.33, 0.40), (0.33, 0.40), (-0.18, 0.50), (0.18, 0.50), (0, 0.50)]
    box = lambda dx, lw, g=0: (cx + dx * w - lw * w / 2 - g, cy - h / 2 - g, cx + dx * w + lw * w / 2 + g, cy + h / 2 + g)
    for dx, lw in spec:
        d.ellipse(box(dx, lw, ol), fill=BLACK)
    for dx, lw in spec:
        d.ellipse(box(dx, lw), fill=ORANGE, outline=ORANGE_DK, width=max(1, int(ol * 0.6)))


def pumpkin(size, cx, cy, w, h, u, glow_rgba):
    """Layers (outer glow, stem, face glow, body) of a carved pumpkin, body w x h centred on cx, cy (image px)."""
    bcx, bcy, bw, bh = FACE["body"]
    kx, ky = w / bw, h / bh
    T = lambda pts: [(cx + (x - bcx) * kx, cy + (y - bcy) * ky) for x, y in pts]
    ol = 2.4 * u
    st = layer(size)
    sd = ImageDraw.Draw(st)
    sw, top, bot = 0.13 * w, cy - h * 0.66, cy - h * 0.40
    sd.polygon([(cx - sw / 2, bot), (cx + sw / 2, bot), (cx + sw * 0.9, top + (bot - top) * 0.06), (cx + sw * 0.1, top)],
               fill=STEM, outline=BLACK, width=max(1, int(ol * 0.7)))
    body = layer(size)
    lobes(ImageDraw.Draw(body), cx, cy, w, h, ol)
    eyes = [T(tri(*e)) for e in FACE["eyes"]]
    nose = T(tri(*FACE["nose"]))
    mouth = T(FACE["mouth"])
    hole = mask_of(size, eyes + [nose, mouth])
    rim = grow(hole, 2.0 * u)
    body = Image.composite(Image.new("RGBA", size, BLACK), body, ImageChops.multiply(rim, body.getchannel("A")))
    body = apply_mask(body, ImageChops.invert(hole))
    glow = layer(size)
    gd = ImageDraw.Draw(glow)
    for p in eyes + [nose, mouth]:
        gd.polygon(p, fill=GLOW)
    for p in eyes + [nose]:
        gd.polygon(shrink(p, 0.45), fill=GLOW_HI)
    glow = apply_mask(glow, hole)
    halo = layer(size)
    ImageDraw.Draw(halo).ellipse((cx - w * 0.75, cy - h * 0.8, cx + w * 0.75, cy + h * 0.75), fill=glow_rgba)
    sil = layer(size)
    lobes(ImageDraw.Draw(sil), cx, cy, w, h, ol)
    halo = apply_mask(halo.filter(ImageFilter.GaussianBlur(14 * u)), ImageChops.invert(sil.getchannel("A")))
    return halo, st, glow, body


# ------------------------------------------------------------------ kits
def ground_line(c, rnd, fy=0.70, wobble=0.04):
    pts = []
    for i in range(9):
        fx = i / 8
        pts.append(c.at(fx, fy + rnd.uniform(-wobble, wobble)))
    return pts


def kit_halloween(c, art, rnd):
    size, u, k = c.size, c.u, c.k
    P = c.P
    S = lambda v: v * k  # scenery size in stream px
    out = []

    glow = layer(size)
    gd = ImageDraw.Draw(glow)
    for fx, fw in ((0.47, 0.33), (0.21, 0.23), (0.77, 0.26)):
        x, _ = c.at(fx, 0)
        gd.ellipse((*P(x - fw * c.w, c.y1 + 0.45 * c.h), *P(x + fw * c.w, c.y2 + 10)), fill=(120, 255, 170, 70))
    out.append(("graveyard_glow", glow.filter(ImageFilter.GaussianBlur(22 * u))))

    moon = layer(size)
    mx, my = c.at(0.18, 0.25)
    mr = S(26)
    md = ImageDraw.Draw(moon)
    md.ellipse((*P(mx - mr * 2.2, my - mr * 2.2), *P(mx + mr * 2.2, my + mr * 2.2)), fill=(255, 240, 190, 90))
    moon = moon.filter(ImageFilter.GaussianBlur(14 * u))
    md = ImageDraw.Draw(moon)
    md.ellipse((*P(mx - mr, my - mr), *P(mx + mr, my + mr)), fill=(255, 244, 205, 255))
    for ox, oy, cr in ((-0.35, -0.2, 0.22), (0.3, 0.25, 0.16), (0.1, -0.45, 0.1)):
        md.ellipse((*P(mx + ox * mr - cr * mr, my + oy * mr - cr * mr), *P(mx + ox * mr + cr * mr, my + oy * mr + cr * mr)),
                   fill=(236, 222, 180, 255))
    out.append(("moon", moon))

    bats = layer(size)
    bd = ImageDraw.Draw(bats)
    wing = [(0.1, -0.3), (0.13, -0.12), (0.3, -0.22), (0.55, -0.42), (0.8, -0.48), (1.0, -0.3), (0.86, -0.2),
            (0.8, 0.06), (0.66, -0.04), (0.55, 0.16), (0.42, 0.0), (0.26, 0.16), (0.12, 0.1), (0, 0.22)]
    for fx, fy, bw in ((0.34, 0.12, 42), (0.59, 0.08, 34), (0.78, 0.17, 28)):
        bx, by = c.at(fx, fy)
        h = S(bw) / 2
        poly = [P(bx + x * h, by + y * h) for x, y in wing] + [P(bx - x * h, by + y * h) for x, y in reversed(wing)]
        bd.polygon(poly, fill=BLACK)
        bd.ellipse((*P(bx - h * 0.16, by - h * 0.22), *P(bx + h * 0.16, by + h * 0.2)), fill=BLACK)
    out.append(("bats", bats))

    line = ground_line(c, rnd)
    ground = layer(size)
    gdr = ImageDraw.Draw(ground)
    gdr.polygon([P(*p) for p in line] + [P(c.x2, c.y2), P(c.x1, c.y2)], fill=(12, 14, 22, 255))
    gdr.line([P(*p) for p in line], fill=(34, 40, 56, 255), width=max(1, int(2.5 * u)))
    out.append(("ground", ground))
    gy = lambda fx: line[min(8, round(fx * 8))][1]  # ground height near fx

    tree = layer(size)
    td = ImageDraw.Draw(tree)

    def branch(x, y, ang, length, width, depth):
        x2, y2 = x + math.cos(ang) * length, y - math.sin(ang) * length
        td.line([P(x, y), P(x2, y2)], fill=BLACK, width=max(1, int(width * u)))
        td.ellipse((*P(x2 - width / 2, y2 - width / 2), *P(x2 + width / 2, y2 + width / 2)), fill=BLACK)
        if depth:
            for da in (rnd.uniform(0.35, 0.6), -rnd.uniform(0.35, 0.6)):
                branch(x2, y2, ang + da, length * rnd.uniform(0.6, 0.75), width * 0.62, depth - 1)
    tx = c.at(0.07, 0)[0]
    branch(tx, gy(0.07) + S(4), math.pi / 2 + 0.08, S(125) * 0.42, S(9), 4)
    out.append(("tree", tree))

    stones = layer(size)
    f = font(S(22) * u)
    for fx, sw_, sh_, tilt, text in ((0.27, 58, 74, -4, "RIP"), (0.47, 74, 104, 0, "RIP"), (0.93, 40, 48, -6, "")):
        sw_, sh_ = S(sw_), S(sh_)
        cxs = c.at(fx, 0)[0]
        base_y = gy(fx) + S(8)
        st = layer((int(sw_ * u * 1.6) + 2, int(sh_ * u * 1.4) + 2))
        sd = ImageDraw.Draw(st)
        ox, oy, r = sw_ * u * 0.3, sh_ * u * 0.2, sw_ * u / 2
        for fill, pad in ((BLACK, 3 * u), ((78, 84, 100, 255), 0), ((112, 118, 136, 255), 0)):
            sd.rectangle((ox - pad, oy + r, ox + sw_ * u + pad, oy + sh_ * u + pad), fill=fill)
            sd.ellipse((ox - pad, oy - pad, ox + sw_ * u + pad, oy + 2 * r + pad), fill=fill)
        sd.rectangle((ox + sw_ * u * 0.78, oy + r, ox + sw_ * u, oy + sh_ * u), fill=(78, 84, 100, 255))
        if text:
            tb = sd.textbbox((0, 0), text, font=f)
            sd.text((ox + (sw_ * u * 0.78 - (tb[2] - tb[0])) / 2 + sw_ * u * 0.06, oy + sh_ * u * 0.38), text, font=f,
                    fill=(58, 62, 74, 255))
        st = st.rotate(tilt, resample=Image.BICUBIC, center=(st.width / 2, oy + sh_ * u))
        stones.alpha_composite(st, (int(cxs * u - st.width / 2), int(base_y * c.sy - (oy + sh_ * u))))
    ccx, cby, chh = c.at(0.80, 0)[0], gy(0.80) + S(10), S(62)
    sd = ImageDraw.Draw(stones)
    for pad, fill in ((3, BLACK), (0, (112, 118, 136, 255))):
        sd.rectangle((*P(ccx - S(6) - pad, cby - chh - pad), *P(ccx + S(6) + pad, cby + pad)), fill=fill)
        sd.rectangle((*P(ccx - S(22) - pad, cby - chh * 0.72 - pad), *P(ccx + S(22) + pad, cby - chh * 0.72 + S(11) + pad)), fill=fill)
    out.append(("tombstones", stones))

    fog = layer(size)
    fd = ImageDraw.Draw(fog)
    for _ in range(8):
        fx_, fy_ = c.at(rnd.uniform(0, 1), rnd.uniform(0.78, 0.95))
        fw, fh = S(rnd.uniform(50, 110)), S(rnd.uniform(7, 13))
        fd.ellipse((*P(fx_ - fw, fy_ - fh), *P(fx_ + fw, fy_ + fh)), fill=(205, 225, 235, 38))
    out.append(("fog", fog.filter(ImageFilter.GaussianBlur(8 * u))))

    pk = art.get("pumpkin", True)
    if pk is not False:
        if isinstance(pk, (list, tuple)) and len(pk) == 4:
            pcx, pcy, pw, ph = pk
        else:
            pw, ph = S(70), S(56)
            pcx = c.at(0.64, 0)[0]
            pcy = gy(0.64) - ph * 0.35
        halo, stem_l, face, body = pumpkin(size, pcx * u, pcy * c.sy, pw * u, ph * c.sy, u, (165, 115, 255, 100))
        out += [("pumpkin_outer_glow", halo), ("pumpkin_stem", stem_l), ("pumpkin_face_glow", face), ("pumpkin_body", body)]
    return out


def kit_winter(c, art, rnd):
    size, u, k = c.size, c.u, c.k
    P = c.P
    S = lambda v: v * k
    out = []
    sky = layer(size)
    ImageDraw.Draw(sky).ellipse((*P(c.x1 - 40, c.y1 + 0.2 * c.h), *P(c.x2 + 40, c.y2 + 60)), fill=(150, 200, 255, 60))
    out.append(("cold_glow", sky.filter(ImageFilter.GaussianBlur(24 * u))))
    line = ground_line(c, rnd, fy=0.72, wobble=0.05)
    snow = layer(size)
    sd = ImageDraw.Draw(snow)
    sd.polygon([P(*p) for p in line] + [P(c.x2, c.y2), P(c.x1, c.y2)], fill=(236, 244, 255, 255))
    sd.line([P(*p) for p in line], fill=(190, 210, 235, 255), width=max(1, int(2.5 * u)))
    out.append(("snow_ground", snow))
    gy = lambda fx: line[min(8, round(fx * 8))][1]
    trees = layer(size)
    td = ImageDraw.Draw(trees)
    for fx, th in ((0.08, 120), (0.20, 85), (0.86, 105), (0.95, 70)):
        x, base = c.at(fx, 0)[0], gy(fx) + S(6)
        h, w = S(th), S(th) * 0.55
        td.rectangle((*P(x - S(4), base - S(10)), *P(x + S(4), base)), fill=(70, 50, 40, 255))
        for i, f in enumerate((0.0, 0.3, 0.55)):
            ty = base - S(10) - h * f
            tw = w * (1 - f * 0.8)
            td.polygon([P(x - tw / 2, ty), P(x + tw / 2, ty), P(x, ty - h * 0.5)], fill=(30, 90, 60, 255))
            td.polygon([P(x - tw / 2, ty), P(x + tw / 2, ty), P(x + tw / 4, ty - S(5)), P(x - tw / 4, ty - S(5))],
                       fill=(236, 244, 255, 255))
    out.append(("trees", trees))
    flakes = layer(size)
    fd = ImageDraw.Draw(flakes)
    for _ in range(70):
        x, y = c.at(rnd.uniform(0, 1), rnd.uniform(0, 0.75))
        r = S(rnd.uniform(1.2, 3.2))
        fd.ellipse((*P(x - r, y - r), *P(x + r, y + r)), fill=(255, 255, 255, rnd.randint(150, 255)))
    out.append(("snowflakes", flakes))
    return out


KITS = {"halloween": kit_halloween, "winter": kit_winter}
ROUNDS = {
    "halloween": {"finalsLabel": "Final Haunt", "finalsFrom": 4, "rounds": {
        "Winners Round {n}": "Survivors Round {n}", "Winners Quarter-Final": "Survivors Quarters",
        "Winners Semi-Final": "Survivors Semis", "Winners Final": "Survivors Final",
        "Losers Round {n}": "Graveyard Round {n}", "Losers Top 8": "Graveyard Top 8",
        "Losers Quarter-Final": "Graveyard Quarters", "Losers Semi-Final": "Graveyard Semis",
        "Losers Final": "Graveyard Final", "Grand Final": "Grand Fright", "Grand Final Reset": "Grand Fright Reset"}},
    "winter": {"finalsLabel": "Summit", "finalsFrom": 4, "rounds": {
        "Grand Final": "Grand Final (Winter Edition)"}},
}
TINTS = {"halloween": [40, 0, 70, 80], "winter": [0, 30, 70, 50]}


# ------------------------------------------------------------------ main
def load_layout():
    lay = json.loads(json.dumps(LAYOUT))
    p = os.path.join(HERE, "layout.json")
    if os.path.isfile(p):
        with open(p, encoding="utf-8-sig") as f:
            for key, v in json.load(f).items():
                if isinstance(v, dict) and isinstance(lay.get(key), dict):
                    lay[key].update(v)
                elif not key.startswith("_"):
                    lay[key] = v
    return lay


def main():
    ap = argparse.ArgumentParser(description="Draw a seasonal version of your stream overlay.")
    ap.add_argument("theme", help="theme folder name, e.g. Halloween (made if missing)")
    ap.add_argument("--base", default=os.path.join(HERE, "Default", "overlay.png"), help="your normal panel")
    a = ap.parse_args()
    folder = os.path.join(HERE, a.theme)
    art_file = os.path.join(folder, "art.json")
    art = {}
    if os.path.isfile(art_file):
        with open(art_file, encoding="utf-8-sig") as f:
            art = json.load(f)
    kit = str(art.get("kit") or (a.theme.lower() if a.theme.lower() in KITS else "halloween")).lower()
    if kit not in KITS:
        sys.exit(f"Unknown kit {kit!r}; known: {', '.join(KITS)}")
    if not os.path.isfile(a.base):
        sys.exit(f"Base overlay not found: {a.base}")
    lay = load_layout()
    base = Image.open(a.base).convert("RGBA")
    pw = lay["panel_w"]
    round_bottom = lay["round"]["cy"] + lay.get("round_box", [520, 64])[1] / 2 + 24
    scene = art.get("scene") or [0, min(1000, round_bottom), pw, 1080]
    c = Canvas(base.size, pw, scene)
    rnd = random.Random(art.get("seed", 57))
    print(f"Theme {a.theme}: kit {kit}, base {a.base} ({base.size[0]}x{base.size[1]}), scene {scene}")

    layers = []
    tint = art.get("tint", TINTS.get(kit, [0, 0, 0, 0]))
    if tint and tint[3] > 0:
        t = Image.new("RGBA", base.size, tuple(tint))
        layers.append(("tint", t))
    # Scenery stays inside the scene box (and inside the panel's own opaque shape)
    box = Image.new("L", base.size, 0)
    ImageDraw.Draw(box).rectangle((*c.P(scene[0], scene[1] - 0.15 * c.h), *c.P(scene[2], scene[3])), fill=255)
    box = box.filter(ImageFilter.GaussianBlur(6 * c.u))
    for name, im in KITS[kit](c, art, rnd):
        layers.append((name, apply_mask(im, box)))

    opaque = base.getchannel("A").point(lambda v: 255 if v > 200 else 0)  # never paint into the webcam hole
    out_dir = os.path.join(folder, "overlay_layers")
    os.makedirs(out_dir, exist_ok=True)
    flat = base.copy()
    for i, (name, im) in enumerate(layers, 1):
        im = apply_mask(im, opaque)
        im.save(os.path.join(out_dir, f"{i:02d}_{name}.png"))
        flat = Image.alpha_composite(flat, im)
    flat.save(os.path.join(folder, "overlay.png"))
    small = Image.new("RGBA", (pw, 1080), (255, 0, 255, 255))
    small.alpha_composite(flat.resize((pw, 1080), Image.LANCZOS))
    small.convert("RGB").save(os.path.join(folder, "Preview_small.png"))
    tj = os.path.join(folder, "theme.json")
    if not os.path.isfile(tj):
        with open(tj, "w", encoding="utf-8") as f:
            json.dump({"name": a.theme, **ROUNDS.get(kit, {})}, f, indent=2)
        print(f"wrote {tj} (edit the round names)")
    print(f"wrote {os.path.join(folder, 'overlay.png')}, Preview_small.png and {len(layers)} layers in overlay_layers\\")


if __name__ == "__main__":
    main()
