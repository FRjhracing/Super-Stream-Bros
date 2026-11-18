#!/usr/bin/env python3
"""
ultimate_overlay.py - the Protocol Ultimate VOD overlay, filled in per set (names, scores, round,
best of, W/L, pictures) on top of frame.png. For the Ultimate VOD cutter (render PC).

Stdlib + ffmpeg only. Self-contained: everything it needs is in this folder (layout.json, frame.png,
fonts\\, default_pfp.png). ffmpeg: ..\\tools\\ffmpeg\\bin\\ffmpeg.exe, else PROTOCOL_FFMPEG, else PATH.

  from ultimate_overlay import build_overlay, overlay_video
  build_overlay("set_C.png", {
      "p1": {"prefix": "OAC", "tag": "ApplSaucFactory", "score": 2, "mark": "W", "imageUrl": "https://..."},
      "p2": {"tag": "Swizzy", "score": 1, "mark": "L"},
      "round": "Grand Final", "bestOf": 5})
  overlay_video("Recording 1.mp4", [(start_s, end_s, "set_C.png"), ...], "out.mp4", trim=(start_s, end_s))

State fields (all optional):
  pN.prefix / pN.tag  sponsor prefix + tag (shown "OAC | ApplSaucFactory"); or pN.name = full text as is
  pN.score            number or text; None/"" leaves the score box empty
  pN.mark             "W" / "L" under the score box (grand finals), or any short text
  pN.imageUrl/.image  start.gg picture URL or a local file; else default_pfp.png
  pN.sub              override the text under that player's name bar
  round               shown under P1's name bar (unless p1.sub is given)
  bestOf              shown under P2's name bar as "Best of N" (unless p2.sub is given)
Long names follow the Stream Dock's rule (fitName): keep "prefix | tag" down to 70% of the normal size,
else the tag alone down to 50%, else cut with "...". The fitted text is what gets drawn.

CLI:  python ultimate_overlay.py demo          writes demo_*.png next to this script
      python ultimate_overlay.py '<state json>' out.png
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_FILE = os.path.join(HERE, "layout.json")
FRAME = os.path.join(HERE, "frame.png")
def _pick_font():
    """The stream font in fonts\\ (Typo Round, else any .otf/.ttf you put there), else a standard Windows font."""
    fdir = os.path.join(HERE, "fonts")
    first = os.path.join(fdir, "Typo_Round_Regular_Demo.otf")
    if os.path.isfile(first):
        return first
    own = sorted(f for f in (os.listdir(fdir) if os.path.isdir(fdir) else []) if f.lower().endswith((".otf", ".ttf")))
    if own:
        return os.path.join(fdir, own[0])
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(p):
            return p
    return first


FONT = _pick_font()
DEFAULT_PFP = os.path.join(HERE, "default_pfp.png")


def find_ffmpeg(name="ffmpeg"):
    # project root = 4 levels up (tools\\render\\overlays\\ultimate); also works copied next to tools\\
    up = [os.path.join(HERE, *([".."] * k), "tools", "ffmpeg", "bin", name + ".exe") for k in (4, 1)]
    for p in (*up,
              os.environ.get("PROTOCOL_" + name.upper()), shutil.which(name)):
        if p and os.path.isfile(p):
            return p
    raise FileNotFoundError(f"{name} not found (tools\\ffmpeg\\bin, PROTOCOL_{name.upper()} or PATH)")


def load_layout():
    with open(LAYOUT_FILE, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------- font widths (no Pillow)

class FontWidths:
    """Advance widths from an OpenType/TrueType file (cmap + hmtx), for fitting names. No kerning,
    which is close enough for picking a size (ffmpeg draws the real text)."""

    def __init__(self, path):
        data = open(path, "rb").read()
        n = struct.unpack(">H", data[4:6])[0]
        tables = {data[12 + 16 * i:16 + 16 * i].decode("latin-1"):
                  struct.unpack(">II", data[20 + 16 * i:28 + 16 * i]) for i in range(n)}
        off = tables["head"][0]
        self.upem = struct.unpack(">H", data[off + 18:off + 20])[0]
        off = tables["hhea"][0]
        nh = struct.unpack(">H", data[off + 34:off + 36])[0]
        off = tables["hmtx"][0]
        self.adv = [struct.unpack(">H", data[off + 4 * i:off + 4 * i + 2])[0] for i in range(nh)]
        self.cmap = self._cmap(data, tables["cmap"][0])

    @staticmethod
    def _cmap(data, base):
        n = struct.unpack(">H", data[base + 2:base + 4])[0]
        subs = [struct.unpack(">HHI", data[base + 4 + 8 * i:base + 12 + 8 * i]) for i in range(n)]
        out = {}
        for plat, enc, off in sorted(subs, key=lambda s: (s[0], s[1]) != (3, 10)):
            p = base + off
            fmt = struct.unpack(">H", data[p:p + 2])[0]
            if fmt == 12:
                for i in range(struct.unpack(">I", data[p + 12:p + 16])[0]):
                    a, b, g = struct.unpack(">III", data[p + 16 + 12 * i:p + 28 + 12 * i])
                    for c in range(a, b + 1):
                        out.setdefault(c, g + c - a)
            elif fmt == 4:
                seg = struct.unpack(">H", data[p + 6:p + 8])[0] // 2
                ends = struct.unpack(f">{seg}H", data[p + 14:p + 14 + 2 * seg])
                q = p + 16 + 2 * seg
                starts = struct.unpack(f">{seg}H", data[q:q + 2 * seg])
                deltas = struct.unpack(f">{seg}h", data[q + 2 * seg:q + 4 * seg])
                ro_at = q + 4 * seg
                ros = struct.unpack(f">{seg}H", data[ro_at:ro_at + 2 * seg])
                for i in range(seg):
                    for c in range(starts[i], ends[i] + 1):
                        if c == 0xFFFF:
                            continue
                        if ros[i] == 0:
                            g = (c + deltas[i]) & 0xFFFF
                        else:
                            a = ro_at + 2 * i + ros[i] + 2 * (c - starts[i])
                            g = struct.unpack(">H", data[a:a + 2])[0]
                            g = (g + deltas[i]) & 0xFFFF if g else 0
                        out.setdefault(c, g)
        return out

    def width(self, text, size):
        total = 0
        for ch in text:
            g = self.cmap.get(ord(ch), 0)
            total += self.adv[min(g, len(self.adv) - 1)]
        return total * size / self.upem


_FW = None


def widths():
    global _FW
    if _FW is None:
        _FW = FontWidths(FONT)
    return _FW


def full_name(p):
    if p.get("name"):
        return str(p["name"])
    return " | ".join(x for x in (p.get("prefix"), p.get("tag")) if x) or "?"


def fit_name(p, box_w, normal, keep_prefix=0.7, min_scale=0.5):
    """(text, font size) like the Stream Dock's fitName."""
    fw = widths()
    scale = lambda t: min(normal, box_w / max(1.0, fw.width(t, 1)))
    full = full_name(p)
    if scale(full) >= keep_prefix * normal:
        return full, scale(full)
    tag = str(p["tag"]) if p.get("prefix") and p.get("tag") else full
    if scale(tag) >= min_scale * normal:
        return tag, scale(tag)
    cut = tag
    while len(cut) > 1 and scale(cut + "…") < min_scale * normal:
        cut = cut[:-1]
    cut = cut.rstrip() + "…"
    return cut, scale(cut)


# ------------------------------------------------------------- ffmpeg helpers

def ff_path(p):
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def ff_text(t):
    return (str(t).replace("\\", "\\\\").replace("'", "’").replace(":", "\\:")
            .replace("%", "\\%").replace(",", "\\,"))


def hexcol(rgb):
    return "0x%02x%02x%02x" % tuple(rgb[:3])


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "ProtocolVOD/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def circle_pfp(src, size, dest):
    vf = (f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size},format=rgba,"
          f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-{size/2},Y-{size/2}),{size/2}),alpha(X,Y),0)'")
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", src, "-vf", vf, "-frames:v", "1", dest], check=True)
    return dest


def text_in_box(box, text, size, color, align="center", font=None):
    """drawtext centred vertically in box; align = left/center/right."""
    x1, y1, x2, y2 = box
    x = {"left": f"{x1}", "right": f"{x2}-text_w", "center": f"{x1}+({x2 - x1}-text_w)/2"}[align]
    return (f"drawtext=fontfile='{ff_path(font or FONT)}':text='{ff_text(text)}':fontsize={size:.1f}"
            f":fontcolor={hexcol(color)}:x={x}:y={(y1 + y2) / 2:.1f}-ascent/2-1")


# ------------------------------------------------------------- the overlay

def build_overlay(out_png, state, layout=None):
    """Write a 1920x1080 RGBA PNG: frame + this set's text and pictures; the rest stays transparent."""
    L = layout or load_layout()
    C, T = L["colors"], L["text"]
    if not os.path.isfile(FRAME):
        raise FileNotFoundError("frame.png missing: run make_frame.py (needs Pillow) once")
    tmp = tempfile.mkdtemp(prefix="ultovl_")
    try:
        inputs = ["-i", FRAME]
        draws = []
        pfps = []
        for key in ("p1", "p2"):
            P, p = L[key], state.get(key) or {}
            nb = P["name"]
            text, size = fit_name(p, nb[2] - nb[0] - 28, T["name_size"], T["keep_prefix"], T["min_scale"])
            draws.append(text_in_box(nb, text, size, C["name_text"]))
            if p.get("score") not in (None, ""):
                draws.append(text_in_box(P["score"], p["score"], T["score_size"], C["score_text"]))
            sub = p.get("sub")
            if sub is None:
                sub = state.get("round") if key == "p1" else (f"Best of {state['bestOf']}" if state.get("bestOf") else "")
            if sub:
                draws.append(text_in_box(P["sub"], sub, T["sub_size"], C["sub_text"]))
            if p.get("mark"):
                draws.append(text_in_box(P["mark"], p["mark"], T["mark_size"], C["mark_text"]))
            src = p.get("image") if p.get("image") and os.path.isfile(p.get("image")) else DEFAULT_PFP
            if p.get("imageUrl"):
                try:
                    src = fetch(p["imageUrl"], os.path.join(tmp, f"{key}_src"))
                except OSError:
                    pass
            cx, cy, r = P["pfp"]
            d = 2 * (r - 3)
            inputs += ["-i", circle_pfp(src, d, os.path.join(tmp, f"{key}_pfp.png"))]
            pfps.append((len(inputs) // 2 - 1, cx - d // 2, cy - d // 2))
        chain = "[0:v]format=rgba" + "".join("," + d for d in draws) + "[t]"
        last = "t"
        for n, (i, x, y) in enumerate(pfps):
            chain += f";[{last}][{i}:v]overlay={x}:{y}[o{n}]"
            last = f"o{n}"
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", *inputs, "-filter_complex", chain,
                        "-map", f"[{last}]", "-frames:v", "1", out_png], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_png


def probe_size(video):
    out = subprocess.run([find_ffmpeg("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", video], capture_output=True, text=True, check=True)
    w, h = out.stdout.strip().split(",")[:2]
    return int(w), int(h)


def overlay_video(video, states, out_mp4, trim=None, encoder="h264_amf", gain_db=0):
    """Burn overlays onto a recording.
    states: [(start_s, end_s, png), ...] in the source video's time; each png shows only in its window.
    trim: (start_s, end_s) to cut that part out (window times stay in source time).
    gain_db: audio gain (with a limiter just under 0 dB), e.g. 10 like the Melee VODs."""
    w, h = probe_size(video)
    ff = find_ffmpeg()
    args = [ff, "-v", "error", "-y"]
    if trim:
        args += ["-ss", f"{trim[0]:.3f}", "-to", f"{trim[1]:.3f}"]
    args += ["-i", video]
    for _, _, png in states:
        args += ["-loop", "1", "-i", png]
    shift = trim[0] if trim else 0
    fc, last = [], "0:v"
    for n, (a, b, _) in enumerate(states):
        fc.append(f"[{n + 1}:v]scale={w}:{h},format=rgba[s{n}]")
        fc.append(f"[{last}][s{n}]overlay=0:0:shortest=1:enable='between(t,{a - shift:.3f},{b - shift:.3f})'[v{n}]")
        last = f"v{n}"
    fc.append(f"[{last}]format=yuv420p[v]")
    enc = (["-c:v", encoder, "-quality", "quality", "-rc", "vbr_peak", "-b:v", "12M", "-maxrate", "16M"]
           if encoder.endswith("_amf") else ["-c:v", "libx264", "-preset", "medium", "-crf", "18"])
    af = ["-af", f"volume={gain_db}dB,alimiter=limit=0.97"] if gain_db else []
    # -ss before -i starts the cut video at t=0, so the overlay windows above are shifted by trim[0].
    subprocess.run(args + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "0:a?", *enc, *af,
                           "-c:a", "aac", "-b:a", "192k", out_mp4], check=True)
    return out_mp4


DEMO = {
    "demo_grand_final.png": {"p1": {"prefix": "OAC", "tag": "ApplSaucFactory", "score": 2, "mark": "W"},
                             "p2": {"tag": "Swizzy", "score": 1, "mark": "L"},
                             "round": "Grand Final", "bestOf": 5},
    "demo_long_names.png": {"p1": {"prefix": "SOVA", "tag": "AnExtremelyLongTagForTesting", "score": 0},
                            "p2": {"prefix": "Team Ridiculous Sponsor", "tag": "Kalifg22", "score": 0},
                            "round": "Winners Quarter-Final", "bestOf": 3},
    "demo_no_score.png": {"p1": {"tag": "VoltaicPickle"}, "p2": {"tag": "Javi"}, "round": "Losers Round 1",
                          "bestOf": 3},
}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        for name, st in DEMO.items():
            print("wrote", build_overlay(os.path.join(HERE, name), st))
    elif len(sys.argv) > 2:
        print("wrote", build_overlay(sys.argv[2], json.loads(sys.argv[1])))
    else:
        print(__doc__)
