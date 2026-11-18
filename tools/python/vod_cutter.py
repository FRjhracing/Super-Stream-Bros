#!/usr/bin/env python3
"""
vod_cutter.py - build the tournament VOD from the stream recording, Slippi replays
and start.gg.

Usage:
    python tools\\python\\vod_cutter.py plan   "I:\\Protocol VOD\\Melee\\Protocol #N\\vod_config.json"
    python tools\\python\\vod_cutter.py render "I:\\Protocol VOD\\Melee\\Protocol #N\\vod_config.json" [--only D,G]
    python tools\\python\\vod_cutter.py kit    "I:\\Protocol VOD\\Melee\\Protocol #N\\vod_config.json"

kit    writes <out>\\upload_kit\\ : one .txt per video (title + description) and
       upload_kit.md. Titles follow "PROTOCOL #56: ..." (config keys title_full /
       title_set); descriptions are "Replays: <Drive folder link>" and
       "Bracket: <start.gg link>" plus chapters. Runs automatically after render.

plan   matches start.gg sets to replays and writes <out>\\plan.json + review.md.
       Nothing is rendered; read review.md first.
render renders every set to <out>\\sets\\NN - <round> - <A> vs <B>.mp4 (per-set uploads),
       then joins them into <out>\\<name> - Full VOD.mp4 with chapters
       (youtube_chapters.txt + embedded).

Rules (see VODCUTTER_PROJECT_NOTES.md):
- Games abandoned by quitting (no_contest) and games under 30 s are not counted, except a quit-out
  on the quitter's last stock in the middle of a set (counted for the other player, flagged in
  review.md and kept in player_notes.json).
- A set is the last N counted games of that pairing before start.gg marked it done
  (N = sum of the set's scores); extra earlier games are handwarmers.
- On-stream sets are cut from the recording; everything between their games is kept;
  pad_before_s / pad_after_s around each set.
- Off-stream sets are rendered from replays (replay_render.py) with the overlay
  rebuilt (vod_overlay.py), when include_offstream is true.
- Audio +gain_db with a limiter just under 0 dB; the measured peak is printed.
- Sets are ordered by when their first game started.
Inputs are only read: the recording, Recording-BACKUP and the .slp files are never written.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import socket

# Try IPv4 before IPv6 (flaky IPv6 to start.gg on the laptop's network; see StreamDock/dock_server.py).
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_getaddrinfo(*a, **k), key=lambda r: r[0] != socket.AF_INET)

CODE = os.path.dirname(os.path.abspath(__file__))           # tools\\python (the scripts)
ROOT = os.path.dirname(os.path.dirname(CODE))                # project folder
HERE = ROOT  # older name, kept for compatibility
sys.path.insert(0, CODE)
import slippi_scan  # noqa: E402
import vod_overlay  # noqa: E402

FFMPEG = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe")
FFPROBE = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffprobe.exe")
API_URL = "https://api.start.gg/gql/alpha"
MELEE_ID = 1
MIN_GAME_S = 30
MAX_GAP_IN_SET_S = 8 * 60

# Slippi costume index -> Stream Updater / dock color names (Melee costume order).
COSTUMES = {
    "Captain Falcon": ["neutral", "black", "red", "white", "green", "blue"],
    "Donkey Kong": ["neutral", "black", "red", "blue", "green"],
    "Fox": ["neutral", "red", "blue", "green"],
    "Mr. Game & Watch": ["neutral", "red", "blue", "green"],
    "Kirby": ["neutral", "yellow", "blue", "red", "green", "white"],
    "Bowser": ["neutral", "red", "blue", "black"],
    "Link": ["neutral", "red", "blue", "black", "white"],
    "Luigi": ["neutral", "white", "blue", "pink"],
    "Mario": ["neutral", "yellow", "brown", "blue", "green"],
    "Marth": ["neutral", "red", "green", "black", "white"],
    "Mewtwo": ["neutral", "red", "blue", "green"],
    "Ness": ["neutral", "yellow", "blue", "green"],
    "Peach": ["neutral", "daisy", "white", "blue", "green"],
    "Pikachu": ["neutral", "red", "blue", "green"],
    "Ice Climbers": ["neutral", "green", "orange", "red"],
    "Jigglypuff": ["neutral", "bow", "headband", "flower", "crown"],
    "Samus": ["neutral", "pink", "brown", "green", "blue"],
    "Yoshi": ["neutral", "red", "blue", "yellow", "pink", "cyan"],
    "Zelda": ["neutral", "red", "blue", "green", "lavender"],
    "Sheik": ["neutral", "red", "blue", "green", "black"],
    "Falco": ["neutral", "red", "blue", "green"],
    "Young Link": ["neutral", "red", "blue", "white", "black"],
    "Doctor Mario": ["neutral", "red", "blue", "green", "black"],
    "Roy": ["neutral", "red", "blue", "green", "yellow"],
    "Pichu": ["neutral", "red", "blue", "green"],
    "Ganondorf": ["neutral", "red", "blue", "green", "purple"],
}
CHAR_NAME = {"Dr. Mario": "Doctor Mario"}


def char_color(p):
    ch = CHAR_NAME.get(p["character"], p["character"])
    cols = COSTUMES.get(ch, ["neutral"])
    return ch, cols[p["costume"]] if p["costume"] < len(cols) else "neutral"


def hms(s):
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def safe_name(s):
    s = s.replace("|", "-")  # "ODU | Aris" -> "ODU - Aris"
    return re.sub(r"\s+", " ", re.sub(r'[<>:"/\\?*]', "", s)).strip()


# ---------------------------------------------------------------- inputs

def find_volume(label):
    """Drive root ("I:\\") of the volume with this label (drive letters change; labels don't)."""
    import ctypes
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        buf = ctypes.create_unicode_buffer(261)
        if os.path.isdir(root) and ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0):
            if buf.value.lower() == label.lower():
                return root
    return None


def resolve_path(p, base):
    """A path in a config: "{ssd}" = the external SSD "Project Storage" (whatever its drive letter);
    relative paths are tried next to the config first, then in the project folder."""
    if not p:
        return p
    if p.startswith("{ssd}"):
        drive = find_volume("Project Storage")
        if not drive:
            raise SystemExit(f'External SSD "Project Storage" is not connected (needed for {p}).')
        p = os.path.join(drive, p[len("{ssd}"):].lstrip("/\\"))
    if os.path.isabs(p):
        return os.path.normpath(p)
    near = os.path.join(base, p)
    return near if os.path.exists(near) else os.path.join(ROOT, p)


def on_ssd(path):
    drive = find_volume("Project Storage")
    return bool(drive) and os.path.abspath(path).lower().startswith(drive.lower())


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    cfg["_out"] = base
    cfg["_work"] = os.path.join(base, "work")
    # Videos (sets, Full VODs, rendered games) go to the external SSD "Project Storage" by default
    # (user, 2026-11-10); config, plan, review, upload kit and caches stay next to the config.
    # "media_dir": null keeps everything next to the config (how #59 and earlier were made).
    # Since 2026-11-11 a tournament's whole folder (config included) lives on the SSD:
    # <SSD>\\Protocol VOD\\Melee\\Protocol #N\\. Then the videos simply go next to the config.
    if "media_dir" not in cfg and on_ssd(base):
        cfg["media_dir"] = None
    if "media_dir" not in cfg:
        drive = find_volume("Project Storage")
        if not drive:
            raise SystemExit('External SSD "Project Storage" is not connected (or set "media_dir" in the config).')
        cfg["media_dir"] = os.path.join(drive, "Protocol VOD", "Melee", cfg.get("title", cfg["tournament"]).replace("PROTOCOL", "Protocol"))
    cfg["_media"] = resolve_path(cfg["media_dir"], base) if cfg["media_dir"] else base
    if cfg["media_dir"]:
        drive = os.path.splitdrive(os.path.abspath(cfg["_media"]))[0]
        if drive and not os.path.isdir(drive + os.sep):
            raise SystemExit(f"media_dir drive {drive} is not connected (external SSD?): {cfg['_media']}")
    cfg["_mwork"] = os.path.join(cfg["_media"], "work") if cfg["media_dir"] else cfg["_work"]
    # Replays: the tournament folder's replays\\ (the uploader copies the flash drives there), unless set.
    cfg.setdefault("replays", "replays")
    for k in ("recording", "replays"):
        cfg[k] = resolve_path(cfg[k], base)
    cfg.setdefault("pad_before_s", 10)
    cfg.setdefault("pad_after_s", 10)
    cfg.setdefault("gain_db", 10)
    cfg.setdefault("include_offstream", True)
    cfg.setdefault("clock_offset_s", {})
    cfg.setdefault("sets", {})
    cfg.setdefault("title", cfg["tournament"])
    cfg.setdefault("overlay_stream", True)  # stream sets: lay the rebuilt overlay over the live one
    if cfg.get("dock_log"):
        cfg["dock_log"] = resolve_path(cfg["dock_log"], base)
    return cfg


# ---------------------------------------------------------------- dock setup log

def setup_key(name):
    """Loose setup name for matching dock names to replay folders: case, punctuation, the word
    'setup' and a trailing plural/possessive s don't count ("Bzimm's Setup" == "BZimm's")."""
    k = re.sub(r"[^a-z0-9]", "", (name or "").lower().replace("setup", ""))
    return k[:-1] if len(k) > 3 and k.endswith("s") else k


def map_dock_setups(cfg, dock_names, replay_setups):
    """Dock setup name -> replay folder. Config "dock_setups" wins, then the loose name match."""
    manual = {k: v for k, v in cfg.get("dock_setups", {}).items() if not k.startswith("_")}
    by_key = {setup_key(s): s for s in replay_setups}
    out = {}
    for n in dock_names:
        out[n] = manual.get(n) or by_key.get(setup_key(n))
    return out


def load_dock(cfg, replay_setups):
    """Melee Stream Dock setups.jsonl (RENDER_PC_HANDOFF.md section 2-3) -> per set letter a list
    of segments {setup (replay folder), dock_setup, t0, t1, end_reason, result, zero, note}."""
    path = cfg.get("dock_log")
    if not path or not os.path.isfile(path):
        return {}, {}
    events = []
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f):
            try:
                events.append((json.loads(line), n))
            except ValueError:
                continue
    events.sort(key=lambda en: (en[0].get("t", 0), en[1]))
    names = {e.get("setupName") for e, _ in events if e.get("setupName")}
    setup_map = map_dock_setups(cfg, names, replay_setups)
    starts, sets = {}, {}
    for e, _ in events:
        if e.get("event") == "on_setup":
            starts[e["id"]] = e
        elif e.get("event") == "set_end":
            s = starts.pop(e.get("seg") or "", None)
            if not s:
                continue
            sets.setdefault(s["identifier"], []).append({
                "setup": setup_map.get(s.get("setupName")), "dock_setup": s.get("setupName"),
                "t0": datetime.fromtimestamp(s["t"]), "t1": datetime.fromtimestamp(e["t"]),
                "end_reason": e.get("reason", ""), "result": e.get("result"),
                "zero": e["t"] - s["t"] < 1, "note": s.get("note", "")})
    for s in starts.values():  # never ended (still playing when the log was copied)
        sets.setdefault(s["identifier"], []).append({
            "setup": setup_map.get(s.get("setupName")), "dock_setup": s.get("setupName"),
            "t0": datetime.fromtimestamp(s["t"]), "t1": None, "end_reason": "no end in the log",
            "result": None, "zero": False, "note": s.get("note", "")})
    return sets, setup_map


def dock_notes(segs):
    """Things worth a look in review.md for one set's dock segments."""
    out = []
    real = [s for s in segs if not s["zero"]]
    if any(s["zero"] for s in segs):
        out.append("dock: setup picked at report with no start time (zero-length entry)")
    if len([s for s in segs if s["result"]]) > 1:
        out.append("dock: reported more than once (" + " / ".join(s["result"] for s in segs if s["result"])
                   + "); start.gg's final score is used")
    for s in segs:
        if s["end_reason"].startswith("moved to"):
            out.append(f"dock: {s['end_reason']} from {s['dock_setup']} at {s['t1']:%H:%M:%S}")
    for i, x in enumerate(real):
        for y in real[i + 1:]:
            if x["dock_setup"] != y["dock_setup"] and x["t1"] and y["t1"] and x["t0"] < y["t1"] and y["t0"] < x["t1"]:
                out.append(f"dock: on {x['dock_setup']} and {y['dock_setup']} at the same time "
                           f"({max(x['t0'], y['t0']):%H:%M}-{min(x['t1'], y['t1']):%H:%M})")
    return out


def recording_start(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})-(\d{2})", os.path.basename(path))
    if not m:
        raise SystemExit("Recording filename must start with 'YYYY-MM-DD HH-MM-SS'.")
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}")


def probe_duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def clock_offset(val):
    """Seconds a setup's Wii clock is ahead of the laptop. Either a number, or an anchor
    {"wii": "<Wii date time>", "laptop": "<laptop date time>"} for the same moment, for
    Wiis whose date is wrong too (#57: 2009, 2017 and 2025)."""
    if isinstance(val, dict):
        return (datetime.fromisoformat(val["wii"]) - datetime.fromisoformat(val["laptop"])).total_seconds()
    return float(val)


def load_replays(cfg):
    rows, errors = slippi_scan.collect(cfg["replays"])
    # "replay_repairs": {"<setup>/<file>.slp": "<repaired copy>"} - a replay with damaged bytes
    # is read (and rendered) from its repaired copy (slp_repair.py); the original stays as is.
    repairs = {os.path.normcase(os.path.normpath(k)): v for k, v in cfg.get("replay_repairs", {}).items()
               if not k.startswith("_")}
    for r in rows:
        fix = repairs.get(os.path.normcase(os.path.normpath(r["path"])))
        if fix:
            fix = fix if os.path.isabs(fix) else os.path.join(ROOT, fix)
            new = slippi_scan.scan_file(fix)
            for k, v in new.items():
                if k not in ("file", "setup", "path"):
                    r[k] = v
            r["render_from"] = fix
            r["flags"] = list(r["flags"]) + ["repaired"]
    offsets = {k: clock_offset(v) for k, v in cfg["clock_offset_s"].items() if not k.startswith("_")}
    for r in rows:
        # Console replays store local wall-clock time without a timezone (see PROJECT_NOTES).
        t = datetime.fromisoformat(r["start_utc"])
        if t.tzinfo is not None:
            t = t.astimezone().replace(tzinfo=None)
        r["wii_time"] = t
        r["laptop_time"] = t - timedelta(seconds=offsets.get(r["setup"], 0))
        r["counted"] = (r["end_method"] != "no_contest" and (r["duration_s"] or 0) >= MIN_GAME_S
                        and "not_singles" not in r["flags"]
                        and all(p.get("type") == "human" for p in r["players"]))  # tournament sets never have CPUs
        # Quit-out on the quitter's last stock (user rule 2026-11-17, #60 H game 2): a real game, won by
        # the other player, but only when it sits in the middle of a set (see match_sets).
        r["quitter"] = None
        r["last_stock_quit"] = False
        if (r["end_method"] == "no_contest" and r.get("winner_basis") == "quit" and (r["duration_s"] or 0) >= MIN_GAME_S
                and "not_singles" not in r["flags"] and all(p.get("type") == "human" for p in r["players"])):
            q = next((p for p in r["players"] if p["port"] != r["winner_port"]), None)
            if q:
                r["quitter"] = q["port"]
                r["last_stock_quit"] = q.get("final_stocks") == 1
    return rows, errors


def get_token():
    tok = os.environ.get("STARTGG_TOKEN", "").strip()
    if tok:
        return tok
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        return str(winreg.QueryValueEx(k, "STARTGG_TOKEN")[0]).strip()


def gql(query, variables):
    import urllib.request
    req = urllib.request.Request(API_URL, json.dumps({"query": query, "variables": variables}).encode(), {
        "Authorization": "Bearer " + get_token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    if d.get("errors"):
        raise SystemExit(f"start.gg: {d['errors']}")
    return d["data"]


def load_startgg(cfg):
    cache = os.path.join(cfg["_work"], "startgg.json")
    if os.path.isfile(cache) and not cfg.get("refresh_startgg"):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    t = gql("""query($s:String!){tournament(slug:$s){name events{id name videogame{id} numEntrants}}}""",
            {"s": cfg["tournament"]})["tournament"]
    ev = sorted([e for e in t["events"] if e["videogame"]["id"] == MELEE_ID],
                key=lambda e: e["numEntrants"] or 0, reverse=True)[0]
    d = gql("""query($e:ID!){event(id:$e){sets(page:1,perPage:80,sortType:STANDARD){nodes{
      id identifier fullRoundText state startedAt completedAt winnerId displayScore
      stream{streamName}
      slots{entrant{id name participants{gamerTag prefix user{images{type url}}}}
            standing{stats{score{value}}}}}}}}""", {"e": ev["id"]})
    data = {"tournament": t["name"], "event": ev["name"], "sets": d["event"]["sets"]["nodes"]}
    os.makedirs(cfg["_work"], exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def entrant_info(slot):
    ent = slot.get("entrant") or {}
    p = (ent.get("participants") or [{}])[0]
    img = next((i["url"] for i in ((p.get("user") or {}).get("images") or []) if i.get("type") == "profile"), "")
    tag = p.get("gamerTag") or ent.get("name") or "?"
    score = (((slot.get("standing") or {}).get("stats") or {}).get("score") or {}).get("value")
    return {"entrantId": ent.get("id"), "tag": tag, "prefix": p.get("prefix") or "",
            "name": f"{p['prefix']} | {tag}" if p.get("prefix") else tag, "imageUrl": img, "score": score}


# ---------------------------------------------------------------- matching

def chars_by_port(r):
    return {p["port"]: p["character"] for p in r["players"]}


QUICK_RESTART_S = 90  # games in a set start within ~1 min; a new pair takes 3+ min to sit down


def same_players(r, nxt):
    """Could r and the next game nxt be the same two players? Players keep their ports for a
    whole set; a counterpick changes one side's character, a new pairing usually changes both.
    (Uncle B / Hyraks / Applesauc switch characters mid-set, so the pair alone isn't enough.)
    Both sides switching at once still counts as the same set when the next game started
    quickly (#57 O: Killajive Zelda/Sheik/DK vs bjh500 Bowser/Doc/Falco, 30-51 s apart)."""
    a, b = chars_by_port(r), chars_by_port(nxt)
    if set(a) != set(b):
        return False
    if sum(a[p] != b[p] for p in a) < len(a):
        return True
    gap = (nxt["laptop_time"] - (r["laptop_time"] + timedelta(seconds=r["duration_s"] or 0))).total_seconds()
    return gap < QUICK_RESTART_S


def score_fits(set_games, sa, sb):
    """start.gg score vs replay winners; games with no known winner (cut-off replay) fill in."""
    wins, unknown = {}, 0
    for g in set_games:
        if g["winner_port"] is None:
            unknown += 1
        else:
            wins[g["winner_port"]] = wins.get(g["winner_port"], 0) + 1
    known = sorted(wins.values(), reverse=True) + [0] * (2 - len(wins))
    want = sorted([sa, sb], reverse=True)
    if len(wins) > 2 or len(set_games) != sa + sb:
        return False
    # Unknown games can go to either side; known wins may never exceed a side's score.
    return any(known[0] <= want[i] and known[1] <= want[1 - i]
               and (want[i] - known[0]) + (want[1 - i] - known[1]) == unknown for i in (0, 1))


def game_blocks(replays, setups):
    """Runs of consecutive counted games on one setup that look like the same two players.
    Last-stock quit-outs are in the runs too; match_sets only lets them count mid-set."""
    blocks = []
    for setup in setups:
        games = sorted((r for r in replays if r["setup"] == setup and (r["counted"] or r["last_stock_quit"])),
                       key=lambda r: r["laptop_time"])
        cur = []
        for r in games:
            if cur:
                prev = cur[-1]
                gap = (r["laptop_time"] - (prev["laptop_time"] + timedelta(seconds=prev["duration_s"] or 0))).total_seconds()
                if gap > MAX_GAP_IN_SET_S or not same_players(prev, r):
                    blocks.append(cur)
                    cur = []
            cur.append(r)
        if cur:
            blocks.append(cur)
    return blocks


def handwarmers(before, first):
    """Up to 2 games right before a set with exactly the same characters in the same ports.
    Anything else earlier in the run is another set (#57: W's Sheik vs Luigi runs straight
    into the Grand Final's Peach vs Luigi, Bichon never leaving port 3)."""
    out = []
    for r in reversed(before):
        if len(out) == 2 or chars_by_port(r) != chars_by_port(first):
            break
        out.insert(0, r)
    return out


def ports_for(games, a, b):
    """Which port is which entrant: the set's winner holds the port that won the most games."""
    wins = {}
    for g in games:
        if g["winner_port"] is not None:
            wins[g["winner_port"]] = wins.get(g["winner_port"], 0) + 1
    ports = [p["port"] for p in games[-1]["players"]]
    top = max(wins, key=wins.get) if wins else ports[0]
    other = next((p for p in ports if p != top), None)
    a_won = (a["score"] or 0) > (b["score"] or 0)
    return {"a": top if a_won else other, "b": other if a_won else top}


def looks_on(games, port):
    return [char_color(p) for g in games for p in g["players"] if p["port"] == port]


def identity_score(cand, a, b, profiles):
    """+1 per entrant whose games here use characters/colors seen in their other sets
    (+0.5 same characters, other colors), -1 when an entrant with a known profile shows
    none of them; 0 while the entrant is still unknown."""
    score = 0.0
    for side, ent in (("a", a), ("b", b)):
        prof = profiles.get(ent["entrantId"])
        if not prof:
            continue
        looks = looks_on(cand["games"], cand["port_of"][side])
        exact = sum(1 for lk in looks if lk in prof) / len(looks)
        chars = {c for c, _ in prof}
        char = sum(1 for lk in looks if lk[0] in chars) / len(looks)
        score += exact if exact else (0.5 * char if char else -1.0)
    return score


def match_sets(cfg, sg, replays):
    """Return (planned_sets, notes). Each planned set has its games (replay rows).

    Candidates for a set: the last N games (N = start.gg game count) of any run of
    same-player games on any setup that ends before the set was reported, inside its
    time window, and whose winners fit the score. Timing alone can't pick between them
    when several setups finish 3-0s minutes apart (#57: 5 setups), so: stream-assigned
    sets go to the stream setup first; then the set whose best candidate stands out most
    is taken, one at a time, scoring candidates by the characters/colors each player
    showed in the sets already matched."""
    notes, planned, quit_outs = [], [], []
    setups = sorted({r["setup"] for r in replays})
    stream_setup, stream_name = cfg["stream_setup"], cfg.get("stream_name", "").lower()
    blocks = game_blocks(replays, setups)
    dock, setup_map = load_dock(cfg, setups)
    if dock:
        unmapped = sorted(n for n, v in setup_map.items() if not v)
        notes.append("dock setups -> replay folders: " + ", ".join(
            f"{n} -> {v}" for n, v in sorted(setup_map.items()) if v)
            + (f"; NOT FOUND: {', '.join(unmapped)} (add \"dock_setups\" to vod_config.json)" if unmapped else ""))
    todo = []
    for s in sorted((s for s in sg["sets"] if s["state"] == 3), key=lambda s: s["completedAt"] or 0):
        sid = s["identifier"]
        ov = cfg["sets"].get(sid, {})
        a, b = (entrant_info(x) for x in s["slots"])
        if ov.get("score"):  # [a, b] when start.gg's reported score is wrong (e.g. #59 C reported 4-0)
            a["score"], b["score"] = ov["score"]
        score_txt = "DQ" if min(a["score"] or 0, b["score"] or 0) < 0 else f"{a['score']}-{b['score']}"
        label = f"{sid} {s['fullRoundText']}: {a['name']} {score_txt} {b['name']}"
        if ov.get("skip"):
            notes.append(f"{label}: skipped by config ({ov.get('reason', 'no reason given')})")
            continue
        if a["score"] is None or b["score"] is None or a["score"] < 0 or b["score"] < 0:
            notes.append(f"{label}: DQ / no score, not in the VOD")
            continue
        need = a["score"] + b["score"]
        assigned_stream = bool(stream_name) and (s.get("stream") or {}).get("streamName", "").lower() == stream_name
        done_at = datetime.fromtimestamp(s["completedAt"])
        start_at = datetime.fromtimestamp(s["startedAt"]) if s.get("startedAt") else done_at
        if (done_at - start_at).total_seconds() < 120:
            start_at = done_at - timedelta(minutes=60)  # reported in one click: no real start time
        # Dock log: which setup(s) the set was on, and when it went on (the TO's clicks, so with slack).
        dsegs = dock.get(sid, [])
        dock_setups = {d["setup"] for d in dsegs if d["setup"]}
        dinfo = dock_notes(dsegs) if dock else []
        if dock and not dsegs:
            dinfo.append("dock: not in the setup log (reported straight on start.gg); matched without it")
        real_starts = [d["t0"] for d in dsegs if not d["zero"]]
        if real_starts:
            start_at = min(start_at, min(real_starts))
        cands = []
        if ov.get("games"):
            # Manual pick: exactly these files, no checks.
            games = sorted((r for r in replays if r["file"] in ov["games"]), key=lambda r: r["laptop_time"])
            if games:
                cands.append({"setup": games[0]["setup"], "games": games, "handwarmers": [], "report_gap": 0,
                              "port_of": ports_for(games, a, b), "score_ok": score_fits(games, a["score"], b["score"])})
        else:
            seen = set()
            for blk0 in blocks:
                if ov.get("setup") and blk0[0]["setup"] != ov["setup"]:
                    continue
                # Games after the report are friendlies; the set is the last N games before it.
                usable0 = [r for r in blk0 if r["laptop_time"] <= done_at + timedelta(seconds=60)]
                # With last-stock quit-outs counted, and without them (a quit-out only counts mid-set).
                versions = [usable0]
                if any(r["last_stock_quit"] for r in usable0):
                    versions.append([r for r in usable0 if not r["last_stock_quit"]])
                for usable in versions:
                    if len(usable) < need:
                        continue
                    set_games = usable[-need:]
                    if set_games[0]["last_stock_quit"] or set_games[-1]["last_stock_quit"]:
                        continue  # a quit-out only counts in the middle of a set
                    key = tuple(r["path"] for r in set_games)
                    if key in seen:
                        continue
                    seen.add(key)
                    if set_games[0]["laptop_time"] < start_at - timedelta(minutes=15):
                        continue
                    if not score_fits(set_games, a["score"], b["score"]):
                        continue
                    last = set_games[-1]
                    report_gap = (done_at - (last["laptop_time"] + timedelta(seconds=last["duration_s"] or 0))).total_seconds()
                    before = [r for r in usable[:-need] if not r["last_stock_quit"]]
                    cands.append({"setup": usable[0]["setup"], "games": set_games,
                                  "handwarmers": handwarmers(before, set_games[0]),
                                  "report_gap": report_gap, "port_of": ports_for(set_games, a, b), "score_ok": True})
        if dock_setups and not ov.get("games") and not ov.get("setup"):
            on_dock = [c for c in cands if c["setup"] in dock_setups]
            if on_dock:
                cands = on_dock
            elif cands:
                dinfo.append(f"dock: put on {', '.join(sorted(dock_setups))}, but no games there fit; "
                             "matched on another setup, check it")
        todo.append({"s": s, "id": sid, "a": a, "b": b, "label": label, "dock_info": dinfo,
                     "assigned_stream": assigned_stream, "cands": cands})

    profiles, used = {}, set()

    def live(t):
        return [c for c in t["cands"] if not any(g["path"] in used for g in c["games"])]

    def rank(t):
        """Candidates best first: identity match (+1 for the stream setup on a
        stream-assigned set), then the last game ending closest to the report."""
        def key(c):
            stream_pref = 1 if (t["assigned_stream"] and c["setup"] == stream_setup) else 0
            return (identity_score(c, t["a"], t["b"], profiles) + stream_pref, -abs(c["report_gap"]) / 3600)
        return sorted(((key(c), c) for c in live(t)), key=lambda kc: kc[0], reverse=True)

    def take(t, c, why):
        for g in c["games"] + c["handwarmers"]:
            used.add(g["path"])
        for side in ("a", "b"):
            profiles.setdefault(t[side]["entrantId"], set()).update(looks_on(c["games"], c["port_of"][side]))
        t["pick"], t["why"] = c, why

    # 1. Stream-assigned sets with exactly one fitting run on the stream setup.
    for t in todo:
        if t["assigned_stream"]:
            on = [c for c in live(t) if c["setup"] == stream_setup]
            if len(on) == 1:
                take(t, on[0], "assigned to our stream on start.gg, and the only fit on " + stream_setup)
    # 2. The rest, most clear-cut first.
    while True:
        open_ = [t for t in todo if "pick" not in t and live(t)]
        if not open_:
            break
        scored = []
        for t in open_:
            r = rank(t)
            margin = (r[0][0][0] - r[1][0][0]) if len(r) > 1 else 99.0
            scored.append((margin, r[0][0], t, r))
        margin, _, t, r = max(scored, key=lambda x: (x[0], x[1]))
        alts = [c["setup"] for _, c in r[1:]]
        why = ("the only run of games that fits" if not alts else
               f"picked over {len(alts)} other run(s) that fit the score (on {', '.join(sorted(set(alts)))}): "
               "the players' characters match their other sets")
        take(t, r[0][1], why)

    # 3. Back-to-back sets between the same two players (#60: Grand Final + reset as one run of 6 games):
    # both sets' candidates are "the last N games before the report", so the first one reported takes the
    # games the second needs. Split the run by report order: the earlier-reported set gets the earlier games.
    for t in todo:
        if "pick" in t or not t["cands"] or cfg["sets"].get(t["id"], {}).get("games"):
            continue
        pair = {t["a"].get("entrantId"), t["b"].get("entrantId")}
        for t2 in todo:
            if t2 is t or "pick" not in t2 or {t2["a"].get("entrantId"), t2["b"].get("entrantId")} != pair:
                continue
            if cfg["sets"].get(t2["id"], {}).get("games"):
                continue
            first, second = sorted((t, t2), key=lambda x: x["s"]["completedAt"] or 0)
            n1 = first["a"]["score"] + first["b"]["score"]
            n2 = second["a"]["score"] + second["b"]["score"]
            paths = {g["path"] for g in t2["pick"]["games"]}
            blk = next((bl for bl in blocks if any(r["path"] in paths for r in bl)), None)
            if not blk or any(r["last_stock_quit"] for r in blk):
                continue
            done2 = datetime.fromtimestamp(second["s"]["completedAt"])
            usable = [r for r in blk if r["laptop_time"] <= done2 + timedelta(seconds=60)]
            if len(usable) < n1 + n2:
                continue
            g2, g1 = usable[-n2:], usable[-(n1 + n2):-n2]
            if any(r["path"] in used and r["path"] not in paths for r in g1 + g2):
                continue
            if not (score_fits(g1, first["a"]["score"], first["b"]["score"])
                    and score_fits(g2, second["a"]["score"], second["b"]["score"])):
                continue
            for x, games in ((first, g1), (second, g2)):
                x["pick"] = {"setup": blk[0]["setup"], "games": games, "handwarmers": [], "report_gap": 0,
                             "port_of": ports_for(games, x["a"], x["b"]), "score_ok": True}
                x["why"] = (f"played back to back with set {(second if x is first else first)['id']} (same players, "
                            "one run of games): split by report order, the earlier-reported set takes the earlier games")
            for g in g1 + g2:
                used.add(g["path"])
            break

    for t in todo:
        a, b = t["a"], t["b"]
        if t["dock_info"] and "pick" not in t:
            notes.append(f"{t['label']}: " + "; ".join(t["dock_info"]))
        if "pick" not in t:
            notes.append(f"{t['label']}: its {len(t['cands'])} candidate run(s) were all taken by other sets" if t["cands"]
                         else f"{t['label']}: no run of games on any setup fits the score before the report")
            continue
        c, s = t["pick"], t["s"]
        info = [f"matched: {t['why']}"] + t["dock_info"]
        if t["assigned_stream"] and c["setup"] != stream_setup:
            info.append(f"assigned to the stream on start.gg but played on {c['setup']}")
        if any(g["winner_port"] is None for g in c["games"]):
            info.append("a replay has no winner (cut off); counted toward the start.gg score")
        for n, g in enumerate(c["games"], start=1):
            if g["end_method"] == "no_contest" and g.get("quitter"):
                quitter = a if c["port_of"]["a"] == g["quitter"] else b
                winner = b if quitter is a else a
                qp = next((p for p in g["players"] if p["port"] == g["quitter"]), {})
                info.append(f"QUIT-OUT: game {n}, {quitter['name']} quit on their last stock "
                            f"({qp.get('final_percent') or 0:.0f}%) after {g['duration_s'] or 0:.0f} s; counted as {winner['name']}'s game")
                quit_outs.append({"tournament": cfg["tournament"], "set": t["id"], "round": s["fullRoundText"],
                                  "game": n, "player": quitter["name"], "entrantId": quitter.get("entrantId"),
                                  "opponent": winner["name"], "file": g["file"],
                                  "stocks_left": qp.get("final_stocks"), "percent": qp.get("final_percent"),
                                  "after_s": g["duration_s"]})
        for side, ent in (("a", a), ("b", b)):
            looks = sorted({f"{ch} ({col})" for ch, col in looks_on(c["games"], c["port_of"][side])})
            if len(looks) > 1:
                info.append(f"{ent['name']} played {', '.join(looks)}")
        planned.append({
            "id": t["id"], "setId": s["id"], "round": s["fullRoundText"], "a": a, "b": b,
            "on_stream": c["setup"] == stream_setup, "setup": c["setup"],
            "games": c["games"], "handwarmers": c["handwarmers"], "score_ok": c["score_ok"],
            "port_of": c["port_of"], "label": t["label"], "info": info,
        })
    planned.sort(key=lambda p: p["games"][0]["laptop_time"])
    return planned, notes, quit_outs


PLAYER_NOTES = os.path.join(ROOT, "player_notes.json")


def record_quit_outs(cfg, quit_outs):
    """Keep every counted last-stock quit-out in player_notes.json (project folder, all tournaments;
    this tournament's entries are replaced on each plan). Returns earlier tournaments' entries."""
    data = {"_note": "Players who quit out of tournament games (vod_cutter.py plan writes this). "
                     "A quit-out on the quitter's last stock in the middle of a set counts as the other player's game."}
    if os.path.isfile(PLAYER_NOTES):
        with open(PLAYER_NOTES, encoding="utf-8") as f:
            data = json.load(f)
    old = [q for q in data.get("quit_outs", []) if q.get("tournament") != cfg["tournament"]]
    data["quit_outs"] = old + quit_outs
    if quit_outs or os.path.isfile(PLAYER_NOTES):
        with open(PLAYER_NOTES, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return old


def player_look(ps, port):
    """character/color for an entrant from the set's games (most common)."""
    seen = {}
    for g in ps["games"]:
        for p in g["players"]:
            if p["port"] == port:
                k = char_color(p)
                seen[k] = seen.get(k, 0) + 1
    if not seen:
        return "", "neutral"
    return max(seen, key=seen.get)


# ---------------------------------------------------------------- plan

def make_plan(cfg):
    rec = cfg["recording"]
    rec_start = recording_start(rec)
    rec_len = probe_duration(rec)
    replays, errors = load_replays(cfg)
    sg = load_startgg(cfg)
    planned, notes, quit_outs = match_sets(cfg, sg, replays)
    quit_history = record_quit_outs(cfg, quit_outs)
    segs = []
    for n, ps in enumerate(planned, start=1):
        first, last = ps["games"][0], ps["games"][-1]
        t0 = (first["laptop_time"] - rec_start).total_seconds()
        t1 = (last["laptop_time"] - rec_start).total_seconds() + (last["duration_s"] or 0)
        mode = "stream" if ps["on_stream"] else "replay"
        flags = []
        if not ps["score_ok"]:
            flags.append("game count / winners don't match start.gg")
        if mode == "stream":
            if t0 < 0:
                flags.append(f"first game started {hms(-t0)} before the recording: game 1 is rebuilt from its "
                             "replay over the stream (webcam held on the first recorded frame until it starts)")
            if t1 > rec_len:
                flags.append("set runs past the end of the recording")
        elif not cfg["include_offstream"]:
            notes.append(f"{ps['label']}: off stream, include_offstream is false")
            continue
        seg = {
            "n": n, "id": ps["id"], "setId": ps["setId"], "round": ps["round"], "mode": mode, "setup": ps["setup"],
            "a": {**ps["a"], "port": ps["port_of"]["a"]}, "b": {**ps["b"], "port": ps["port_of"]["b"]},
            "games": [{"file": g["path"], "render_from": g.get("render_from"), "repaired": "repaired" in g["flags"],
                       "laptop_time": g["laptop_time"].isoformat(sep=" "),
                       "video_t": round((g["laptop_time"] - rec_start).total_seconds(), 2),
                       "duration_s": g["duration_s"], "stage": g["stage"], "winner_port": g["winner_port"],
                       "quit_out": g["end_method"] == "no_contest",
                       "players": [{"port": p["port"], "character": char_color(p)[0], "color": char_color(p)[1]}
                                   for p in g["players"]]} for g in ps["games"]],
            "handwarmers": [g["path"] for g in ps["handwarmers"]],
            "flags": flags,
            "info": ps.get("info", []),
        }
        for side in ("a", "b"):
            seg[side]["character"], seg[side]["color"] = player_look(ps, seg[side]["port"])
        if mode == "stream":
            seg["cut"] = [round(max(0.0, t0 - cfg["pad_before_s"]), 2),
                          round(min(rec_len, t1 + cfg["pad_after_s"]), 2)]
            seg["game1_from_replay"] = t0 < 0
            rg = cfg["sets"].get(ps["id"], {}).get("replay_games")
            if rg:
                seg["replay_games"] = list(range(1, len(ps["games"]) + 1)) if rg == "all" else sorted(rg)
                flags.append("game(s) " + ", ".join(map(str, seg["replay_games"]))
                             + " rebuilt from the replay over the stream (stream audio missing); webcam stays live")
        segs.append(seg)
    plan = {"tournament": sg["tournament"], "event": sg["event"], "recording": rec,
            "recording_start": rec_start.isoformat(sep=" "), "recording_length_s": rec_len,
            "clock_offset_s": cfg["clock_offset_s"], "segments": segs, "notes": notes,
            "quit_outs": quit_outs,
            # Earlier quit-outs by players in tonight's bracket (player_notes.json), for the review.
            "quit_history": [q for q in quit_history if q["player"].lower() in
                             {s[x]["name"].lower() for s in segs for x in ("a", "b")}],
            "unreadable_replays": errors}
    os.makedirs(cfg["_work"], exist_ok=True)
    with open(os.path.join(cfg["_out"], "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    write_review(cfg, plan, replays)
    return plan


def cell(t):
    """Table-safe text ("OAC | Hyraks" would split a markdown table column)."""
    return str(t).replace("|", "\\|")


def mmss(s):
    s = int(round(s or 0))
    return f"{s // 60}:{s % 60:02d}"


def offset_text(val):
    sec = clock_offset(val)
    ahead = "ahead of" if sec > 0 else "behind"
    sec = abs(sec)
    d, rest = divmod(int(round(sec)), 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    if d:
        return f"Wii date/time set wrong (about {d / 365.25:.1f} years {ahead.split()[0]}); lined up with the laptop clock"
    parts = [f"{h} h" if h else "", f"{m} min" if m else "", f"{s} s" if s or not (h or m) else ""]
    return f"{' '.join(p for p in parts if p)} {ahead} the laptop"


def why_left_out(r, segs):
    if any(p.get("type") == "cpu" for p in r["players"]):
        return "vs CPU"
    end = r["laptop_time"] + timedelta(seconds=r["duration_s"] or 0)
    nxt = [s for s in segs if s["setup"] == r["setup"]
           and 0 <= (datetime.fromisoformat(s["games"][0]["laptop_time"]) - end).total_seconds() <= 180]
    before = f", right before set {nxt[0]['id']}" if nxt else ""
    if r["end_method"] == "no_contest":
        return f"quit after {mmss(r['duration_s'])}{before}"
    if (r["duration_s"] or 0) < MIN_GAME_S:
        return f"under {MIN_GAME_S} s{before}"
    if "not_singles" in r["flags"]:
        return "not a 1v1"
    return "friendly (not part of any set)"


def write_review(cfg, plan, replays):
    segs = plan["segments"]
    L = [f"# VOD plan: {plan['tournament']} / {plan['event']}", "",
         "**How to read this:** times of day are the stream laptop's clock (each Wii's clock is corrected "
         "first). \"In the recording\" is the position inside the stream recording file (h:mm:ss from its start).", "",
         f"- Stream recording: `{os.path.basename(plan['recording'])}`, started {plan['recording_start'][11:19]}, "
         f"{hms(plan['recording_length_s'])} long",
         "- Wii clock corrections:"]
    L += [f"  - {k}: {offset_text(v)}" for k, v in plan["clock_offset_s"].items() if not k.startswith("_")]
    L += [f"- {n}" for n in plan["notes"] if n.startswith("dock setups")]
    qo, qh = plan.get("quit_outs", []), plan.get("quit_history", [])
    if qo or qh:
        L += ["", "## Quit-outs (flagged players)", "",
              "A quit-out on the quitter's last stock in the middle of a set counts as the other player's game. "
              "Every one is kept in `player_notes.json` (project folder).", ""]
        L += [f"- **{cell(q['player'])}** quit set {q['set']} ({cell(q['round'])}) game {q['game']} vs {cell(q['opponent'])} "
              f"on their last stock at {q.get('percent') or 0:.0f}%, after {mmss(q.get('after_s'))}" for q in qo]
        L += [f"- earlier: **{cell(q['player'])}** quit {q['tournament']} set {q['set']} game {q['game']} vs {cell(q['opponent'])}"
              for q in qh]
    L += ["", "## The VOD, in order", "",
          "| # | Set | Round | Match | Setup | Started | Games | Video comes from | Check |",
          "|---|---|---|---|---|---|---|---|---|"]
    for s in segs:
        a, b = s["a"], s["b"]
        match = f"{cell(a['name'])} ({a['character']}) **{a['score']}–{b['score']}** {cell(b['name'])} ({b['character']})"
        src = (f"stream recording, {hms(s['cut'][0])}–{hms(s['cut'][1])} in the recording" if s["mode"] == "stream"
               else "rendered from the replays")
        L.append(f"| {s['n']} | {s['id']} | {cell(s['round'])} | {match} | {cell(s['setup'])} | "
                 f"{s['games'][0]['laptop_time'][11:16]} | {len(s['games'])} | {src} | {cell('; '.join(s['flags']) or 'ok')} |")
    L += ["", "## Games per set", ""]
    for s in segs:
        a, b = s["a"], s["b"]
        first, last = s["games"][0], s["games"][-1]
        end = datetime.fromisoformat(last["laptop_time"]) + timedelta(seconds=last["duration_s"] or 0)
        L += [f"### {s['n']}. Set {s['id']}, {s['round']}: {a['name']} {a['score']}–{b['score']} {b['name']}", "",
              f"{s['setup']}, {first['laptop_time'][11:16]}–{end:%H:%M}, "
              + (f"cut from the stream recording at {hms(s['cut'][0])}–{hms(s['cut'][1])}" if s["mode"] == "stream"
                 else "rendered from the replays"), ""]
        L += [f"- {i}" for i in s.get("info", [])]
        L += ["", f"| Game | Started | Stage | {cell(a['name'])} | {cell(b['name'])} | Won by | Length |",
              "|---|---|---|---|---|---|---|"]
        for n, g in enumerate(s["games"], start=1):
            look = {p["port"]: f"{p['character']} ({p['color']})" for p in g["players"]}
            who = ("unknown (replay cut off)" if g["winner_port"] is None
                   else s["a" if g["winner_port"] == a["port"] else "b"]["name"])
            rep = " (replay repaired, see slp_repair.py)" if g.get("repaired") else ""
            if g.get("quit_out"):
                who += " (QUIT-OUT on last stock)"
            L.append(f"| {n} | {g['laptop_time'][11:19]} | {g['stage']}{rep} | {look.get(a['port'], '?')} | "
                     f"{look.get(b['port'], '?')} | {cell(who)} | {mmss(g['duration_s'])} |")
        for h in s["handwarmers"]:
            L.append(f"\nHandwarmer before the set, left out: `{os.path.basename(h)}`")
        L.append("")
    used = {g["file"] for s in segs for g in s["games"]} | {h for s in segs for h in s["handwarmers"]}
    unused = [r for r in replays if r["path"] not in used]
    L += ["## Left out", "", "### Sets", ""] + [f"- {cell(n)}" for n in plan["notes"] if not n.startswith("dock setups")]
    L += ["", "### Games that aren't part of any set", ""]
    for setup in sorted({r["setup"] for r in unused}):
        L += [f"**{setup}**", "", "| Started | Stage | Players | Why left out |", "|---|---|---|---|"]
        for r in sorted((r for r in unused if r["setup"] == setup), key=lambda r: r["laptop_time"]):
            players = " vs ".join(f"{p['character']}{' (CPU)' if p.get('type') == 'cpu' else ''}" for p in r["players"])
            L.append(f"| {r['laptop_time']:%H:%M:%S} | {r['stage']} | {players} | {why_left_out(r, segs)} |")
        L.append("")
    with open(os.path.join(cfg["_out"], "review.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- render

def audio_peak(path, start=None, length=None):
    args = [FFMPEG, "-hide_banner", "-nostats"]
    if start is not None:
        args += ["-ss", str(start), "-t", str(length)]
    args += ["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(args, capture_output=True, text=True).stderr
    mx = re.search(r"max_volume: (-?[\d.]+) dB", err)
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return (float(mx.group(1)) if mx else None, float(mean.group(1)) if mean else None)


# 12 Mbps = YouTube's recommendation for 1080p60 SDR uploads.
ENC = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak", "-b:v", "12M", "-maxrate", "18M",
       "-bufsize", "24M", "-pix_fmt", "yuv420p", "-r", "60",
       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
LIMIT = "alimiter=limit=0.966:level=disabled"  # about -0.3 dBFS


def game_panels(cfg, seg, work, cam_label):
    """One overlay panel per game: names/pictures/round from start.gg, stock icon = the character
    and color that player used in that game (replay), so counterpicks show correctly.
    Games with the same looks share a panel. Returns the panel path per game."""
    season = cfg.get("season")  # optional, e.g. "Halloween": theme overlay + round names
    round_text = vod_overlay.season_round(season, seg["round"]) if season else seg["round"]
    built, out = {}, []
    for g in seg["games"]:
        look = {p["port"]: (p["character"], p["color"]) for p in g["players"]}
        sides = []
        for side in ("a", "b"):
            ch, col = look.get(seg[side]["port"], (seg[side]["character"], seg[side]["color"]))
            sides.append({**seg[side], "character": ch, "color": col})
        key = (sides[0]["character"], sides[0]["color"], sides[1]["character"], sides[1]["color"])
        if key not in built:
            path = os.path.join(work, f"panel_{len(built) + 1}{'_stream' if not cam_label else ''}.png")
            vod_overlay.build_panel(path, sides[0], sides[1], round_text, cam_label=cam_label,
                                    panel_png=vod_overlay.season_panel(season))
            built[key] = path
        out.append(built[key])
    return out


def render_game_replay(cfg, g, raw, tries=3):
    """replay_render.render with retries: Dolphin sometimes freezes or closes mid-game (#57, #60 A game 3);
    a fresh start nearly always plays through."""
    import replay_render
    for n in range(1, tries + 1):
        try:
            return replay_render.render(g.get("render_from") or os.path.join(cfg["replays"], g["file"]), raw)
        except (RuntimeError, TimeoutError) as e:
            if n == tries:
                raise
            print(f"    replay render failed ({e}); retrying ({n + 1}/{tries})...", flush=True)
            try:
                os.remove(raw)
            except OSError:
                pass


PRE_GO_S = 123 / 60  # a replay (and its render) starts at frame -123, about 2 s before GO


def game1_replay_span(seg):
    """Game 1 of a stream set that the recording cut into: (recording time where the replay
    render starts (negative), length of the rebuilt part, recording time the stream takes over).
    video_t lines up with GO (Main Setup's clock is calibrated from the in-game timer)."""
    g = seg["games"][0]
    start = g["video_t"] - PRE_GO_S
    length = (g["duration_s"] or 0) + 1.0
    return start, length, start + length


def render_game1_over_stream(cfg, seg, work, panel, out, target_mean_db):
    """The recording started mid-game: game 1 from its replay in the game area, the stream
    underneath for the webcam (its first frame held until the recording starts), the live-style
    panel (see-through webcam box) on top. Audio is the replay's, matched to the stream."""
    import replay_render
    g = seg["games"][0]
    raw = os.path.join(work, "g1_raw.mp4")
    if not os.path.isfile(raw):
        print(f"    rendering game 1 from replay ({g['duration_s']:.0f} s of play; recording started mid-game)...")
        render_game_replay(cfg, g, raw)
    start, length, take_over = game1_replay_span(seg)
    hold = -start
    bg_len = max(take_over, 0.1)  # game 1 entirely before the recording: just hold frame 0
    _, mean = audio_peak(raw)
    gain = (target_mean_db - mean) if (mean is not None and target_mean_db is not None) else cfg["gain_db"]
    fc = (f"[1:v]trim=0:{bg_len:.3f},setpts=PTS-STARTPTS,tpad=start_duration={hold:.3f}:start_mode=clone,"
          f"fps=60,trim=0:{length:.3f},setpts=PTS-STARTPTS[bg];"
          f"[0:v]trim=0:{length:.3f},setpts=PTS-STARTPTS,scale={vod_overlay.GAME_W}:{vod_overlay.H}:flags=lanczos,setsar=1[g];"
          f"[bg][g]overlay={vod_overlay.GAME_X}:0:eof_action=repeat[bgg];"
          f"[bgg][2:v]overlay=0:0:shortest=1,format=yuv420p[v];"
          f"[0:a]atrim=0:{length:.3f},asetpts=PTS-STARTPTS,volume={gain:.1f}dB,{LIMIT}[a]")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", raw, "-t", f"{bg_len:.3f}", "-i", cfg["recording"],
                    "-loop", "1", "-t", f"{length:.3f}", "-i", panel,
                    "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *ENC, out], check=True)


def render_stream_set(cfg, seg, out, target_mean_db=None):
    if seg.get("game1_from_replay"):
        # Game 1 rebuilt from the replay, then the rest of the set from the recording; joined losslessly.
        work = os.path.join(cfg["_mwork"], f"set_{seg['id']}")
        os.makedirs(work, exist_ok=True)
        panels = game_panels(cfg, seg, work, cam_label=None)
        part1, part2 = os.path.join(work, "part1_game1.mp4"), os.path.join(work, "part2_stream.mp4")
        render_game1_over_stream(cfg, seg, work, panels[0], part1, target_mean_db)
        rest = {**seg, "game1_from_replay": False, "games": seg["games"][1:],
                "replay_games": [n - 1 for n in seg.get("replay_games") or [] if n > 1],
                "cut": [game1_replay_span(seg)[2], seg["cut"][1]]}
        render_stream_set(cfg, rest, part2)
        lst = os.path.join(work, "parts.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.writelines(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in (part1, part2))
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                        "-movflags", "+faststart", out], check=True)
        return
    a, b = seg["cut"]
    args = [FFMPEG, "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", cfg["recording"]]
    work = os.path.join(cfg["_mwork"], f"set_{seg['id']}")
    os.makedirs(work, exist_ok=True)
    fc, cur, idx = [], "0:v", 1
    # "replay_games" (vod_config sets.X): games whose picture and sound come from their replay, laid over
    # the stream's game area (webcam stays live). For stream audio dropouts (#60 E, G game 1).
    swap, mix = seg.get("replay_games") or [], []
    stream_audio = f"[0:a]volume={cfg['gain_db']}dB"
    if swap:
        import replay_render
    for n in swap:
        g = seg["games"][n - 1]
        raw = os.path.join(work, f"g{n}_raw.mp4")
        if not os.path.isfile(raw):
            print(f"    rendering game {n} from replay for the stream set ({g['duration_s']:.0f} s of play)...")
            render_game_replay(cfg, g, raw)
        off = max(0.0, g["video_t"] - PRE_GO_S - a)
        ln = (g["duration_s"] or 0) + 1.0
        _, mean = audio_peak(raw)
        gain = (target_mean_db - mean) if (mean is not None and target_mean_db is not None) else cfg["gain_db"]
        args += ["-i", raw]
        fc.append(f"[{idx}:v]trim=0:{ln:.3f},setpts=PTS-STARTPTS+{off:.3f}/TB,"
                  f"scale={vod_overlay.GAME_W}:{vod_overlay.H}:flags=lanczos,setsar=1[r{idx}]")
        fc.append(f"[{cur}][r{idx}]overlay={vod_overlay.GAME_X}:0:eof_action=pass:"
                  f"enable='between(t,{off:.3f},{off + ln:.3f})'[s{idx}]")
        fc.append(f"[{idx}:a]atrim=0:{ln:.3f},asetpts=PTS-STARTPTS,volume={gain:.1f}dB,"
                  f"adelay={int(off * 1000)}:all=1[ra{idx}]")
        stream_audio += f",volume=0:enable='between(t,{off:.3f},{off + ln:.3f})'"
        mix.append(f"[ra{idx}]")
        cur, idx = f"s{idx}", idx + 1
    if cfg["overlay_stream"]:
        # Rebuilt overlay over the live one (the live one can be late or show the wrong character/
        # color); the webcam box is see-through. Each game's panel from its start, game 1's from 0.
        panels = game_panels(cfg, seg, work, cam_label=None)
        starts = [0.0] + [max(0.0, g["video_t"] - a) for g in seg["games"][1:]] + [b - a + 1]
        for i, p in enumerate(panels):
            args += ["-loop", "1", "-i", p]
            fc.append(f"[{cur}][{idx}:v]overlay=0:0:shortest=1:"
                      f"enable='between(t,{starts[i]:.3f},{starts[i + 1]:.3f})'[o{i}]")
            cur, idx = f"o{i}", idx + 1
    fc.append(f"[{cur}]format=yuv420p[v]")
    if mix:
        fc.append(stream_audio + "[sa]")
        fc.append(f"[sa]{''.join(mix)}amix=inputs={len(mix) + 1}:normalize=0:duration=first,{LIMIT}[a]")
    else:
        fc.append(f"{stream_audio},{LIMIT}[a]")
    subprocess.run(args + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", *ENC, out], check=True)


def render_replay_set(cfg, seg, out, target_mean_db):
    import replay_render
    work = os.path.join(cfg["_mwork"], f"set_{seg['id']}")
    os.makedirs(work, exist_ok=True)
    panels = game_panels(cfg, seg, work, cam_label=("REPLAY", "off-stream setup"))
    parts = []
    for i, g in enumerate(seg["games"], start=1):
        raw = os.path.join(work, f"g{i}_raw.mp4")
        if not os.path.isfile(raw):
            print(f"    rendering game {i}/{len(seg['games'])} from replay ({g['duration_s']:.0f} s of play)...")
            render_game_replay(cfg, g, raw)
        comp = os.path.join(work, f"g{i}_overlay.mp4")
        if not os.path.isfile(comp):
            vod_overlay.composite_game(raw, panels[i - 1], comp)
        parts.append(comp)
    # Match loudness to the stream footage (game audio only, so bring the mean up to the stream's).
    _, mean = audio_peak(parts[0])
    gain = (target_mean_db - mean) if (mean is not None and target_mean_db is not None) else cfg["gain_db"]
    lst = os.path.join(work, "parts.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in parts)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-af", f"volume={gain:.1f}dB,{LIMIT}", *ENC, out], check=True)


def render_all(cfg, plan, only=None):
    out_sets = os.path.join(cfg["_media"], "sets")
    os.makedirs(out_sets, exist_ok=True)
    peak, mean = audio_peak(cfg["recording"])
    print(f"Recording audio: peak {peak} dB, mean {mean} dB; applying +{cfg['gain_db']} dB with a limiter at -0.3 dB.")
    target_mean = (mean + cfg["gain_db"]) if mean is not None else None
    files = []
    for seg in plan["segments"]:
        name = safe_name(f"{seg['n']:02d} - {seg['round']} - {seg['a']['name']} vs {seg['b']['name']}") + ".mp4"
        out = os.path.join(out_sets, name)
        files.append((seg, out))
        if only and seg["id"] not in only:
            continue
        print(f"  {name} ({seg['mode']})")
        if seg["mode"] == "stream":
            render_stream_set(cfg, seg, out, target_mean)
        else:
            render_replay_set(cfg, seg, out, target_mean)
    if only:
        return
    build_full_vods(cfg, plan)


def set_file(cfg, seg):
    name = safe_name(f"{seg['n']:02d} - {seg['round']} - {seg['a']['name']} vs {seg['b']['name']}") + ".mp4"
    return os.path.join(cfg["_media"], "sets", name)


def setup_order(cfg, plan):
    """Setups that have sets: the stream setup first, then by when their first set started."""
    first = {}
    for seg in plan["segments"]:
        first.setdefault(seg["setup"], seg["games"][0]["laptop_time"])
    return sorted(first, key=lambda k: (k != cfg["stream_setup"], first[k]))


def full_vod_path(cfg, setup):
    return os.path.join(cfg["_media"], safe_name(f"{cfg['title']} - {setup} Full VOD") + ".mp4")


def build_full_vods(cfg, plan):
    """One Full VOD per setup (user's choice from #57 on): that setup's set files back to back
    in play order, chapters per set. Stream copy, no re-encode."""
    for setup in setup_order(cfg, plan):
        segs = [seg for seg in plan["segments"] if seg["setup"] == setup]
        if len(segs) < 2:
            print(f"{setup}: only set {segs[0]['id']}, no Full VOD (its set upload is the whole thing)")
            continue
        files = [(seg, set_file(cfg, seg)) for seg in segs]
        missing =[os.path.basename(p) for _, p in files if not os.path.isfile(p)]
        if missing:
            print(f"{setup} Full VOD skipped, sets not rendered yet: {', '.join(missing)}")
            continue
        key = safe_name(setup).replace(" ", "_")
        lst = os.path.join(cfg["_work"], f"full_vod_{key}.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.writelines(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for _, p in files)
        meta, chapters, t = [";FFMETADATA1"], [], 0.0
        for seg, p in files:
            d = probe_duration(p)
            title = f"{seg['round']}: {seg['a']['name']} vs {seg['b']['name']}"
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}", f"END={int((t + d) * 1000)}",
                     f"title={title}"]
            chapters.append(f"{hms(t)} {title}")
            t += d
        meta_path = os.path.join(cfg["_work"], f"chapters_{key}.ffmeta")
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write("\n".join(meta) + "\n")
        full = full_vod_path(cfg, setup)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", meta_path,
                        "-map", "0", "-map_metadata", "1", "-c", "copy", "-movflags", "+faststart", full], check=True)
        with open(os.path.join(cfg["_out"], f"youtube_chapters - {safe_name(setup)}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(chapters) + "\n")
        print(f"{setup} Full VOD: {full} ({hms(t)}, {len(files)} sets)")


# ---------------------------------------------------------------- upload kit

DEFAULT_TITLE_FULL = "{tournament}: {setup} Full VOD"
DEFAULT_TITLE_SET = "{tournament}: {round} - {a} ({a_char}) vs {b} ({b_char})"
DEFAULT_TITLE_SET_SHORT = "{tournament}: {round} - {a} vs {b}"  # used when the long one is over 100 chars
CHAR_SHORT = {"Captain Falcon": "Falcon", "Mr. Game & Watch": "Game & Watch", "Doctor Mario": "Dr. Mario"}


def rclone_dirs(cfg, path):
    """Folders under a gdrive: path as {name: share link}. Successful lookups are cached in
    work/drive_links.json and reused if rclone fails (e.g. its Google sign-in expired)."""
    cache_p = os.path.join(cfg["_work"], "drive_links.json")
    try:
        cache = json.load(open(cache_p, encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    rclone = os.path.join(ROOT, "tools", "rclone", "rclone.exe")
    r = subprocess.run([rclone, "lsjson", f"gdrive:{path}", "--dirs-only"], capture_output=True, text=True)
    try:
        if r.returncode:
            raise ValueError(r.stderr)
        found = {d["Name"]: f"https://drive.google.com/drive/folders/{d['ID']}?usp=sharing" for d in json.loads(r.stdout or "[]")}
    except ValueError as e:
        if path in cache:
            print(f"  rclone failed, using cached Drive links for '{path}'")
            return cache[path]
        hint = ' (Google sign-in expired: run "tools/rclone/rclone.exe config reconnect gdrive:")' if "invalid_grant" in str(e) else ""
        raise SystemExit(f"Can't list Drive folder '{path}' with rclone{hint}. Upload text not written.")
    cache[path] = found
    os.makedirs(cfg["_work"], exist_ok=True)
    with open(cache_p, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)
    return found


def drive_folder_link(cfg):
    name = cfg.get("drive_folder", cfg["title"])
    return rclone_dirs(cfg, "").get(name, f"(Drive folder '{name}' not found)")


def drive_subfolder_links(cfg):
    """Share links of the per-setup folders inside the tournament's Drive folder."""
    return rclone_dirs(cfg, cfg.get("drive_folder", cfg["title"]))


def event_slug(cfg):
    t = gql("""query($s:String!){tournament(slug:$s){events{slug videogame{id} numEntrants}}}""",
            {"s": cfg["tournament"]})["tournament"]
    ev = sorted([e for e in t["events"] if e["videogame"]["id"] == MELEE_ID],
                key=lambda e: e["numEntrants"] or 0, reverse=True)[0]
    return ev["slug"]  # "tournament/protocol-56/event/melee-singles"


def game_chapters(cfg, seg, set_file):
    """Per-game chapter times inside a per-set file."""
    if seg["mode"] == "stream":
        starts = [g["video_t"] - seg["cut"][0] for g in seg["games"]]
        if seg.get("game1_from_replay"):  # rebuilt game 1 first, then the recording from take_over
            _, length, take_over = game1_replay_span(seg)
            starts = [0.0] + [length + g["video_t"] - take_over for g in seg["games"][1:]]
    else:
        work = os.path.join(cfg["_mwork"], f"set_{seg['id']}")
        starts, t = [], 0.0
        for i in range(1, len(seg["games"]) + 1):
            starts.append(t)
            t += probe_duration(os.path.join(work, f"g{i}_overlay.mp4"))
    rows = []
    for i, (g, t) in enumerate(zip(seg["games"], starts), start=1):
        rows.append((0.0 if i == 1 else max(0.0, t), f"Game {i}: {g['stage']}"))
    return rows if len(rows) >= 3 else []  # YouTube needs at least 3 chapters


LS_LABEL = "Lucky Stats replays and analysis"


def ls_link(cfg, seg):
    """Lucky Stats page of a set. vod_config "luckystats": {"<set letter or start.gg set id>": "<Lucky Stats
    set id or URL>", "_event": "<event URL>"} (Lucky Stats numbers its sets itself, so the links are
    collected after the zips are uploaded)."""
    ls = cfg.get("luckystats") or {}
    v = ls.get(seg["id"]) or ls.get(str(seg["setId"])) or ls.get("_event")  # no set link: the event page
    if not v:
        return None
    v = str(v)
    return v if v.startswith("http") else f"https://luckystats.gg/set/{v}"


def write_kit(cfg, plan):
    out_sets = os.path.join(cfg["_media"], "sets")
    kit = os.path.join(cfg["_out"], "upload_kit")
    os.makedirs(kit, exist_ok=True)
    tname = plan["tournament"]
    replays = drive_folder_link(cfg)
    ev = event_slug(cfg)
    bracket = f"https://www.start.gg/{ev}"
    full_tpl = cfg.get("title_full", DEFAULT_TITLE_FULL)
    set_tpl = cfg.get("title_set", DEFAULT_TITLE_SET)
    entries, chapters, t = [], [], 0.0
    for seg in plan["segments"]:
        fname = safe_name(f"{seg['n']:02d} - {seg['round']} - {seg['a']['name']} vs {seg['b']['name']}") + ".mp4"
        path = os.path.join(out_sets, fname)
        if not os.path.isfile(path):
            print(f"  kit: {fname} not rendered yet, skipped")
            continue
        d = probe_duration(path)
        chapters.append(f"{hms(t)} {seg['round']}: {seg['a']['name']} vs {seg['b']['name']}")
        t += d
        f = {"tournament": tname, "round": seg["round"], "a": seg["a"]["name"], "b": seg["b"]["name"],
             "a_char": CHAR_SHORT.get(seg["a"]["character"], seg["a"]["character"]),
             "b_char": CHAR_SHORT.get(seg["b"]["character"], seg["b"]["character"])}
        title = set_tpl.format(**f)
        room = 100 - (len(" Melee") if cfg.get("account", "sova") else 0)  # the uploader adds " Melee" on SoVA
        if len(title) > room:
            title = cfg.get("title_set_short", DEFAULT_TITLE_SET_SHORT).format(**f)[:room]
        desc = [f"Replays: {replays}", f"Bracket: {bracket}/set/{seg['setId']}"]
        if ls_link(cfg, seg):
            desc.append(f"{LS_LABEL}: {ls_link(cfg, seg)}")
        gch = game_chapters(cfg, seg, path)
        if gch:
            desc += [""] + [f"{hms(ct)} {label}" for ct, label in gch]
        entries.append((fname, title, desc, path))
    # One Full VOD per setup, listed first (stream setup on top); replays link that setup's folder.
    sub = drive_subfolder_links(cfg)
    fulls = []
    for setup in setup_order(cfg, plan):
        full_path = full_vod_path(cfg, setup)
        if not os.path.isfile(full_path):
            continue
        ch, t = [], 0.0
        for seg in (x for x in plan["segments"] if x["setup"] == setup):
            ch.append(f"{hms(t)} {seg['round']}: {seg['a']['name']} vs {seg['b']['name']}")
            t += probe_duration(set_file(cfg, seg))
        full_desc = [f"Replays: {sub.get(setup, replays)}", f"Bracket: {bracket}"]
        if (cfg.get("luckystats") or {}).get("_event"):
            full_desc.append(f"{LS_LABEL}: {cfg['luckystats']['_event']}")
        if len(ch) >= 3:
            full_desc += [""] + ch
        fulls.append((os.path.basename(full_path), full_tpl.format(tournament=tname, setup=setup), full_desc, full_path))
    entries[:0] = fulls
    md = [f"# Upload kit: {tname}", "",
          "Category: Gaming. Paste each title and description into YouTube Studio.", ""]
    for fname, title, desc, path in entries:
        txt = os.path.join(kit, os.path.splitext(fname)[0] + ".txt")
        with open(txt, "w", encoding="utf-8") as fh:
            # Labels sit on their own "=====" lines so they don't get copied into YouTube
            # (#56's descriptions went up starting with "DESCRIPTION:").
            fh.write(f"FILE: {path}\n\n===== TITLE (copy the next line) =====\n{title}\n\n"
                     "===== DESCRIPTION (copy everything below this line) =====\n" + "\n".join(desc) + "\n")
        md += [f"## {title}", "", f"File: `{path}`", "", "```", *desc, "```", ""]
    with open(os.path.join(kit, "upload_kit.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    # Same list for youtube_upload.py (upload order = kit order: Full VODs first, then sets in play order).
    pl_desc = [f"Bracket: {bracket}", f"Replays: {replays}"]
    if (cfg.get("luckystats") or {}).get("_event"):
        pl_desc.append(f"{LS_LABEL}: {cfg['luckystats']['_event']}")
    with open(os.path.join(kit, "upload_kit.json"), "w", encoding="utf-8") as fh:
        # All Protocol uploads (Melee and Ultimate) go to the SoVA channel (user, 2026-11-10); "account": null = main channel.
        json.dump({"tournament": tname, "playlist": tname, "playlist_description": "\n".join(pl_desc),
                   "game": "Melee", "account": cfg.get("account", "sova"), "videos": [
            {"file": path, "title": title, "description": "\n".join(desc)} for _, title, desc, path in entries]},
            fh, indent=2, ensure_ascii=False)
    print(f"Upload kit: {kit} ({len(entries)} videos)")


def main():
    ap = argparse.ArgumentParser(description="Cut the tournament VOD.")
    ap.add_argument("command", choices=["plan", "render", "full", "kit"])
    ap.add_argument("config")
    ap.add_argument("--only", help="comma-separated set identifiers to render (skips the full VOD)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config(a.config)
    plan = make_plan(cfg)
    print(f"Plan: {len(plan['segments'])} sets -> {os.path.join(cfg['_out'], 'review.md')}")
    for s in plan["segments"]:
        where = f"{hms(s['cut'][0])}-{hms(s['cut'][1])}" if s["mode"] == "stream" else f"replays ({s['setup']})"
        print(f"  {s['n']}. {s['id']} {s['round']}: {s['a']['name']} {s['a']['score']}-{s['b']['score']} "
              f"{s['b']['name']}  [{where}] {'; '.join(s['flags'])}")
    if a.command == "render":
        render_all(cfg, plan, set(a.only.split(",")) if a.only else None)
    if a.command == "full":
        build_full_vods(cfg, plan)
    if a.command in ("render", "full", "kit"):
        write_kit(cfg, plan)


if __name__ == "__main__":
    main()
