#!/usr/bin/env python3
"""
ultimate_cutter.py - cut the Ultimate bracket recordings into one video per set, using the
Ultimate Dock's recording log (no replays exist for Ultimate).

    python tools\\python\\ultimate_cutter.py plan   "I:/Protocol VOD/Ultimate/Protocol #58/vod_config.json"
    python tools\\python\\ultimate_cutter.py render "I:/Protocol VOD/Ultimate/Protocol #58/vod_config.json" [--only BT,BU]
    python tools\\python\\ultimate_cutter.py kit    "I:/Protocol VOD/Ultimate/Protocol #58/vod_config.json"

Inputs (see RENDER_PC_HANDOFF.md section 4):
- dock folder: log.jsonl (rec_start / on_stream / set_end / mark per recording "1"/"2"), characters.json
- recordings: {"1": file, "2": file}. Video time = log t - that recording's rec_start
  (fallback: the OBS file name time). Recording 1 = main OBS (hosts the dock), 2 = portable OBS.
- start.gg (Ultimate event): round, entrant names, final score. start.gg wins over the dock's result text.

The dock's times are when the TO clicked. When the TO is playing or catching up on reports they drift
(#58: Winners Final, Losers Semi/Final, Grand Final + reset). Fix those in vod_config "sets":
    "BU": {"rec": "2", "start": "3:21:20", "end": "3:33:50", "chars": {"<entrant name>": ["Steve"]},
           "note": "why"}
Override times are exact video times on that recording (no padding added). A set listed only in the
config (never logged, e.g. #58 BT) is added from start.gg. "skip": true drops a logged set.

Output: <SSD>/Protocol VOD/Ultimate/<tournament>/ plan.json, review.md, sets/*.mp4, one Full VOD per
recording (its sets back to back, chapters), upload_kit/ (for youtube_upload.py, account from config).
Stdlib + tools/ffmpeg; start.gg token from STARTGG_TOKEN.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import vod_cutter as vc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "render", "overlays", "ultimate"))
import ultimate_overlay as uo
from vod_cutter import FFMPEG, FFPROBE, ENC, LIMIT, hms, safe_name, probe_duration, recording_start, gql

HERE = ROOT = vc.ROOT
ULTIMATE_ID = 1386
PAD_BEFORE_S = 15   # dock "on" click usually comes after the players sit down
PAD_AFTER_S = 15    # report click comes after the last results screen
DEFAULT_TAGS = ["Smash Ultimate", "Super Smash Bros Ultimate", "Smash Bros", "Ultimate", "Weekly",
                "Tournament", "SoVA", "Protocol"]
TITLE_SET = "{tournament}: {round} - {a} ({a_char}) vs {b} ({b_char})"
TITLE_SET_SHORT = "{tournament}: {round} - {a} vs {b}"
TITLE_FULL = "{tournament}: {rec} Full VOD"
CHAR_SHORT = {"Random Character": "Random", "Mr. Game & Watch": "Game & Watch"}


def parse_vt(v):
    """'3:21:20' / '21:20' / seconds -> seconds."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(p) for p in str(v).split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_out"] = os.path.dirname(os.path.abspath(path))
    cfg["_work"] = os.path.join(cfg["_out"], "work")
    # Big files (sets, Full VODs) can go to another drive (external SSD); config, plan, review and the
    # upload kit stay next to the config so a dropped drive can't take them.
    import vod_cutter
    base = cfg["_out"]
    if "media_dir" not in cfg and vod_cutter.on_ssd(base):  # whole tournament folder on the SSD
        cfg["media_dir"] = None
    if "media_dir" not in cfg:  # default: the external SSD (user, 2026-11-10); "media_dir": null = next to the config
        import vod_cutter
        drive = vod_cutter.find_volume("Project Storage")
        if not drive:
            raise SystemExit('External SSD "Project Storage" is not connected (or set "media_dir" in the config).')
        cfg["media_dir"] = os.path.join(drive, "Protocol VOD", "Ultimate", cfg.get("title", cfg["tournament"]).replace("PROTOCOL", "Protocol"))
    cfg["_media"] = vod_cutter.resolve_path(cfg["media_dir"], base) if cfg.get("media_dir") else base
    if cfg.get("media_dir"):
        drive = os.path.splitdrive(os.path.abspath(cfg["_media"]))[0]
        if drive and not os.path.isdir(drive + os.sep):
            raise SystemExit(f"media_dir drive {drive} is not connected (external SSD?): {cfg['_media']}")
    cfg["dock"] = vod_cutter.resolve_path(cfg["dock"], base)
    cfg["recordings"] = {r: vod_cutter.resolve_path(p, base) for r, p in cfg["recordings"].items()}
    if cfg.get("player_characters"):
        cfg["player_characters"] = vod_cutter.resolve_path(cfg["player_characters"], base)
    cfg.setdefault("sets", {})
    return cfg


def load_startgg(cfg):
    cache = os.path.join(cfg["_work"], "startgg.json")
    if os.path.isfile(cache) and not cfg.get("refresh_startgg"):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    t = gql("""query($s:String!){tournament(slug:$s){name events{id name slug videogame{id} numEntrants}}}""",
            {"s": cfg["tournament"]})["tournament"]
    ev = sorted([e for e in t["events"] if e["videogame"]["id"] == ULTIMATE_ID],
                key=lambda e: e["numEntrants"] or 0, reverse=True)[0]
    nodes, page = [], 1
    while True:
        d = gql("""query($e:ID!,$p:Int!){event(id:$e){sets(page:$p,perPage:50,sortType:STANDARD){
          pageInfo{totalPages} nodes{id identifier fullRoundText state startedAt completedAt winnerId displayScore
          totalGames slots{entrant{id name participants{gamerTag prefix player{id} user{images{type url}}}}}}}}}""", {"e": ev["id"], "p": page})
        s = d["event"]["sets"]
        nodes += s["nodes"]
        if page >= s["pageInfo"]["totalPages"]:
            break
        page += 1
    data = {"tournament": t["name"], "event": ev["name"], "event_slug": ev["slug"],
            "numEntrants": ev["numEntrants"], "sets": nodes}
    os.makedirs(cfg["_work"], exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return data


def entrant_look(s):
    """{entrant name: {prefix, tag, imageUrl}} for the overlay."""
    out = {}
    for sl in s["slots"]:
        ent = sl.get("entrant") or {}
        p = (ent.get("participants") or [{}])[0]
        img = next((i["url"] for i in ((p.get("user") or {}).get("images") or []) if i.get("type") == "profile"), "")
        out[ent.get("name")] = {"prefix": p.get("prefix") or "", "tag": p.get("gamerTag") or ent.get("name"),
                                "imageUrl": img}
    return out


def sg_result(s):
    """(name_a, score_a, name_b, score_b, winner_name) from start.gg's displayScore 'A 3 - B 0'."""
    names = [sl["entrant"]["name"] for sl in s["slots"] if sl.get("entrant")]
    winner = next((sl["entrant"]["name"] for sl in s["slots"]
                   if sl.get("entrant") and str(sl["entrant"]["id"]) == str(s.get("winnerId"))), None)
    m = re.fullmatch(r"(.*) (\d+|DQ) - (.*) (\d+|DQ)", s.get("displayScore") or "")
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4), winner
    return (names + ["?", "?"])[0], "", (names + ["?", "?"])[1], "", winner


# ---------------------------------------------------------------- plan

def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def dock_segments(cfg):
    """Pair on_stream with the next set_end on the same recording. Video time from that recording's
    latest rec_start (else the OBS file name)."""
    ev = sorted(read_jsonl(os.path.join(cfg["dock"], "log.jsonl")), key=lambda e: e["t"])
    rec0 = {r: recording_start(p).timestamp() for r, p in cfg["recordings"].items()}
    rec_start, open_, segs, marks = dict(rec0), {}, [], []
    for e in ev:
        r = str(e.get("stream"))
        if e["event"] == "rec_start":
            rec_start[r] = e["t"]
        elif e["event"] == "on_stream":
            open_[r] = e
        elif e["event"] == "set_end" and r in open_:
            on = open_.pop(r)
            base = rec_start.get(r, rec0.get(r))
            segs.append({"rec": r, "setId": on.get("setId"), "identifier": on.get("identifier"),
                         "round": on.get("round"), "p1": on.get("p1"), "p2": on.get("p2"),
                         "t0": on["t"], "t1": e["t"], "v0": on["t"] - base, "v1": e["t"] - base,
                         "reason": e.get("reason"), "result": e.get("result")})
        elif e["event"] == "mark":
            marks.append(e)
    for r, on in open_.items():
        segs.append({"rec": r, "identifier": on.get("identifier"), "setId": on.get("setId"), "round": on.get("round"),
                     "p1": on.get("p1"), "p2": on.get("p2"), "t0": on["t"], "t1": None,
                     "v0": on["t"] - rec_start.get(r, rec0[r]), "v1": None, "reason": "no end logged"})
    return segs, marks, rec_start


def load_chars(cfg):
    p = os.path.join(cfg["dock"], "characters.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def chars_for(chars, set_id, ident, name):
    rec = chars.get(str(set_id)) or next((c for c in chars.values() if c.get("identifier") == ident), None)
    if not rec:
        return []
    if rec.get("p1") == name:
        return rec.get("chars1") or []
    if rec.get("p2") == name:
        return rec.get("chars2") or []
    return []


def make_plan(cfg):
    sg = load_startgg(cfg)
    by_ident = {s["identifier"]: s for s in sg["sets"]}
    segs, marks, rec_start = dock_segments(cfg)
    chars = load_chars(cfg)
    durations = {r: probe_duration(p) for r, p in cfg["recordings"].items()}
    # Several segments per set (re-clicks, zero-length re-reports): keep the longest per set.
    best, notes = {}, []
    for s in segs:
        if s["v1"] is None:
            notes.append(f"{s['identifier']}: on recording {s['rec']} with no end in the log")
            continue
        k = s["identifier"]
        if k not in best or (s["v1"] - s["v0"]) > (best[k]["v1"] - best[k]["v0"]):
            if k in best and best[k]["v1"] - best[k]["v0"] > 1:
                notes.append(f"{k}: logged more than once; kept the longest window")
            best[k] = s
        elif s["v1"] - s["v0"] > 1:
            notes.append(f"{k}: logged more than once; kept the longest window")
    plan_sets = []
    idents = list(best) + [k for k in cfg["sets"] if k not in best and not k.startswith("_")]
    for ident in idents:
        ov = cfg["sets"].get(ident, {})
        if ov.get("skip"):
            notes.append(f"{ident}: skipped by config ({ov.get('note', '')})")
            continue
        dock = best.get(ident)
        s = by_ident.get(ident)
        if not s:
            notes.append(f"{ident}: not found on start.gg")
            continue
        rec = str(ov.get("rec") or dock["rec"])
        if "start" in ov:
            v0, v1, how = parse_vt(ov["start"]), parse_vt(ov["end"]), "fixed by hand"
        else:
            v0 = dock["v0"] - cfg.get("pad_before_s", PAD_BEFORE_S)
            v1 = dock["v1"] + cfg.get("pad_after_s", PAD_AFTER_S)
            how = "dock"
        v0, v1 = max(0.0, v0), min(durations[rec], v1)
        a, sa, b, sb, winner = sg_result(s)
        p_order = [dock["p1"], dock["p2"]] if dock else [a, b]
        if set(p_order) != {a, b}:
            p_order = [a, b]
        score = {a: sa, b: sb}
        players = []
        for name in p_order:
            c = (ov.get("chars") or {}).get(name) or chars_for(chars, s["id"], ident, name)
            players.append(dict({"name": name, "chars": c, "score": score.get(name, "")},
                                **entrant_look(s).get(name, {})))
        row_notes = []
        if dock and dock.get("result") and winner:
            if not dock["result"].startswith(winner + " "):
                row_notes.append(f"dock result '{dock['result']}' disagrees with start.gg ({winner} won); start.gg used")
        if ov.get("note"):
            row_notes.append(ov["note"])
        if not dock:
            row_notes.append("not in the dock's recording log; times found by watching the recording")
        plan_sets.append({
            "identifier": ident, "setId": s["id"], "round": s["fullRoundText"], "rec": rec,
            "start": round(v0, 2), "end": round(v1, 2), "how": how,
            "clock": datetime.fromtimestamp(rec_start[rec] + v0).strftime("%H:%M:%S"),
            "dock": {"v0": dock["v0"], "v1": dock["v1"]} if dock else None,
            "a": players[0], "b": players[1], "winner": winner,
            # start.gg's totalGames says 5 for every #58 set; the bracket is Bo3 until top 8, so go by the score.
            "bestOf": 5 if "3" in (sa, sb) else 3,
            "score": f"{players[0]['score']}-{players[1]['score']}", "notes": row_notes})
    plan_sets.sort(key=lambda p: rec_start[p["rec"]] + p["start"])
    for n, p in enumerate(plan_sets, 1):
        p["n"] = n
    # Overlaps on the same recording. Padding-only overlaps (both from the dock) meet in the middle;
    # anything else is flagged.
    for r in cfg["recordings"]:
        rs = sorted((p for p in plan_sets if p["rec"] == r), key=lambda p: p["start"])
        for x, y in zip(rs, rs[1:]):
            if y["start"] >= x["end"] - 1:
                continue
            if x["how"] == "dock" and y["how"] == "dock" and y["dock"]["v0"] >= x["dock"]["v1"] - 30:
                mid = round((x["dock"]["v1"] + y["dock"]["v0"]) / 2, 2)
                x["end"], y["start"] = mid, mid
            else:
                x["notes"].append(f"overlaps the next set {y['identifier']} by {hms(x['end'] - y['start'])}")
    for p in plan_sets:
        p["check"] = "; ".join(p["notes"]) if p["how"] != "dock" or any(
            "overlaps" in n or "disagrees" in n for n in p["notes"]) else ""
    unrec = [s for s in sg["sets"] if s["identifier"] not in {p["identifier"] for p in plan_sets}
             and s.get("state") == 3]
    plan = {"tournament": cfg["title"], "event": sg["event"], "event_slug": sg["event_slug"],
            "entrants": sg.get("numEntrants"), "recordings": {r: os.path.basename(p) for r, p in cfg["recordings"].items()},
            "durations": durations, "sets": plan_sets, "notes": notes,
            "marks": [{"rec": m.get("stream"), "t": m["t"], "note": m.get("note")} for m in marks],
            "not_recorded": len(unrec)}
    with open(os.path.join(cfg["_out"], "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    write_review(cfg, plan)
    return plan


def char_text(p, unknown="?"):
    return ", ".join(CHAR_SHORT.get(c, c) for c in p["chars"]) or unknown


def player_title(p):
    c = char_text(p, "")
    return f"{p['name']} ({c})" if c else p["name"]


def write_review(cfg, plan):
    L = [f"# {plan['tournament']} Ultimate: cut plan", "",
         f"{plan['event']}, {plan['entrants']} entrants. {len(plan['sets'])} sets on the recordings, "
         f"{plan['not_recorded']} played off recording.", ""]
    for r, name in plan["recordings"].items():
        L.append(f"- Recording {r}: `{name}` ({hms(plan['durations'][r])})")
    L += ["", "| # | Set | Round | Players (start.gg score) | Rec | Cut | Length | Source | Notes |",
          "|---|---|---|---|---|---|---|---|---|"]
    for p in plan["sets"]:
        who = (f"{p['a']['name']} ({char_text(p['a'])}) **{p['score']}** {p['b']['name']} ({char_text(p['b'])})"
               .replace("|", "\\|"))
        src = p["how"]
        if p["how"] != "dock" and p["dock"]:
            src += f" (dock: {hms(p['dock']['v0'])}-{hms(p['dock']['v1'])})"
        L.append(f"| {p['n']} | {p['identifier']} | {p['round']} | {who} | {p['rec']} | "
                 f"{hms(p['start'])}-{hms(p['end'])} | {hms(p['end'] - p['start'])} | {src} | "
                 f"{'; '.join(p['notes']).replace('|', '/')} |")
    if plan["notes"]:
        L += ["", "## Notes", ""] + [f"- {n}" for n in plan["notes"]]
    if plan["marks"]:
        L += ["", "## TO's marks", ""] + [
            f"- Recording {m['rec']} {datetime.fromtimestamp(m['t']).strftime('%H:%M:%S')}: {m['note']}"
            for m in plan["marks"]]
    with open(os.path.join(cfg["_out"], "review.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- render

def set_file(cfg, p):
    return os.path.join(cfg["_media"], "sets", safe_name(
        f"{p['n']:02d} - {p['round']} - {p['a']['name']} vs {p['b']['name']}") + ".mp4")


TARGET_MEAN_DB = -20.0  # about where the Melee VODs sit after their +10 dB


def overlay_state(p):
    """UltimateOverlay state for a set. Score boxes stay empty: the dock only knows the final score,
    and showing it from the first frame would spoil the set. Grand finals get W/L (bracket side)."""
    st = {"round": p["round"], "bestOf": p.get("bestOf")}
    for key, pl in (("p1", p["a"]), ("p2", p["b"])):
        st[key] = {"prefix": pl.get("prefix"), "tag": pl.get("tag") or pl["name"], "imageUrl": pl.get("imageUrl")}
    if p["round"] == "Grand Final":
        # p1 of a start.gg grand final is the winners-side player
        st["p1"]["mark"], st["p2"]["mark"] = "W", "L"
    elif p["round"] == "Grand Final Reset":
        st["p1"]["mark"] = st["p2"]["mark"] = "L"
    return st


def set_gain(cfg, p):
    if "gain_db" in cfg:
        return cfg["gain_db"]
    _, mean = vc.audio_peak(cfg["recordings"][p["rec"]], p["start"], p["end"] - p["start"])
    return max(0.0, min(30.0, TARGET_MEAN_DB - mean)) if mean is not None else 10.0


def render_set(cfg, p):
    out = set_file(cfg, p)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.makedirs(cfg["_work"], exist_ok=True)
    tmp = out + ".part.mp4"
    gain = set_gain(cfg, p)
    if cfg.get("overlay", True):
        states = []
        for t0, t1, sa, sb in score_windows(p):
            st = overlay_state(p)
            st["p1"]["score"], st["p2"]["score"] = sa, sb
            png = os.path.join(cfg["_work"], f"overlay_{p['identifier']}_{sa}-{sb}.png")
            states.append((t0, t1 if t1 < p["end"] else p["end"] + 1, uo.build_overlay(png, st)))
        uo.overlay_video(cfg["recordings"][p["rec"]], states, tmp, trim=(p["start"], p["end"]), gain_db=round(gain, 1))
    else:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{p['start']:.3f}", "-t", f"{p['end'] - p['start']:.3f}",
                        "-i", cfg["recordings"][p["rec"]], "-map", "0:v:0", "-map", "0:a:0",
                        "-af", f"volume={gain:.1f}dB,{LIMIT}", *ENC, "-movflags", "+faststart", tmp], check=True)
    os.replace(tmp, out)
    print(f"    audio +{gain:.1f} dB", flush=True)
    return out


# ---------------------------------------------------------------- game-by-game scan of the video

SCAN_W, SCAN_H, SCAN_FPS = 192, 108, 4


def _avg(f, x1, y1, x2, y2):
    r = g = b = c = 0
    for y in range(y1, y2):
        row = y * SCAN_W
        for x in range(x1, x2):
            i = (row + x) * 3
            r += f[i]; g += f[i + 1]; b += f[i + 2]; c += 1
    return r / c, g / c, b / c


def frame_vs(f):
    """Pre-game VS screen: red P1 badge top-left, blue P2 badge top-centre, dark name band.
    (Character art covers the screen edges, never the top band.) Tuned on #58, 2026-11-03."""
    p1, p2 = _avg(f, 1, 2, 7, 7), _avg(f, 98, 2, 104, 7)
    band, band2 = _avg(f, 20, 1, 90, 4), _avg(f, 115, 1, 180, 4)
    return (p1[0] > 55 and p1[0] - max(p1[1], p1[2]) > 35 and p2[2] > 70 and p2[2] - p2[0] > 15
            and sum(band) / 3 < 70 and sum(band2) / 3 < 70)


def _digit(f, x1, y1, x2, y2):
    gold = silver = n = 0
    for y in range(y1, y2):
        row = y * SCAN_W
        for x in range(x1, x2):
            i = (row + x) * 3
            r, g, b = f[i], f[i + 1], f[i + 2]
            n += 1
            if r > 170 and 110 < g < 215 and b < 120 and r - b > 90:
                gold += 1
            elif r > 185 and g > 185 and b > 185:
                silver += 1
    return gold / n, silver / n


def frame_winner(f):
    """Results cards (2 players): P1's card on the left, P2's on the right, each with its placing in the
    top-right corner: a gold '1' for the winner, a silver '2' for the loser. Returns 1, 2 or None.
    Tuned on #58 (2026-11-03): winner corner ~15% gold / 0 silver, loser ~14-20% silver / 0 gold."""
    g1, s1 = _digit(f, 66, 1, 86, 19)
    g2, s2 = _digit(f, 145, 1, 165, 19)
    if g1 > 0.08 and s1 < 0.04 and s2 > 0.09 and g2 < 0.03 and _strip(f, 30, 70, "R") > 0.5:
        return 1
    if g2 > 0.08 and s2 < 0.04 and s1 > 0.09 and g1 < 0.03 and _strip(f, 110, 150, "B") > 0.5:
        return 2
    return None


def _strip(f, x1, x2, colour):
    """Share of the card's name strip (y 19-25) in the port colour: P1 red, P2 blue."""
    hit = n = 0
    for y in range(19, 26):
        row = y * SCAN_W
        for x in range(x1, x2):
            i = (row + x) * 3
            r, g, b = f[i], f[i + 1], f[i + 2]
            n += 1
            hit += (r - max(g, b) > 70) if colour == "R" else (b - max(r, g) > 70)
    return hit / n


def game_area(cfg, rec):
    """[w, h, x, y] of the game picture inside the recording, or None when it fills the frame. #60's OBS capture
    was inset by a black border (1864x1052 at 28,14), which moved every screen the scan looks at. Config
    "crop": {"<rec>": [w, h, x, y]} wins; else ffmpeg cropdetect at 5 points, keeping the largest box (a dark
    stage can only make one sample smaller). Cached in work/crop_<rec>.json."""
    if (cfg.get("crop") or {}).get(rec):
        return cfg["crop"][rec]
    cache = os.path.join(cfg["_work"], f"crop_{rec}.json")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)["crop"]
    path = cfg["recordings"][rec]
    dur = probe_duration(path)
    boxes = []
    for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
        err = subprocess.run([FFMPEG, "-hide_banner", "-ss", f"{dur * frac:.1f}", "-t", "20", "-i", path, "-an",
                              "-vf", "cropdetect=limit=20:round=2:reset=0", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
        if m:
            boxes.append([int(v) for v in m[-1]])
    box = None
    if boxes:
        x0 = min(b[2] for b in boxes); y0 = min(b[3] for b in boxes)
        x1 = max(b[2] + b[0] for b in boxes); y1 = max(b[3] + b[1] for b in boxes)
        box = [x1 - x0, y1 - y0, x0, y0]
        full = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                               "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip().split(",")
        if [box[0], box[1]] == [int(full[0]), int(full[1])] or box[0] < int(full[0]) * 0.8:
            box = None  # fills the frame, or implausible (mostly dark samples): don't crop
    os.makedirs(cfg["_work"], exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump({"crop": box, "samples": boxes}, fh)
    if box:
        print(f"  recording {rec}: game picture {box[0]}x{box[1]} at {box[2]},{box[3]} (border cropped for the scan)")
    return box


def scan_set(cfg, p, refresh=False):
    """[(t, 'vs')] and [(t, 'win', port)] for the set's window, cached in work/scan_<id>.json."""
    cache = os.path.join(cfg["_work"], f"scan_{p['identifier']}.json")
    crop = game_area(cfg, p["rec"])
    key = [round(p["scan"][0], 2), round(p["scan"][1], 2)] + ([crop] if crop else [])
    if os.path.isfile(cache) and not refresh:
        with open(cache, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("window") == key:
            return d
    a, b = p["scan"]
    vf = (f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}," if crop else "") + f"fps={SCAN_FPS},scale={SCAN_W}:{SCAN_H}"
    proc = subprocess.Popen([FFMPEG, "-v", "error", "-hwaccel", "d3d11va", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                             "-i", cfg["recordings"][p["rec"]], "-an", "-vf", vf,
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    fs = SCAN_W * SCAN_H * 3
    vs, wins, k = [], [], 0
    while True:
        f = proc.stdout.read(fs)
        if len(f) < fs:
            break
        t = round(a + k / SCAN_FPS, 2)
        if frame_vs(f):
            vs.append(t)
        else:
            w = frame_winner(f)
            if w:
                wins.append([t, w])
        k += 1
    proc.wait()
    d = {"window": key, "vs": vs, "wins": wins}
    os.makedirs(cfg["_work"], exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return d


def clusters(times, gap=20.0):
    out = []
    for t in times:
        if out and t - out[-1][-1] <= gap:
            out[-1].append(t)
        else:
            out.append([t])
    return out


RESTART_S = 90  # two VS screens closer than this: the first game was quit and restarted


def games_from_scan(p, d):
    """Real games from the scan. Returns (games, problems); games: [{"vs", "port" (1/2/None), "res", "last"}].
    A game = a VS screen; a VS followed by another within RESTART_S was a restart. The winner's port
    comes from a results screen when one was caught (players often skip it)."""
    vs = [c[0] for c in clusters(d["vs"])]
    vs = [t for i, t in enumerate(vs) if not (i + 1 < len(vs) and vs[i + 1] - t < RESTART_S)]
    games, problems = [], []
    for i, t0 in enumerate(vs):
        t1 = vs[i + 1] if i + 1 < len(vs) else float("inf")
        ws = [w for w in d["wins"] if t0 < w[0] < t1]
        port = res = last = None
        if ws:
            ports = [w[1] for w in ws]
            port = max((1, 2), key=ports.count)
            if ports.count(port) < len(ports) * 0.8:
                problems.append(f"game at {hms(t0)}: mixed winner signal {ports.count(1)}xP1/{ports.count(2)}xP2")
                port = None
            else:
                res, last = ws[0][0], ws[-1][0]
        games.append({"vs": t0, "port": port, "res": res, "last": last})
    return games, problems


def side_sequences(sa, sb):
    """Every order of game winners ('a'/'b') ending sa-sb, with the set winner taking the last game
    (so nobody reached the target earlier)."""
    from itertools import permutations
    if sa == sb:
        return []
    w = "a" if sa > sb else "b"
    return sorted({seq for seq in permutations(["a"] * sa + ["b"] * sb) if seq[-1] == w})


LEAD_IN_S = 20    # keep this much before game 1's VS screen (stage pick / ready to fight)
TAIL_S = 8        # and after the last results screen
SCAN_TAIL_S = 90  # look this far past the cut for the last game's results (never into the next set)


def analyze_sets(cfg, plan, refresh=False):
    """Per set: games from the video (VS screen -> results screen winner), handwarmers dropped, ports
    mapped to players with start.gg's score, then a tight cut and a game-by-game score timeline.
    Sets that don't add up keep the dock cut and empty score boxes (flagged in the review)."""
    for r in cfg["recordings"]:
        rs = sorted((p for p in plan["sets"] if p["rec"] == r), key=lambda p: p["start"])
        for i, p in enumerate(rs):
            nxt = rs[i + 1]["start"] if i + 1 < len(rs) else plan["durations"][r]
            p["scan"] = (p["start"], min(max(p["end"], nxt - 1), p["end"] + SCAN_TAIL_S))
    for p in plan["sets"]:
        if (cfg.get("sets", {}).get(p["identifier"]) or {}).get("no_scan"):
            continue
        print(f"  scan {p['n']:02d} {p['identifier']} {p['round']}", flush=True)
        d = scan_set(cfg, p, refresh)
        games, problems = games_from_scan(p, d)
        sa, sb = int(p["a"]["score"] or 0), int(p["b"]["score"] or 0)
        total = sa + sb
        p["games_seen"] = [{"vs": g["vs"], "port": g["port"]} for g in games]
        why = None
        if len(games) < total:
            why = f"found {len(games)} games (VS screens), start.gg has {total}"
        else:
            if len(games) > total:
                p["notes"].append(f"{len(games) - total} game(s) before game 1 left out (handwarmer / friendly)")
                games = games[len(games) - total:]
            # winner order: start.gg's score + every results screen that was caught
            fits = set()
            for seq in side_sequences(sa, sb):
                for p1side in ("a", "b"):
                    other = "b" if p1side == "a" else "a"
                    if all(g["port"] is None or seq[k] == (p1side if g["port"] == 1 else other)
                           for k, g in enumerate(games)):
                        fits.add(tuple(seq))
            caught = sum(g["port"] is not None for g in games)
            if len(fits) == 1:
                seq = list(fits.pop())
                ticks = []
                for k, g in enumerate(games):
                    nxt = games[k + 1]["vs"] if k + 1 < len(games) else None
                    ticks.append(g["res"] or nxt)  # results screen, else the next game's VS
                p["games"] = [{"vs": g["vs"], "winner": seq[k], "result": ticks[k]} for k, g in enumerate(games)]
                p["start"] = round(max(p["start"], games[0]["vs"] - LEAD_IN_S), 2)
                if games[-1]["last"]:
                    p["end"] = round(min(games[-1]["last"] + TAIL_S, p["scan"][1]), 2)
                if p["games"][-1]["result"] is None:
                    p["games"][-1]["result"] = p["end"] - 15
            else:
                why = (f"{len(fits)} possible game orders for {sa}-{sb} ({caught} of {total} results screens caught)"
                       if fits else "results screens contradict start.gg's score")
                p["start"] = round(max(p["start"], games[0]["vs"] - LEAD_IN_S), 2)
        if why:
            p["games"] = None
            p["notes"].append(f"score not shown game by game: {why}")
        p["notes"] += problems
    with open(os.path.join(cfg["_out"], "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    write_review(cfg, plan)


def score_windows(p):
    """[(t0, t1, score_a, score_b)] in video time: 0-0, then +1 at each game's results screen."""
    if not p.get("games"):
        return [(p["start"], p["end"], None, None)]
    out, a, b, t = [], 0, 0, p["start"]
    for g in p["games"]:
        out.append((t, g["result"], a, b))
        a += g["winner"] == "a"
        b += g["winner"] == "b"
        t = g["result"]
    out.append((t, p["end"], a, b))
    return [w for w in out if w[1] > w[0]]


# ---------------------------------------------------------------- thumbnails (generated VS card)

ART_DIR = os.path.join(ROOT, "tools", "render", "overlays", "ultimate", "char_art")  # start.gg character renders, cached by name
IMPACT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "impact.ttf")
THUMB_W, THUMB_H = 1280, 720


def char_art(name):
    """Local copy of start.gg's render for an Ultimate character (videogame 1386 'icon' image)."""
    os.makedirs(ART_DIR, exist_ok=True)
    path = os.path.join(ART_DIR, safe_name(name) + ".png")
    if os.path.isfile(path):
        return path
    index = os.path.join(ART_DIR, "_index.json")
    if os.path.isfile(index):
        with open(index, encoding="utf-8") as f:
            cs = json.load(f)
    else:
        cs = gql("""query{videogame(id:1386){characters{name images{type url width}}}}""", {})["videogame"]["characters"]
        with open(index, "w", encoding="utf-8") as f:
            json.dump(cs, f, indent=1)
    c = next((x for x in cs if x["name"].lower() == name.lower()), None)
    if not c:
        return None
    url = max(c["images"], key=lambda i: (i["type"] == "icon", i.get("width") or 0))["url"]
    uo.fetch(url, path)
    return path


def player_history(cfg):
    """{lowercased tag: Counter of characters} from player_characters.json (all tournaments)."""
    from collections import Counter
    out = {}
    for path in (cfg.get("player_characters"), os.path.join(os.path.dirname(cfg["dock"].rstrip("/\\")), "..", "player_characters.json"),
                 os.path.join(ROOT, "Recording-IN", "Ultimate", cfg["title"].replace("PROTOCOL", "Protocol"), "player_characters.json")):
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                for pl in json.load(f).get("players", {}).values():
                    c = out.setdefault((pl.get("tag") or "").lower(), Counter())
                    for st in pl.get("sets", []):
                        c.update(st.get("chars") or [])
            break
    return out


def thumb_char(pl, history):
    """(character, how): first character of the set (game 1), else the player's most used, else Random."""
    if pl["chars"]:
        return pl["chars"][0], "set"
    h = history.get((pl.get("tag") or pl["name"]).lower())
    if h:
        return h.most_common(1)[0][0], "history"
    return "Random Character", "unknown"


def fit_size(fw, text, box_w, size, min_size):
    w = fw.width(text, size)
    return max(min_size, min(size, size * box_w / w)) if w else size


def thumb_path(cfg, p):
    return os.path.join(cfg["_out"], "thumbs", f"{p['n']:02d}_{p['identifier']}.jpg")


def make_thumbnail(cfg, p, history=None):
    """Uniform VS card: red P1 half / blue P2 half, character renders, names, round, Protocol emblem."""
    history = history if history is not None else player_history(cfg)
    out = thumb_path(cfg, p)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    impact = uo.FontWidths(IMPACT)
    typo = uo.widths()
    sides, how = [], []
    for pl in (p["a"], p["b"]):
        ch, src = thumb_char(pl, history)
        art = char_art(ch) or char_art("Random Character")
        sides.append((pl, ch, art))
        how.append(f"{pl.get('tag') or pl['name']}: {CHAR_SHORT.get(ch, ch)} ({src})")
    split = "(680-80*Y/720)"
    bg = (f"color=black:s={THUMB_W}x{THUMB_H},format=rgb24,geq="
          f"r='if(lt(abs(X-{split}),5),235,if(lt(X,{split}),200-110*Y/720,30-18*Y/720))':"
          f"g='if(lt(abs(X-{split}),5),235,if(lt(X,{split}),30-18*Y/720,80-50*Y/720))':"
          f"b='if(lt(abs(X-{split}),5),235,if(lt(X,{split}),40-24*Y/720,205-115*Y/720))'")
    font_i, font_t = uo.ff_path(IMPACT), uo.ff_path(uo.FONT)
    draws = ["drawbox=x=0:y=0:w=1280:h=92:color=black@0.88:t=fill"]
    for i, (pl, ch, _) in enumerate(sides):
        label = "?" if how[i].endswith("(unknown)") else CHAR_SHORT.get(ch, ch).upper()
        size = fit_size(impact, label, 470, 70, 34)
        x = "28" if i == 0 else f"{THUMB_W - 28}-text_w"
        draws.append(f"drawtext=fontfile='{font_i}':text='{uo.ff_text(label)}':fontsize={size:.0f}:fontcolor=white"
                     f":x={x}:y=46-ascent/2+4")
        tag = pl.get("tag") or pl["name"]
        size = fit_size(typo, tag, 540, 54, 26)
        x0 = 24 if i == 0 else 664
        draws.append(f"drawbox=x={x0}:y=628:w=592:h=72:color=black@0.78:t=fill")
        draws.append(f"drawtext=fontfile='{font_t}':text='{uo.ff_text(tag)}':fontsize={size:.0f}:fontcolor=white"
                     f":x={x0}+(592-text_w)/2:y=664-ascent/2")
    draws.append(f"drawtext=fontfile='{font_i}':text='VS':fontsize=170:fontcolor=white:borderw=9:bordercolor=black"
                 f":x=(w-text_w)/2-20:y=300")
    rnd = p["round"]
    draws.append(f"drawtext=fontfile='{font_t}':text='{uo.ff_text(rnd)}':fontsize=34:fontcolor=0x6bb0e1"
                 f":box=1:boxcolor=black@0.8:boxborderw=10:x=(w-text_w)/2:y=150")
    emblem = os.path.join(ROOT, "tools", "render", "overlays", "ultimate", "emblem.png")
    flip = "" if sides[1][1] == "Random Character" else ",hflip"  # face P1, but don't mirror the "?"
    fc = (f"[1:v]scale=640:600:force_original_aspect_ratio=decrease[c1];"
          f"[2:v]scale=640:600:force_original_aspect_ratio=decrease{flip}[c2];"
          f"[3:v]scale=250:-1[em];"
          f"[0:v][c1]overlay=x='330-w/2':y='H-h-20'[a];[a][c2]overlay=x='950-w/2':y='H-h-20'[b];"
          f"[b]{','.join(draws)}[c];[c][em]overlay=x='(W-w)/2':y=4")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", bg, "-i", sides[0][2], "-i", sides[1][2],
                    "-i", emblem, "-filter_complex", fc, "-frames:v", "1", "-q:v", "2", out], check=True)
    p["thumb_chars"] = how
    print(f"    thumbnail: {'; '.join(how)}", flush=True)
    return out


def full_vod_path(cfg, rec):
    return os.path.join(cfg["_media"], safe_name(f"{cfg['title']} - {rec_label(cfg, rec)} Full VOD") + ".mp4")


def rec_label(cfg, rec):
    return (cfg.get("recording_names") or {}).get(rec, f"Recording {rec}")


def build_full_vods(cfg, plan):
    for rec in cfg["recordings"]:
        sets = [p for p in plan["sets"] if p["rec"] == rec]
        if len(sets) < 2:
            continue
        files = [set_file(cfg, p) for p in sets]
        if not all(os.path.isfile(f) for f in files):
            print(f"Recording {rec} Full VOD skipped: not all sets rendered")
            continue
        key = f"rec{rec}"
        lst = os.path.join(cfg["_work"], f"full_vod_{key}.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.writelines(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in files)
        meta, t = [";FFMETADATA1"], 0.0
        for p, fp in zip(sets, files):
            d = probe_duration(fp)
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}", f"END={int((t + d) * 1000)}",
                     f"title={p['round']}: {p['a']['name']} vs {p['b']['name']}"]
            t += d
        mp = os.path.join(cfg["_work"], f"chapters_{key}.ffmeta")
        with open(mp, "w", encoding="utf-8") as f:
            f.write("\n".join(meta) + "\n")
        out = full_vod_path(cfg, rec)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", mp,
                        "-map", "0", "-map_metadata", "1", "-c", "copy", "-movflags", "+faststart", out], check=True)
        print(f"{rec_label(cfg, rec)} Full VOD: {out} ({hms(t)}, {len(sets)} sets)")


def render(cfg, plan, only=None):
    analyze_sets(cfg, plan)
    for p in plan["sets"]:
        if only and p["identifier"] not in only:
            continue
        print(f"  {os.path.basename(set_file(cfg, p))}  [rec {p['rec']} {hms(p['start'])}-{hms(p['end'])}]", flush=True)
        render_set(cfg, p)
        make_thumbnail(cfg, p)
    if not only:
        build_full_vods(cfg, plan)
        write_kit(cfg, plan)


# ---------------------------------------------------------------- upload kit

def write_kit(cfg, plan):
    kit = os.path.join(cfg["_out"], "upload_kit")
    os.makedirs(kit, exist_ok=True)
    tname = plan["tournament"]
    bracket = f"https://www.start.gg/{plan['event_slug']}"
    entries = []
    for rec in cfg["recordings"]:
        full = full_vod_path(cfg, rec)
        if not os.path.isfile(full):
            continue
        ch, t = [], 0.0
        for p in (x for x in plan["sets"] if x["rec"] == rec):
            ch.append(f"{hms(t)} {p['round']}: {p['a']['name']} vs {p['b']['name']}")
            t += probe_duration(set_file(cfg, p))
        desc = [f"Bracket: {bracket}"] + ([""] + ch if len(ch) >= 3 else [])
        entries.append((full, cfg.get("title_full", TITLE_FULL).format(tournament=tname, rec=rec_label(cfg, rec)), desc))
    for p in plan["sets"]:
        path = set_file(cfg, p)
        if not os.path.isfile(path):
            print(f"  kit: {os.path.basename(path)} not rendered yet, skipped")
            continue
        f = {"tournament": tname, "round": p["round"], "a": p["a"]["name"], "b": p["b"]["name"]}
        room = 100 - (len(cfg["game"]) + 1 if cfg.get("account") else 0)  # a second channel adds " Ultimate"
        title = f"{tname}: {p['round']} - {player_title(p['a'])} vs {player_title(p['b'])}"
        if len(title) > room:  # keep the characters, drop sponsor prefixes
            title = f"{tname}: {p['round']} - {player_title(dict(p['a'], name=p['a'].get('tag') or p['a']['name']))} "                     f"vs {player_title(dict(p['b'], name=p['b'].get('tag') or p['b']['name']))}"
        if len(title) > room:
            title = cfg.get("title_set_short", TITLE_SET_SHORT).format(**f)[:100]
        desc = [f"{p['round']}: {p['a']['name']} vs {p['b']['name']} ({p['winner']} won "
                f"{max(p['a']['score'], p['b']['score'])}-{min(p['a']['score'], p['b']['score'])})",
                f"Bracket: {bracket}/set/{p['setId']}"]
        thumb = thumb_path(cfg, p)
        entries.append((path, title, desc, p.get("check", ""), thumb if os.path.isfile(thumb) else None))
    entries = [e if len(e) == 5 else (*e, "", None) for e in entries]
    md = [f"# Upload kit: {tname} Ultimate", ""]
    for path, title, desc, check, thumb in entries:
        with open(os.path.join(kit, os.path.splitext(os.path.basename(path))[0] + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(f"FILE: {path}\n\n===== TITLE (copy the next line) =====\n{title}\n\n"
                     "===== DESCRIPTION (copy everything below this line) =====\n" + "\n".join(desc) + "\n")
        md += [f"## {title}", "", f"File: `{path}`", "", "```", *desc, "```", ""]
    with open(os.path.join(kit, "upload_kit.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    with open(os.path.join(kit, "upload_kit.json"), "w", encoding="utf-8") as fh:
        json.dump({"tournament": tname, "playlist": tname, "game": "Ultimate", "account": cfg.get("account"),
                   "tags": cfg.get("tags") or DEFAULT_TAGS,
                   "videos": [dict({"file": p, "title": t, "description": "\n".join(d)},
                                   **({"privacy": "private", "check": c} if c else {}),
                                   **({"thumbnail": th} if th else {}))
                              for p, t, d, c, th in entries]},
                  fh, indent=2, ensure_ascii=False)
    print(f"Upload kit: {kit} ({len(entries)} videos, {sum(1 for e in entries if e[3])} held private to check)")
    write_to_questions(cfg, plan)


def write_to_questions(cfg, plan):
    """Short list for the Ultimate TO: hand-fixed sets to confirm and missing characters."""
    L = [f"{plan['tournament']} Ultimate - please check", ""]
    fixed = [p for p in plan["sets"] if p.get("check")]
    if fixed:
        L += ["These sets' dock times were off, so I cut them by watching the recording. Do they look right?", ""]
        for p in fixed:
            L.append(f"- {p['round']} ({p['identifier']}): {p['a']['name']} vs {p['b']['name']}, "
                     f"Recording {p['rec']} {hms(p['start'])} to {hms(p['end'])}")
        L.append("")
    missing = [p for p in plan["sets"] if not p["a"]["chars"] or not p["b"]["chars"]]
    if missing:
        L += ["Characters missing (who played what, in order):", ""]
        for p in missing:
            who = [x["name"] for x in (p["a"], p["b"]) if not x["chars"]]
            L.append(f"- {p['round']} ({p['identifier']}): {' and '.join(who)}")
    with open(os.path.join(cfg["_out"], "questions_for_TO.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Cut the Ultimate bracket recordings into set videos.")
    ap.add_argument("command", choices=["plan", "scan", "render", "thumbs", "kit"])
    ap.add_argument("config")
    ap.add_argument("--only", help="comma-separated set letters to (re)render")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if os.name == "nt" and a.command in ("render", "thumbs", "scan"):
        import ctypes  # keep Windows awake while rendering (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    plan = make_plan(cfg)
    print(f"{len(plan['sets'])} sets planned; review: {os.path.join(cfg['_out'], 'review.md')}")
    if a.command == "render":
        render(cfg, plan, set(a.only.split(",")) if a.only else None)
    elif a.command == "scan":
        analyze_sets(cfg, plan)
        print(f"review: {os.path.join(cfg['_out'], 'review.md')}")
    elif a.command == "thumbs":
        for p in plan["sets"]:
            if not a.only or p["identifier"] in a.only.split(","):
                print(f"  {p['n']:02d} {p['identifier']} {p['round']}", flush=True)
                make_thumbnail(cfg, p)
    elif a.command == "kit":
        write_kit(cfg, plan)


if __name__ == "__main__":
    main()
