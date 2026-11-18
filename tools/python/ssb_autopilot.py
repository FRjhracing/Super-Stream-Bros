#!/usr/bin/env python3
"""
ssb_autopilot.py - Super Stream Bros hands-off Melee pipeline (no AI agent needed).

    python tools\\python\\ssb_autopilot.py <N>                  plan + checks; render/kit/Lucky Stats only if confident
    python tools\\python\\ssb_autopilot.py <N> --upload         ... and upload to YouTube when it gets that far
    python tools\\python\\ssb_autopilot.py <N> --plan-only      stop after the plan + checks (nothing rendered)
    python tools\\python\\ssb_autopilot.py <N> --offsets-only   only estimate the Wii clock offsets and print them

What it does for Protocol #N (the SSD "Project Storage" must be plugged in):
 1. Finds the stream recording and the Melee dock's setups.jsonl in <SSD>\\MeleeRecordings\\Protocol-N\\
    (the stream PC's handoff puts them there), and the replays in <SSD>\\Protocol VOD\\Melee\\Protocol #N\\replays\\
    (slippi_uploader.py puts them there; plugging in the flash drives stays a human job).
 2. Writes vod_config.json from last week's (stream setup, channel, titles...) unless one exists. Values a person
    already put in an existing config are kept; it only fills what is missing.
 3. Estimates every setup's Wii clock offset from the dock windows (any error size, wrong year included), and
    calibrates the stream setup to the frame by matching one game's replay audio against the stream audio.
 4. Maps dock setup names it can't match by name (e.g. renamed mid-night) to replay folders from where their
    sets were found.
 5. Finds stream audio dropouts and rebuilds those games' picture + sound from the replays ("replay_games").
 6. Runs vod_cutter.py plan, then checks it. Anything a human must decide (a set with no fitting games, a score
    the replays disagree with, a doubtful clock, an unreadable replay, a dock/replay disagreement) goes into
    NEEDS_REVIEW.md in the tournament folder and the run stops there (exit code 2) - the "review folder" step.
 7. Confident: Lucky Stats export + zips, render, upload kit, optional YouTube upload + link fixes.

Never writes to replays or recordings. Stdlib only. See the Super Stream Bros guide, "AI vs no AI".
"""
import argparse
import array
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slippi_scan  # noqa: E402
import vod_cutter as vc  # noqa: E402

PY = sys.executable
CODE = os.path.dirname(os.path.abspath(__file__))
SLACK_S = 30            # a game counts as inside a dock window with this much slack each side
MIN_FIT_GAMES = 2       # a dock window "explained" by an offset holds at least this many games
ENV_HZ = 50             # audio envelope rate for the stream calibration
KEEP_KEYS = ("stream_setup", "stream_name", "overlay_stream", "account", "pad_before_s", "pad_after_s",
             "gain_db", "include_offstream", "title_full", "title_set", "title_set_short", "dock_setups", "tags")


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- inputs / config

def find_inputs(ssd, n):
    rec_dir = None
    for name in (f"Protocol-{n}", f"Protocol #{n}", f"protocol-{n}"):
        p = os.path.join(ssd, "MeleeRecordings", name)
        if os.path.isdir(p):
            rec_dir = p
            break
    if not rec_dir:
        raise SystemExit(f"No {ssd}MeleeRecordings\\Protocol-{n}\\ (run the stream PC handoff first).")
    vids = [os.path.join(rec_dir, f) for f in os.listdir(rec_dir)
            if f.lower().endswith(".mp4") and re.match(r"\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}", f)]
    if not vids:
        raise SystemExit(f"No OBS recording (YYYY-MM-DD HH-MM-SS.mp4) in {rec_dir}.")
    if len(vids) > 1:
        log(f"  {len(vids)} recordings found; using the largest (the cutter takes one recording per night).")
    rec = max(vids, key=os.path.getsize)
    dock = None
    for root, _, files in os.walk(rec_dir):
        if "setups.jsonl" in files:
            dock = root
            break
    return rec_dir, rec, dock


def previous_config(ssd, n):
    base = os.path.join(ssd, "Protocol VOD", "Melee")
    best = None
    for d in os.listdir(base) if os.path.isdir(base) else []:
        m = re.fullmatch(r"Protocol #(\d+)", d)
        if m and int(m.group(1)) < n and os.path.isfile(os.path.join(base, d, "vod_config.json")):
            if not best or int(m.group(1)) > best[0]:
                best = (int(m.group(1)), os.path.join(base, d, "vod_config.json"))
    return best[1] if best else None


def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def prepare_config(ssd, n, tdir, rec, dock_src):
    path = os.path.join(tdir, "vod_config.json")
    cfg = read_json(path) if os.path.isfile(path) else {}
    fresh = not cfg
    if fresh:
        prev = previous_config(ssd, n)
        if prev:
            old = read_json(prev)
            cfg.update({k: v for k, v in old.items() if k in KEEP_KEYS})
            log(f"  new vod_config.json from {prev}")
        cfg.setdefault("stream_setup", "Main Setup")
    rel = os.path.relpath(rec, ssd).replace("\\", "/")
    cfg.setdefault("tournament", f"protocol-{n}")
    cfg.setdefault("title", f"PROTOCOL #{n}")
    cfg.setdefault("recording", "{ssd}/" + rel)
    cfg.setdefault("replays", "replays")
    cfg.setdefault("drive_folder", f"Protocol #{n}")
    cfg.setdefault("clock_offset_s", {})
    cfg.setdefault("sets", {})
    if dock_src:
        ddir = os.path.join(tdir, "dock")
        os.makedirs(ddir, exist_ok=True)
        for f in ("setups.jsonl", "setups.csv", "Setup times.txt"):
            src, dst = os.path.join(dock_src, f), os.path.join(ddir, f)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
        cfg.setdefault("dock_log", "dock/setups.jsonl")
    write_json(path, cfg)
    return path, cfg


# ---------------------------------------------------------------- clock offsets

def dock_windows(cfg_path):
    """Per replay folder: the dock's (start, end) windows on the laptop clock, plus unmapped dock names."""
    cfg = vc.load_config(cfg_path)
    setups = sorted(d for d in os.listdir(cfg["replays"]) if os.path.isdir(os.path.join(cfg["replays"], d)))
    sets, setup_map = vc.load_dock(cfg, setups)
    win = {}
    for sid, segs in sets.items():
        for s in segs:
            if s["setup"] and not s["zero"] and s["t1"] and s["t1"] > s["t0"]:
                win.setdefault(s["setup"], []).append((s["t0"], s["t1"], sid))
    unmapped = sorted(k for k, v in setup_map.items() if not v)
    return cfg, setups, win, unmapped, sets


def startgg_windows(cfg):
    sg = vc.load_startgg(cfg)
    out = []
    for s in sg["sets"]:
        if s.get("state") == 3 and s.get("startedAt") and s.get("completedAt") and s["completedAt"] - s["startedAt"] > 120:
            out.append((datetime.fromtimestamp(s["startedAt"]), datetime.fromtimestamp(s["completedAt"]), s["identifier"]))
    return out


def fit_count(games, windows, off):
    inside, explained = 0, set()
    for t, dur in games:
        a = t - timedelta(seconds=off)
        b = a + timedelta(seconds=dur)
        for w0, w1, sid in windows:
            if a >= w0 - timedelta(seconds=SLACK_S) and b <= w1 + timedelta(seconds=SLACK_S):
                inside += 1
                explained.add((w0, sid))
                break
    return inside, explained


def estimate_offset(games, windows):
    """Wii-minus-laptop seconds that put the most games inside the windows. Coarse candidates come from
    every game/window pair (so a wrong date or year is found too), then a 5 s sweep around the best."""
    if not games or not windows:
        return None
    coarse = {0}
    for t, _ in games:
        for w0, _, _ in windows:
            coarse.add(int((t - w0).total_seconds() // 60) * 60)
    scored = sorted(((fit_count(games, windows, c)[0], c) for c in coarse), reverse=True)
    best = None
    for _, c in scored[:6]:
        for off in range(c - 900, c + 901, 5):
            k = fit_count(games, windows, off)[0]
            if not best or k > best[0]:
                best = (k, [off])
            elif k == best[0]:
                best[1].append(off)
    top, offs = best
    # Contiguous range around the best offsets nearest the first one; other clusters = ambiguity.
    offs.sort()
    clusters, cur = [], [offs[0]]
    for o in offs[1:]:
        if o - cur[-1] <= 10:
            cur.append(o)
        else:
            clusters.append(cur)
            cur = [o]
    clusters.append(cur)
    main = max(clusters, key=len)
    off = (main[0] + main[-1]) // 2
    explained = fit_count(games, windows, off)[1]
    rivals = [c for c in clusters if c is not main and abs(c[0] - main[0]) > 300]
    return {"offset": off, "range": [main[0], main[-1]], "inside": top, "games": len(games),
            "windows": len(windows), "explained": len({w for w, _ in explained}), "rivals": len(rivals)}


def counted_games(cfg_path):
    cfg = vc.load_config(cfg_path)
    cfg["clock_offset_s"] = {}
    rows, errors = vc.load_replays(cfg)
    by = {}
    for r in rows:
        if r["counted"]:
            by.setdefault(r["setup"], []).append((r["wii_time"], r["duration_s"] or 0))
    return by, rows, errors


def estimate_all(cfg_path, stream_setup):
    cfg, setups, win, unmapped, _ = dock_windows(cfg_path)
    by, _, _ = counted_games(cfg_path)
    sg_win = None
    res = {}
    for s in setups:
        basis, w = "dock", win.get(s, [])
        if not w:
            if sg_win is None:
                sg_win = startgg_windows(cfg)
            basis, w = "start.gg times (no dock windows for this setup)", sg_win
        e = estimate_offset(by.get(s, []), w)
        if not e:
            res[s] = {"offset": 0, "confidence": "low", "basis": basis, "why": "no games or no windows"}
            continue
        e["basis"] = basis
        width = e["range"][1] - e["range"][0]
        ratio = e["explained"] / max(1, e["windows"]) if basis == "dock" else e["inside"] / max(1, e["games"])
        if basis == "dock" and ratio >= 0.6 and not e["rivals"] and width <= 300:
            e["confidence"] = "high"
        elif ratio >= 0.4 and not e["rivals"]:
            e["confidence"] = "medium"
        else:
            e["confidence"] = "low"
        e["why"] = (f"{e['inside']}/{e['games']} games inside {e['explained']}/{e['windows']} windows; "
                    f"fits {e['range'][0]}..{e['range'][1]} s" + (f"; {e['rivals']} other offset(s) fit as well" if e["rivals"] else ""))
        res[s] = e
    return res, unmapped


# ---------------------------------------------------------------- stream calibration (audio)

def envelope(path, start, length, hz=ENV_HZ):
    """Loudness onsets (rising edges of a log-energy envelope) at `hz`, from ffmpeg-decoded mono audio."""
    rate = 4000
    args = [vc.FFMPEG, "-hide_banner", "-loglevel", "error"]
    if start is not None:
        args += ["-ss", f"{max(0.0, start):.3f}"]
    args += ["-i", path, "-t", f"{length:.3f}", "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    raw = subprocess.run(args, capture_output=True).stdout
    a = array.array("h")
    a.frombytes(raw[: len(raw) // 2 * 2])
    step = rate // hz
    import math
    env = []
    for i in range(0, len(a) - step + 1, step):
        blk = a[i:i + step]
        env.append(math.log10(1 + sum(x * x for x in blk) / step))
    on = [0.0] + [max(0.0, env[i] - env[i - 1]) for i in range(1, len(env))]
    m = sum(on) / len(on) if on else 0
    return [x - m for x in on]


def xcorr(tpl, sig):
    import math
    nt = len(tpl)
    tn = math.sqrt(sum(x * x for x in tpl)) or 1
    out = []
    for lag in range(0, len(sig) - nt + 1):
        seg = sig[lag:lag + nt]
        sn = math.sqrt(sum(x * x for x in seg)) or 1
        out.append(sum(map(float.__mul__, tpl, seg)) / (tn * sn))
    return out


def calibrate_stream(cfg_path, est_offset, stream_setup, silences, work):
    """Fine offset for the stream setup: render one short stream game from its replay and find its audio in the
    recording. Returns (offset in the cutter's convention (video_t = GO), note) or (None, why)."""
    cfg = vc.load_config(cfg_path)
    cfg["clock_offset_s"] = {stream_setup: est_offset}
    rows, _ = vc.load_replays(cfg)
    rec_start = vc.recording_start(cfg["recording"])
    rec_len = vc.probe_duration(cfg["recording"])
    cands = []
    for r in rows:
        if r["setup"] != stream_setup or not r["counted"]:
            continue
        vt = (r["laptop_time"] - rec_start).total_seconds()
        dur = r["duration_s"] or 0
        if 90 <= vt and vt + dur + 120 < rec_len and 50 <= dur <= 240 and not any(a < vt + dur and vt - 5 < b for a, b in silences):
            cands.append((dur, vt, r))
    if not cands:
        return None, "no stream game with clean audio to calibrate on"
    tried, found = [], []
    for dur, vt, r in sorted(cands, key=lambda c: c[0])[:4]:
        raw = os.path.join(work, "calib_" + os.path.splitext(r["file"])[0] + ".mp4")
        if not os.path.isfile(raw):
            log(f"  calibrating {stream_setup} on {r['file']} ({dur:.0f} s game, rendering its replay)...")
            vc.render_game_replay(cfg, {"file": r["path"], "render_from": r.get("render_from")}, raw)
        tlen = min(dur, 75.0)
        tpl = envelope(raw, 0, tlen)
        search0 = vt - vc.PRE_GO_S - 75
        sig = envelope(cfg["recording"], search0, tlen + 150)
        cc = xcorr(tpl, sig)
        if not cc:
            continue
        best = max(range(len(cc)), key=cc.__getitem__)
        second = max((c for i, c in enumerate(cc) if abs(i - best) > ENV_HZ), default=0)
        peak, ratio = cc[best], (cc[best] / second if second > 0 else 9.9)
        start_in_rec = search0 + best / ENV_HZ               # recording time of the replay's frame -123
        true_off = (r["wii_time"] - (rec_start + timedelta(seconds=start_in_rec))).total_seconds()
        conv = round(true_off - vc.PRE_GO_S, 1)              # cutter convention: video_t = GO
        tried.append(f"{r['file']}: {conv} s (match {peak:.2f}, {ratio:.2f}x the next best)")
        log(f"    {tried[-1]}")
        if ratio >= 1.5:
            found.append((conv, ratio, r["file"]))
        # Accept when two games agree (the webcam mic and commentary make one match alone unreliable).
        for i, x in enumerate(found):
            for y in found[i + 1:]:
                if abs(x[0] - y[0]) <= 0.3:
                    return round((x[0] + y[0]) / 2, 1), f"audio match on {x[2]} and {y[2]} ({x[0]} / {y[0]} s)"
    return None, "audio matches didn't agree (" + "; ".join(tried) + ")"


# ---------------------------------------------------------------- stream audio dropouts

def silences(rec, min_s=3.0):
    err = subprocess.run([vc.FFMPEG, "-hide_banner", "-nostats", "-i", rec, "-vn", "-af",
                          f"silencedetect=n=-70dB:d={min_s}", "-f", "null", "-"], capture_output=True, text=True).stderr
    out, start = [], None
    for line in err.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: (-?[\d.]+)", line)
        if m and start is not None:
            out.append((max(0.0, start), float(m.group(1))))
            start = None
    if start is not None:
        out.append((start, vc.probe_duration(rec)))
    return out


def dropout_games(plan, sil):
    """{set id: [game numbers]} for stream games whose sound is (partly) digital silence."""
    out = {}
    for s in plan["segments"]:
        if s["mode"] != "stream":
            continue
        for n, g in enumerate(s["games"], start=1):
            a, b = g["video_t"] - vc.PRE_GO_S, g["video_t"] + (g["duration_s"] or 0)
            if any(min(b, y) - max(a, x) > 2 for x, y in sil):
                out.setdefault(s["id"], []).append(n)
    return out


# ---------------------------------------------------------------- plan + checks

def run(cmd, logfile=None):
    log("  $ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if logfile:
        with open(logfile, "w", encoding="utf-8") as f:
            p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    else:
        p = subprocess.run(cmd)
    if p.returncode:
        raise SystemExit(f"Step failed (exit {p.returncode}): {' '.join(cmd)}" + (f" - see {logfile}" if logfile else ""))


def plan(cfg_path):
    run([PY, os.path.join(CODE, "vod_cutter.py"), "plan", cfg_path])
    return read_json(os.path.join(os.path.dirname(cfg_path), "plan.json"))


def automap_dock(cfg_path, unmapped, dock_sets, p):
    """Dock names with no matching replay folder -> the folder where most of their sets were found."""
    cfg = read_json(cfg_path)
    where = {s["id"]: s["setup"] for s in p["segments"]}
    added = {}
    for name in unmapped:
        votes = {}
        for sid, segs in dock_sets.items():
            if any(x["dock_setup"] == name for x in segs) and sid in where:
                votes[where[sid]] = votes.get(where[sid], 0) + 1
        if votes:
            folder = max(votes, key=votes.get)
            added[name] = folder
    if added:
        cfg.setdefault("dock_setups", {}).update(added)
        cfg["dock_setups"]["_autopilot"] = "names matched to replay folders from where their sets were found"
        write_json(cfg_path, cfg)
    return added


def check(p, offsets, stream_cal):
    """(blocking, advisory) lists for NEEDS_REVIEW.md."""
    block, adv = [], []
    for n in p["notes"]:
        if "no run of games" in n or "all taken by other sets" in n:
            block.append(f"Set missing from the plan: {n}. Usual causes: a wrong clock offset for its setup, a "
                         "replay missing from the flash drive, or a wrong score on start.gg. Fix: correct the offset or "
                         'add "sets": {"<letter>": {"games": [...], "score": [a, b]}} in vod_config.json.')
        elif "NOT FOUND" in n:
            block.append(f"{n}")
    for e in p.get("unreadable_replays") or []:
        block.append(f"Unreadable replay: {e} (see slp_repair.py and \"replay_repairs\" in the guide).")
    for s in p["segments"]:
        lab = f"{s['id']} {s['round']}: {s['a']['name']} {s['a']['score']}-{s['b']['score']} {s['b']['name']}"
        for f in s["flags"]:
            if f.startswith("game count"):
                block.append(f"{lab}: {f}.")
            elif f.startswith("set runs past"):
                adv.append(f"{lab}: {f} (the video ends where the recording ends).")
        for i in s.get("info", []):
            if "check it" in i:
                block.append(f"{lab}: {i}.")
            elif i.startswith("matched: picked over"):
                adv.append(f"{lab}: {i[9:]} - watch its first game if the players' characters look unusual.")
            elif i.startswith("QUIT-OUT"):
                adv.append(f"{lab}: {i}.")
    for s, e in offsets.items():
        sets_here = [x for x in p["segments"] if x["setup"] == s]
        if e["confidence"] == "low" and sets_here:
            block.append(f"Clock offset for {s} is doubtful ({e['why']}; basis: {e['basis']}). {len(sets_here)} set(s) use "
                         "it. Check one of its sets' characters against what was played, or set the offset by hand.")
        elif e["confidence"] == "medium" and sets_here:
            adv.append(f"Clock offset for {s}: medium confidence ({e['why']}).")
    if stream_cal:
        adv.append(stream_cal)
    return block, adv


def write_needs_review(tdir, block, adv, offsets):
    path = os.path.join(tdir, "NEEDS_REVIEW.md")
    head = (["# Needs review (autopilot stopped before rendering)", "",
             f"Written {datetime.now():%Y-%m-%d %H:%M}. Fix the items below in `vod_config.json` (or on start.gg), "
             "then run the autopilot again: it keeps your edits. `review.md` has the full plan.", "",
             "## Must fix", ""] + [f"- {b}" for b in block] if block else
            ["# Autopilot notes (nothing blocking; it went on to render)", "",
             f"Written {datetime.now():%Y-%m-%d %H:%M}. `review.md` has the full plan."])
    lines = head + ["", "## Worth a look (not blocking)", ""] + \
            [f"- {a}" for a in adv] + ["", "## Clock offsets used", "",
                                        "| Setup | Offset (s, Wii ahead) | Confidence | Basis |", "|---|---|---|---|"] + \
            [f"| {s} | {e.get('offset')} | {e.get('confidence')} | {e.get('why', '')} |" for s, e in offsets.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def lucky_stats(tdir, n):
    out = os.path.join(vc.ROOT, "LuckyStats", f"Protocol #{n}")
    sets_dir, zips = os.path.join(out, "sets"), os.path.join(out, "zips")
    run([PY, os.path.join(CODE, "luckystats_export.py"), os.path.join(tdir, "plan.json"),
         os.path.join(tdir, "replays"), sets_dir])
    os.makedirs(zips, exist_ok=True)
    k = 0
    for d in sorted(os.listdir(sets_dir)):
        src = os.path.join(sets_dir, d)
        z = os.path.join(zips, d + ".zip")
        if os.path.isdir(src) and not d.endswith(".partial") and not os.path.exists(z):
            with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(os.listdir(src)):
                    zf.write(os.path.join(src, f), f)  # files at the zip root (Lucky Stats' upload format)
            k += 1
    log(f"  Lucky Stats: {k} new zip(s) in {zips} (upload them on luckystats.gg; that step has no API)")


# ---------------------------------------------------------------- main

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Hands-off Melee pipeline for Protocol #N.")
    ap.add_argument("number", type=int)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--offsets-only", action="store_true")
    ap.add_argument("--upload", action="store_true", help="upload to YouTube (SoVA) after rendering")
    ap.add_argument("--keep-offsets", action="store_true", help="use the offsets already in vod_config.json")
    ap.add_argument("--folder", help="tournament folder (default <SSD>\\Protocol VOD\\Melee\\Protocol #N)")
    a = ap.parse_args()
    n = a.number
    ssd = vc.find_volume("Project Storage")
    if not ssd:
        raise SystemExit('Plug in the external SSD "Project Storage".')
    tdir = a.folder or os.path.join(ssd, "Protocol VOD", "Melee", f"Protocol #{n}")
    log(f"Super Stream Bros autopilot: Protocol #{n} -> {tdir}")
    _, rec, dock_src = find_inputs(ssd, n)
    log(f"  recording {rec}" + ("" if dock_src else "  (no dock setups.jsonl: offsets fall back to start.gg times)"))
    if not os.path.isdir(os.path.join(tdir, "replays")) or not os.listdir(os.path.join(tdir, "replays")):
        raise SystemExit(f'No replays in {tdir}\\replays. Run: python tools\\python\\slippi_uploader.py "Protocol #{n}" '
                         "and plug in each setup's flash drive.")
    os.makedirs(tdir, exist_ok=True)
    cfg_path, cfg = prepare_config(ssd, n, tdir, rec, dock_src)
    stream_setup = cfg.get("stream_setup", "Main Setup")
    work = os.path.join(tdir, "work", "autopilot")
    os.makedirs(work, exist_ok=True)

    # 1. Clock offsets
    manual = {k: v for k, v in cfg.get("clock_offset_s", {}).items() if not k.startswith("_")}
    offsets, unmapped = estimate_all(cfg_path, stream_setup)
    log("  Wii clock offsets (seconds the Wii is ahead of the laptop):")
    for s, e in offsets.items():
        log(f"    {s:<16} {e.get('offset'):>9}  {e['confidence']:<6} {e.get('why', '')}")
    sil = silences(rec)
    stream_note = None
    if stream_setup in offsets and stream_setup not in manual:
        conv, why = calibrate_stream(cfg_path, offsets[stream_setup]["offset"], stream_setup, sil, work)
        if conv is not None:
            offsets[stream_setup].update({"offset": conv, "confidence": "high", "why": why})
            log(f"    {stream_setup} calibrated: {conv} s ({why})")
        else:
            stream_note = (f"{stream_setup}: stream clock not calibrated ({why}); cuts use the dock estimate, so set "
                           "starts/ends can be off by up to ~30 s. Padding raised to 30 s.")
            log("    " + stream_note)
    if a.offsets_only:
        return
    cfg = read_json(cfg_path)
    if not a.keep_offsets:
        co = cfg.setdefault("clock_offset_s", {})
        for s, e in offsets.items():
            if s not in manual:
                co[s] = e["offset"]
        co["_autopilot"] = {s: f"{e['confidence']}: {e.get('why', '')}" for s, e in offsets.items() if s not in manual}
    if stream_note:
        cfg["pad_before_s"] = max(cfg.get("pad_before_s", 10), 30)
        cfg["pad_after_s"] = max(cfg.get("pad_after_s", 10), 30)
    write_json(cfg_path, cfg)

    # 2. Plan (twice if dock names had to be mapped from the first plan)
    p = plan(cfg_path)
    if unmapped:
        _, _, _, _, dock_sets = dock_windows(cfg_path)
        added = automap_dock(cfg_path, unmapped, dock_sets, p)
        if added:
            log(f"  dock names mapped from the plan: {added}; re-estimating offsets and re-planning")
            again, _ = estimate_all(cfg_path, stream_setup)
            cfg = read_json(cfg_path)
            for s, e in again.items():
                if s in manual or a.keep_offsets or (s == stream_setup and stream_note is None):
                    continue  # hand-set, or the stream setup already calibrated from audio
                offsets[s] = e
                cfg["clock_offset_s"][s] = e["offset"]
                cfg["clock_offset_s"]["_autopilot"][s] = f"{e['confidence']}: {e.get('why', '')}"
                log(f"    {s:<16} {e['offset']:>9}  {e['confidence']:<6} {e.get('why', '')}")
            write_json(cfg_path, cfg)
            p = plan(cfg_path)

    # 3. Stream audio dropouts -> rebuild those games from the replays
    drop = dropout_games(p, sil)
    if drop:
        cfg = read_json(cfg_path)
        changed = False
        for sid, games in drop.items():
            ov = cfg["sets"].setdefault(sid, {})
            if "replay_games" not in ov:
                ov["replay_games"] = games
                ov["_autopilot"] = "stream audio silent during these games: rebuilt from the replays"
                changed = True
        if changed:
            write_json(cfg_path, cfg)
            log(f"  stream audio dropouts: {drop}; re-planning")
            p = plan(cfg_path)

    # 4. Checks
    block, adv = check(p, {s: e for s, e in offsets.items() if s not in manual}, stream_note)
    rv = write_needs_review(tdir, block, adv, offsets)
    if block:
        log(f"\nSTOPPED: {len(block)} item(s) need a person. See {rv}")
        sys.exit(2)
    log(f"  plan is confident: {len(p['segments'])} sets ({len(adv)} note(s) in {rv})")
    if a.plan_only:
        return

    # 5. Lucky Stats, render, kit, upload
    lucky_stats(tdir, n)
    run([PY, os.path.join(CODE, "vod_cutter.py"), "render", cfg_path], os.path.join(tdir, "render_log.txt"))
    log("  render done (sets\\, Full VODs, upload_kit\\)")
    if a.upload:
        run([PY, os.path.join(CODE, "youtube_upload.py"), "upload", tdir], os.path.join(tdir, "upload_log.txt"))
        run([PY, os.path.join(CODE, "youtube_upload.py"), "tags", tdir])
        log("  uploaded (Private until the Google project passes YouTube's audit: publish in YouTube Studio)")
    log("Done.")


if __name__ == "__main__":
    main()
