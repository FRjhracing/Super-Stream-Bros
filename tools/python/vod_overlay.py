#!/usr/bin/env python3
"""
vod_overlay.py - rebuild the Protocol stream overlay for footage that was not on
stream (sets rendered from replays), using the same pieces OBS uses.

Layout (1920x1080) measured from the OBS scene collection "Protocol" and a
recorded frame of Protocol #56:
  side panel   tools/render/overlays/melee_themes/Default/overlay.png (or a theme's) scaled to 607 px wide, at 0,0
  webcam box   16,37  580x326      -> replaced by a "REPLAY" card
  P1 name      right edge x=452, centre y=631   P1 picture 488,590 77x77
  P2 name      right edge x=455, centre y=737   P2 picture 488,698 79x79
  stock icons  540,627 / 540,750, 47x47 (only when a character is known)
  round        centred on x=303 (bar 43..563), centre y=846
  names        tag only (no sponsor prefix), as the Stream Dock shows them
  game         x=607..1920, full height (Dolphin 642x528 -> 1313x1080)

Text uses the stream's font (Typo Round Regular Demo). Stdlib + tools\\ffmpeg only.
"""
import json
import os
import subprocess
import tempfile
import urllib.request

CODE = os.path.dirname(os.path.abspath(__file__))           # tools\\python (the scripts)
ROOT = os.path.dirname(os.path.dirname(CODE))                # project folder
HERE = ROOT  # older name, kept for compatibility
FFMPEG = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe")
# Stream looks: tools\\render\\overlays\\melee_themes\\ (desktop, since 2026-11-11); Seasonal\\ on the laptop.
SEASONAL = next((d for d in (os.path.join(ROOT, "tools", "render", "overlays", "melee_themes"),
                             os.path.join(ROOT, "Seasonal")) if os.path.isdir(d)),
                os.path.join(ROOT, "tools", "render", "overlays", "melee_themes"))
# Normal stream overlay (moved here from Pictures\protocoloverlaynew_26x.png on 2026-10-24).
PANEL_PNG = os.path.join(SEASONAL, "Default", "overlay.png")


def season_panel(season):
    """Overlay image for a seasonal theme (melee_themes\\<season>\\overlay.png), else the normal one."""
    p = os.path.join(SEASONAL, season or "Default", "overlay.png")
    return p if season and os.path.isfile(p) else PANEL_PNG


def season_round(season, text):
    """Round name in the theme's wording (same table the Stream Dock uses). The dock also knows
    which losers round is top 8; here that round keeps its 'Losers Round N' mapping."""
    import re
    try:
        with open(os.path.join(SEASONAL, season, "theme.json"), encoding="utf-8") as f:
            rounds = json.load(f).get("rounds") or {}
    except (OSError, ValueError, TypeError):
        return text
    if text in rounds:
        return rounds[text]
    for key, value in rounds.items():
        if "{n}" in key:
            m = re.fullmatch(re.escape(key).replace(re.escape("{n}"), r"(\d+)"), text or "")
            if m:
                return value.replace("{n}", m.group(1))
    return text
FONT_FILE = "Typo_Round_Regular_Demo.otf"  # the stream font


FALLBACK_FONTS = ("segoeuib.ttf", "arialbd.ttf", "arial.ttf")  # standard Windows fonts
_warned = []


def find_font():
    """The stream font (layout.json "font_file", else Typo Round), looked up in melee_themes\\Default\\ (travels
    with the folder), then the per-user and system font folders. Missing: a standard Windows font, with a note."""
    dirs = (os.path.join(SEASONAL, "Default"), SEASONAL,
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    want = FONT_FILE_OVERRIDE or FONT_FILE
    for name in (want,) + FALLBACK_FONTS:
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                if name != want and not _warned:
                    _warned.append(1)
                    print(f"  note: stream font {want} not found; using {name} (see melee_themes\\PROVIDE YOUR OWN.md)")
                return p
    raise FileNotFoundError(f"No font found: put {want} in tools\\render\\overlays\\melee_themes\\Default\\")

# Dock art: StreamDock\ on the laptop; tools\render\docks\stream_dock\ on the desktop.
ASSETS = next((d for d in (os.path.join(ROOT, "tools", "render", "docks", "stream_dock", "assets"),
                           os.path.join(ROOT, "tools", "render", "docks", "melee", "assets"),  # Super Stream Bros package
                           os.path.join(ROOT, "StreamDock", "assets"))
               if os.path.isdir(d)), os.path.join(ROOT, "StreamDock", "assets"))
STOCKS = os.path.join(ASSETS, "stock_icons")
DEFAULT_PFP = next((p for p in (os.path.join(ASSETS, "default.png"),
                                os.path.join(SEASONAL, "Default", "default.png"))  # generic sample asset
                    if os.path.isfile(p)), os.path.join(ASSETS, "default.png"))

W, H = 1920, 1080
PANEL_W = 607
GAME_X, GAME_W = 607, 1313

# PROTOCOL's layout. Another stream layout: put a layout.json in melee_themes\ (same keys; see
# examples\melee_layout.example.json and the "Overlay layout map" guide). Anything it leaves out keeps these values.
LAYOUT = {
    "p1": {"name_right": 452, "name_cy": 631, "pfp": (488, 590, 77), "stock": (540, 627, 47)},
    "p2": {"name_right": 455, "name_cy": 737, "pfp": (488, 698, 79), "stock": (540, 750, 47)},
    "round": {"cx": 303, "cy": 846},  # centred in the round bar (43..563), like OBS's fit-to-bar box
    "name_size": 46,
    "round_size": 50,
    "cam": (16, 37, 580, 326),
    "cam_fill": "0x0d1b33", "cam_edge": "0x3a6fd8", "cam_sub": "0xb8c7e6", "text": "white",
}
LAYOUT_FILE = os.path.join(SEASONAL, "layout.json")
if os.path.isfile(LAYOUT_FILE):
    with open(LAYOUT_FILE, encoding="utf-8-sig") as _f:
        _user = {k: v for k, v in json.load(_f).items() if not k.startswith("_")}
    PANEL_W = _user.pop("panel_w", PANEL_W)                 # panel image is scaled to this width, at 0,0
    GAME_X, GAME_W = _user.pop("game_x", GAME_X), _user.pop("game_w", GAME_W)  # game picture box (full height)
    FONT_FILE_OVERRIDE = _user.pop("font_file", None)
    for _k, _v in _user.items():
        if isinstance(_v, dict) and isinstance(LAYOUT.get(_k), dict):
            LAYOUT[_k].update({a: tuple(b) if isinstance(b, list) else b for a, b in _v.items()})
        else:
            LAYOUT[_k] = tuple(_v) if isinstance(_v, list) else _v
else:
    FONT_FILE_OVERRIDE = None


def ff_escape_path(p):
    """Path for use inside an ffmpeg filter argument."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def ff_escape_text(t):
    return (t.replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:")
             .replace("%", "\\%").replace(",", "\\,"))


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "ProtocolVOD/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def circle_pfp(src, size, dest):
    """Cover-crop to a square and cut a circle, like the dock / Stream Updater."""
    vf = (f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size},format=rgba,"
          f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-{size/2},Y-{size/2}),{size/2}),alpha(X,Y),0)'")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", src, "-vf", vf, "-frames:v", "1", dest], check=True)
    return dest


def build_panel(out_png, p1, p2, round_text, cam_label=("REPLAY", "off-stream setup"), panel_png=None):
    """Write a 1920x1080 RGBA PNG: side panel + names + pictures + round; game area transparent.

    p1/p2: {"name": "ODU | Aris", "imageUrl": "...", "character": "Luigi", "color": "neutral"}
    panel_png: overlay image (default: the normal one; see season_panel()).
    """
    tmp = tempfile.mkdtemp(prefix="vodpanel_")
    inputs, chains = [], []

    def add_input(path):
        inputs.extend(["-i", path])
        return len(inputs) // 2  # input index (0 is the base canvas)

    # base: transparent canvas
    base = ["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x{H},format=rgba"]
    panel_i = add_input(panel_png or PANEL_PNG)
    chains.append(f"[{panel_i}:v]scale={PANEL_W}:-1[panel]")
    cur = "[0:v][panel]overlay=0:0"

    x, y, w, h = LAYOUT["cam"]
    font = ff_escape_path(find_font())
    if cam_label:  # replay sets: card in the webcam box. Stream sets (None): box stays see-through.
        cur += (f",drawbox=x={x}:y={y}:w={w}:h={h}:color={LAYOUT['cam_fill']}@1:t=fill"
            f",drawbox=x={x}:y={y}:w={w}:h={h}:color={LAYOUT['cam_edge']}@1:t=4"
            f",drawtext=fontfile='{font}':text='{ff_escape_text(cam_label[0])}':fontsize=96:fontcolor={LAYOUT['text']}"
            f":x={x}+({w}-text_w)/2:y={y}+{h}/2-text_h+6"
            f",drawtext=fontfile='{font}':text='{ff_escape_text(cam_label[1])}':fontsize=40:fontcolor={LAYOUT['cam_sub']}"
            f":x={x}+({w}-text_w)/2:y={y}+{h}/2+24")

    for key, p in (("p1", p1), ("p2", p2)):
        L = LAYOUT[key]
        cur += (f",drawtext=fontfile='{font}':text='{ff_escape_text(p.get('tag') or p.get('name', ''))}':fontsize={LAYOUT['name_size']}"
                f":fontcolor={LAYOUT['text']}:x={L['name_right']}-text_w:y={L['name_cy']}-ascent/2-2")
    r = LAYOUT["round"]
    cur += (f",drawtext=fontfile='{font}':text='{ff_escape_text(round_text)}':fontsize={LAYOUT['round_size']}"
            f":fontcolor={LAYOUT['text']}:x={r['cx']}-text_w/2:y={r['cy']}-ascent/2-2")
    chains.append(cur + "[t0]")
    last = "t0"

    for n, (key, p) in enumerate((("p1", p1), ("p2", p2))):
        px, py, ps = LAYOUT[key]["pfp"]
        src = DEFAULT_PFP
        if p.get("imageUrl"):
            try:
                src = fetch(p["imageUrl"], os.path.join(tmp, f"{key}_src"))
            except OSError:
                src = DEFAULT_PFP
        pfp = circle_pfp(src, ps, os.path.join(tmp, f"{key}_pfp.png"))
        i = add_input(pfp)
        chains.append(f"[{last}][{i}:v]overlay={px}:{py}[t{n}a]")
        last = f"t{n}a"
        if p.get("character"):
            icon = os.path.join(STOCKS, f"{p.get('color') or 'neutral'} {p['character']}.png")
            if os.path.isfile(icon):
                sx, sy, ss = LAYOUT[key]["stock"]
                j = add_input(icon)
                chains.append(f"[{j}:v]scale={ss}:{ss}:flags=neighbor[s{n}];[{last}][s{n}]overlay={sx}:{sy}[t{n}b]")
                last = f"t{n}b"

    args = [FFMPEG, "-v", "error", "-y"] + base + inputs + [
        "-filter_complex", ";".join(chains), "-map", f"[{last}]", "-frames:v", "1", out_png]
    subprocess.run(args, check=True)
    return out_png


def composite_game(game_mp4, panel_png, out_mp4, encoder="h264_amf"):
    """Put a rendered game (642x528) into the game area and the panel on top."""
    fc = (f"color=c=black:s={W}x{H}:r=60[bg];"
          f"[0:v]scale={GAME_W}:{H}:flags=lanczos,setsar=1[g];"
          f"[bg][g]overlay={GAME_X}:0:shortest=1[bgg];"
          f"[bgg][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")  # panel is a looped still: end with the game
    enc = ["-c:v", encoder, "-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20"] \
        if encoder == "h264_amf" else ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", game_mp4, "-loop", "1", "-i", panel_png,
                    "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", *enc,
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-r", "60", out_mp4], check=True)
    return out_mp4


if __name__ == "__main__":
    import sys
    cfg = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    build_panel(cfg.get("out", "panel_test.png"),
                cfg.get("p1", {"name": "FRjhracing"}), cfg.get("p2", {"name": "Bichon Frise"}),
                cfg.get("round", "Round 2"))
