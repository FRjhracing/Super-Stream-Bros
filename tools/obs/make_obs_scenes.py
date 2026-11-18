#!/usr/bin/env python3
"""
make_obs_scenes.py - build an OBS scene collection for the Super Stream Bros Melee dock.

    python tools\\obs\\make_obs_scenes.py                 (stdlib only; run from anywhere)
    python tools\\obs\\make_obs_scenes.py --name "My Weekly" --out "%USERPROFILE%\\Desktop"

Then in OBS: Scene Collection > Import > pick the .json it wrote > (tick it) > Import, and switch to it
under Scene Collection. Pick your capture card / webcam in the two video sources (their devices are
left empty on purpose) and add your audio sources.

Positions come from tools\\render\\overlays\\melee_themes\\layout.json, the same file the VOD renderer
uses, so the stream and the rendered VODs line up. Keys it reads (1920x1080 pixels; missing keys keep
the defaults below, which are PROTOCOL's stream):
    panel_w                    overlay.png is fitted to panel_w x 1080 at 0,0
    game_x, game_w             game capture box (full height, kept 4:3 inside it)
    cam                        [x, y, w, h] webcam box (keep it transparent in overlay.png)
    p1/p2.name_right, name_cy  name box: right edge x, centre y
    name_box                   [w, h] name box size (OBS shrinks long names into it; the dock cuts
                               names that would get too small, using the same box)
    p1/p2.pfp, p1/p2.stock     [x, y, size] picture and stock icon squares
    round.cx, round.cy         round text centre;  round_box [w, h] its box
    obs_font                   installed font name for the OBS text (e.g. your stream font after
                               installing it; default "Segoe UI")
    obs_font_bold              true/false
    text                       text colour ("white" or "0xRRGGBB")

Writes (never overwrites without --force):
    <out>\\<name>.json             the scene collection to import
    <out>\\<name> layout.svg       a picture of where every source goes (open in a browser)
"""
import argparse
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(os.path.dirname(HERE))  # package root (tools\obs -> tools -> root)
DEF_THEMES = os.path.join(PKG, "tools", "render", "overlays", "melee_themes")
DEF_DOCK = os.path.join(PKG, "tools", "render", "docks", "melee")

LAYOUT = {
    "panel_w": 607, "game_x": 607, "game_w": 1313,
    "cam": [16, 37, 580, 326],
    "p1": {"name_right": 452, "name_cy": 631, "pfp": [488, 590, 77], "stock": [540, 627, 47]},
    "p2": {"name_right": 455, "name_cy": 737, "pfp": [488, 698, 79], "stock": [540, 750, 47]},
    "round": {"cx": 303, "cy": 846},
    "name_box": [273, 59], "round_box": [520, 64],
    "obs_font": "Segoe UI", "obs_font_bold": True, "text": "white",
}

# OBS constants
ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, ALIGN_TOP = 0, 1, 2, 4
TOP_LEFT = ALIGN_LEFT | ALIGN_TOP
BOUNDS_NONE, BOUNDS_STRETCH, BOUNDS_INNER = 0, 1, 2


def load_layout(path):
    lay = json.loads(json.dumps(LAYOUT))
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for k, v in json.load(f).items():
                if k.startswith("_"):
                    continue
                if isinstance(v, dict) and isinstance(lay.get(k), dict):
                    lay[k].update(v)
                else:
                    lay[k] = v
        print(f"Layout: {path}")
    else:
        print("Layout: built-in defaults (no layout.json found)")
    return lay


def obs_color(c):
    """'white' / '0xRRGGBB' / '#RRGGBB' -> OBS's 0xAABBGGRR integer."""
    named = {"white": "ffffff", "black": "000000"}
    s = named.get(str(c).lower(), str(c).lower().replace("0x", "").replace("#", ""))
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except (ValueError, IndexError):
        r = g = b = 255
    return 0xFF000000 | (b << 16) | (g << 8) | r


def path_for_obs(p):
    return os.path.abspath(p).replace("\\", "/")


class Collection:
    def __init__(self, name):
        self.name = name
        self.sources = []
        self.by_name = {}

    def source(self, kind, name, settings, versioned=None):
        s = {"name": name, "uuid": str(uuid.uuid4()), "id": kind, "versioned_id": versioned or kind,
             "settings": settings, "mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5,
             "enabled": True, "muted": False, "hotkeys": {}, "deinterlace_mode": 0,
             "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}}
        self.sources.append(s)
        self.by_name[name] = s
        return s

    def scene(self, name, items):
        """items: (source name, x, y, align, bounds_type, bw, bh, bounds_align), bottom first."""
        out = []
        for i, (src, x, y, align, btype, bw, bh, balign) in enumerate(items, 1):
            out.append({"name": src, "source_uuid": self.by_name[src]["uuid"], "visible": True, "locked": False,
                        "rot": 0.0, "pos": {"x": float(x), "y": float(y)}, "scale": {"x": 1.0, "y": 1.0},
                        "align": align, "bounds_type": btype, "bounds_align": balign,
                        "bounds": {"x": float(bw), "y": float(bh)}, "bounds_crop": False,
                        "crop_left": 0, "crop_top": 0, "crop_right": 0, "crop_bottom": 0, "id": i,
                        "group_item_backup": False, "scale_filter": "disable", "blend_method": "default",
                        "blend_type": "normal", "private_settings": {}})
        self.source("scene", name, {"id_counter": len(out), "custom_size": False, "items": out})

    def json(self, scenes):
        return {"name": self.name, "current_scene": scenes[0], "current_program_scene": scenes[0],
                "scene_order": [{"name": s} for s in scenes], "sources": self.sources, "groups": [],
                "current_transition": "Fade", "transition_duration": 300, "transitions": [],
                "quick_transitions": [], "saved_projectors": [], "preview_locked": False,
                "scaling_enabled": False, "resolution": {"x": 1920, "y": 1080}, "version": 2, "modules": {}}


def build(lay, out_dir, name):
    f = lambda n: path_for_obs(os.path.join(out_dir, n))
    font = {"face": lay["obs_font"], "style": "Bold" if lay.get("obs_font_bold") else "Regular",
            "size": 96, "flags": 1 if lay.get("obs_font_bold") else 0}
    color = obs_color(lay.get("text", "white"))
    c = Collection(name)

    # Video: devices left empty, picked in OBS (they differ on every PC)
    c.source("dshow_input", "Game capture", {"last_video_device_id": "", "video_device_id": ""})
    c.source("dshow_input", "Webcam", {"last_video_device_id": "", "video_device_id": ""})
    # Dock output files
    c.source("image_source", "Overlay", {"file": f("overlay.png")})
    for i in (1, 2):
        c.source("text_gdiplus", f"P{i} name", {"read_from_file": True, "file": f(f"player{i}_tag.txt"),
                                                "font": font, "color": color, "align": "right", "valign": "center"},
                 versioned="text_gdiplus_v3")
        c.source("image_source", f"P{i} picture", {"file": f(f"player{i}_pfp.png")})
        c.source("image_source", f"P{i} stock icon", {"file": f(f"player{i}_stock.png")})
    c.source("text_gdiplus", "Round", {"read_from_file": True, "file": f("match_round.txt"), "font": font,
                                       "color": color, "align": "center", "valign": "center"},
             versioned="text_gdiplus_v3")

    gx, gw = lay["game_x"], lay["game_w"]
    cx, cy, cw, ch = lay["cam"]
    nbw, nbh = lay["name_box"]
    rbw, rbh = lay["round_box"]
    items = [
        ("Game capture", gx, 0, TOP_LEFT, BOUNDS_INNER, gw, 1080, ALIGN_CENTER),
        ("Webcam", cx, cy, TOP_LEFT, BOUNDS_INNER, cw, ch, ALIGN_CENTER),
        ("Overlay", 0, 0, TOP_LEFT, BOUNDS_STRETCH, lay["panel_w"], 1080, ALIGN_CENTER),
    ]
    for i in (1, 2):
        p = lay[f"p{i}"]
        px, py, ps = p["pfp"]
        sx, sy, ss = p["stock"]
        items += [
            # name: right edge at name_right, centred on name_cy; long names shrink into the box
            (f"P{i} name", p["name_right"], p["name_cy"], ALIGN_RIGHT, BOUNDS_INNER, nbw, nbh, ALIGN_RIGHT),
            (f"P{i} picture", px, py, TOP_LEFT, BOUNDS_INNER, ps, ps, ALIGN_CENTER),
            (f"P{i} stock icon", sx, sy, TOP_LEFT, BOUNDS_INNER, ss, ss, ALIGN_CENTER),
        ]
    items.append(("Round", lay["round"]["cx"], lay["round"]["cy"], ALIGN_CENTER, BOUNDS_INNER, rbw, rbh, ALIGN_CENTER))
    c.scene("SSB Stream", items)
    c.scene("SSB No Overlay", [("Game capture", 0, 0, TOP_LEFT, BOUNDS_INNER, 1920, 1080, ALIGN_CENTER)])
    return c.json(["SSB Stream", "SSB No Overlay"]), items


def svg_preview(lay, items, overlay_png):
    """A to-scale picture of the SSB Stream scene: every source's box and name."""
    colors = {"Game capture": "#ae3ec9", "Webcam": "#ae3ec9", "Overlay": "#2f9e44"}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             'viewBox="0 0 1920 1080" width="1920" height="1080" font-family="Segoe UI, sans-serif">',
             '<rect width="1920" height="1080" fill="#20242c"/>']
    if os.path.isfile(overlay_png):
        parts.append(f'<image x="0" y="0" width="{lay["panel_w"]}" height="1080" preserveAspectRatio="none" '
                     f'xlink:href="file:///{path_for_obs(overlay_png)}" href="file:///{path_for_obs(overlay_png)}"/>')
    for src, x, y, align, btype, bw, bh, _ in items:
        # top-left corner of the box from the item's alignment point
        left = x - (bw if align & ALIGN_RIGHT else 0 if align & ALIGN_LEFT else bw / 2)
        top = y if align & ALIGN_TOP else y - bh / 2
        col = colors.get(src, "#1c7ed6")
        parts.append(f'<rect x="{left:.0f}" y="{top:.0f}" width="{bw}" height="{bh}" fill="{col}" fill-opacity="0.12" '
                     f'stroke="{col}" stroke-width="4" stroke-dasharray="12 6"/>')
        fs = 34 if bh > 120 else 18
        ty = top + (40 if bh > 120 else bh / 2 + 6)
        parts.append(f'<text x="{left + 8:.0f}" y="{ty:.0f}" font-size="{fs}" font-weight="700" fill="{col}" '
                     f'stroke="#000" stroke-width="3" paint-order="stroke">{src}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Build an OBS scene collection for the Super Stream Bros Melee dock.")
    ap.add_argument("--name", default="Super Stream Bros", help="scene collection name (default: %(default)s)")
    ap.add_argument("--themes", default=DEF_THEMES, help="themes folder with layout.json (default: the package's)")
    ap.add_argument("--dock", default=DEF_DOCK, help="Melee dock folder; OBS reads its output\\ (default: the package's)")
    ap.add_argument("--output", help="the overlay folder OBS reads, if not <dock>\\output (e.g. a hub's share: "
                                     "\\\\192.168.1.10\\ssb-melee; see guides\\06)")
    ap.add_argument("--out", default=os.path.join(HERE, "generated"), help="where to write (default: tools\\obs\\generated)")
    ap.add_argument("--force", action="store_true", help="overwrite files written before")
    a = ap.parse_args()

    lay = load_layout(os.path.join(a.themes, "layout.json"))
    overlay_dir = a.output or os.path.join(a.dock, "output")
    coll, items = build(lay, overlay_dir, a.name)
    out = os.path.expandvars(a.out)
    os.makedirs(out, exist_ok=True)
    jpath = os.path.join(out, f"{a.name}.json")
    spath = os.path.join(out, f"{a.name} layout.svg")
    for p in (jpath, spath):
        if os.path.exists(p) and not a.force:
            sys.exit(f"{p} exists. Use --force to overwrite it (or --name for another collection).")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(coll, f, indent=2)
    with open(spath, "w", encoding="utf-8") as f:
        f.write(svg_preview(lay, items, os.path.join(a.themes, "Default", "overlay.png")))
    print(f"Dock output: {overlay_dir}")
    print(f"Wrote {jpath}")
    print(f"Wrote {spath}")
    print("OBS: Scene Collection > Import > this .json > Import; then Scene Collection > " + a.name + ".")
    print("Then pick your devices in 'Game capture' and 'Webcam', and add your audio sources.")
    if not os.path.isdir(overlay_dir):
        print("Note: the overlay folder isn't reachable yet (start the dock once to create it; for a share, "
              "check it opens in Explorer).")


if __name__ == "__main__":
    main()
